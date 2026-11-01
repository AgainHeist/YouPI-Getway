import { escapeHtml } from '../markdown.js';
import { BRAND } from '../content.js';

/**
 * Shared chrome for every public page.
 * Everything is rendered server-side; the only script is a tiny progressive-enhancement
 * file loaded from `public/js/site.js`, which keeps the CSP at `script-src 'self'`.
 */

const NAV = [
  { href: '/why', label: 'Why YOUPI' },
  { href: '/features', label: 'Features' },
  { href: '/pricing', label: 'Pricing' },
  { href: '/docs', label: 'Docs' },
  { href: '/faq', label: 'FAQ' }
];

function navLink(item, active) {
  const isActive = active === item.href;
  return `<a href="${escapeHtml(item.href)}"${isActive ? ' aria-current="page"' : ''}>${escapeHtml(item.label)}</a>`;
}

function footerColumn(title, links) {
  return `<div>
    <h4>${escapeHtml(title)}</h4>
    ${links.map(link => `<a href="${escapeHtml(link.href)}">${escapeHtml(link.label)}</a>`).join('\n')}
  </div>`;
}

/**
 * @param {{
 *   title: string,
 *   description?: string,
 *   body: string,
 *   active?: string,
 *   links: { admin: string, store: string, docs: string, help: string },
 *   brand?: string
 * }} options
 */
export function renderLayout(options) {
  const {
    title,
    description = BRAND.description,
    body,
    active = '',
    links,
    brand = BRAND.name
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
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <div class="wrap">
    <a class="brand" href="/">
      <span class="brand-mark">YP</span>
      <span>${escapeHtml(brand)}<small>${escapeHtml(BRAND.tagline)}</small></span>
    </a>
    <nav class="nav-links" aria-label="Primary">
      ${NAV.map(item => navLink(item, active)).join('\n      ')}
    </nav>
    <div class="header-actions">
      <a class="btn btn-ghost btn-sm" href="${escapeHtml(links.store)}">Live demo</a>
      <a class="btn btn-primary btn-sm" href="${escapeHtml(links.admin)}">Get started</a>
    </div>
  </div>
</header>
<main id="main">
${body}
</main>
<footer class="site-footer">
  <div class="wrap">
    <div class="footer-grid">
      <div>
        <a class="brand" href="/" style="margin-bottom:14px">
          <span class="brand-mark">YP</span>
          <span>${escapeHtml(brand)}<small>${escapeHtml(BRAND.tagline)}</small></span>
        </a>
        <p style="font-size:.88rem;max-width:34ch">Self-hosted UPI payment gateway. Your bank account, your brand, zero gateway fees.</p>
        <p style="font-size:.8rem;margin-top:12px;color:#7b8dab">${escapeHtml(BRAND.origin)}</p>
      </div>
      ${footerColumn('Product', [
        { href: '/why', label: 'Why YOUPI' },
        { href: '/features', label: 'Features' },
        { href: '/pricing', label: 'Pricing' },
        { href: '/faq', label: 'FAQ' },
        { href: links.store, label: 'Live demo store' }
      ])}
      ${footerColumn('Developers', [
        { href: '/docs', label: 'Documentation' },
        { href: '/docs/DEVELOPER_INTEGRATION', label: 'API & webhooks' },
        { href: '/docs/CONFIGURATION', label: 'Configuration' },
        { href: '/docs/DEPLOYMENT', label: 'Deployment' },
        { href: '/status', label: 'Service status' }
      ])}
      ${footerColumn('Company', [
        { href: '/about', label: 'About' },
        { href: '/contact', label: 'Contact' },
        { href: links.admin, label: 'Merchant dashboard' },
        { href: '/legal/terms', label: 'Terms of use' },
        { href: '/legal/privacy', label: 'Privacy' }
      ])}
    </div>
    <div class="footer-base">
      <span>© ${new Date().getFullYear()} ${escapeHtml(brand)}. Software provided for research and experimentation.</span>
      <span class="footer-legal">
        <a href="/legal/terms">Terms</a>
        <a href="/legal/privacy">Privacy</a>
        <a href="/legal/refund">Refunds</a>
        <a href="/legal/disclaimer">Disclaimer</a>
      </span>
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
