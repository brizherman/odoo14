/* Run with node from the repository root. Uses the frozen core and optional
 * extensions directly; no production data or network is used. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const root = 'source/odoo14-server/addons/point_of_sale/static/src/js/';
const own = 'addons/custom/pos_customer_data_validation/static/src/js/';
const extensions = [];
const modules = {};
const hooks = {
    useAsyncLockedMethod(fn) {
        let busy = false;
        return async function (...args) {
            if (busy) return;
            busy = true;
            try { return await fn.apply(currentScreen, args); } finally { busy = false; }
        };
    },
};
for (const name of ['useListener', 'useErrorHandlers', 'onChangeOrder']) hooks[name] = () => {};
let currentScreen;
class PosComponent {
    constructor(env) { this.env = env; currentScreen = this; }
    showPopup(name, props) { return this.env.popup(name, props); }
    showScreen(name) { this.env.screens.push(name); }
    rpc(...args) { return this.env.rpc(...args); }
}
Object.assign(modules, {
    'point_of_sale.PosComponent': PosComponent,
    'point_of_sale.Registries': { Component: { add() {}, extend(base, fn) { extensions.push(fn); } } },
    'point_of_sale.custom_hooks': hooks, 'web.custom_hooks': hooks,
    'point_of_sale.NumberBuffer': { use() {}, reset() {} },
    'web.field_utils': { parse: {} },
    'web.core': { _t: x => x },
    'point_of_sale.Gui': { Gui: { showPopup() {} } },
});
function load(file) {
    const sandbox = {
        odoo: { define(name, factory) { modules[name] = factory(key => {
            assert(key in modules, 'Unknown dependency: ' + key);
            return modules[key];
        }); } },
        owl: { hooks }, setTimeout, clearTimeout, console,
    };
    vm.runInNewContext(fs.readFileSync(file, 'utf8'), sandbox, { filename: file });
}
load(root + 'Screens/PaymentScreen/PaymentScreen.js');
const core = modules['point_of_sale.PaymentScreen'];
extensions.length = 0;
load('addons/custom/production/pos_wholesale_control/static/src/js/PaymentScreen.js');
load('addons/third-party/production/odf_pos_salesperson/static/src/js/PaymentScreen.js');
const optional = extensions.splice(0);
load(own + 'PaymentScreen.js');
const review = extensions.pop();
function deferred() {
    let resolve;
    const promise = new Promise(r => { resolve = r; });
    return { promise, resolve };
}
function setup(ordering = [review, ...optional]) {
    const client = { id: 7, name: 'Customer', mobile: '123', customer_type: 'publico_general', property_product_pricelist: [1, 'Public'] };
    const listeners = new Map();
    const order = {
        client, pricelist: { id: 99 }, wholesale: { loading: false }, total: 10, paid: 10, sent: 0,
        salesperson: true, lines: [{ id: 1 }], payments: [{ is_done: () => true }],
        get_client() { return this.client; }, get_orderlines() { return this.lines; },
        get_paymentlines() { return this.payments; }, is_to_invoice: () => false,
        is_paid() { return this.paid >= this.total; }, has_not_valid_rounding: () => false,
        get_total_with_tax() { return this.total; }, get_total_paid() { return this.paid; },
        get_rounding_applied: () => 0, is_salesperson_set() { return this.salesperson; },
        trigger(event) { for (const fn of [...(listeners.get(event) || [])]) fn(); },
        on(event, fn) { if (!listeners.has(event)) listeners.set(event, new Set()); listeners.get(event).add(fn); },
        off(event, fn) { if (listeners.has(event)) listeners.get(event).delete(fn); },
        updatePricelist() { this.total = 20; }, save_to_db() {},
        export_as_JSON() { return { partner_id: this.client && this.client.id, total: this.total, paid: this.paid }; },
    };
    const calls = [];
    const env = {
        _t: x => x, screens: [],
        popup: async (name) => {
            calls.push(name);
            return { confirmed: true, payload: { partner: { ...client } } };
        },
        pos: {
            get_order: () => order, on() {}, off() {},
            config: { id: 1, payment_method_ids: [1] },
            payment_methods: [{ id: 1, is_cash_count: true }],
            db: { partner_write_date: 'old', add_partners() {} },
            wholesaleControlActive: () => false,
            format_currency: String,
        },
    };
    const Final = ordering.reduce((Base, ext) => ext(Base), core);
    const screen = new Final(env);
    screen._finalizeValidation = async () => { order.sent++; };
    return { screen, order, client, env, calls };
}
async function run() {
    for (const ordering of [[review, ...optional], [...optional, review]]) {
        let x = setup(ordering);
        await x.screen.lockedValidateOrder();
        assert.equal(x.order.sent, 1);
        assert.equal(x.calls[0], 'CustomerDataPopup');
        assert.equal(x.order.pricelist.id, 99, 'Ticket pricelist may differ from customer');
        x = setup(ordering);
        x.order.client = null;
        await x.screen.lockedValidateOrder();
        assert.equal(x.calls.length, 0);
        assert.equal(x.order.sent, 1);
        x = setup(ordering);
        x.env.popup = async name => { x.calls.push(name); return { confirmed: false }; };
        await x.screen.lockedValidateOrder();
        assert.equal(x.order.sent, 0);
        assert.equal(x.order.lines.length, 1);
        assert.equal(x.order.payments.length, 1);
        x = setup(ordering);
        x.env.popup = async name => {
            x.calls.push(name);
            return { confirmed: true, payload: { partner: { ...x.client, property_product_pricelist: [2, 'Other'] } } };
        };
        await x.screen.lockedValidateOrder();
        assert.equal(x.order.total, 20);
        assert.equal(x.order.sent, 0, 'Insufficient payment after repricing must block');
        assert.equal(x.order.payments.length, 1);
        assert.equal(x.env.pos.db.partner_write_date, 'old');
    }
    let x = setup();
    const confirm = deferred();
    x.order.paid = 10001;
    const originalExport = x.order.export_as_JSON.bind(x.order);
    let exportClock = 0;
    x.order.export_as_JSON = () => ({ ...originalExport(), statement_ids: [
        [0, 0, { name: String(++exportClock), amount: x.order.paid }],
    ] });
    x.env.popup = async name => {
        x.calls.push(name);
        if (name === 'ConfirmPopup') return confirm.promise;
        return { confirmed: true, payload: { partner: { ...x.client } } };
    };
    await x.screen.lockedValidateOrder();
    assert.equal(x.order.sent, 0);
    confirm.resolve({ confirmed: true });
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(x.order.sent, 1, 'Large amount must continue exactly once');
    assert.equal(x.calls.filter(name => name === 'CustomerDataPopup').length, 1);
    x = setup();
    x.order.salesperson = false;
    await x.screen.lockedValidateOrder();
    assert.equal(x.order.sent, 0, 'Salesperson extension must still block');
    x = setup();
    x.env.pos.wholesaleControlActive = () => true;
    x.order.updatePricelist = () => {};
    x.screen._wholesaleBlockingMessage = async () => 'Commercial rejection';
    await x.screen.lockedValidateOrder();
    assert.deepEqual(x.calls, ['CustomerDataPopup', 'ErrorPopup']);
    assert.equal(x.order.sent, 0, 'Wholesale extension must still block');
    x = setup();
    const late = deferred();
    x.env.popup = name => { x.calls.push(name); return late.promise; };
    const pending = x.screen.lockedValidateOrder();
    await x.screen.lockedValidateOrder();
    assert.equal(x.calls.length, 1, 'Repeated validate must not open another popup');
    x.order.trigger('change:client');
    late.resolve({ confirmed: true, payload: { partner: { ...x.client } } });
    await pending;
    assert.equal(x.order.sent, 0, 'Client changed away and back must invalidate review');
    assert.equal(x.screen.customerDataPending, null);
    x = setup();
    const commercial = deferred();
    x.env.pos.wholesaleControlActive = () => true;
    x.order.updatePricelist = () => {};
    x.screen._wholesaleBlockingMessage = () => commercial.promise;
    const commercialPending = x.screen.lockedValidateOrder();
    await new Promise(resolve => setTimeout(resolve, 0));
    x.order.trigger('change:client');
    commercial.resolve(false);
    await commercialPending;
    assert.equal(x.order.sent, 0, 'Changing context during commercial check must block');
    console.log('PASS: entry order, unchanged confirmation, anonymous ticket, cancel and insufficient payment after repricing');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
