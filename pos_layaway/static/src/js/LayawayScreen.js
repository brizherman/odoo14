odoo.define('pos_layaway.LayawayScreen', function (require) {
    'use strict';

    const IndependentToOrderScreen = require('point_of_sale.IndependentToOrderScreen');
    const PosComponent = require('point_of_sale.PosComponent');
    const ProductScreen = require('point_of_sale.ProductScreen');
    const Registries = require('point_of_sale.Registries');
    const models = require('point_of_sale.models');
    const session = require('web.session');
    const { useListener } = require('web.custom_hooks');
    const { useState } = owl.hooks;

    models.load_fields('product.product', ['type']);

    function operationReference() {
        const bytes = window.crypto.getRandomValues(new Uint8Array(16));
        bytes[6] = (bytes[6] & 15) | 64;
        bytes[8] = (bytes[8] & 63) | 128;
        const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
        return hex.replace(/^(........)(....)(....)(....)(............)$/, '$1-$2-$3-$4-$5');
    }

    class LayawayScreen extends IndependentToOrderScreen {
        constructor() {
            super(...arguments);
            this.state = useState({
                rows: [], campaigns: [], stores: [], detail: null,
                stale: !navigator.onLine, loaded: false, loading: false, hasMore: false,
                transferBusy: false, transferMessage: '', transferRetry: false,
                canOpen: false, canReviewExpired: false, draft: null, checkoutBusy: false, checkoutMessage: '',
                originalReceipt: null,
                pendingConfirmation: JSON.parse(sessionStorage.getItem(this.confirmationKey)),
                pendingCorrection: null, correctionPayment: '', correctionMethod: '',
                correctionKind: '', expiryResolution: '',
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

        showExpired() {
            this.state.filters.expiry = 'expired';
            return this.search();
        }

        async loadPage(offset) {
            const result = await this.request('get_layaways', [this.filters, offset]);
            if (result) {
                this.state.rows = offset ? this.state.rows.concat(result.rows) : result.rows;
                this.state.campaigns = result.campaigns;
                this.state.stores = result.stores;
                this.state.hasMore = result.has_more;
                this.state.canOpen = result.can_open_layaway;
                this.state.canReviewExpired = result.can_review_expired;
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
                this.state.pendingCorrection = JSON.parse(sessionStorage.getItem(this.correctionKey));
            }
        }

        backToSearch() {
            this.requestNumber++;
            this.state.loading = false;
            this.state.detail = null;
            this.state.originalReceipt = null;
            this.state.transferMessage = '';
            this.state.correctionPayment = '';
            this.state.correctionKind = '';
            this.state.correctionMethod = '';
            if (!this.state.stale) {
                this.loadPage(0);
            }
        }

        refresh() {
            if (this.state.loading || this.state.transferBusy || this.state.checkoutBusy || !navigator.onLine) {
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

        get confirmationKey() {
            return ['pos_layaway_checkout', session.db, session.uid, this.env.pos.pos_session.id].join(':');
        }

        startExpiryReview(folio) {
            this.state.checkoutMessage = '';
            this.state.expiryResolution = '';
            this.state.draft = { folio, expiryReview: true };
        }

        async startCheckout(folio, change = false) {
            if (this.state.stale || this.state.transferBusy || this.state.checkoutBusy || !navigator.onLine) {
                return;
            }
            this.state.checkoutMessage = '';
            const selected = this.env.pos.layawayCampaign;
            const draft = {
                folio, change, removeIds: [], campaigns: [], campaign: folio ? folio.campaign_id : '',
                partner: null, phone: '', partnerQuery: '', productQuery: '', lines: [], quote: null,
            };
            if (!folio) {
                const campaigns = await this.request('get_layaway_campaigns', []);
                if (!campaigns) {
                    return;
                }
                draft.campaigns = campaigns;
                if (selected && campaigns.some(campaign => campaign.id === selected.id)) {
                    draft.campaign = selected.id;
                } else if (campaigns.length === 1) {
                    draft.campaign = campaigns[0].id;
                }
            }
            this.state.draft = draft;
        }

        startInstallment(folio, settle = false) {
            this.state.checkoutMessage = '';
            this.state.draft = { installment: true, folio, settle };
        }

        startPickup(folio, settle = false) {
            this.state.checkoutMessage = '';
            this.state.draft = { installment: settle, folio, settle, pickup: true };
        }

        startRelocation(folio) {
            this.state.checkoutMessage = '';
            this.state.draft = { folio, relocate: true };
        }

        cancelCheckout() {
            this.state.draft = null;
            this.state.checkoutMessage = '';
        }

        updateCheckoutField(field, event) {
            const value = event.target.value;
            this.state.draft[field] = field === 'campaign' && value ? Number(value) : value;
        }

        updateCheckoutQuantity(productId, event) {
            const line = this.state.draft.lines.find(item => item.product_id === productId);
            line.qty = event.target.value;
        }

        get matchingPartners() {
            const query = this.state.draft.partnerQuery.trim();
            return query ? this.env.pos.db.search_partner(query).slice(0, 8) : [];
        }

        get matchingProducts() {
            const query = this.state.draft.productQuery.trim();
            return query ? this.env.pos.db.search_product_in_category(0, query)
                .filter(product => product.type === 'product').slice(0, 8) : [];
        }

        selectPartner(partner) {
            Object.assign(this.state.draft, {
                partner, phone: partner.mobile || partner.phone || '', partnerQuery: '',
            });
        }

        addProduct(product) {
            const draft = this.state.draft;
            const existing = draft.lines.find(line => line.product_id === product.id);
            if (existing) {
                existing.qty = Number(existing.qty) + 1;
            } else {
                draft.lines.push({ product_id: product.id, name: product.display_name, qty: 1 });
            }
            draft.productQuery = '';
        }

        removeProduct(productId) {
            const draft = this.state.draft;
            draft.lines = draft.lines.filter(line => line.product_id !== productId);
        }

        toggleRemoval(lineId, event) {
            const draft = this.state.draft;
            if (event.target.checked) {
                draft.removeIds.push(lineId);
            } else {
                draft.removeIds = draft.removeIds.filter(id => id !== lineId);
            }
        }

        get changeableLines() {
            const { folio } = this.state.draft;
            return folio.lines.filter(line => folio.changeable_lines.includes(line.id));
        }

        async quoteCheckout() {
            const draft = this.state.draft;
            const lines = draft.lines.map(line => ({ product_id: line.product_id, qty: Number(line.qty) }));
            if (draft.change) {
                const args = [draft.folio.id, [...draft.removeIds], lines];
                const quote = await this.checkoutRequest('quote_layaway_change', args);
                if (quote) {
                    draft.proposal = args;
                    draft.quote = quote;
                }
                return;
            }
            const proposal = {
                lines,
                campaign_id: Number(draft.campaign),
                partner_id: draft.partner ? draft.partner.id : false,
                phone: draft.phone || false,
                layaway_id: draft.folio ? draft.folio.id : false,
            };
            const quote = await this.checkoutRequest('quote_layaway', [
                proposal.lines, proposal.campaign_id, proposal.partner_id, proposal.phone, proposal.layaway_id,
            ]);
            if (quote) {
                draft.proposal = proposal;
                draft.quote = quote;
            }
        }

        async confirmCheckout(event) {
            if (this.state.stale || this.state.checkoutBusy || !navigator.onLine) {
                return;
            }
            if (!this.state.pendingConfirmation) {
                const {
                    quote, proposal, change, installment, folio, settle, pickup, relocate, expiryReview,
                } = this.state.draft;
                const data = new FormData(event.currentTarget);
                const reference = operationReference();
                let pending;
                const recipient = pickup && {
                    kind: data.get('recipient') === 'holder' ? 'holder' : 'authorized',
                    authorization_reference: data.get('recipient') === 'holder' ? false : data.get('recipient'),
                    identity_verified: data.get('identity_verified') === 'on',
                };
                if (expiryReview) {
                    pending = {
                        method: 'review_expired_layaway',
                        args: [folio.id, reference, data.get('resolution'), data.get('notes')],
                    };
                } else if (relocate) {
                    pending = {
                        method: 'relocate_layaway_block',
                        args: [folio.id, reference, Number(data.get('destination')), folio.pickup.lines],
                    };
                } else if (installment) {
                    const tenders = this.checkoutTenders(folio.installment_methods, data);
                    if (!tenders.length) {
                        this.state.checkoutMessage = this.env._t('Indica un importe para el abono.');
                        return;
                    }
                    pending = {
                        method: pickup ? 'settle_and_pickup_layaway'
                            : settle ? 'settle_layaway' : 'register_layaway_installment',
                        args: [folio.id, reference, tenders],
                    };
                    if (pickup) {
                        pending.args.push(recipient, folio.pickup.lines);
                    }
                } else if (pickup) {
                    pending = {
                        method: 'confirm_layaway_pickup',
                        args: [folio.id, reference, recipient, folio.pickup.lines],
                    };
                } else if (change) {
                    pending = {
                        method: 'confirm_layaway_change',
                        args: [reference, ...proposal, quote.confirmation, data.get('reason')],
                    };
                } else {
                    pending = [reference, proposal, quote.confirmation, this.checkoutTenders(quote.methods, data)];
                }
                sessionStorage.setItem(this.confirmationKey, JSON.stringify(pending));
                this.state.pendingConfirmation = pending;
            }
            const pending = this.state.pendingConfirmation;
            const result = await this.checkoutRequest(
                pending.method || 'confirm_layaway', pending.args || pending
            );
            if (result !== null) {
                sessionStorage.removeItem(this.confirmationKey);
                this.state.pendingConfirmation = null;
            }
            if (result) {
                this.state.draft = null;
                this.showOriginalReceipts(result);
                const messages = {
                    confirm_layaway_change: this.env._t('Cambio autorizado'),
                    register_layaway_installment: this.env._t('Abono confirmado'),
                    confirm_layaway_pickup: this.env._t('Recogida confirmada'),
                    settle_and_pickup_layaway: this.env._t('Liquidación y recogida confirmadas'),
                    relocate_layaway_block: this.env._t('Traslado registrado'),
                    review_expired_layaway: result.credit ? this.env._t('Saldo por vencimiento emitido')
                        : this.env._t('Revisión de vencimiento registrada'),
                };
                const pickupConfirmed = result.pickup || result.recipient;
                const message = pickupConfirmed ? messages[pending.method]
                    : result.sale_adjustment ? this.env._t('Ajuste vinculado a la venta')
                    : result.sale_id && !result.amount_due ? this.env._t('Apartado liquidado')
                    : messages[pending.method] || this.env._t('Reserva confirmada');
                this.state.checkoutMessage = message + ' · ' + result.folio;
                await this.openDetail(result.id);
            }
        }

        checkoutTenders(methods, data) {
            return methods.filter(method => Number(data.get('apply-' + method.id)) > 0)
                .map(method => {
                    const amount = Number(data.get('apply-' + method.id));
                    return {
                        method_id: method.id, amount,
                        amount_tendered: Number(data.get('received-' + method.id) || amount),
                    };
                });
        }

        async checkoutRequest(method, args) {
            if (this.state.stale || this.state.checkoutBusy || !navigator.onLine) {
                return null;
            }
            this.state.checkoutMessage = '';
            this.state.checkoutBusy = true;
            try {
                return await this.rpc({
                    model: 'pos.session', method,
                    args: [[this.env.pos.pos_session.id], ...args],
                }, { shadow: true, timeout: 10000 });
            } catch (error) {
                if (error.event) {
                    error.event.preventDefault();
                }
                if (error.message && error.message.code === 200) {
                    this.state.checkoutMessage = error.message.data.message;
                    return false;
                }
                this.markOffline();
                return null;
            } finally {
                this.state.checkoutBusy = false;
            }
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
                pending = { reference: operationReference(), tenders, kind: detail.transfer_review.kind };
                sessionStorage.setItem(key, JSON.stringify(pending));
            }
            const { reference, kind, tenders } = pending;
            const result = await this.submitLayawayOperation(
                'register_layaway_transfer', [detail.id, reference, kind, tenders],
            );
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
            const result = await this.submitLayawayOperation('authorize_layaway_transfer', [
                this.state.detail.id, transferId, data.get('bank_reference'),
                data.get('reason'), data.get('evidence'),
            ]);
            if (result) {
                this.state.transferMessage = result.sale_id && !result.amount_due ? this.env._t('Apartado liquidado')
                    : this.env._t('Transferencia confirmada.');
                this.showOriginalReceipts(result);
            }
        }

        get correctionKey() {
            return this.transferKey + ':correction';
        }

        get correctionPayment() {
            return this.state.detail.payment_corrections.find(
                payment => payment.id === Number(this.state.correctionPayment),
            );
        }

        get correctionMethod() {
            const payment = this.correctionPayment;
            return payment && payment.methods.find(
                method => method.id === Number(this.state.correctionMethod),
            );
        }

        async submitPaymentCorrection(event) {
            if (this.state.stale || this.state.transferBusy || !navigator.onLine) {
                return;
            }
            let pending = this.state.pendingCorrection;
            const key = this.correctionKey;
            if (!pending) {
                const data = new FormData(event.currentTarget);
                const correction = {
                    kind: data.get('kind'), reason: data.get('reason'), evidence: data.get('evidence'),
                };
                if (correction.kind === 'refund_payment') {
                    correction.amount = Number(data.get('amount'));
                } else {
                    correction.method_id = Number(data.get('method_id'));
                    correction.bank_reference = data.get('bank_reference') || '';
                }
                pending = [this.state.detail.id, this.correctionPayment.id, operationReference(), correction];
                sessionStorage.setItem(key, JSON.stringify(pending));
                this.state.pendingCorrection = pending;
            }
            const result = await this.submitLayawayOperation('correct_layaway_payment', pending);
            if (result !== null) {
                sessionStorage.removeItem(key);
                this.state.pendingCorrection = null;
            }
            if (result) {
                this.state.correctionPayment = '';
                this.state.correctionKind = '';
                this.state.correctionMethod = '';
                this.state.transferMessage = this.env._t('Corrección confirmada.');
            }
        }

        async submitLayawayOperation(method, args) {
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
                paid: this.env._t('Liquidado'), converted: this.env._t('Convertido en saldo') };
        }

        get pickupLabels() {
            return { pending: this.env._t('Pendiente'), partial: this.env._t('Parcial'),
                done: this.env._t('Entregado'), released: this.env._t('Reserva liberada') };
        }

        get expiryResolutionLabels() {
            return {
                keep_reserved: this.env._t('Mantener en revisión y conservar la reserva'),
                authorize_late_pickup: this.env._t('Autorizar recogida tardía'),
                convert_to_credit: this.env._t('Liberar la reserva y emitir saldo'),
            };
        }

        money(amount) {
            return this.env.pos.format_currency(amount);
        }

        get labelUrl() {
            return '/pos/layaway/label/' + this.env.pos.pos_session.id + '/' + this.state.detail.id;
        }

        showOriginalReceipts(result) {
            const pickup = Boolean(result.pickup || result.recipient);
            this.state.originalReceipt = result.receipt || result.settlement || pickup ? {
                id: result.id,
                reference: result.reference,
                receipt: Boolean(result.receipt),
                finalSale: Boolean(result.settlement),
                pickup,
            } : null;
        }

        receiptUrl(reference, original = false, finalSale = false, pickup = false) {
            const query = new URLSearchParams();
            if (original) {
                query.set('original', '1');
            }
            if (finalSale) {
                query.set('final_sale', '1');
            }
            if (pickup) {
                query.set('pickup', '1');
            }
            return '/pos/layaway/receipt/' + this.env.pos.pos_session.id + '/'
                + this.state.detail.id + '/' + encodeURIComponent(reference)
                + (query.toString() ? '?' + query : '');
        }

        openOriginalReceipt(kind) {
            const receipt = this.state.originalReceipt;
            window.setTimeout(() => {
                if (this.state.originalReceipt === receipt) {
                    receipt[kind] = false;
                }
            }, 0);
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
