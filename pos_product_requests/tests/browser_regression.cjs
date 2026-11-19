/* Run with host Chromium against the isolated database seeded by ui_fixture.py. */
'use strict';

const fs = require('node:fs');
const { randomUUID } = require('node:crypto');
const assert = require('node:assert/strict');
const { chromium, expect } = require(process.env.PLAYWRIGHT_MODULE || '@playwright/test');

const [base, fixtureFile, output] = process.argv.slice(2);
const fixture = JSON.parse(fs.readFileSync(fixtureFile, 'utf8'));
const results = [];

async function run(browser) {
    const page = await browser.newPage({ viewport: { width: 1366, height: 900 }, hasTouch: true });
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    page.setDefaultTimeout(15000);
    await page.goto(base + '/web/login?db=' + fixture.database);
    await page.locator('input[name=login]').fill(fixture.login);
    await page.locator('input[name=password]').fill('requests-ui-test');
    await Promise.all([
        page.waitForURL(url => !url.pathname.includes('login')),
        page.locator('button[type=submit]').click(),
    ]);

    const productScreen = page.locator('.product-screen');
    const register = page.getByRole('button', { name: 'Registrar faltante' });
    const historyButton = page.getByRole('button', { name: 'Faltantes', exact: true });
    const popup = page.getByRole('dialog', { name: 'Registrar faltante' });
    const text = popup.getByLabel('Producto solicitado');
    const save = popup.getByRole('button', { name: 'Guardar' });
    const history = page.locator('.product-request-history');
    const rows = history.locator('tbody tr');
    const saveRoute = '**/web/dataset/call_kw/pos.product.request/save_from_pos';
    const historyRoute = '**/web/dataset/call_kw/pos.product.request/history_from_pos';

    async function openPos(config) {
        await page.goto(base + '/pos/ui?config_id=' + config);
        await productScreen.waitFor({ timeout: 90000 });
        assert.equal(await clientState('config'), config);
    }

    function clientState(type) {
        return page.evaluate((key) => {
            const pos = window.posmodel;
            const order = pos.get_order();
            return {
                config: pos.config.id,
                session: pos.pos_session.id,
                ticket: [
                    order.uid, order.get_client() && order.get_client().id,
                    order.get_orderlines().map(line => [line.product.id, line.quantity]),
                ],
            }[key];
        }, type);
    }

    function rpc(model, method, args) {
        return page.evaluate(async ({ model, method, args }) => {
            const response = await fetch('/web/dataset/call_kw/' + model + '/' + method, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: { model, method, args, kwargs: {} } }),
            });
            const data = await response.json();
            if (data.error) throw new Error(data.error.data.message);
            return data.result;
        }, { model, method, args });
    }

    async function closeHistory() {
        await history.getByRole('button', { name: 'Volver' }).click();
        await expect(productScreen).toBeVisible();
    }

    async function capture(product, reason) {
        await register.click();
        await text.fill(product);
        await popup.getByRole('button', { name: reason }).click();
    }

    await openPos(fixture.first_config);
    await expect(page.locator('.order-management + .product-request-history-button')).toHaveCount(1);
    await historyButton.click();
    await expect(history).toContainText('Aún no hay faltantes registrados');
    await closeHistory();
    await page.route(historyRoute, route => route.abort('internetdisconnected'));
    await historyButton.click();
    await expect(history.getByRole('alert')).toContainText('No se pudo cargar el historial');
    await closeHistory();
    await page.unroute(historyRoute);
    results.push('Icono junto a la lupa, lista vacía, error de conexión y regreso a la venta');

    const emptyTicket = await clientState('ticket');
    assert.deepEqual(emptyTicket[2], []);
    await register.click();
    await expect(popup.locator('button[aria-pressed="false"]')).toHaveCount(3);
    await save.click();
    await expect(popup).toContainText('Escribe el producto solicitado.');
    await expect(popup).toContainText('Selecciona un motivo.');
    await text.fill('   ');
    await popup.getByRole('button', { name: 'Sin stock' }).click();
    await save.click();
    await expect(popup).toContainText('Escribe el producto solicitado.');
    await expect(text).toHaveValue('   ');
    await expect(popup.getByRole('button', { name: 'Sin stock' })).toHaveAttribute('aria-pressed', 'true');
    await text.fill('Captura cancelada');
    await expect(popup.getByRole('button', { name: 'Cancelar' })).toBeVisible();
    await popup.getByRole('button', { name: 'Cancelar' }).click();
    await historyButton.click();
    await expect(history).toContainText('Aún no hay faltantes registrados');
    await closeHistory();
    assert.deepEqual(await clientState('ticket'), emptyTicket);
    results.push('Motivos sin selección inicial, validación de campos, espacios y cancelación sin cambios');

    const screw = 'Tornillo inoxidable de 3/8, cabeza plana';
    await capture(screw, 'Sin stock');
    let saves = 0;
    await page.route(saveRoute, async route => {
        saves += 1;
        await route.continue();
    });
    await save.evaluate(button => {
        button.click();
        button.click();
    });
    await expect(popup).toBeHidden();
    await page.unroute(saveRoute);
    assert.equal(saves, 1);
    assert.deepEqual(await clientState('ticket'), emptyTicket);
    results.push('Guardado con ticket vacío y dos toques producen una sola solicitud RPC');

    await page.locator('.product[data-product-id="' + fixture.product + '"]').click();
    const ticket = await clientState('ticket');
    assert.equal(ticket[2].length, 1);
    const tube = 'Tubo transparente de 2 metros';
    await capture(tube, 'No lo manejamos');
    let lostResponse;
    let retryKey;
    await page.route(saveRoute, async route => {
        const key = route.request().postDataJSON().params.args[3];
        if (lostResponse === undefined) {
            lostResponse = key;
            const response = await route.fetch();
            assert.ok((await response.json()).result > 0);
            await route.abort('connectionreset');
        } else {
            retryKey = key;
            await route.continue();
        }
    });
    await save.click();
    await expect(popup.getByRole('alert')).toContainText('No se pudo guardar el faltante');
    await expect(text).toHaveValue(tube);
    await expect(popup.getByRole('button', { name: 'No lo manejamos' })).toHaveAttribute('aria-pressed', 'true');
    await save.click();
    await expect(popup).toBeHidden();
    await page.unroute(saveRoute);
    assert.equal(retryKey, lostResponse);
    assert.deepEqual(await clientState('ticket'), ticket);

    await capture('Adaptador especial 2026', 'No existe');
    await text.press('End');
    await text.press('1');
    await expect(text).toHaveValue('Adaptador especial 20261');
    await page.evaluate(() => window.posmodel.barcode_reader.scan('1234567890128'));
    await save.click();
    await expect(popup).toBeHidden();
    assert.deepEqual(await clientState('ticket'), ticket);
    results.push('Pérdida de respuesta tras guardar, reintento con la misma clave y protección del ticket frente al teclado y escáner');

    const expected = [
        ['Adaptador especial 20261', 'No existe'],
        [tube, 'No lo manejamos'],
        [screw, 'Sin stock'],
    ];
    async function checkHistory() {
        await historyButton.click();
        await expect(rows).toHaveCount(3);
        assert.deepEqual(await history.locator('th').allTextContents(), [
            'Producto solicitado', 'Motivo', 'Fecha y hora',
        ]);
        for (const [index, [product, reason]] of expected.entries()) {
            const cells = await rows.nth(index).locator('td').allTextContents();
            assert.deepEqual(cells.slice(0, 2), [product, reason]);
            assert.match(cells[2], /\d{1,2}:\d{2}/);
        }
    }
    await checkHistory();
    await page.evaluate(() => window.posmodel.barcode_reader.scan('1234567890128'));
    await page.screenshot({ path: output + '/historial.png' });
    await closeHistory();
    assert.deepEqual(await clientState('ticket'), ticket);
    results.push('Tres motivos en español, fecha visible, orden descendente y regreso al mismo ticket');

    const session = await clientState('session');
    await page.locator('.pay').click();
    await page.locator('.paymentmethod').filter({ hasText: 'Efectivo de prueba' }).click();
    await page.locator('.payment-screen .next').click();
    await page.locator('.receipt-screen').waitFor();
    assert.equal(await rpc('pos.order', 'search_count', [[
        ['session_id', '=', session], ['state', 'in', ['paid', 'done', 'invoiced']],
    ]]), 1);
    results.push('Venta pagada después de capturar y consultar faltantes');

    await openPos(fixture.first_config);
    await checkHistory();
    await closeHistory();
    await rpc('pos.session', 'action_pos_session_closing_control', [[session]]);
    await rpc('pos.config', 'open_session_cb', [[fixture.first_config]]);
    await openPos(fixture.first_config);
    assert.notEqual(await clientState('session'), session);
    await checkHistory();
    await closeHistory();
    results.push('Recarga y reapertura en otro turno conservan el historial del mismo POS');

    await page.setViewportSize({ width: 390, height: 844 });
    await openPos(fixture.second_config);
    await expect(page.locator('.order-management')).toHaveCount(0);
    await historyButton.tap();
    await expect(history).toContainText('Aún no hay faltantes registrados');
    await closeHistory();
    await productScreen.locator('.switchpane .btn-switchpane.secondary').tap();
    await register.tap();
    await text.fill('Prueba táctil');
    await popup.getByRole('button', { name: 'No existe' }).tap();
    assert.ok((await popup.getByRole('button', { name: 'No existe' }).boundingBox()).height >= 44);
    await page.screenshot({ path: output + '/captura-movil.png' });
    await popup.getByRole('button', { name: 'Cancelar' }).click();

    const secondSession = await clientState('session');
    const args = [secondSession, 'Captura concurrente', 'out_of_stock', randomUUID()];
    const ids = await Promise.all(Array.from({ length: 8 }, () =>
        rpc('pos.product.request', 'save_from_pos', args)));
    assert.ok(ids[0] > 0);
    assert.equal(new Set(ids).size, 1);
    await historyButton.click();
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText('Captura concurrente');
    await closeHistory();
    results.push('Segunda caja sin lupa y aislada, captura táctil desde el panel del ticket y ocho reintentos RPC concurrentes con una sola fila');
    assert.deepEqual(pageErrors, []);
}

(async () => {
    fs.mkdirSync(output, { recursive: true });
    const browser = await chromium.launch({
        executablePath: process.env.CHROMIUM || '/usr/bin/chromium',
        headless: true,
    });
    try {
        await run(browser);
        fs.writeFileSync(output + '/browser-results.json', JSON.stringify(results, null, 2) + '\n');
        console.log(results.join('\n'));
    } finally {
        await browser.close();
    }
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
