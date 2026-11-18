odoo.define('pos_layaway.LayawayScreen', function (require) {
    'use strict';

    const IndependentToOrderScreen = require('point_of_sale.IndependentToOrderScreen');
    const PosComponent = require('point_of_sale.PosComponent');
    const ProductScreen = require('point_of_sale.ProductScreen');
    const Registries = require('point_of_sale.Registries');
    const { useListener } = require('web.custom_hooks');
    const { useState } = owl.hooks;

    class LayawayScreen extends IndependentToOrderScreen {
        constructor() {
            super(...arguments);
            this.state = useState({
                rows: [], campaigns: [], stores: [], detail: null,
                stale: !navigator.onLine, loaded: false, loading: false, hasMore: false,
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
            }
        }

        backToSearch() {
            this.requestNumber++;
            this.state.loading = false;
            this.state.detail = null;
            if (!this.state.stale) {
                this.loadPage(0);
            }
        }

        refresh() {
            if (this.state.loading || !navigator.onLine) {
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
