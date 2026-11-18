/* Host browser fallback for the preserved runtime, which has no Chromium.
 * Usage: PLAYWRIGHT_MODULE=/path/to/@playwright/test node .../browser_regression.cjs
 *        http://TEST_CONTAINER_IP:8069 /tmp/fixture.json /tmp/evidence */
'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { chromium, expect } = require(process.env.PLAYWRIGHT_MODULE || '@playwright/test');
const [base, fixtureFile, output] = process.argv.slice(2);
const fixture = JSON.parse(fs.readFileSync(fixtureFile, 'utf8'));
const results = [];
let browser;
async function run() {
    fs.mkdirSync(output, { recursive: true });
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM || '/usr/bin/chromium', headless: true });
    const page = await browser.newPage({ viewport: { width: 1366, height: 1000 } });
    page.setDefaultTimeout(15000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + '/web/login?db=' + fixture.database);
    await page.locator('input[name=login]').fill(fixture.login);
    await page.locator('input[name=password]').fill('customer-review-ui-test');
    await Promise.all([page.waitForURL(url => !url.pathname.includes('login')), page.locator('button[type=submit]').click()]);
    await page.goto(base + '/pos/ui?config_id=' + fixture.config_id + '&debug=assets');
    await page.locator('.product-screen').waitFor({ timeout: 90000 });
    async function rpc(model, method, args, kwargs = {}) {
        return page.evaluate(async ({ model, method, args, kwargs }) => {
            const response = await fetch('/web/dataset/call_kw/' + model + '/' + method, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: { model, method, args, kwargs } }),
            });
            const data = await response.json();
            if (data.error) throw new Error(data.error.data.message);
            return data.result;
        }, { model, method, args, kwargs });
    }
    async function count() {
        const session = await page.evaluate(() => window.posmodel.pos_session.id);
        return rpc('pos.order', 'search_count', [[['session_id', '=', session]]]);
    }
    async function partner(id) {
        return (await rpc('res.partner', 'pos_customer_data_read', [id, fixture.config_id])).partner;
    }
    async function ticket(id) {
        await page.evaluate(({ id, product, salesperson }) => {
            const pos = window.posmodel;
            pos.add_new_order();
            const order = pos.get_order();
            if (id) {
                const client = pos.db.get_partner_by_id(id);
                order.set_client(client);
                order.updatePricelist(client);
            }
            order.add_product(pos.db.get_product_by_id(product));
            if (salesperson) order.set_salesperson(pos.pos_salespersons_by_id[salesperson]);
        }, { id, product: fixture.product_id, salesperson: fixture.salesperson_id });
        await page.locator('.pay').click();
        await page.locator('.paymentmethod').filter({ hasText: 'Review Cash' }).click();
    }
    const popup = page.locator('.pos-customer-data-popup');
    async function review() {
        await page.locator('.payment-screen .next').click();
        await popup.locator('input[name=name]').waitFor();
    }
    const start = await count();
    await ticket(null);
    await page.locator('.payment-screen .next').click();
    await page.locator('.receipt-screen').waitFor();
    assert.equal(await popup.count(), 0);
    assert.equal(await count(), start + 1);
    results.push('Anonymous ticket follows normal payment flow');

    await ticket(fixture.partner_id);
    const before = await partner(fixture.partner_id);
    await review();
    await expect(popup.locator('[name=name]')).toHaveValue(before.name);
    await popup.locator('[name=name]').fill('Discard this edit');
    await popup.locator('.cancel').click();
    assert.equal((await partner(fixture.partner_id)).name, before.name);
    assert.equal(await count(), start + 1);
    assert.deepEqual(await page.evaluate(() => [window.posmodel.get_order().get_orderlines().length, window.posmodel.get_order().get_paymentlines().length]), [1, 1]);
    await review();
    await popup.locator('.confirm').click();
    await page.locator('.receipt-screen').waitFor();
    assert.equal(await count(), start + 2);
    assert.deepEqual(await partner(fixture.partner_id), before);
    results.push('Complete customer reviewed on every attempt; cancel preserves ticket; unchanged confirmation preserves dates');

    await ticket(fixture.historical_id);
    const old = await partner(fixture.historical_id);
    await review();
    await expect(popup).toContainText('Sin fecha registrada');
    await expect(popup).toContainText('2021');
    await popup.screenshot({ path: output + '/historical-popup.png' });
    for (const name of ['name', 'mobile']) await popup.locator('[name=' + name + ']').fill('  ');
    await popup.locator('[name=customer_type]').selectOption('');
    await popup.locator('[name=property_product_pricelist]').selectOption('');
    await popup.locator('.confirm').click();
    await expect(popup.locator('.customer-data-error')).toHaveCount(4);
    assert.equal(await count(), start + 2);
    await popup.locator('[name=name]').fill(old.name);
    await popup.locator('[name=mobile]').fill(old.mobile);
    await popup.locator('[name=customer_type]').selectOption(old.customer_type);
    await popup.locator('.confirm').click();
    await page.locator('.receipt-screen').waitFor();
    assert.deepEqual(await partner(fixture.historical_id), old);
    results.push('All missing fields shown together; old and unknown dates visible; old data confirm without date changes');

    await rpc('res.partner', 'write', [[fixture.partner_id], { mobile: '6641111111' }]);
    await ticket(fixture.partner_id);
    await review();
    await expect(popup.locator('[name=mobile]')).toHaveValue('6641111111');
    const fresh = await partner(fixture.partner_id);
    await popup.locator('[name=mobile]').fill('6642222222');
    await popup.locator('.confirm').click();
    await page.locator('.receipt-screen').waitFor();
    const changed = await partner(fixture.partner_id);
    assert.equal(changed.mobile, '6642222222');
    assert.equal(changed.pos_name_updated_at, fresh.pos_name_updated_at);
    assert.equal(changed.pos_customer_type_updated_at, fresh.pos_customer_type_updated_at);
    assert.equal(changed.pos_pricelist_updated_at, fresh.pos_pricelist_updated_at);
    results.push('Backend edit loaded freshly; mobile correction persisted without changing other dates');

    const saveUrl = '**/web/dataset/call_kw/res.partner/pos_customer_data_save';
    await ticket(fixture.partner_id);
    await review();
    await popup.locator('[name=mobile]').fill('6643333333');
    const blockedCount = await count();
    await page.route(saveUrl, route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ jsonrpc: '2.0', error: { code: 200, message: 'Odoo Server Error', data: { name: 'odoo.exceptions.AccessError', message: 'Permiso de prueba denegado', arguments: ['Permiso de prueba denegado'], debug: '' } } }) }));
    await popup.locator('.confirm').click();
    await expect(popup).toContainText('Permiso de prueba denegado');
    await expect(popup.locator('[name=mobile]')).toHaveValue('6643333333');
    assert.equal(await count(), blockedCount);
    await page.unroute(saveUrl);
    await page.route(saveUrl, route => route.abort());
    await popup.locator('.confirm').click();
    await expect(popup).toContainText('Revisa la conexión');
    assert.equal(await count(), blockedCount);
    await page.unroute(saveUrl);
    await popup.locator('.cancel').click();
    results.push('Permission and connection failures retain edits and do not submit an order');

    await ticket(fixture.partner_id);
    await review();
    let release;
    let requests = 0;
    const hold = new Promise(resolve => { release = resolve; });
    await page.route(saveUrl, async route => { requests++; await hold; await route.continue(); });
    await popup.locator('.confirm').dblclick({ force: true });
    await expect(popup.locator('.confirm')).toBeDisabled();
    await expect(popup.locator('.cancel')).toBeDisabled();
    await page.keyboard.press('Escape');
    assert.equal(await popup.count(), 1);
    release();
    await page.locator('.receipt-screen').waitFor();
    assert.equal(requests, 1);
    assert.equal(await count(), blockedCount + 1);
    await page.unroute(saveUrl);
    results.push('Double Save sends one RPC and one order; Escape cannot cancel a submitted save');

    await ticket(fixture.partner_id);
    await review();
    let releaseLate;
    const late = new Promise(resolve => { releaseLate = resolve; });
    await page.route(saveUrl, async route => { await late; await route.continue(); });
    await popup.locator('.confirm').click();
    await expect(popup.locator('.confirm')).toBeDisabled();
    await page.evaluate(() => window.posmodel.add_new_order());
    releaseLate();
    await expect(popup).toContainText('El ticket o cliente cambió');
    assert.equal(await count(), blockedCount + 1);
    await page.unroute(saveUrl);
    await popup.locator('.cancel').click();
    results.push('Changing tickets while save is pending prevents late payment continuation');
    await ticket(fixture.partner_id);
    await review();
    let releaseClient;
    const clientResponse = new Promise(resolve => { releaseClient = resolve; });
    await page.route(saveUrl, async route => { await clientResponse; await route.continue(); });
    const beforeClientChange = await count();
    await popup.locator('.confirm').click();
    await expect(popup.locator('.confirm')).toBeDisabled();
    await page.evaluate(() => window.posmodel.get_order().set_client(null));
    releaseClient();
    await expect(popup).toContainText('El ticket o cliente cambió');
    assert.equal(await count(), beforeClientChange);
    await page.unroute(saveUrl);
    await popup.locator('.cancel').click();
    results.push('Changing customers while save is pending prevents late payment continuation');

    await ticket(fixture.partner_id);
    let readRequests = 0;
    const countReads = request => { if (request.url().endsWith('/pos_customer_data_read')) readRequests++; };
    page.on('request', countReads);
    await page.locator('.payment-screen .next').evaluate(element => { element.click(); element.click(); });
    await popup.locator('input[name=name]').waitFor();
    assert.equal(await popup.count(), 1);
    assert.equal(readRequests, 1);
    page.off('request', countReads);
    await popup.locator('[name=customer_type]').selectOption('mayorista_dormido');
    await popup.locator('.confirm').click();
    await page.locator('.receipt-screen').waitFor();
    assert.equal((await partner(fixture.partner_id)).customer_type, 'mayorista_dormido');
    results.push('Double Validate opens one review; dormant wholesale customer type is accepted');

    await ticket(fixture.partner_id);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('.btn-switchpane').filter({ hasText: 'Validate' }).click();
    await popup.locator('input[name=name]').waitFor();
    await popup.screenshot({ path: output + '/mobile-popup.png' });
    await popup.locator('.cancel').click();
    await page.setViewportSize({ width: 1366, height: 1000 });
    results.push('Mobile Validate button also opens review and cancellation preserves the ticket');
    if (fixture.salesperson_id) {
        await ticket(fixture.partner_id);
        await page.evaluate(() => window.posmodel.get_order().set_salesperson(null));
        const beforeVendor = await count();
        await review();
        await popup.locator('.confirm').click();
        await expect(page.locator('.popup-error')).toContainText('Please select sales person.');
        assert.equal(await count(), beforeVendor);
        await page.locator('.popup-error .button').first().click();
        await page.evaluate(id => window.posmodel.get_order().set_salesperson(window.posmodel.pos_salespersons_by_id[id]), fixture.salesperson_id);
        await review();
        await popup.locator('.confirm').click();
        await page.locator('.receipt-screen').waitFor();
        assert.equal(await count(), beforeVendor + 1);
        results.push('Missing salesperson still blocks after review; a new attempt reviews again and can finish');

        await ticket(fixture.partner_id);
        // Refresh and precheck must see different server decisions to exercise
        // the real commercial rejection rather than replacing its UI method.
        const eligibilityUrl = '**/web/dataset/call_kw/res.partner/get_wholesale_eligibility';
        await review();
        let eligibilityRequests = 0;
        await page.route(eligibilityUrl, async route => {
            const response = await route.fetch();
            const body = await response.json();
            eligibilityRequests++;
            if (eligibilityRequests >= 2) {
                body.result.expected_pricelist = { id: fixture.pricelist_ids[1], name: 'Changed commercial decision' };
            }
            await route.fulfill({ response, json: body });
        });
        const beforeCommercial = await count();
        await popup.locator('.confirm').click();
        await expect(page.locator('.popup-error')).toContainText('No se puede cobrar');
        assert.equal(await count(), beforeCommercial);
        assert.equal(eligibilityRequests, 2);
        await page.unroute(eligibilityUrl);
        await page.locator('.popup-error .button').first().click();
        results.push('Wholesale server precheck rejection is preserved after a successful customer review');

        await ticket(fixture.partner_id);
        await page.evaluate(() => {
            const order = window.posmodel.get_order();
            order.get_selected_orderline().set_quantity(200);
        });
        await review();
        await popup.locator('[name=customer_type]').selectOption('mayorista');
        const repricedCount = await count();
        await popup.locator('.confirm').click();
        // The old cash payment was 10, so the recalculated total must keep
        // this ticket open until the cashier supplies the missing payment.
        await expect(popup).toHaveCount(0);
        await page.waitForFunction(() => !window.posmodel.get_order().wholesale.loading);
        const pricing = await page.evaluate(() => ({
            total: window.posmodel.get_order().get_total_with_tax(),
            price: window.posmodel.get_order().pricelist.id,
            paid: window.posmodel.get_order().get_total_paid(),
        }));
        assert.equal(pricing.price, fixture.pricelist_ids[1]);
        assert.equal(pricing.total, 1200);
        assert.equal(pricing.paid, 10);
        assert.equal(await count(), repricedCount);
        results.push('Customer type correction waits for wholesale repricing; insufficient existing payment blocks finalization');
    }
    await ticket(fixture.partner_id);
    await page.evaluate(() => window.posmodel.get_order().get_paymentlines()[0].set_amount(100000));
    let reviewCalls = 0;
    const observeReview = request => { if (request.url().endsWith('/pos_customer_data_read')) reviewCalls++; };
    page.on('request', observeReview);
    await review();
    const beforeLarge = await count();
    await popup.locator('.confirm').click();
    await expect(page.locator('.popup-confirm')).toContainText('Please Confirm Large Amount');
    await page.locator('.popup-confirm .confirm').click();
    await page.locator('.receipt-screen').waitFor();
    assert.equal(await count(), beforeLarge + 1);
    assert.equal(reviewCalls, 1);
    page.off('request', observeReview);
    results.push('Large amount confirmation continues once without reopening the review');
    assert.deepEqual(errors, [], 'No uncaught browser errors');
    fs.writeFileSync(output + '/browser-results.json', JSON.stringify({ database: fixture.database, browser: await browser.version(), results }, null, 2));
    console.log(JSON.stringify({ passed: results.length, results }, null, 2));
}
run().then(() => browser.close()).catch(async error => {
    console.error(error);
    fs.mkdirSync(output, { recursive: true });
    if (browser) {
        const pages = browser.contexts().flatMap(context => context.pages());
        if (pages[0]) await pages[0].screenshot({ path: output + '/failure.png' }).catch(() => {});
        await browser.close();
    }
    process.exitCode = 1;
});
