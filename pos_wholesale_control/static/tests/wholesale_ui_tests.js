odoo.define('pos_wholesale_control.tests.ui', function (require) {
    'use strict';

    const models = require('point_of_sale.models');
    const PosComponent = require('point_of_sale.PosComponent');
    const makeTestEnvironment = require('web.test_env');
    const testUtils = require('web.test_utils');
    const { useListener } = require('web.custom_hooks');
    const { xml } = owl.tags;
    const { useState } = owl;

    require('pos_wholesale_control.WholesaleStatusPanel');
    require('point_of_sale.ActionpadWidget');

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

    function makeOrder(client, wholesale, pricelist) {
        return {
            wholesale: wholesale || {},
            pricelist: pricelist || null,
            get_client() {
                return client;
            },
            on() {},
            off() {},
            trigger() {},
        };
    }

    function fakePos(order, active) {
        return {
            wholesaleControlActive() {
                return active;
            },
            get_order() {
                return order;
            },
            format_currency(amount) {
                return 'MXN ' + (amount || 0);
            },
            on() {},
            off() {},
            previous() {
                return null;
            },
            config: {},
            employees: [],
        };
    }

    async function mountParent(assert, template, pos, extra) {
        class Parent extends PosComponent {
            constructor() {
                super(...arguments);
                useListener('click-customer', () => assert.step('click-customer'));
                this.state = useState({ client: extra.client || null });
            }
        }
        Parent.env = makeTestEnvironment(Object.assign({
            _t: (text) => text,
            pos: pos,
            isMobile: !!extra.isMobile,
        }, extra.env || {}));
        Parent.template = template;
        const parent = new Parent();
        await parent.mount(testUtils.prepareTarget());
        await testUtils.nextTick();
        return parent;
    }

    QUnit.module('pos_wholesale_control.layout', function () {
        QUnit.test('the panel is in the right pane before the product list', function (assert) {
            assert.expect(7);
            const env = makeTestEnvironment({
                _t: (text) => text,
                pos: fakePos(makeOrder(null), true),
            });
            const template = env.qweb.templates.ProductScreen;
            assert.ok(template, 'ProductScreen template is loaded');
            const rightpane = template.elem.querySelector('.rightpane');
            const tags = Array.from(rightpane.children).map((child) => child.tagName);
            const panelIndex = tags.indexOf('WholesaleStatusPanel');
            const productsIndex = tags.indexOf('ProductsWidget');
            assert.ok(panelIndex >= 0, 'panel is in the right pane');
            assert.ok(productsIndex >= 0, 'ProductsWidget stays in the right pane');
            assert.ok(panelIndex < productsIndex, 'panel is above the product widget');
            const panel = rightpane.children[panelIndex];
            assert.ok(panel.getAttribute('t-if').indexOf('wholesaleControlActive') >= 0);
            assert.ok(panel.getAttribute('t-if').indexOf('cashControl') >= 0);
            const leftpane = template.elem.querySelector('.leftpane');
            assert.strictEqual(leftpane.getElementsByTagName('WholesaleStatusPanel').length, 0);
        });

        QUnit.test('desktop shows one customer selector only while wholesale control is active', async function (assert) {
            assert.expect(4);
            const inactive = await mountParent(assert, xml`
                <div class="pos">
                    <ActionpadWidget client="state.client"/>
                </div>
            `, fakePos(makeOrder(null), false), { client: { name: 'Ada' }, isMobile: false });
            assert.strictEqual(inactive.el.querySelectorAll('button.set-customer').length, 1);
            inactive.destroy();

            const active = await mountParent(assert, xml`
                <div class="pos">
                    <ActionpadWidget client="state.client"/>
                    <WholesaleStatusPanel/>
                </div>
            `, fakePos(makeOrder(null), true), { client: { name: 'Ada' }, isMobile: false });
            assert.strictEqual(active.el.querySelectorAll('button.set-customer').length, 0);
            assert.strictEqual(active.el.querySelectorAll('button.wholesale-customer-button').length, 1);
            assert.strictEqual(active.el.querySelectorAll('button.pay').length, 1);
            active.destroy();
        });

        QUnit.test('mobile keeps the order-pane customer button because the product pane is the other screen', async function (assert) {
            assert.expect(2);
            const parent = await mountParent(assert, xml`
                <div class="pos">
                    <ActionpadWidget client="state.client"/>
                    <WholesaleStatusPanel/>
                </div>
            `, fakePos(makeOrder(null), true), { client: { name: 'Ada' }, isMobile: true });
            assert.strictEqual(parent.el.querySelectorAll('button.set-customer').length, 1);
            assert.strictEqual(parent.el.querySelectorAll('button.wholesale-customer-button').length, 1);
            parent.destroy();
        });

        QUnit.test('the customer button emits click-customer for the product screen', async function (assert) {
            assert.expect(2);
            const parent = await mountParent(assert, xml`
                <div class="pos"><WholesaleStatusPanel/></div>
            `, fakePos(makeOrder(null), true), {});
            const button = parent.el.querySelector('button.wholesale-customer-button');
            await testUtils.dom.click(button);
            await testUtils.nextTick();
            assert.verifySteps(['click-customer']);
            assert.strictEqual(button.getAttribute('aria-label'), 'Choose customer');
            parent.destroy();
        });

        QUnit.test('the panel renders customer, pricing, error, loading, and month states', async function (assert) {
            assert.expect(16);
            const empty = await mountParent(assert, xml`
                <div class="pos"><WholesaleStatusPanel/></div>
            `, fakePos(makeOrder(null, {}), true), {});
            assert.ok(empty.el.querySelector('.wholesale-state-retail'));
            assert.ok(empty.el.textContent.includes('Choose customer'));
            assert.ok(empty.el.textContent.includes('Retail / General Public'));
            assert.ok(empty.el.textContent.includes('Identify a customer'));
            assert.strictEqual(empty.el.querySelector('.wholesale-month'), null);
            assert.strictEqual(empty.el.querySelector('.wholesale-customer-button').closest('[aria-live]'), null);
            empty.destroy();

            const selected = await mountParent(assert, xml`
                <div class="pos"><WholesaleStatusPanel/></div>
            `, fakePos(makeOrder(
                { name: 'Janett Alejandra Meza Cota', customer_type: 'mayorista' },
                {
                    customerType: 'mayorista',
                    automaticDecision: 'wholesale',
                    reasonText: 'Previous month reached the minimum.',
                    months: [
                        { label: 'septiembre 2026', amount: 10, is_current: false },
                        { label: 'octubre 2026', amount: 20, is_current: false },
                        { label: 'noviembre 2026', amount: 30, is_current: true },
                    ],
                },
                { name: 'Club Mayorista' }
            ), true), {});
            assert.ok(selected.el.querySelector('.wholesale-state-wholesale'));
            assert.ok(selected.el.textContent.includes('Janett Alejandra Meza Cota'));
            assert.ok(selected.el.textContent.includes('Mayorista'));
            assert.ok(selected.el.textContent.includes('Club Mayorista'));
            assert.ok(selected.el.textContent.includes('Previous month reached the minimum.'));
            assert.strictEqual(selected.el.querySelectorAll('.wholesale-month').length, 3);
            assert.ok(selected.el.textContent.includes('MTD'));
            assert.strictEqual(selected.el.querySelector('.wholesale-override-button'), null);
            selected.destroy();

            const problem = await mountParent(assert, xml`
                <div class="pos"><WholesaleStatusPanel/></div>
            `, fakePos(makeOrder(
                { name: 'Ada', customer_type: 'publico_general' },
                { loading: true, error: 'History unavailable', validationError: false }
            ), true), {});
            assert.ok(problem.el.querySelector('.wholesale-state-loading'));
            assert.ok(problem.el.querySelector('.wholesale-status-error'));
            problem.destroy();
        });

        QUnit.test('manager override stays available only for the existing conditions', async function (assert) {
            assert.expect(4);
            const retail = await mountParent(assert, xml`
                <div class="pos"><WholesaleStatusPanel/></div>
            `, fakePos(makeOrder(
                { name: 'Ada', customer_type: 'publico_general' },
                { automaticDecision: 'retail', reasonText: 'Below the minimum.' }
            ), true), {});
            assert.ok(retail.el.querySelector('.wholesale-override-button'));
            assert.ok(retail.el.querySelector('.wholesale-state-retail'));
            retail.destroy();

            const blocked = await mountParent(assert, xml`
                <div class="pos"><WholesaleStatusPanel/></div>
            `, fakePos(makeOrder(
                { name: 'Ada', customer_type: 'mayorista' },
                {
                    automaticDecision: 'wholesale',
                    reasonText: 'Qualified.',
                    override: { pricelist_id: 9, final_decision: 'wholesale' },
                }
            ), true), {});
            assert.strictEqual(blocked.el.querySelector('.wholesale-override-button'), null);
            assert.ok(blocked.el.querySelector('.wholesale-state-override'));
            blocked.destroy();
        });

        QUnit.test('long text wraps inside the desktop and narrow bar widths', async function (assert) {
            assert.expect(4);
            const longName = 'Cliente con un nombre excepcional que no debe tapar las categorias';
            const parent = await mountParent(assert, xml`
                <div class="pos"><WholesaleStatusPanel/></div>
            `, fakePos(makeOrder(
                { name: longName, customer_type: 'distribuidores' },
                {
                    customerType: 'distribuidores',
                    automaticDecision: 'retail',
                    reasonText: 'Ni el mes anterior ni este pedido alcanzan el minimo de mayoreo publicado para la sucursal.',
                },
                { name: 'Super Precios a Distribuidores con nombre largo' }
            ), true), {});
            const panel = parent.el.querySelector('.wholesale-status-panel');
            parent.el.style.width = '520px';
            await testUtils.nextTick();
            assert.ok(panel.scrollWidth <= panel.clientWidth + 1, 'desktop right pane does not overflow at 520px');
            parent.el.style.width = '320px';
            await testUtils.nextTick();
            assert.ok(panel.scrollWidth <= panel.clientWidth + 1, 'narrow width does not overflow at 320px');
            const buttonText = parent.el.querySelector('.wholesale-customer-button-text');
            const valueStyle = window.getComputedStyle(parent.el.querySelector('.wholesale-status-value'));
            assert.strictEqual(valueStyle.overflowWrap, 'anywhere');
            assert.ok(buttonText.textContent.includes(longName));
            parent.destroy();
        });
    });
});
