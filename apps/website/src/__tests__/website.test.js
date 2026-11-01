import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';

import { startWebsite } from '../index.js';
import { renderMarkdown, extractDocMeta, escapeHtml } from '../markdown.js';

const TEST_PORT = 6388;

function get(pathname, options = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request(
      { host: '127.0.0.1', port: TEST_PORT, path: pathname, method: options.method || 'GET', headers: options.headers },
      res => {
        let body = '';
        res.on('data', chunk => { body += chunk; });
        res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body }));
      }
    );
    req.on('error', reject);
    req.end();
  });
}

test('Public website & documentation portal', async (t) => {
  // Point the health probe at a port that is guaranteed closed so the suite stays offline.
  const instance = await startWebsite(TEST_PORT, {
    paymentApiUrl: 'http://127.0.0.1:1',
    healthTimeoutMs: 250
  });

  t.after(async () => {
    await instance.close();
  });

  await t.test('1. Landing page renders with brand, pricing claim and integration snippet', async () => {
    const res = await get('/');
    assert.equal(res.status, 200);
    assert.match(res.headers['content-type'], /text\/html/);
    assert.match(res.body, /YOUPI PG/);
    assert.match(res.body, /Keep every rupee/);
    assert.match(res.body, /data-youpi-pay/);
    assert.match(res.body, /href="\/docs"/);
  });

  await t.test('2. Landing page degrades gracefully when the payment API is down', async () => {
    const res = await get('/');
    assert.equal(res.status, 200);
    assert.match(res.body, /Gateway unreachable/);
  });

  await t.test('3. Security headers lock the site down', async () => {
    const res = await get('/');
    assert.equal(res.headers['x-frame-options'], 'DENY');
    assert.equal(res.headers['x-content-type-options'], 'nosniff');
    const csp = res.headers['content-security-policy'];
    assert.match(csp, /frame-ancestors 'none'/);
    assert.match(csp, /object-src 'none'/);
    assert.match(csp, /script-src 'self'/);
  });

  await t.test('4. Health endpoint is served and reports the gateway probe', async () => {
    const res = await get('/health');
    assert.equal(res.status, 200);
    const payload = JSON.parse(res.body);
    assert.equal(payload.status, 'UP');
    assert.equal(payload.service, 'website');
    assert.equal(payload.gateway.state, 'down');
  });

  await t.test('5. Docs index lists the repository guides', async () => {
    const res = await get('/docs');
    assert.equal(res.status, 200);
    assert.match(res.body, /Documentation/);
    assert.match(res.body, /\/docs\/CONFIGURATION/);
    assert.match(res.body, /\/docs\/DEPLOYMENT/);
  });

  await t.test('6. A guide renders markdown into HTML', async () => {
    const res = await get('/docs/CONFIGURATION');
    assert.equal(res.status, 200);
    assert.match(res.body, /<h1[^>]*>Configuration/);
    assert.match(res.body, /<table>/);
    assert.match(res.body, /SQLITE_DB_PATH/);
    assert.match(res.body, /class="docs-nav"/);
  });

  await t.test('7. Path traversal and unknown slugs are rejected with 404', async () => {
    for (const pathname of ['/docs/..%2f..%2fpackage', '/docs/%2e%2e%2fpackage', '/docs/nope-not-a-doc', '/nope']) {
      const res = await get(pathname);
      assert.equal(res.status, 404, `${pathname} should 404`);
    }
  });

  await t.test('8. Non-GET methods are rejected', async () => {
    const res = await get('/docs', { method: 'POST' });
    assert.equal(res.status, 405);
  });

  await t.test('9. Static assets are served with correct content types', async () => {
    const css = await get('/css/site.css');
    assert.equal(css.status, 200);
    assert.match(css.headers['content-type'], /text\/css/);

    const font = await get('/fonts/sora.woff2');
    assert.equal(font.status, 200);
    assert.match(font.headers['content-type'], /font\/woff2/);
    assert.match(font.headers['cache-control'], /immutable/);

    const js = await get('/js/site.js');
    assert.equal(js.status, 200);
    assert.match(js.headers['content-type'], /javascript/);
  });

  await t.test('10. Every marketing page renders with its own content', async () => {
    const pages = [
      ['/why', /Why YOUPI|payment gateway should not own/],
      ['/features', /Everything the checkout needs/],
      ['/pricing', /Zero gateway commission/],
      ['/faq', /The questions people actually ask/],
      ['/about', /Built in the open/],
      ['/contact', /Talk to the people who build it/]
    ];
    for (const [pathname, pattern] of pages) {
      const res = await get(pathname);
      assert.equal(res.status, 200, `${pathname} should render`);
      assert.match(res.body, pattern, `${pathname} should contain its headline`);
      assert.match(res.body, /<footer class="site-footer">/, `${pathname} should keep the shared chrome`);
    }
  });

  await t.test('11. Navigation links to every top-level page', async () => {
    const res = await get('/');
    for (const href of ['/why', '/features', '/pricing', '/docs', '/faq', '/about', '/contact', '/status']) {
      assert.match(res.body, new RegExp(`href="${href}"`), `header/footer should link ${href}`);
    }
  });

  await t.test('12. Status page probes services and degrades to "Unreachable"', async () => {
    const res = await get('/status');
    assert.equal(res.status, 200);
    assert.match(res.body, /Service status|systems operational|not responding/i);
    assert.match(res.body, /Unreachable/);
  });

  await t.test('13. All four legal pages render and carry the template warning', async () => {
    for (const slug of ['terms', 'privacy', 'refund', 'disclaimer']) {
      const res = await get(`/legal/${slug}`);
      assert.equal(res.status, 200, `/legal/${slug} should render`);
      assert.match(res.body, /Template document/, `/legal/${slug} must keep the legal warning`);
    }
  });

  await t.test('14. Unknown legal slugs 404 instead of throwing', async () => {
    const res = await get('/legal/not-a-real-policy');
    assert.equal(res.status, 404);
  });

  await t.test('15. Sitemap lists every page', async () => {
    const res = await get('/sitemap.xml');
    assert.equal(res.status, 200);
    assert.match(res.headers['content-type'], /application\/xml/);
    for (const pathname of ['/why', '/pricing', '/faq', '/legal/privacy', '/docs/CONFIGURATION']) {
      assert.match(res.body, new RegExp(`<loc>[^<]*${pathname}</loc>`), `sitemap should include ${pathname}`);
    }
  });

  await t.test('16. robots.txt is served', async () => {
    const res = await get('/robots.txt');
    assert.equal(res.status, 200);
    assert.match(res.body, /Disallow: \/health/);
  });
});

test('Markdown renderer escapes hostile input', async (t) => {
  await t.test('script tags and event handlers are neutralised', () => {
    const html = renderMarkdown('# Title\n\n<script>alert(1)</script>\n\n<img src=x onerror="alert(1)">');
    assert.ok(!html.includes('<script>'), 'raw script tag must not survive');
    assert.ok(!html.includes('<img'), 'raw img tag must not survive');
    assert.ok(!/<img[^>]*onerror/i.test(html), 'attribute payload must not survive');
    assert.match(html, /&lt;script&gt;/);
  });

  await t.test('javascript: links are dropped', () => {
    const html = renderMarkdown('[click](javascript:alert(1))');
    assert.ok(!html.includes('javascript:'));
    assert.match(html, /<p>click<\/p>/);
  });

  await t.test('safe http links are kept and marked noopener', () => {
    const html = renderMarkdown('[docs](https://example.com/x)');
    assert.match(html, /href="https:\/\/example\.com\/x"/);
    assert.match(html, /rel="noopener noreferrer"/);
  });

  await t.test('tables, lists and code fences render', () => {
    const html = renderMarkdown('| a | b |\n| - | - |\n| 1 | 2 |\n\n- one\n- two\n\n```js\nconst x = 1;\n```');
    assert.match(html, /<table>/);
    assert.match(html, /<ul>/);
    assert.match(html, /<pre><code class="language-js">/);
  });

  await t.test('doc metadata is extracted', () => {
    const meta = extractDocMeta('# Hello World\n\nFirst paragraph here.');
    assert.equal(meta.title, 'Hello World');
    assert.equal(meta.summary, 'First paragraph here.');
  });

  await t.test('escapeHtml covers all five entities', () => {
    assert.equal(escapeHtml(`<>&"'`), '&lt;&gt;&amp;&quot;&#39;');
  });
});
