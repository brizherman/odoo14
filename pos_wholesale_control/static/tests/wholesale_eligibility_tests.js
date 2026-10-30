odoo.define('pos_wholesale_control.tests.eligibility', function (require) {
    'use strict';

    const models = require('point_of_sale.models');

    QUnit.module('pos_wholesale_control.eligibility', function () {
        function bareOrder() {
            const order = Object.create(models.Order.prototype);
            order._wholesaleDestroyed = false;
            order.wholesale = {
                requestVersion: 2,
                customerId: 20,
            };
            order.get_client = function () {
                return {id: 20, customer_type: 'mayorista'};
            };
            order.applied = [];
            order.failed = 0;
            order._wholesaleApplyServer = function () {
                order.applied.push('server');
            };
            order._wholesaleApplyHistoryFailure = function () {
                order.failed += 1;
            };
            return order;
        }

        QUnit.test('a stale customer response does not replace the new customer', function (assert) {
            assert.expect(4);
            const order = bareOrder();
            order._wholesaleAcceptResponse(1, 10, {
                customer_id: 10,
                automatic_decision: 'wholesale',
                reason_code: 'previous_month',
            });
            order._wholesaleAcceptFailure(1, 10);
            assert.strictEqual(order.applied.length, 0);
            assert.strictEqual(order.failed, 0);
            assert.strictEqual(order.wholesale.customerId, 20);
            assert.strictEqual(order.wholesale.requestVersion, 2);
        });

        QUnit.test('a response for a different customer is ignored', function (assert) {
            assert.expect(2);
            const order = bareOrder();
            order._wholesaleAcceptResponse(2, 10, {
                customer_id: 10,
                automatic_decision: 'wholesale',
            });
            assert.strictEqual(order.applied.length, 0);
            assert.strictEqual(order.wholesale.customerId, 20);
        });

        QUnit.test('the current response is applied to the selected customer', function (assert) {
            assert.expect(1);
            const order = bareOrder();
            order._wholesaleAcceptResponse(2, 20, {
                customer_id: 20,
                automatic_decision: 'retail',
                reason_code: 'below_threshold',
            });
            assert.deepEqual(order.applied, ['server']);
        });

        QUnit.test('history failure stays retail unless this ticket has an override', function (assert) {
            assert.expect(4);
            const order = Object.create(models.Order.prototype);
            order.wholesale = {override: false};
            const used = [];
            order._wholesaleReasonText = function () {
                return 'No se pudo consultar el historial de compras.';
            };
            order._wholesaleRetailAmount = function () {
                return 1500;
            };
            order._wholesaleRetailPricelist = function () {
                return {id: 1, name: 'Public Pricelist'};
            };
            order._wholesaleAllowedPricelist = function () {
                return {id: 9, name: 'Club Mayorista'};
            };
            order._wholesaleUsePricelist = function (list) {
                used.push(list.id);
            };
            order.wholesale.override = false;
            order._wholesaleApplyHistoryFailure();
            assert.strictEqual(order.wholesale.reasonCode, 'history_unavailable');
            assert.strictEqual(order.wholesale.automaticDecision, 'retail');
            assert.strictEqual(used[0], 1);
            order.wholesale.override = {pricelist_id: 9};
            order._wholesaleApplyHistoryFailure();
            assert.strictEqual(used[1], 9);
        });
    });
});
