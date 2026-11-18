odoo.define('pos_layaway.LayawayScreen', function (require) {
    'use strict';

    const IndependentToOrderScreen = require('point_of_sale.IndependentToOrderScreen');
    const PosComponent = require('point_of_sale.PosComponent');
    const ProductScreen = require('point_of_sale.ProductScreen');
    const Registries = require('point_of_sale.Registries');
    const session = require('web.session');
    const { useListener } = require('web.custom_hooks');
    const { useState } = owl.hooks;

    class LayawayScreen extends IndependentToOrderScreen {
        constructor() {
            super(...arguments);
            this.state = useState({
                rows: [], campaigns: [], stores: [], detail: null,
                stale: !navigator.onLine, loaded: false, loading: false, hasMore: false,
                transferBusy: false, transferMessage: '', transferRetry: false,
                filters: { query: '', campaign: '', store: '', from: '', to: '',
                    payment_state: '', pickup_state: '', expiry: '' },
            });
            this.filters = {};
            this.requestNumber = 0;
            this.markOffline = () => {
                this.requestNumber++;
                this.state.loading = false;
                this.state.stale = true;
            };
            this.checkConnection = () => this.refresh();
        }

        mounted() {
            window.addEventListener('offline', this.markOffline);
            window.addEventListener('online', this.checkConnection);
            this.timer = window.setInterval(this.checkConnection, 12000);
            this.search();
        }

        willUnmount() {
            this.requestNumber++;
            window.removeEventListener('offline', this.markOffline);
            window.removeEventListener('online', this.checkConnection);
            window.clearInterval(this.timer);
        }

        async request(method, params) {
            if (!navigator.onLine) {
                this.markOffline();
                return null;
            }
            const number = ++this.requestNumber;
            this.state.loading = true;
            try {
                const result = await this.rpc({
                    model: 'pos.session',
                    method,
                    args: [[this.env.pos.pos_session.id], ...params],
                }, { shadow: true, timeout: 5000 });
                if (number === this.requestNumber) {
                    this.state.stale = false;
                    return result;
                }
            } catch (error) {
                if (error.event) {
                    error.event.preventDefault();
                }
                if (number === this.requestNumber) {
                    this.state.stale = true;
                }
            } finally {
                if (number === this.requestNumber) {
                    this.state.loading = false;
                }
            }
            return null;
        }

        async search() {
            this.filters = { ...this.state.filters };
            for (const key of ['campaign', 'store']) {
                this.filters[key] = Number(this.filters[key]) || false;
            }
            await this.loadPage(0);
        }

        async loadPage(offset) {
            const result = await this.request('get_layaways', [this.filters, offset]);
            if (result) {
                this.state.rows = offset ? this.state.rows.concat(result.rows) : result.rows;
                this.state.campaigns = result.campaigns;
                this.state.stores = result.stores;
                this.state.hasMore = result.has_more;
                this.state.loaded = true;
            }
        }

        async openDetail(id) {
            const result = await this.request('get_layaway_detail', [id]);
            if (result) {
                this.state.detail = result;
                this.state.transferRetry = Boolean(
                    result.transfer_review && result.transfer_review.methods
                    && sessionStorage.getItem(this.transferKey)
                );
            }
        }

        backToSearch() {
            this.requestNumber++;
            this.state.loading = false;
            this.state.detail = null;
            this.state.transferMessage = '';
            if (!this.state.stale) {
                this.loadPage(0);
            }
        }

        refresh() {
            if (this.state.loading || this.state.transferBusy || !navigator.onLine) {
                return;
            }
            if (this.state.detail) {
                return this.openDetail(this.state.detail.id);
            }
            if (this.state.stale || !this.state.loaded) {
                return this.loadPage(0);
            }
            // Confirm reachability without discarding the current search page.
            return this.request('get_layaways', [this.filters, 0]);
        }

        async submitTransfer(event) {
            if (this.state.stale || this.state.transferBusy || !navigator.onLine) {
                return;
            }
            const detail = this.state.detail;
            const key = this.transferKey;
            let pending = JSON.parse(sessionStorage.getItem(key));
            if (!pending) {
                const data = new FormData(event.currentTarget);
                const tenders = detail.transfer_review.methods
                    .filter(method => Number(data.get('method-' + method.id)) > 0)
                    .map(method => ({
                        method_id: method.id,
                        amount: Number(data.get('method-' + method.id)),
                    }));
                const bytes = window.crypto.getRandomValues(new Uint8Array(16));
                bytes[6] = (bytes[6] & 15) | 64;
                bytes[8] = (bytes[8] & 63) | 128;
                const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
                const reference = hex.replace(/^(........)(....)(....)(....)(............)$/, '$1-$2-$3-$4-$5');
                pending = { reference, tenders, kind: detail.transfer_review.kind };
                sessionStorage.setItem(key, JSON.stringify(pending));
            }
            const { reference, kind, tenders } = pending;
            const result = await this.changeTransfer('register_layaway_transfer', [detail.id, reference, kind, tenders]);
            if (result !== null) {
                sessionStorage.removeItem(key);
                this.state.transferRetry = false;
            } else {
                this.state.transferRetry = true;
            }
            if (result) {
                event.target.reset();
                this.state.transferMessage = this.env._t('Transferencia pendiente de verificación.');
            }
        }

        get transferKey() {
            return ['pos_layaway', session.db, session.uid, this.env.pos.pos_session.id, this.state.detail.id].join(':');
        }

        async authorizeTransfer(event, transferId) {
            const data = new FormData(event.currentTarget);
            const result = await this.changeTransfer('authorize_layaway_transfer', [
                this.state.detail.id, transferId, data.get('bank_reference'),
                data.get('reason'), data.get('evidence'),
            ]);
            if (result) {
                this.state.transferMessage = this.env._t('Transferencia confirmada.');
            }
        }

        async changeTransfer(method, args) {
            if (this.state.stale || this.state.transferBusy || !navigator.onLine) {
                return null;
            }
            this.state.transferBusy = true;
            this.state.transferMessage = '';
            try {
                const result = await this.rpc({
                    model: 'pos.session', method,
                    args: [[this.env.pos.pos_session.id], ...args],
                }, { shadow: true, timeout: 5000 });
                await this.openDetail(args[0]);
                return result;
            } catch (error) {
                if (error.event) {
                    error.event.preventDefault();
                }
                const code = error.message && error.message.code;
                if (code === 200) {
                    this.state.transferMessage = error.message.data.message;
                    return false;
                }
                this.markOffline();
                this.state.transferMessage = this.env._t('Actualiza el apartado para recuperar el resultado.');
                return null;
            } finally {
                this.state.transferBusy = false;
            }
        }

        get paymentLabels() {
            return { unpaid: this.env._t('Sin pago'), partial: this.env._t('Pago parcial'),
                paid: this.env._t('Liquidado') };
        }

        get pickupLabels() {
            return { pending: this.env._t('Pendiente'), partial: this.env._t('Parcial'),
                done: this.env._t('Entregado') };
        }

        money(amount) {
            return this.env.pos.format_currency(amount);
        }

        get labelUrl() {
            return '/pos/layaway/label/' + this.env.pos.pos_session.id + '/' + this.state.detail.id;
        }
    }

    class LayawayScreenButton extends PosComponent {
        constructor() {
            super(...arguments);
            useListener('click', () => this.showScreen('LayawayScreen'));
        }
    }

    LayawayScreen.template = 'pos_layaway.LayawayScreen';
    LayawayScreenButton.template = 'pos_layaway.LayawayScreenButton';
    ProductScreen.addControlButton({
        component: LayawayScreenButton,
        condition: function () {
            return Boolean(this.env.pos.pos_session);
        },
    });
    Registries.Component.add(LayawayScreen);
    Registries.Component.add(LayawayScreenButton);
});
