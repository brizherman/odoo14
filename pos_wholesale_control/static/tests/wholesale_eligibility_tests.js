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

        function distributorOrder() {
            const order = Object.create(models.Order.prototype);
            order.pos = {currency: {rounding: 0.01}};
            order.wholesale = {
                pricingProgram: 'distributor',
                customerType: 'distribuidores',
                distributorMin: 10000,
                previousMonthMin: 800,
                currentOrderMin: 1500,
                months: [{is_current: true, amount: 5000}],
                override: false,
                historyLoaded: true,
                reasonCode: 'below_threshold',
            };
            order.get_client = function () {
                return {id: 7, customer_type: 'distribuidores'};
            };
            return order;
        }

        QUnit.test('distributor customers stay retail until ten thousand', function (assert) {
            assert.expect(6);
            const order = distributorOrder();
            assert.deepEqual(order._wholesaleDecide(10000, 1), {
                decision: 'wholesale',
                reason: 'previous_month',
                program: 'distributor',
            });
            assert.deepEqual(order._wholesaleDecide(0, 5000), {
                decision: 'wholesale',
                reason: 'current_order',
                program: 'distributor',
            });
            order.wholesale.months[0].amount = 10000;
            assert.deepEqual(order._wholesaleDecide(0, 0), {
                decision: 'wholesale',
                reason: 'current_month',
                program: 'distributor',
            });
            order.wholesale.months[0].amount = 0;
            assert.deepEqual(order._wholesaleDecide(800, 0), {
                decision: 'retail',
                reason: 'below_threshold',
                program: 'distributor',
            });
            order.wholesale.months[0].amount = 1200;
            assert.deepEqual(order._wholesaleDecide(0, 300), {
                decision: 'retail',
                reason: 'below_threshold',
                program: 'distributor',
            });
            order.wholesale.months[0].amount = 0;
            assert.deepEqual(order._wholesaleDecide(0, 100), {
                decision: 'retail',
                reason: 'below_threshold',
                program: 'distributor',
            });
        });

        QUnit.test('a restored distributor exception must match the ticket and customer', function (assert) {
            assert.expect(3);
            const order = distributorOrder();
            order.uid = 'ticket-a';
            order.get_client = function () {
                return {id: 7};
            };
            const saved = {
                customer_id: 7,
                pos_uid: 'ticket-a',
                override: {pricelist_id: 4},
            };
            assert.strictEqual(order._wholesaleRestoredOverride(saved).pricelist_id, 4);
            saved.customer_id = 8;
            assert.strictEqual(order._wholesaleRestoredOverride(saved), false);
            saved.customer_id = 7;
            saved.pos_uid = 'ticket-b';
            assert.strictEqual(order._wholesaleRestoredOverride(saved), false);
        });

        QUnit.test('a distributor exception blocks a customer change', function (assert) {
            assert.expect(2);
            const order = distributorOrder();
            order.wholesale.override = {pricelist_id: 4};
            assert.strictEqual(order._wholesaleBlocksCustomerChange({id: 7}), false);
            assert.strictEqual(order._wholesaleBlocksCustomerChange({id: 8}), true);
        });

        QUnit.test('a missing distributor mapping does not fall back to club', function (assert) {
            assert.expect(1);
            const order = distributorOrder();
            order.pos.wholesale_mapping_by_type = {};
            order.pos.wholesaleFindPricelist = function () {
                return {id: 3, name: 'Club Mayorista'};
            };
            order._wholesaleRetailPricelist = function () {
                return {id: 1, name: 'Public Pricelist'};
            };
            assert.strictEqual(order._wholesalePricelistForDecision('wholesale'), null);
        });
    });
});
