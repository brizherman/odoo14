odoo.define('pos_customer_data_validation.PaymentScreen', function (require) {
    'use strict';

    const PaymentScreen = require('point_of_sale.PaymentScreen');
    const Registries = require('point_of_sale.Registries');
    const { _t } = require('web.core');

    const CustomerDataPaymentScreen = Base => class extends Base {
        constructor() {
            super(...arguments);
            // Core captured the complete validateOrder chain, including optional addons.
            const inheritedValidate = this.lockedValidateOrder;
            this.lockedValidateOrder = async (isForceValidate) => {
                if (this.customerDataBusy) return;
                const force = this.customerDataForce;
                this.customerDataForce = null;
                if (isForceValidate && (!force || !this.isCustomerAttemptCurrent(force.attempt)
                    || this.customerOrderSignature(force.attempt.order) !== force.signature)) {
                    this.clearCustomerAttempt();
                    return;
                }
                if (!isForceValidate) this.clearCustomerAttempt();
                this.customerDataBusy = true;
                const order = this.currentOrder;
                if (!order || order.finalized) {
                    this.customerDataBusy = false;
                    return;
                }
                const client = order.get_client();
                const attempt = isForceValidate ? force.attempt : { order, client, valid: true };
                if (!isForceValidate) {
                    const invalidate = () => { attempt.valid = false; };
                    order.on('change:client', invalidate);
                    this.env.pos.on('change:selectedOrder', invalidate);
                    attempt.cleanup = () => {
                        order.off('change:client', invalidate);
                        this.env.pos.off('change:selectedOrder', invalidate);
                    };
                    this.customerDataPending = attempt;
                }
                attempt.finished = new Promise(resolve => { attempt.release = resolve; });
                this.customerDataAttempt = attempt;
                try {
                    if (client && !isForceValidate) {
                        const result = await this.showPopup('CustomerDataPopup', {
                            partnerId: client.id,
                            isCurrent: () => this.isCustomerAttemptCurrent(attempt),
                        });
                        if (!result.confirmed || !this.isCustomerAttemptCurrent(attempt)) return;
                        await this.refreshCustomerData(order, client, result.payload);
                        if (!this.isCustomerAttemptCurrent(attempt)) return;
                    }
                    return await inheritedValidate.call(this, isForceValidate);
                } catch (error) {
                    await this.showPopup('ErrorPopup', {
                        title: _t('No se pudo continuar el pago'),
                        body: error.message || _t('Vuelve a revisar el cliente y los precios.'),
                    });
                } finally {
                    this.customerDataAttempt = null;
                    this.customerDataBusy = false;
                    attempt.release();
                    if (!attempt.confirmationPending) this.clearCustomerAttempt(attempt);
                }
            };
        }
        async _isOrderValid(isForceValidate) {
            const attempt = this.customerDataAttempt;
            const valid = await super._isOrderValid(isForceValidate);
            return valid && (!attempt || this.isCustomerAttemptCurrent(attempt));
        }
        isCustomerAttemptCurrent(attempt) {
            return attempt.valid && this.customerDataPending === attempt && this.currentOrder === attempt.order && attempt.order.get_client() === attempt.client
                && !attempt.order.finalized;
        }
        clearCustomerAttempt(attempt = this.customerDataPending) {
            if (!attempt) return;
            attempt.valid = false;
            if (attempt.cleanup) attempt.cleanup();
            if (this.customerDataPending === attempt) this.customerDataPending = null;
            if (this.customerDataForce && this.customerDataForce.attempt === attempt) this.customerDataForce = null;
        }
        willUnmount() {
            this.clearCustomerAttempt();
            if (super.willUnmount) super.willUnmount();
        }
        customerOrderSignature(order) {
            const data = order.export_as_JSON();
            // Core generates each payment's export name from the current clock;
            // it is not an edit and must not expire a pending confirmation.
            for (const payment of data.statement_ids || []) delete payment[2].name;
            return JSON.stringify(data);
        }
        showPopup(name, props) {
            const response = super.showPopup(name, props);
            const attempt = this.customerDataAttempt;
            if (name !== 'ConfirmPopup' || !attempt
                || props.title !== this.env._t('Please Confirm Large Amount')) return response;
            attempt.confirmationPending = true;
            const signature = this.customerOrderSignature(attempt.order);
            return response.then(async result => {
                // Core schedules the forced call outside validateOrder. Let both
                // the core lock and our outer lock release before forwarding it.
                await attempt.finished;
                attempt.confirmationPending = false;
                if (!result.confirmed || !this.isCustomerAttemptCurrent(attempt)
                    || signature !== this.customerOrderSignature(attempt.order)) {
                    this.clearCustomerAttempt(attempt);
                    return { confirmed: false, payload: null };
                }
                this.customerDataForce = { attempt, signature };
                return result;
            });
        }
        async refreshCustomerData(order, client, data) {
            const partner = data.partner;
            const oldPrice = client.property_product_pricelist && client.property_product_pricelist[0];
            const newPrice = partner.property_product_pricelist && partner.property_product_pricelist[0];
            const pricingChanged = oldPrice !== newPrice || client.customer_type !== partner.customer_type;
            Object.assign(client, partner);
            const db = this.env.pos.db;
            // add_partners skips equal timestamps; this RPC is authoritative, even
            // for same-second writes. Preserve the incremental sync watermark.
            const watermark = db.partner_write_date;
            try {
                db.partner_write_date = false;
                db.add_partners([client]);
            } finally {
                db.partner_write_date = watermark;
            }
            const wholesale = this.env.pos.wholesaleControlActive && this.env.pos.wholesaleControlActive();
            if (pricingChanged || wholesale) {
                order.updatePricelist(client);
                if (wholesale) await this.waitForWholesale(order);
            }
            order.trigger('change', order);
            order.save_to_db();
        }
        waitForWholesale(order) {
            if (!order.wholesale || !order.wholesale.loading) return Promise.resolve();
            return new Promise((resolve, reject) => {
                const finish = (error) => {
                    clearTimeout(timer);
                    order.off('change', check);
                    if (error) reject(error); else resolve();
                };
                const check = () => {
                    if (!order.wholesale.loading) finish();
                };
                const timer = setTimeout(() => finish(new Error(
                    _t('No terminó la actualización de precios. Vuelve a validar.'),
                )), 10000);
                order.on('change', check);
                check();
            });
        }
    };
    Registries.Component.extend(PaymentScreen, CustomerDataPaymentScreen);
    return PaymentScreen;
});
