import { escapeHtml } from '../markdown.js';

/**
 * Shared chrome for every public page.
 * Everything is rendered server-side; the only script is a tiny progressive-enhancement
 * file loaded from `public/js/site.js`, which keeps the CSP at `script-src 'self'`.
 */

export const SITE_NAME = 'YOUPI PG';

function navLink(href, label, active) {
  const isActive = active === href;
  return `<a href="${escapeHtml(href)}"${isActive ? ' aria-current="page"' : ''}>${escapeHtml(label)}</a>`;
}

/**
 * @param {{
 *   title: string,
 *   description?: string,
 *   body: string,
 *   active?: string,
 *   links: { admin: string, store: string, docs: string },
 *   brand?: string
 * }} options
 */
export function renderLayout(options) {
  const {
    title,
    description = 'Self-hosted, white-label UPI payment gateway with 0% gateway fees and direct-to-bank settlement.',
    body,
    active = '',
    links,
    brand = SITE_NAME
  } = options;

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)}</title>
<meta name="description" content="${escapeHtml(description)}">
<meta name="theme-color" content="#0b1526">
<meta property="og:title" content="${escapeHtml(title)}">
<meta property="og:description" content="${escapeHtml(description)}">
<meta property="og:type" content="website">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="preload" href="/fonts/sora.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/css/site.css">
</head>
<body>
<header class="site-header">
  <div class="wrap">
    <a class="brand" href="/">
      <span class="brand-mark">YP</span>
      <span>${escapeHtml(brand)}<small>Payments Infrastructure</small></span>
    </a>
    <nav class="nav-links" aria-label="Primary">
      ${navLink('/#features', 'Features', active)}
      ${navLink('/#how-it-works', 'How it works', active)}
      ${navLink('/docs', 'Docs', active)}
      ${navLink(links.store, 'Live demo', active)}
    </nav>
    <a class="btn btn-primary btn-sm" href="${escapeHtml(links.admin)}" style="margin-left:auto">Merchant dashboard</a>
  </div>
</header>
<main>
${body}
</main>
<footer class="site-footer">
  <div class="wrap">
    <div class="footer-grid">
      <div>
        <a class="brand" href="/" style="margin-bottom:14px">
          <span class="brand-mark">YP</span>
          <span>${escapeHtml(brand)}<small>Payments Infrastructure</small></span>
        </a>
        <p style="font-size:.88rem;max-width:34ch">Self-hosted UPI payment gateway. Your bank account, your brand, zero gateway fees.</p>
      </div>
      <div>
        <h4>Product</h4>
        <a href="/#features">Features</a>
        <a href="/#how-it-works">How it works</a>
        <a href="/#integrate">Integration</a>
        <a href="${escapeHtml(links.store)}">Live demo store</a>
      </div>
      <div>
        <h4>Developers</h4>
        <a href="/docs">Documentation</a>
        <a href="/docs/DEVELOPER_INTEGRATION">API &amp; webhooks</a>
        <a href="/docs/CONFIGURATION">Configuration</a>
        <a href="/docs/DEPLOYMENT">Deployment</a>
      </div>
      <div>
        <h4>Operations</h4>
        <a href="${escapeHtml(links.admin)}">Merchant dashboard</a>
        <a href="/docs/OBSERVERS_SETUP">Payment observers</a>
        <a href="/docs/OPERATIONS_TROUBLESHOOTING">Troubleshooting</a>
        <a href="/health">Service health</a>
      </div>
    </div>
    <p class="footer-note">
      <strong style="color:#cbd8ee">Research project — experimental use only.</strong>
      ${escapeHtml(brand)} is an independent, experimental research project. It is not affiliated with, endorsed by or
      sponsored by NPCI, RBI, any bank or any UPI app, and it is not a certified or audited production payment gateway.
      Verify every payment against your bank's official records before fulfilling an order. You are responsible for
      assessing the legal and compliance requirements that apply to your own use.
    </p>
  </div>
</footer>
<script src="/js/site.js" defer></script>
</body>
</html>`;
}
