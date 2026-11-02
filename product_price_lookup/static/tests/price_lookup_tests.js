odoo.define('product_price_lookup.tests', function (require) {
    'use strict';

    const makeTestEnvironment = require('web.test_env');
    const testUtils = require('web.test_utils');
    const PosComponent = require('point_of_sale.PosComponent');
    const PopupControllerMixin = require('point_of_sale.PopupControllerMixin');
    const Registries = require('point_of_sale.Registries');
    const BarcodeReader = require('point_of_sale.BarcodeReader');
    const { xml } = owl.tags;

    require('product_price_lookup.PriceLookupPopup');

    QUnit.module('product_price_lookup', {
        before: function () {
            Registries.Component.freeze();
        },
    });

    QUnit.test('a scan in the lookup does not change the open order', async function (assert) {
        assert.expect(6);
        const order = {
            pricelist: {id: 42, name: 'Public Pricelist'},
            lines: [{id: 1}],
            get_orderlines: function () {
                return this.lines;
            },
            add_product: function () {
                this.lines.push({id: 99});
            },
            set_pricelist: function (list) {
                this.pricelist = list;
            },
        };
        const screenScans = [];
        let lookupOpen = true;
        const reader = new BarcodeReader({
            pos: {},
            proxy: {},
            barcode_parser: {
                parse_barcode: function (code) {
                    return {
                        type: 'product',
                        code: code,
                        base_code: code,
                        value: 0,
                    };
                },
            },
        });
        reader.set_action_callback('product', function () {
            screenScans.push('product');
            if (lookupOpen) {
                order.add_product();
            }
        });
        const env = makeTestEnvironment({
            pos: {
                config: {company_id: [1, 'Branch']},
                barcode_reader: reader,
                get_order: function () {
                    return order;
                },
            },
        }, function (route, params) {
            if (params && params.model === 'product.price.lookup') {
                return Promise.resolve({
                    state: 'prices',
                    message: false,
                    product: {
                        id: 1,
                        name: 'Caja',
                        default_code: 'CB7P',
                        barcode: '750',
                    },
                    matches: [],
                    prices: [{
                        label: 'Público General',
                        amount: 430.1,
                        currency: 'MXN',
                        display: 'MXN 430.10',
                    }],
                });
            }
            return Promise.resolve();
        });

        class Root extends PopupControllerMixin(PosComponent) {}
        Root.template = xml`
            <div>
                <t t-if="popup.isShown" t-component="popup.component" t-props="popupProps" t-key="popup.name"/>
            </div>
        `;
        Root.env = env;

        const root = new Root();
        await root.mount(testUtils.prepareTarget());
        const popupPromise = root.showPopup('PriceLookupPopup');
        await testUtils.nextTick();
        await testUtils.nextTick();

        reader.scan('7501234567890');
        await testUtils.nextTick();
        await testUtils.nextTick();

        assert.strictEqual(screenScans.length, 0);
        assert.strictEqual(order.get_orderlines().length, 1);

        testUtils.dom.click(root.el.querySelector('.cancel'));
        await testUtils.nextTick();
        await popupPromise;
        await testUtils.nextTick();
        lookupOpen = false;

        assert.strictEqual(order.get_orderlines().length, 1);
        assert.strictEqual(order.pricelist.id, 42);

        reader.scan('7501234567890');
        assert.strictEqual(screenScans.length, 1);
        assert.strictEqual(order.get_orderlines().length, 1);

        root.unmount();
        root.destroy();
    });
});
