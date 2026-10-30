odoo.define('pos_wholesale_control.tests.ui', function (require) {
    'use strict';

    const models = require('point_of_sale.models');

    QUnit.module('pos_wholesale_control.ui', function () {
        QUnit.test('the cashier cannot keep a manually selected wholesale list', function (assert) {
            assert.expect(3);
            const order = Object.create(models.Order.prototype);
            const used = [];
            order.uid = 'ticket-ui';
            order.pos = {
                wholesaleControlActive: function () {
                    return true;
                },
            };
            order._wholesaleApplying = false;
            order._wholesaleRestoring = false;
            order.wholesale = {validationError: false};
            order._wholesaleAllowedPricelist = function () {
                return {id: 1, name: 'Public Pricelist'};
            };
            order._wholesaleUsePricelist = function (list) {
                used.push(list.id);
            };
            order.trigger = function () {};
            order.save_to_db = function () {};
            const result = order.set_pricelist({id: 99, name: 'Club Mayorista'});
            assert.strictEqual(result, undefined);
            assert.deepEqual(used, [1]);
            assert.ok(order.wholesale.validationError);
        });
    });
});
