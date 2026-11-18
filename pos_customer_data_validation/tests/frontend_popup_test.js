'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let Popup;
const translated = [];
class Base {
    constructor() {
        this.props = { partnerId: 1, isCurrent: () => true, resolve: result => { this.result = result; } };
        this.env = { pos: { config: { id: 2 } } };
    }
    trigger() {}
    cancel() { this.result = { confirmed: false }; }
}
vm.runInNewContext(fs.readFileSync('addons/custom/pos_customer_data_validation/static/src/js/CustomerDataPopup.js', 'utf8'), {
    owl: { hooks: { useState: value => value } },
    odoo: { define(name, factory) {
        Popup = factory(key => ({
            'point_of_sale.AbstractAwaitablePopup': Base,
            'point_of_sale.Registries': { Component: { add() {} } },
            'web.core': { _t: value => { translated.push(value); return value; } },
            'web.field_utils': { parse: { datetime: v => v }, format: { datetime: v => v } },
        })[key]);
    } },
});
function data() {
    return {
        partner: { id: 1, name: 'Customer', mobile: '123', customer_type: 'publico_general', property_product_pricelist: [5, 'Public'] },
        customer_types: [['publico_general', 'Public'], ['mayorista', 'Wholesale'], ['distribuidores', 'Distributor'], ['mayorista_dormido', 'Dormant']],
        pricelists: [{ id: 5 }, { id: 6 }, { id: 7 }],
        type_pricelist_ids: { publico_general: [5], mayorista: [6], distribuidores: [7], mayorista_dormido: [5] },
    };
}
async function setup() {
    const popup = new Popup();
    popup.rpc = async () => data();
    await popup.load();
    return popup;
}
async function run() {
    let p = await setup();
    let calls = 0;
    p.rpc = async () => { calls++; return data(); };
    Object.assign(p.state.values, { name: '  ', mobile: ' ', customer_type: '', property_product_pricelist: '' });
    await p.confirm();
    assert.equal(Object.keys(p.state.errors).length, 4);
    assert.equal(calls, 0);
    assert.equal(p.state.values.name, '  ');
    for (const type of data().customer_types.map(row => row[0])) {
        p = await setup();
        p.change({ target: { name: 'customer_type', value: type } });
        assert.equal(p.validate(), true, type);
        await p.confirm();
        assert.equal(p.result.confirmed, true);
    }
    p = await setup();
    p.data.partner.pos_mobile_updated_at = '2021-01-01 12:00:00';
    assert.equal(p.updatedAt('name'), 'Sin fecha registrada');
    assert.equal(p.updatedAt('mobile'), '2021-01-01 12:00:00');
    p.rpc = async request => { assert.equal(Object.keys(request.args[2]).length, 0); return data(); };
    await p.confirm();
    assert.equal(p.result.confirmed, true);
    p = await setup();
    p.state.values.mobile = '456';
    p.rpc = async () => { throw { data: { message: 'Permiso denegado' } }; };
    await p.confirm();
    assert.equal(p.state.error, 'Permiso denegado');
    assert.equal(p.state.values.mobile, '456');
    assert.equal(p.result, undefined);
    assert.equal(p.state.saving, false);
    p = await setup();
    let release;
    p.rpc = () => { calls++; return new Promise(resolve => { release = resolve; }); };
    calls = 0;
    const pending = p.confirm();
    await p.confirm();
    p.cancel();
    assert.equal(p.result, undefined, 'Cancellation must wait for in-flight save');
    assert.equal(calls, 1);
    p.props.isCurrent = () => false;
    release(data());
    await pending;
    assert.equal(p.result, undefined, 'Stale save response cannot confirm payment');
    p.cancel();
    assert.equal(p.result.confirmed, false);
    p = await setup();
    p.props.isCurrent = () => false;
    p.rpc = () => { throw new Error('A stale review must not send a save'); };
    await p.confirm();
    assert.equal(p.state.error, 'El ticket o cliente cambió. Cancela esta revisión y vuelve a validar.');
    assert.equal(p.state.saving, false);
    for (const message of ['Captura el nombre.', 'Captura el WhatsApp.',
        'Selecciona el tipo de cliente.', 'Selecciona una tarifa disponible.',
        'Sin fecha registrada', p.state.error]) {
        assert(translated.includes(message), 'Message must use _t: ' + message);
    }
    console.log('PASS: popup missing fields, four types, old/unknown dates, no-op confirmation, RPC rejection, repeated save and stale response');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
