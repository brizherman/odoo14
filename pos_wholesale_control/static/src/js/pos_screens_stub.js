odoo.define('point_of_sale.screens', function (require) {
    'use strict';
    // Odoo 14 removed point_of_sale.screens. custom_invoice.screens still
    // requires it, so the POS asset bundle never starts that file. This empty
    // module lets the bundle load. The include calls stay on this stub.
    var Screen = function () {};
    Screen.include = function () {};
    return {
        ReceiptScreenWidget: Screen,
        PaymentScreenWidget: Screen,
        ClientListScreenWidget: Screen,
    };
});
