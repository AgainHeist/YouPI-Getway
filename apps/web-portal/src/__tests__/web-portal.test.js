import { test, describe, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { Database } from '@youpi/db';
import { startWebPortal } from '../index.js';

describe('YOUPI PG V2 — Unified Complete Website & Cloud Gateway Suite', () => {
  let instance;
  let baseUrl;
  let customDb;

  before(async () => {
    process.env.YOUPI_DEMO_MODE = 'true';
    customDb = new Database({ inMemory: true });
    instance = await startWebPortal(0, { host: '127.0.0.1', customDb });
    baseUrl = `http://127.0.0.1:${instance.port}`;
  });

  after(async () => {
    if (instance) await instance.close();
    if (customDb) customDb.close();
  });

  test('1. GET / serves the flagship YOUPI PG V2 homepage with sandbox & calculator', async () => {
    const res = await fetch(`${baseUrl}/`);
    assert.equal(res.status, 200);
    assert.ok(res.headers.get('content-type').includes('text/html'));
    const html = await res.text();
    assert.ok(html.includes('YOUPI PG'));
    assert.ok(html.includes('0% Gateway Fees'));
    assert.ok(html.includes('data-launch-sandbox'));
    assert.ok(html.includes('/youpi.js'));
  });

  test('2. GET /docs and /docs/architecture render markdown guides cleanly', async () => {
    const res1 = await fetch(`${baseUrl}/docs`);
    assert.equal(res1.status, 200);
    const html1 = await res1.text();
    assert.ok(html1.includes('DOCUMENTATION HUB'));

    const res2 = await fetch(`${baseUrl}/docs/architecture`);
    assert.equal(res2.status, 200);
    const html2 = await res2.text();
    assert.ok(html2.includes('Canonical System Architecture'));
  });

  test('3. GET /api-docs and /openapi.yaml serve developer API explorer & OpenAPI spec', async () => {
    const explorer = await fetch(`${baseUrl}/api-docs`);
    assert.equal(explorer.status, 200);
    assert.ok((await explorer.text()).includes('REST API EXPLORER'));

    const spec = await fetch(`${baseUrl}/openapi.yaml`);
    assert.equal(spec.status, 200);
    assert.ok((await spec.text()).includes('openapi:'));
  });

  test('4. GET /store, /wallet, /admin, /help, and /youpi.js all work under one domain', async () => {
    for (const route of ['/store', '/wallet', '/admin', '/help', '/youpi.js', '/favicon.svg']) {
      const res = await fetch(`${baseUrl}${route}`);
      assert.equal(res.status, 200, `Expected HTTP 200 for ${route}`);
    }
  });

  test('5. End-to-end live checkout creation, QR SVG rendering, and sandbox Bank SMS settlement', async () => {
    // Create payment session via public API
    const createRes = await fetch(`${baseUrl}/api/v1/payments`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Forwarded-Host': `127.0.0.1:${instance.port}`,
        'X-Forwarded-Proto': 'http'
      },
      body: JSON.stringify({
        orderId: `WEB-E2E-${Date.now()}`,
        amount: '25.00',
        currency: 'INR',
        description: 'Unified Website E2E Test'
      })
    });
    assert.equal(createRes.status, 201);
    const created = await createRes.json();
    assert.ok(created.paymentId);
    assert.ok(created.checkoutUrl.includes(`/checkout/${created.paymentId}`));

    // Render checkout HTML & QR SVG
    const checkoutHtmlRes = await fetch(`${baseUrl}/checkout/${created.paymentId}`);
    assert.equal(checkoutHtmlRes.status, 200);
    const checkoutHtml = await checkoutHtmlRes.text();
    assert.ok(checkoutHtml.includes(created.paymentId));
    assert.ok(checkoutHtml.includes('/site/demo-bridge.js'));

    const qrRes = await fetch(`${baseUrl}/checkout/${created.paymentId}/qr.svg`);
    assert.equal(qrRes.status, 200);
    assert.ok((await qrRes.text()).includes('<svg'));

    // Trigger 1-Tap Cloud Sandbox Bank SMS + Gmail Dual Verification
    const simRes = await fetch(`${baseUrl}/api/demo/simulate-payment`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paymentId: created.paymentId })
    });
    assert.equal(simRes.status, 200);
    const simData = await simRes.json();
    assert.equal(simData.success, true);
    assert.equal(simData.status, 'SUCCESS');
    assert.equal(simData.verificationLevel, 2);
    assert.equal(String(simData.utr).length, 12);
  });
});
