odoo.define('pos_wholesale_control.PaymentScreen', function (require) {
    'use strict';

    const PaymentScreen = require('point_of_sale.PaymentScreen');
    const Registries = require('point_of_sale.Registries');

    const WholesalePaymentScreen = (PaymentScreen_) =>
        class extends PaymentScreen_ {
            constructor() {
                super(...arguments);
                const originalHandler = this._handlePushOrderError;
                this._handlePushOrderError = async (error) => {
                    if (await this._wholesaleHandlePushError(error)) {
                        return;
                    }
                    return originalHandler.call(this, error);
                };
            }
            async validateOrder(isForceValidate) {
                if (this.env.pos.wholesaleControlActive()) {
                    const message = await this._wholesaleBlockingMessage();
                    if (message) {
                        this.currentOrder.wholesale.validationError = message;
                        this.currentOrder.trigger('change', this.currentOrder);
                        await this.showPopup('ErrorPopup', {
                            title: this.env._t('Cannot complete payment'),
                            body: message,
                        });
                        this.showScreen('ProductScreen');
                        return;
                    }
                    this.currentOrder.wholesale.validationError = false;
                }
                return super.validateOrder(isForceValidate);
            }
            async _wholesaleBlockingMessage() {
                const order = this.currentOrder;
                if (!order || !order.wholesale) {
                    return false;
                }
                if (order.wholesale.loading) {
                    return this.env._t(
                        'Wholesale eligibility is still loading. Wait for the check to finish before paying.'
                    );
                }
                if (order.wholesale.validationError) {
                    return order.wholesale.validationError;
                }
                const allowed = order._wholesaleAllowedPricelist
                    ? order._wholesaleAllowedPricelist()
                    : null;
                if (!allowed) {
                    return this.env._t(
                        'Missing retail pricelist configuration. An administrator must set the wholesale-control pricelists for this company.'
                    );
                }
                if (order.pricelist && order.pricelist.id !== allowed.id) {
                    const expectedName = allowed.display_name || allowed.name || '';
                    const reason = order.wholesale.reasonText || '';
                    return (
                        'No se puede cobrar con la lista seleccionada. '
                        + 'La lista que corresponde es "'
                        + expectedName
                        + '".'
                        + (reason ? ' ' + reason : '')
                    );
                }
                if (
                    order.wholesale.reasonCode === 'history_unavailable'
                    && !(order.wholesale.override && order.wholesale.override.pricelist_id)
                    && order.pricelist
                    && order.wholesale.retailPricelistId
                    && order.pricelist.id !== order.wholesale.retailPricelistId
                ) {
                    return this.env._t(
                        'Purchase history is unavailable. Keep retail pricing, or ask a manager for an audited override before charging wholesale.'
                    );
                }
                return this._wholesaleServerPrecheck(order, allowed);
            }
            async _wholesaleServerPrecheck(order, allowed) {
                const client = order.get_client();
                const company = this.env.pos.wholesale_company || this.env.pos.company || {};
                if (!company.id) {
                    return this.env._t(
                        'Wholesale control could not read the register company. Reload the point of sale.'
                    );
                }
                const retailAmount = order._wholesaleRetailAmount
                    ? order._wholesaleRetailAmount()
                    : (order.wholesale.retailAmount || 0);
                try {
                    const response = await this.rpc({
                        model: 'res.partner',
                        method: 'get_wholesale_eligibility',
                        args: [
                            client && client.id,
                            company.id,
                            retailAmount,
                            this.env.pos.config && this.env.pos.config.id,
                        ],
                    }, {
                        shadow: true,
                        timeout: 5000,
                    });
                    if (!response) {
                        return this.env._t(
                            'The eligibility check returned an empty response. Keep retail pricing or retry when the connection is stable.'
                        );
                    }
                    if (response.error && !(order.wholesale.override && order.wholesale.override.pricelist_id)) {
                        // Configuration or history errors stay fail-closed on retail.
                        if (allowed && order.pricelist && order.pricelist.id === allowed.id
                            && (!response.expected_pricelist || response.expected_pricelist.id === allowed.id
                                || response.reason_code === 'history_unavailable')) {
                            if (response.reason_code === 'history_unavailable'
                                && order.pricelist.id !== (response.retail_pricelist && response.retail_pricelist.id)
                                && !(order.wholesale.override && order.wholesale.override.pricelist_id)) {
                                return response.error || this.env._t(
                                    'Purchase history is unavailable. Only retail pricing or a manager override is allowed.'
                                );
                            }
                            return false;
                        }
                        return response.error;
                    }
                    if (order.wholesale.override && order.wholesale.override.pricelist_id) {
                        if (order.pricelist && order.pricelist.id === order.wholesale.override.pricelist_id) {
                            return false;
                        }
                        return this.env._t(
                            'This ticket has a manager override, but the applied pricelist does not match the authorized list.'
                        );
                    }
                    const expected = response.expected_pricelist;
                    if (expected && expected.id && order.pricelist && order.pricelist.id !== expected.id) {
                        const reason = response.reason_text || '';
                        return (
                            'No se puede cobrar con la lista seleccionada. '
                            + 'La lista que corresponde es "'
                            + (expected.name || expected.id)
                            + '".'
                            + (reason ? ' ' + reason : '')
                        );
                    }
                    return false;
                } catch (error) {
                    if (order.wholesale.override && order.wholesale.override.pricelist_id) {
                        return false;
                    }
                    if (allowed && order.pricelist && order.pricelist.id === allowed.id
                        && order.wholesale.automaticDecision === 'retail') {
                        order.wholesale.error = this.env._t(
                            'Could not refresh purchase history before payment. The order stays on retail.'
                        );
                        order.wholesale.reasonCode = 'history_unavailable';
                        order.trigger('change', order);
                        return false;
                    }
                    return this.env._t(
                        'Could not validate wholesale eligibility before payment. Check the connection and try again.'
                    );
                }
            }
            async _wholesaleHandlePushError(error) {
                if (!this.env.pos.wholesaleControlActive()) {
                    return false;
                }
                const message = this._wholesaleErrorMessage(error);
                if (!message || !this._wholesaleLooksLikeValidation(message)) {
                    return false;
                }
                const order = this.currentOrder;
                if (order) {
                    order.finalized = false;
                    order.wholesale.validationError = message;
                    order.trigger('change', order);
                    this._wholesaleRemovePendingOrder(order);
                }
                this.error = true;
                await this.showPopup('ErrorPopup', {
                    title: this.env._t('Payment blocked by wholesale control'),
                    body: message,
                });
                this.showScreen('ProductScreen');
                return true;
            }
            _wholesaleLooksLikeValidation(message) {
                const text = (message || '').toLowerCase();
                return (
                    text.indexOf('lista') !== -1
                    || text.indexOf('pricelist') !== -1
                    || text.indexOf('mayoreo') !== -1
                    || text.indexOf('wholesale') !== -1
                    || text.indexOf('menudeo') !== -1
                    || text.indexOf('historial') !== -1
                    || text.indexOf('excepción') !== -1
                    || text.indexOf('excepcion') !== -1
                );
            }
            _wholesaleErrorMessage(error) {
                const nested = error && error.message;
                const data = (error && error.data) || (nested && nested.data);
                if (data && data.message) {
                    return data.message;
                }
                if (typeof nested === 'string') {
                    return nested;
                }
                return false;
            }
            _wholesaleRemovePendingOrder(order) {
                const pending = this.env.pos.db.get_orders();
                const uid = order.uid || (order.export_as_JSON && order.export_as_JSON().uid);
                const name = order.get_name && order.get_name();
                pending.forEach((row) => {
                    const data = row.data || {};
                    if ((uid && data.uid === uid) || (name && data.name === name)) {
                        this.env.pos.db.remove_order(row.id);
                    }
                });
                this.env.pos.set('failed', false);
                this.env.pos.set_synch(
                    'connected',
                    this.env.pos.db.get_orders().length
                );
            }
        };

    Registries.Component.extend(PaymentScreen, WholesalePaymentScreen);

    return PaymentScreen;
});
