odoo.define('pos_layaway.LayawayStockPayment', function (require) {
    'use strict';

    const PaymentScreen = require('point_of_sale.PaymentScreen');
    const Registries = require('point_of_sale.Registries');
    const { crash_registry, _t } = require('web.core');
    const stockError = 'odoo.addons.pos_layaway.models.stock_picking.LayawayStockError';

    // Background synchronization has no PaymentScreen to handle a rejected sale.
    crash_registry.add(stockError, function (manager, error) {
        return {
            display() {
                if (!error.layawayHandled) {
                    manager.show_warning({ data: { ...error.data, title: _t('Venta sin confirmar') } });
                }
            },
        };
    });

    const LayawayStockPayment = (BasePaymentScreen) => class extends BasePaymentScreen {
        constructor() {
            super(...arguments);
            const handlePushOrderError = this._handlePushOrderError.bind(this);
            this._handlePushOrderError = async (error) => {
                if (error.data && error.data.name === stockError) {
                    error.layawayHandled = true;
                    this.error = true;
                    const order = this.currentOrder;
                    order.finalized = false;
                    this.env.pos.db.remove_order(order.uid);
                    order.save_to_db();
                    this.env.pos.set('failed', false);
                    this.env.pos.set_synch('connected');
                    await this.showPopup('ErrorPopup', {
                        title: this.env._t('Venta sin confirmar'),
                        body: error.data.message,
                    });
                    return;
                }
                await handlePushOrderError(error);
            };
        }
    };

    Registries.Component.extend(PaymentScreen, LayawayStockPayment);
});
