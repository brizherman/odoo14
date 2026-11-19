odoo.define('pos_customer_data_validation.PosConfig', function (require) {
    'use strict';

    const models = require('point_of_sale.models');
    models.load_fields('pos.config', ['customer_data_review_enabled']);
});
