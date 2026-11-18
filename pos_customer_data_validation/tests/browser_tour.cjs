/* Execute the registered Odoo tour with the host browser when the preserved
 * runtime has no Chrome. This does not replace the Python HttpCase assertions.
 * Usage: PLAYWRIGHT_MODULE=/path/to/@playwright/test node browser_tour.cjs
 *        http://TEST_CONTAINER_IP:8069 /tmp/fixture.json /tmp/evidence
 */
'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '@playwright/test');
const [base, fixtureFile, output] = process.argv.slice(2);
const fixture = JSON.parse(fs.readFileSync(fixtureFile, 'utf8'));
assert.match(fixture.database, /^odoo_test(?:_[a-z0-9_]+)?$/);
const tourName = 'CustomerDataValidationTour';
let browser;

async function run() {
    fs.mkdirSync(output, { recursive: true });
    browser = await chromium.launch({
        executablePath: process.env.CHROMIUM || '/usr/bin/chromium', headless: true,
    });
    const page = await browser.newPage({ viewport: { width: 1366, height: 1000 } });
    const messages = [];
    const errors = [];
    let successful = false;
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {
        messages.push({ type: message.type(), text: message.text() });
        if (message.text() === 'test successful') successful = true;
        if (message.type() === 'error') errors.push(message.text());
    });
    async function rpc(model, method, args) {
        return page.evaluate(async ({ model, method, args }) => {
            const response = await fetch('/web/dataset/call_kw/' + model + '/' + method, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ jsonrpc: '2.0', method: 'call',
                    params: { model, method, args, kwargs: {} } }),
            });
            const data = await response.json();
            if (data.error) throw new Error(data.error.data.message);
            return data.result;
        }, { model, method, args });
    }
    await page.goto(base + '/web/login?db=' + fixture.database);
    await page.locator('[name=login]').fill(fixture.login);
    await page.locator('[name=password]').fill('customer-review-ui-test');
    await Promise.all([
        page.waitForURL(url => !url.pathname.includes('login')),
        page.locator('button[type=submit]').click(),
    ]);
    const domain = [['session_id.config_id', '=', fixture.config_id]];
    const before = await rpc('pos.order', 'search_count', [domain]);
    assert.equal(before, 0, 'Tour fixture must have no previous orders');
    const original = await rpc('res.partner', 'pos_customer_data_read',
        [fixture.historical_id, fixture.config_id]);
    await page.goto(base + '/pos/ui?config_id=' + fixture.config_id + '&debug=tests');
    await page.waitForFunction(name => {
        const tour = window.odoo && odoo.__DEBUG__ && odoo.__DEBUG__.services['web_tour.tour'];
        return tour && tour.tours[name] && tour.tours[name].ready;
    }, tourName, { timeout: 90000 });
    await page.locator('.product-screen').waitFor({ timeout: 90000 });
    const steps = await page.evaluate(name => {
        const tour = odoo.__DEBUG__.services['web_tour.tour'].tours[name];
        odoo.startTour(name);
        return tour.steps.length;
    }, tourName);
    const deadline = Date.now() + 90000;
    while (!successful && !errors.length && Date.now() < deadline) {
        await page.waitForTimeout(100);
    }
    fs.writeFileSync(output + '/tour-console.json', JSON.stringify(messages, null, 2));
    assert.deepEqual(errors, [], 'No tour or browser errors');
    assert.ok(successful, 'The Odoo tour must emit test successful');
    const orders = await rpc('pos.order', 'search_read', [domain,
        ['partner_id', 'amount_total', 'amount_paid', 'state']]);
    assert.equal(orders.length, before + 1);
    // Use an isolated fresh fixture so the Python HttpCase's one-order
    // postcondition can also be checked outside its transactional environment.
    assert.equal(orders[0].partner_id[0], fixture.historical_id);
    assert.equal(orders[0].state, 'paid');
    const after = await rpc('res.partner', 'pos_customer_data_read',
        [fixture.historical_id, fixture.config_id]);
    assert.deepEqual(after.partner, original.partner, 'Unchanged historical data and dates');
    assert.equal(after.partner.pos_name_updated_at, false);
    assert.equal(after.partner.pos_mobile_updated_at, '2021-01-01 12:00:00');
    await page.screenshot({ path: output + '/tour-receipt.png' });
    const result = { database: fixture.database, browser: await browser.version(),
        tour: tourName, steps, successful, orders, historicalPartner: after.partner };
    fs.writeFileSync(output + '/tour-results.json', JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
}

run().then(() => browser.close()).catch(async error => {
    console.error(error);
    if (browser) {
        const page = browser.contexts()[0]?.pages()[0];
        if (page) await page.screenshot({ path: output + '/failure.png' }).catch(() => {});
        await browser.close();
    }
    process.exitCode = 1;
});
