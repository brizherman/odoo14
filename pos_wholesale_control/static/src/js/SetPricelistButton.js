odoo.define('pos_wholesale_control.SetPricelistButton', function (require) {
    'use strict';

    const SetPricelistButton = require('point_of_sale.SetPricelistButton');
    const Registries = require('point_of_sale.Registries');

    const WholesaleSetPricelistButton = (SetPricelistButton_) =>
        class extends SetPricelistButton_ {
            async onClick() {
                if (this.env.pos.wholesaleControlActive()) {
                    await this.showPopup('ErrorPopup', {
                        title: this.env._t('Lista de precios bloqueada'),
                        body: this.env._t('Esta caja elige la lista de precios. No se puede cambiar manualmente.'),
                    });
                    return;
                }
                await super.onClick();
            }
        };

    Registries.Component.extend(SetPricelistButton, WholesaleSetPricelistButton);

    return SetPricelistButton;
});
