odoo.define('alta_mayoristas.models', function (require) {
    'use strict';

    const models = require('point_of_sale.models');

    models.load_fields('res.partner', ['customer_type']);
});
