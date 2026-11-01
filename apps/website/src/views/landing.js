import { escapeHtml } from '../markdown.js';
import { renderLayout } from './layout.js';
import { BRAND, FEATURES, STEPS, COMPARISON, FAQ, PRICING, TRUST_NOTES } from '../content.js';

function statusPill(status) {
  const up = status?.state === 'up';
  return `<span class="pill">
    <span class="dot${up ? '' : ' is-down'}"></span>
    ${up ? 'Gateway online' : 'Gateway unreachable'}${status?.latencyMs != null ? ` · ${status.latencyMs} ms` : ''}
  </span>`;
}

const CODE_SAMPLE = `<span class="tok-com">&lt;!-- 1. drop the SDK on any page --&gt;</span>
&lt;script src="<span class="tok-str">https://pay.yourdomain.com/youpi.js</span>"&gt;&lt;/script&gt;

<span class="tok-com">&lt;!-- 2. mark any button --&gt;</span>
&lt;button <span class="tok-key">data-youpi-pay</span>
        <span class="tok-key">data-order-id</span>=<span class="tok-str">"ORDER-1001"</span>
        <span class="tok-key">data-amount</span>=<span class="tok-str">"499.00"</span>
        <span class="tok-key">data-currency</span>=<span class="tok-str">"INR"</span>&gt;
  Buy now
&lt;/button&gt;`;

function featureCard(feature) {
  return `<article class="card">
    <div class="card-icon">${escapeHtml(feature.icon)}</div>
    <h3>${escapeHtml(feature.title)}</h3>
    <p>${escapeHtml(feature.body)}</p>
  </article>`;
}

/**
 * @param {{
 *   status: { state: 'up'|'down', latencyMs?: number },
 *   stats: { payments: number, merchants: number },
 *   docs: Array<{ slug, title, summary }>,
 *   links: { admin: string, store: string, help: string }
 * }} ctx
 */
export function renderLanding(ctx) {
  const { status, docs, links, stats } = ctx;

  const body = `
<section class="hero">
  <div class="wrap hero-grid">
    <div>
      ${statusPill(status)}
      <h1>Accept UPI payments. <span class="accent">Keep every rupee.</span></h1>
      <p class="lede">${escapeHtml(BRAND.description)}</p>
      <div class="hero-actions">
        <a class="btn btn-primary" href="${escapeHtml(links.admin)}">Open merchant dashboard</a>
        <a class="btn btn-ghost" href="${escapeHtml(links.store)}">Try the live demo →</a>
      </div>
      <div class="hero-stats">
        <div><strong>0%</strong><span>Gateway fee</span></div>
        <div><strong>3</strong><span>Observation channels</span></div>
        <div><strong>${stats.merchants}</strong><span>Active merchant${stats.merchants === 1 ? '' : 's'}</span></div>
        <div><strong>${stats.payments}</strong><span>Payment sessions</span></div>
      </div>
    </div>
    <div class="preview" aria-hidden="true">
      <div class="preview-head">
        <span>Checkout preview</span>
        <span>UPI · 300s</span>
      </div>
      <div class="preview-card">
        <div style="display:flex;justify-content:space-between;align-items:flex-start">
          <div>
            <div style="font-size:.72rem;letter-spacing:.1em;text-transform:uppercase;color:#64748b">Amount due</div>
            <div class="preview-amount">₹499.00</div>
          </div>
          <span class="preview-badge"><span class="dot" style="width:6px;height:6px"></span> Secure</span>
        </div>
        <div class="preview-qr"></div>
        <div class="preview-timer">Scan with any UPI app · 04:58 left</div>
        <div class="preview-row"><span>Payee</span><strong>yourstore@upi</strong></div>
        <div class="preview-row"><span>Order</span><strong>ORDER-1001</strong></div>
        <div class="preview-row"><span>Verified by</span><strong>SMS + Gmail</strong></div>
      </div>
    </div>
  </div>
</section>

<section id="features" class="section-alt">
  <div class="wrap">
    <div class="section-head">
      <span class="eyebrow">Why self-hosted</span>
      <h2>Everything an aggregator charges for, running on your own box.</h2>
      <p>Same checkout quality as a mainstream gateway, without the fee, the holdback or the vendor badge on your page.</p>
    </div>
    <div class="cards">
      ${FEATURES.slice(0, 6).map(featureCard).join('\n')}
    </div>
    <p style="margin-top:24px"><a class="btn btn-outline" href="/features">See all features →</a></p>
  </div>
</section>

<section id="how-it-works">
  <div class="wrap">
    <div class="section-head">
      <span class="eyebrow">How it works</span>
      <h2>Four steps from button click to confirmed payment.</h2>
      <p>Every step is server-authoritative and auditable — the browser never gets to decide that a payment succeeded.</p>
    </div>
    <div class="steps">
      ${STEPS.map(step => `<article class="step">
        <h3>${escapeHtml(step.title)}</h3>
        <p>${escapeHtml(step.body)}</p>
      </article>`).join('\n')}
    </div>
    <div class="status-strip" style="margin-top:34px">
      <div>
        <h3>Live infrastructure status</h3>
        <p>Read directly from the payment API's health endpoint, server-side.</p>
      </div>
      <div class="status-list">
        <div class="status-item"><span class="dot${status?.state === 'up' ? '' : ' is-down'}"></span> Payment API ${status?.state === 'up' ? 'operational' : 'unreachable'}</div>
        <div class="status-item"><span class="dot${status?.state === 'up' ? '' : ' is-down'}"></span> ${status?.latencyMs != null ? `${status.latencyMs} ms response` : 'No response'}</div>
        <div class="status-item"><a href="/status" style="color:#8ec5ff">Full status page →</a></div>
      </div>
    </div>
  </div>
</section>

<section class="section-alt">
  <div class="wrap">
    <div class="section-head">
      <span class="eyebrow">Comparison</span>
      <h2>What changes when you own the rail.</h2>
    </div>
    <div class="table-wrap">
      <table class="compare">
        <thead>
          <tr><th>Metric</th><th>Typical aggregator</th><th class="youpi-col">${escapeHtml(BRAND.name)}</th></tr>
        </thead>
        <tbody>
          ${COMPARISON.slice(0, 6).map(([label, them, us]) => `<tr>
            <td>${escapeHtml(label)}</td>
            <td class="cross">${escapeHtml(them)}</td>
            <td class="youpi"><span class="tick">✓</span> ${escapeHtml(us)}</td>
          </tr>`).join('\n')}
        </tbody>
      </table>
    </div>
    <p style="margin-top:20px"><a class="btn btn-outline" href="/why">Read the full comparison →</a></p>
  </div>
</section>

<section id="pricing">
  <div class="wrap">
    <div class="section-head">
      <span class="eyebrow">Pricing</span>
      <h2>${escapeHtml(PRICING.headline)}</h2>
      <p>${escapeHtml(PRICING.sub)}</p>
    </div>
    <div class="price-grid compact">
      ${PRICING.rows.map(row => `<article class="price-card">
        <span class="price-item">${escapeHtml(row.item)}</span>
        <strong>${escapeHtml(row.amount)}</strong>
        <span class="price-note">${escapeHtml(row.note)}</span>
      </article>`).join('\n')}
    </div>
    <p style="margin-top:20px"><a class="btn btn-outline" href="/pricing">See the real running costs →</a></p>
  </div>
</section>

<section id="integrate" class="section-alt">
  <div class="wrap">
    <div class="section-head">
      <span class="eyebrow">Integration</span>
      <h2>Two lines of HTML for the modal checkout.</h2>
      <p>The script auto-binds to any <code>[data-youpi-pay]</code> element and opens the checkout as an iframe modal on desktop, or a bottom drawer on mobile.</p>
    </div>
    <div class="code-card">
      <div class="code-head">
        <span>index.html</span>
        <button class="copy" type="button" data-copy-target="integration-snippet">Copy</button>
      </div>
      <pre><code id="integration-snippet">${CODE_SAMPLE}</code></pre>
    </div>
    <ul class="check-list" style="margin-top:22px">
      ${TRUST_NOTES.map(note => `<li>${escapeHtml(note)}</li>`).join('\n')}
    </ul>
    <p style="margin-top:16px;color:var(--muted);font-size:.9rem">
      React, Vue, Next.js or Nuxt? Use the programmatic API — <a href="/docs/DEVELOPER_INTEGRATION">see the developer guide</a>.
      Server-to-server confirmation should always verify the <code>X-Gateway-Signature</code> HMAC over the raw webhook body.
    </p>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="section-head">
      <span class="eyebrow">FAQ</span>
      <h2>Before you ask.</h2>
    </div>
    <div class="faq-wrap">
      ${FAQ.slice(0, 5).map(item => `<details class="faq-item">
        <summary>${escapeHtml(item.q)}</summary>
        <p>${escapeHtml(item.a)}</p>
      </details>`).join('\n')}
    </div>
    <p style="margin-top:20px"><a class="btn btn-outline" href="/faq">All questions →</a></p>
  </div>
</section>

<section class="section-alt">
  <div class="wrap">
    <div class="section-head">
      <span class="eyebrow">Documentation</span>
      <h2>Set it up, wire it in, run it in production.</h2>
      <p>Every guide in the repository, rendered for reading.</p>
    </div>
    <div class="doc-cards">
      ${docs.slice(0, 6).map(doc => `<a class="doc-card" href="/docs/${encodeURIComponent(doc.slug)}">
        <strong>${escapeHtml(doc.title)}</strong>
        <span>${escapeHtml(doc.summary || 'Read the guide')}</span>
      </a>`).join('\n')}
    </div>
    <p style="margin-top:22px"><a class="btn btn-outline" href="/docs">Browse all documentation →</a></p>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="cta-band">
      <div>
        <h2>Ready to see it working?</h2>
        <p>Open the demo store, run a test payment, then wire the same SDK into your own site.</p>
      </div>
      <div class="hero-actions" style="margin:0">
        <a class="btn btn-primary" href="${escapeHtml(links.store)}">Try the live demo</a>
        <a class="btn btn-ghost" href="/why">Why self-hosted?</a>
      </div>
    </div>
  </div>
</section>`;

  return renderLayout({
    title: `${BRAND.name} — Self-hosted UPI payment gateway with 0% fees`,
    body,
    active: '/',
    links
  });
}
