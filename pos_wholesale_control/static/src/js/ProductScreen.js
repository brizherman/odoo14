odoo.define('pos_wholesale_control.ProductScreen', function (require) {
    'use strict';

    const ProductScreen = require('point_of_sale.ProductScreen');
    const Registries = require('point_of_sale.Registries');

    const WholesaleProductScreen = (ProductScreen_) =>
        class extends ProductScreen_ {
            _scheduleWholesaleReevaluate() {
                const order = this.currentOrder;
                if (order && order.wholesaleScheduleReevaluate) {
                    order.wholesaleScheduleReevaluate();
                }
            }
            async _clickProduct(event) {
                await super._clickProduct(event);
                this._scheduleWholesaleReevaluate();
            }
            async _updateSelectedOrderline(event) {
                await super._updateSelectedOrderline(event);
                this._scheduleWholesaleReevaluate();
            }
            async _barcodeProductAction(code) {
                await super._barcodeProductAction(code);
                this._scheduleWholesaleReevaluate();
            }
            _barcodeDiscountAction(code) {
                super._barcodeDiscountAction(code);
                this._scheduleWholesaleReevaluate();
            }
            _barcodeClientAction(code) {
                const partner = this.env.pos.db.get_partner_by_barcode(code.code);
                if (partner) {
                    if (this.currentOrder.get_client() !== partner) {
                        this.currentOrder.set_client(partner);
                        // updatePricelist asks the server which list applies.
                        // The barcode path must not keep the customer's own list.
                        this.currentOrder.updatePricelist(partner);
                    }
                    return true;
                }
                this._barcodeErrorAction(code);
                return false;
            }
        };

    Registries.Component.extend(ProductScreen, WholesaleProductScreen);

    return ProductScreen;
});
