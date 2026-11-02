odoo.define('product_price_lookup.PriceLookupButton', function (require) {
    'use strict';

    const PosComponent = require('point_of_sale.PosComponent');
    const ProductScreen = require('point_of_sale.ProductScreen');
    const { useListener } = require('web.custom_hooks');
    const Registries = require('point_of_sale.Registries');

    class PriceLookupButton extends PosComponent {
        constructor() {
            super(...arguments);
            useListener('click', this.onClick);
        }
        async onClick() {
            // The popup only reads prices. It must not add lines or change the list.
            await this.showPopup('PriceLookupPopup');
        }
    }
    PriceLookupButton.template = 'PriceLookupButton';

    ProductScreen.addControlButton({
        component: PriceLookupButton,
        condition: function () {
            return true;
        },
    });

    Registries.Component.add(PriceLookupButton);

    return PriceLookupButton;
});
