odoo.define('pos_layaway.LayawayCreditPayment', function (require) {
    'use strict';

    require('pos_layaway.LayawayWholesale');
    require('pos_wholesale_control.PaymentScreen');
    const { operationReference } = require('pos_layaway.LayawayScreen');
    const { _t } = require('web.core');
    const models = require('point_of_sale.models');
    const PaymentScreen = require('point_of_sale.PaymentScreen');
    const Registries = require('point_of_sale.Registries');
    const Order = models.Order.prototype;
    const Paymentline = models.Paymentline.prototype;
    const creditMethod = { id: -1, name: _t('Saldo de apartado'), is_cash_count: false };

    models.load_fields('pos.config', ['layaway_credit_test']);

    models.Paymentline = models.Paymentline.extend({
        init_from_JSON(json) {
            if (json.payment_method_id === creditMethod.id) {
                this.pos.payment_methods_by_id[creditMethod.id] = creditMethod;
            }
            Paymentline.init_from_JSON.apply(this, arguments);
        },
    });

    models.Order = models.Order.extend({
        init_from_JSON(json) {
            this.layawayCredit = json.layaway_credit_selection;
            this.layawayCreditPending = json.layaway_credit_pending;
            Order.init_from_JSON.apply(this, arguments);
            if (this.layawayCreditPending) {
                this.finalized = true;
            }
        },
        export_as_JSON() {
            const json = Order.export_as_JSON.apply(this, arguments);
            if (this.layawayCredit) {
                json.layaway_credit_selection = this.layawayCredit;
            }
            if (this.layawayCreditPending) {
                json.layaway_credit_pending = this.layawayCreditPending;
            }
            return json;
        },
        _wholesaleRetailAmount() {
            const total = Order._wholesaleRetailAmount.apply(this, arguments);
            const credit = this.layawayCredit;
            return credit && this.get_client()?.id === credit.partner_id ? Math.max(0, total - credit.amount) : total;
        },
        remove_paymentline(line) {
            if (line.payment_method.id === creditMethod.id) {
                this.layawayCredit = null;
                this._wholesaleReevaluateLocal();
            }
            return Order.remove_paymentline.apply(this, arguments);
        },
    });

    const LayawayCreditPayment = (BasePaymentScreen) => class extends BasePaymentScreen {
        async selectLayawayCredit() {
            const order = this.currentOrder;
            const partner = order.get_client();
            if (!partner || order.is_to_invoice() || this.paymentLines.some(line => line.payment_method.payment_terminal)) {
                return this._creditError(_t('Selecciona al titular y prepara el pedido sin factura ni terminal de pago.'));
            }
            const { confirmed, payload: folio } = await this.showPopup('TextInputPopup', {
                title: _t('Aplicar saldo de prueba'),
                body: _t('Escribe el folio de origen del saldo.'),
            });
            if (!confirmed) {
                return;
            }
            try {
                const credit = await this._creditRequest('preview_layaway_credit', [folio, partner.id]);
                if (order !== this.currentOrder || order.get_client()?.id !== partner.id || order.layawayCredit) {
                    return;
                }
                if (order.get_total_with_tax() < credit.amount) {
                    return this._creditError(_t('El total de la compra debe cubrir todo el saldo.'));
                }
                const line = order.add_paymentline(creditMethod);
                if (!line) {
                    return;
                }
                order.layawayCredit = credit;
                line.set_amount(credit.amount);
                order._wholesaleReevaluateLocal();
                order.save_to_db();
                this.render();
            } catch (error) {
                return this._creditRpcError(error, _t('Conéctate al servidor para consultar el saldo.'));
            }
        }

        _updateSelectedPaymentline() {
            if (!this.currentOrder.layawayCreditPending && this.selectedPaymentLine?.payment_method.id !== creditMethod.id) {
                return super._updateSelectedPaymentline(...arguments);
            }
        }

        addNewPaymentLine({ detail: method }) {
            if (this.currentOrder.layawayCredit && method.payment_terminal) {
                return this._creditError(_t('Usa un método de prueba sin terminal para cobrar la diferencia.'));
            }
            return super.addNewPaymentLine(...arguments);
        }

        async validateOrder(isForceValidate) {
            if (this.currentOrder.layawayCreditPending) {
                return this._finalizeValidation();
            }
            const order = this.currentOrder;
            const credit = order.layawayCredit;
            if (credit && (order.get_client()?.id !== credit.partner_id || order.is_to_invoice()
                    || order.get_total_with_tax() < credit.amount)) {
                return this._creditError(_t('Comprueba el titular, el importe íntegro del saldo y que el pedido sea sin factura.'));
            }
            return super.validateOrder(isForceValidate);
        }

        async _finalizeValidation() {
            const order = this.currentOrder;
            if (!order.layawayCredit) {
                return super._finalizeValidation(...arguments);
            }
            if (!navigator.onLine) {
                return this._creditError(_t('Conéctate al servidor para confirmar la compra con saldo.'));
            }
            if (!order.layawayCreditPending) {
                order.initialize_validation_date();
                const payload = order.export_as_JSON();
                delete payload.layaway_credit_selection;
                payload.statement_ids = payload.statement_ids.filter(line => line[2].payment_method_id !== creditMethod.id);
                order.layawayCreditPending = [order.layawayCredit.folio_id, operationReference(), payload];
                order.finalized = true;
                order.save_to_db();
                this.render();
            }
            try {
                const result = await this._creditRequest('confirm_layaway_credit_order', order.layawayCreditPending);
                order.server_id = result.id;
                order.layawayCreditPending = null;
                order.pos.db.remove_unpaid_order(order);
                if ((order.is_paid_with_cash() || order.get_change()) && this.env.pos.config.iface_cashdrawer) {
                    this.env.pos.proxy.printer.open_cashbox();
                }
                this.showScreen('ReceiptScreen');
            } catch (error) {
                if (error.message?.code === 200) {
                    order.layawayCreditPending = null;
                    order.finalized = false;
                    order.save_to_db();
                    this.render();
                }
                return this._creditRpcError(error, _t('Recupera la confirmación cuando se restablezca la conexión.'));
            }
        }

        _creditRequest(method, args) {
            return this.rpc({
                model: 'pos.session', method, args: [[this.env.pos.pos_session.id], ...args],
            }, { shadow: true, timeout: 10000 });
        }

        _creditRpcError(error, message) {
            error.event?.preventDefault();
            return this._creditError(error.message?.code === 200 ? error.message.data.message : message);
        }

        _creditError(body) {
            return this.showPopup('ErrorPopup', { title: _t('Saldo de apartado'), body });
        }
    };

    Registries.Component.extend(PaymentScreen, LayawayCreditPayment);
});
