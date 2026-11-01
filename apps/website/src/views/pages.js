import { escapeHtml } from '../markdown.js';
import { renderLayout } from './layout.js';
import {
  BRAND,
  FEATURES,
  WHY_POINTS,
  AUDIENCE,
  PRICING,
  FAQ,
  ABOUT,
  CONTACT,
  STATUS_SERVICES,
  TRUST_NOTES,
  LEGAL_DISCLAIMER,
  COMPARISON
} from '../content.js';

/* ------------------------------------------------------------------ shared -- */

function pageHero({ eyebrow, title, lede, actions = '' }) {
  return `<section class="page-hero">
    <div class="wrap">
      <span class="eyebrow">${escapeHtml(eyebrow)}</span>
      <h1>${escapeHtml(title)}</h1>
      <p class="lede">${escapeHtml(lede)}</p>
      ${actions ? `<div class="hero-actions">${actions}</div>` : ''}
    </div>
  </section>`;
}

function ctaBand(links) {
  return `<section class="cta-band-section">
    <div class="wrap">
      <div class="cta-band">
        <div>
          <h2>Ready to see it working?</h2>
          <p>Open the demo store, run a test payment, then wire the same SDK into your own site.</p>
        </div>
        <div class="hero-actions" style="margin:0">
          <a class="btn btn-primary" href="${escapeHtml(links.store)}">Try the live demo</a>
          <a class="btn btn-ghost" href="/docs/DEVELOPER_INTEGRATION">Read the integration guide</a>
        </div>
      </div>
    </div>
  </section>`;
}

function shell({ title, description, body, active, links }) {
  return renderLayout({ title, description, body, active, links });
}

function legalSection(heading, paragraphs) {
  return `<h2>${escapeHtml(heading)}</h2>` +
    paragraphs.map(p => `<p>${escapeHtml(p)}</p>`).join('\n');
}

/* -------------------------------------------------------------------- why -- */

export function renderWhy({ links }) {
  const body = `
${pageHero({
    eyebrow: 'Why YOUPI',
    title: 'Because a payment gateway should not own your money.',
    lede: 'Aggregators do two useful things — they host a checkout and they prove a payment happened. Everything else they charge for is a consequence of not being your bank account. This project rebuilds just those two pieces.',
    actions: `<a class="btn btn-primary" href="/pricing">See the pricing</a><a class="btn btn-ghost" href="/features">Browse features</a>`
  })}

<section>
  <div class="wrap">
    <div class="why-grid">
      ${WHY_POINTS.map(point => `<article class="card">
        <span class="tag">${escapeHtml(point.tag)}</span>
        <h3>${escapeHtml(point.title)}</h3>
        <p>${escapeHtml(point.body)}</p>
      </article>`).join('\n')}
    </div>
  </div>
</section>

<section class="section-alt">
  <div class="wrap">
    <div class="section-head">
      <span class="eyebrow">Side by side</span>
      <h2>What actually changes.</h2>
      <p>The comparison below is about mechanics, not marketing: where the money sits, who proves the payment, and what you become responsible for.</p>
    </div>
    <div class="table-wrap">
      <table class="compare">
        <thead><tr><th>Metric</th><th>Typical aggregator</th><th class="youpi-col">${escapeHtml(BRAND.name)}</th></tr></thead>
        <tbody>
          ${COMPARISON.map(([label, them, us]) => `<tr>
            <td>${escapeHtml(label)}</td>
            <td class="cross">${escapeHtml(them)}</td>
            <td class="youpi"><span class="tick">✓</span> ${escapeHtml(us)}</td>
          </tr>`).join('\n')}
        </tbody>
      </table>
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="section-head">
      <span class="eyebrow">Who it fits</span>
      <h2>Runs a small store beautifully. Not everything else.</h2>
      <p>Being honest about the edges is part of the product — an unsuitable deployment is a support ticket you cannot win.</p>
    </div>
    <div class="cards two-up">
      ${AUDIENCE.map(item => `<article class="card">
        <h3>${escapeHtml(item.title)}</h3>
        <p>${escapeHtml(item.body)}</p>
      </article>`).join('\n')}
    </div>
  </div>
</section>

<section class="section-alt">
  <div class="wrap">
    <div class="section-head">
      <span class="eyebrow">Built-in safeguards</span>
      <h2>The parts that stop a "free gateway" from being a bad idea.</h2>
    </div>
    <ul class="check-list">
      ${TRUST_NOTES.map(note => `<li>${escapeHtml(note)}</li>`).join('\n')}
    </ul>
  </div>
</section>

${ctaBand(links)}`;

  return shell({
    title: 'Why self-hosted — YOUPI PG',
    description: 'Where the money sits, who proves a payment, and what you take on when you run your own UPI payment gateway.',
    body,
    active: '/why',
    links
  });
}

/* --------------------------------------------------------------- features -- */

const FEATURE_GROUPS = [
  { id: 'checkout', title: 'Checkout experience', blurb: 'The part your customer sees and judges you by.' },
  { id: 'detection', title: 'Payment detection', blurb: 'Three independent ways to learn that money actually arrived.' },
  { id: 'security', title: 'Security & fraud', blurb: 'The controls that make amount-only matching safe to run.' },
  { id: 'money', title: 'Money & settlement', blurb: 'Where the rupees live between "paid" and "spendable".' },
  { id: 'brand', title: 'Brand & data ownership', blurb: 'Your logo, your domain, your database.' }
];

export function renderFeatures({ links }) {
  const body = `
${pageHero({
    eyebrow: 'Platform',
    title: 'Everything the checkout needs, nothing the vendor wants.',
    lede: 'A complete payment path — authentication, queueing, QR, detection, reconciliation and webhooks — assembled from small auditable pieces you can host on one box.',
    actions: `<a class="btn btn-primary" href="/docs">Read the docs</a><a class="btn btn-ghost" href="/pricing">Pricing</a>`
  })}

${FEATURE_GROUPS.map(group => {
    const items = FEATURES.filter(feature => feature.group === group.id);
    if (!items.length) return '';
    return `<section class="section-alt">
    <div class="wrap">
      <div class="section-head">
        <span class="eyebrow">${escapeHtml(group.title)}</span>
        <h2>${escapeHtml(group.blurb)}</h2>
      </div>
      <div class="cards">
        ${items.map(feature => `<article class="card">
          <div class="card-icon">${escapeHtml(feature.icon)}</div>
          <h3>${escapeHtml(feature.title)}</h3>
          <p>${escapeHtml(feature.body)}</p>
        </article>`).join('\n')}
      </div>
    </div>
  </section>`;
  }).join('\n')}

${ctaBand(links)}`;

  return shell({
    title: 'Features — YOUPI PG',
    description: 'WhatsApp OTP checkout, vector UPI QR, tri-channel bank detection, HMAC webhooks, till desk and full white labelling.',
    body,
    active: '/features',
    links
  });
}

/* ---------------------------------------------------------------- pricing -- */

export function renderPricing({ links }) {
  const body = `
${pageHero({
    eyebrow: 'Pricing',
    title: PRICING.headline,
    lede: PRICING.sub,
    actions: `<a class="btn btn-primary" href="${escapeHtml(links.admin)}">Open the dashboard</a><a class="btn btn-ghost" href="/contact">Talk to us</a>`
  })}

<section>
  <div class="wrap">
    <div class="price-grid">
      ${PRICING.rows.map(row => `<article class="price-card">
        <span class="price-item">${escapeHtml(row.item)}</span>
        <strong>${escapeHtml(row.amount)}</strong>
        <span class="price-note">${escapeHtml(row.note)}</span>
      </article>`).join('\n')}
    </div>
    <div class="callout" style="margin-top:26px">
      <strong>Read this before you plan around "₹0".</strong>
      <p>There is no gateway commission, but running a payment system is never free: you pay for a server, a domain, and the person who reconciles disputes. The table below is the honest running cost.</p>
    </div>
  </div>
</section>

<section class="section-alt">
  <div class="wrap">
    <div class="section-head">
      <span class="eyebrow">Your actual bill</span>
      <h2>What self-hosting really costs.</h2>
      <p>Typical Indian pricing at the time of writing. Your bank may also charge for the account you receive payments into.</p>
    </div>
    <div class="table-wrap">
      <table class="compare">
        <thead><tr><th>Item</th><th>Typical cost</th><th>Notes</th></tr></thead>
        <tbody>
          ${PRICING.costItems.map(row => `<tr>
            <td>${escapeHtml(row.item)}</td>
            <td class="youpi">${escapeHtml(row.typical)}</td>
            <td class="cross">${escapeHtml(row.note)}</td>
          </tr>`).join('\n')}
        </tbody>
      </table>
    </div>
    <ul class="check-list" style="margin-top:24px">
      ${PRICING.notes.map(note => `<li>${escapeHtml(note)}</li>`).join('\n')}
    </ul>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="section-head">
      <span class="eyebrow">Compare</span>
      <h2>On a ₹5,00,000 monthly turnover.</h2>
      <p>Illustrative only — aggregator rates vary by category and negotiation.</p>
    </div>
    <div class="table-wrap">
      <table class="compare">
        <thead><tr><th>Cost</th><th>2% aggregator</th><th class="youpi-col">${escapeHtml(BRAND.name)}</th></tr></thead>
        <tbody>
          <tr><td>Commission on ₹5L</td><td class="cross">₹10,000</td><td class="youpi"><span class="tick">✓</span> ₹0</td></tr>
          <tr><td>GST on commission (18%)</td><td class="cross">₹1,800</td><td class="youpi"><span class="tick">✓</span> ₹0</td></tr>
          <tr><td>Platform fee</td><td class="cross">₹0 – ₹3,000</td><td class="youpi"><span class="tick">✓</span> ₹0</td></tr>
          <tr><td>Your own hosting</td><td class="youpi">—</td><td class="cross">₹300 – ₹800</td></tr>
          <tr><td><strong>Approx. monthly difference</strong></td><td class="cross">₹11,800+</td><td class="youpi"><span class="tick">✓</span> ₹11,000+ saved</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>

${ctaBand(links)}`;

  return shell({
    title: 'Pricing — YOUPI PG',
    description: 'Zero gateway commission, zero platform fee. What self-hosting a UPI payment gateway actually costs in infrastructure.',
    body,
    active: '/pricing',
    links
  });
}

/* -------------------------------------------------------------------- FAQ -- */

export function renderFaq({ links }) {
  const body = `
${pageHero({
    eyebrow: 'FAQ',
    title: 'The questions people actually ask.',
    lede: 'Straight answers, including the ones about licensing and limits that a marketing page would normally skip.'
  })}

<section>
  <div class="wrap faq-wrap">
    ${FAQ.map(item => `<details class="faq-item">
      <summary>${escapeHtml(item.q)}</summary>
      <p>${escapeHtml(item.a)}</p>
    </details>`).join('\n')}
  </div>
</section>

${ctaBand(links)}`;

  return shell({
    title: 'FAQ — YOUPI PG',
    description: 'Licensing, payment confirmation, limits, data ownership and reselling — answered plainly.',
    body,
    active: '/faq',
    links
  });
}

/* ------------------------------------------------------------------ about -- */

export function renderAbout({ links }) {
  const body = `
${pageHero({
    eyebrow: 'About',
    title: ABOUT.headline,
    lede: ABOUT.intro
  })}

<section>
  <div class="wrap split">
    <div class="prose">
      ${ABOUT.paragraphs.map(p => `<p>${escapeHtml(p)}</p>`).join('\n')}
      <p style="color:var(--muted);font-size:.9rem">${escapeHtml(BRAND.origin)}</p>
    </div>
    <aside class="fact-card">
      ${ABOUT.facts.map(fact => `<div class="fact-row">
        <span>${escapeHtml(fact.label)}</span>
        <strong>${escapeHtml(fact.value)}</strong>
      </div>`).join('\n')}
      <a class="btn btn-outline" style="margin-top:16px;width:100%" href="/docs">Read the architecture docs</a>
    </aside>
  </div>
</section>

<section class="section-alt">
  <div class="wrap">
    <div class="callout">
      <strong>Not a company you can sue for a lost payment.</strong>
      <p>${escapeHtml(BRAND.name)} is a research project, not a licensed aggregator. There is no escrow, no insurance and no regulated entity behind a transaction. If your business cannot absorb that risk, use a licensed provider.</p>
    </div>
  </div>
</section>

${ctaBand(links)}`;

  return shell({
    title: 'About — YOUPI PG',
    description: 'Why this project exists, how it is built, and what it is not.',
    body,
    active: '/about',
    links
  });
}

/* ---------------------------------------------------------------- contact -- */

export function renderContact({ links }) {
  const body = `
${pageHero({
    eyebrow: 'Contact',
    title: CONTACT.headline,
    lede: CONTACT.intro
  })}

<section>
  <div class="wrap">
    <div class="cards">
      ${CONTACT.channels.map(channel => `<article class="card">
        <h3>${escapeHtml(channel.title)}</h3>
        <p>${escapeHtml(channel.body)}</p>
        <p style="margin-top:14px"><a class="btn btn-outline btn-sm" href="${escapeHtml(channel.href)}"${channel.href.startsWith('http') ? ' target="_blank" rel="noopener noreferrer"' : ''}>${escapeHtml(channel.action)} →</a></p>
      </article>`).join('\n')}
    </div>
  </div>
</section>

<section class="section-alt">
  <div class="wrap split">
    <div class="prose">
      <h2 style="font-family:var(--font-display);font-size:1.35rem;margin-bottom:14px">What to include in a report</h2>
      <p>Most "it did not work" reports are missing one of these four things. Including them cuts the back-and-forth to zero:</p>
      <ul class="check-list">
        ${CONTACT.checklist.map(item => `<li>${escapeHtml(item)}</li>`).join('\n')}
      </ul>
      <p style="margin-top:18px">Email: <a href="mailto:${escapeHtml(BRAND.supportEmail)}">${escapeHtml(BRAND.supportEmail)}</a></p>
      <p style="color:var(--muted);font-size:.85rem">Never send webhook secrets, OTPs, session tokens or full customer bank details over email or in a public issue.</p>
    </div>
    <aside class="fact-card">
      <div class="fact-row"><span>Documentation</span><strong><a href="/docs">/docs</a></strong></div>
      <div class="fact-row"><span>Service status</span><strong><a href="/status">/status</a></strong></div>
      <div class="fact-row"><span>Repository</span><strong><a href="${escapeHtml(BRAND.docsRepo)}" target="_blank" rel="noopener noreferrer">GitHub</a></strong></div>
      <div class="fact-row"><span>Merchant panel</span><strong><a href="${escapeHtml(links.admin)}">Dashboard</a></strong></div>
    </aside>
  </div>
</section>`;

  return shell({
    title: 'Contact — YOUPI PG',
    description: 'How to reach the maintainers for bugs, deployment help and security reports.',
    body,
    active: '/contact',
    links
  });
}

/* ----------------------------------------------------------------- status -- */

export function renderStatus({ links, services, gateway }) {
  const rows = services.map(service => {
    const state = service.state;
    const label = state === 'up' ? 'Operational' : state === 'unknown' ? 'Not probed' : 'Unreachable';
    return `<tr>
      <td><strong>${escapeHtml(service.name)}</strong></td>
      <td><span class="status-pill ${state}"><span class="dot"></span>${label}</span></td>
      <td class="cross">${service.latencyMs != null ? `${service.latencyMs} ms` : '—'}</td>
    </tr>`;
  }).join('\n');

  const body = `
${pageHero({
    eyebrow: 'Status',
    title: gateway?.state === 'up' ? 'All systems operational.' : 'Gateway is not responding.',
    lede: 'Live probe results, read server-side from each service. Nothing here is cached — reload to refresh.'
  })}

<section>
  <div class="wrap">
    <div class="table-wrap">
      <table class="compare">
        <thead><tr><th>Service</th><th>Status</th><th>Response</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <p style="color:var(--muted);font-size:.85rem;margin-top:14px">
      Probed at ${escapeHtml(new Date().toISOString())}. Internal services (Gmail observer, SMS observer, Control Center) are
      not exposed publicly and are therefore not probed from here.
    </p>
  </div>
</section>`;

  return shell({
    title: 'Service status — YOUPI PG',
    description: 'Live availability of the website, payment API, checkout portal and merchant dashboard.',
    body,
    active: '/status',
    links
  });
}

/* ------------------------------------------------------------------ legal -- */

const LEGAL_PAGES = {
  terms: {
    title: 'Terms of use',
    intro:
      'These terms describe the conditions under which this website and the YOUPI PG software may be used. By using the site you accept them.',
    sections: [
      ['1. What this software is', [
        'YOUPI PG is self-hosted software for accepting UPI payments. It is not a payment aggregator, a payment gateway service, a bank, or a regulated financial institution, and it holds no customer funds at any point.',
        'The website you are reading is documentation and marketing material for that software. No payment service is offered or performed through this website.'
      ]],
      ['2. Your responsibilities as an operator', [
        'If you deploy this software you become the operator of that payment system. You are responsible for its availability, its data, reconciliation of every payment against your bank records, refunds, disputes, chargebacks and customer communication.',
        'You are also responsible for the legal and regulatory position of your own business, including tax registration and any authorisation required to accept payments from customers.'
      ]],
      ['3. No warranty', [
        'The software is provided "as is", without warranty of any kind, express or implied, including merchantability, fitness for a particular purpose, accuracy and non-infringement.',
        'Bank alerts can be delayed, duplicated, reordered or missed. A parsed message is evidence, not a settlement guarantee. Reconcile against your bank statement before treating any payment as final.'
      ]],
      ['4. Limitation of liability', [
        'To the maximum extent permitted by law, the authors and maintainers are not liable for any loss of profit, revenue, data or goodwill, or for any indirect, incidental, special or consequential damages arising from the use of this software.'
      ]],
      ['5. Acceptable use', [
        'Do not use this software to deceive customers, to hide that a payment was not received, for unlawful goods or services, or in a way that impersonates a licensed payment provider.',
        'Do not present the software as NPCI-, RBI- or bank-approved. It is not.'
      ]],
      ['6. Changes', [
        'These terms and the software may change at any time. Continuing to use the site or the software after a change means you accept the updated terms.'
      ]]
    ]
  },
  privacy: {
    title: 'Privacy notice',
    intro:
      'This notice covers the public website. When you self-host the software, you are the controller of the customer data it stores — this page explains what the software holds and what it deliberately does not.',
    sections: [
      ['1. The public website', [
        'This website sets no advertising or analytics cookies and loads no third-party scripts, fonts or trackers. Assets are served from this origin.',
        'The only outbound request is a server-side health probe to your own payment API to render the status pill. Your browser IP is not stored by the website.'
      ]],
      ['2. What a self-hosted deployment stores', [
        'Payment sessions (amount, order id, status, timestamps), customer mobile number and optional name/email for WhatsApp authentication, device identifiers used for session binding, parsed bank observations (amount, reference number, sender) and merchant webhook configuration.',
        'Sensitive fields such as webhook secrets, OAuth refresh tokens and device keys are encrypted at rest. The database file lives on your own disk, not on a vendor server.'
      ]],
      ['3. WhatsApp and Google', [
        'Sending OTPs requires a WhatsApp session, and the Gmail observer requires a Google OAuth grant. Those providers process the message metadata under their own policies; read them before deployment.',
        'Connect a dedicated number and a dedicated mailbox rather than personal accounts where possible.'
      ]],
      ['4. Retention and deletion', [
        'Retention is whatever your deployment chooses. The repository includes tooling for a clean customer reset and for backing up or resetting the database, and you should schedule both.',
        'Customers who ask for deletion should be handled by the operator of that deployment, not by the maintainers of this project.'
      ]],
      ['5. Your obligations', [
        'Because you hold customer phone numbers and payment records, you are likely a data controller under applicable law. Provide your own privacy notice to your customers and honour access and deletion requests.'
      ]]
    ]
  },
  refund: {
    title: 'Refund & cancellation policy',
    intro:
      'Money moves directly between the customer and the merchant, so refunds are handled by the merchant — this software never holds the funds to reverse them.',
    sections: [
      ['1. No escrow', [
        'A UPI credit lands in the merchant receiving account. The gateway never holds, routes or pools customer funds, so there is nothing for it to refund from.'
      ]],
      ['2. How a refund happens', [
        'The merchant sends the money back to the customer from their own UPI or bank app, using the reference number captured during verification.',
        'Record the refund against the original payment so reconciliation stays clean, and keep the customer informed of the refund reference.'
      ]],
      ['3. Failed, expired and duplicate payments', [
        'A session that times out without a matching credit is marked EXPIRED — no money was taken and nothing needs to be reversed.',
        'Duplicate credits and credits that arrive after a session ended are flagged in the merchant dashboard for manual reconciliation. Do not silently keep them.'
      ]],
      ['4. Disputes', [
        'Because the customer pays a VPA directly, a dispute is a conversation between the customer and the merchant. Publish your own contact details, response window and refund timeline on your storefront.'
      ]],
      ['5. Our policy for this website', [
        'No payment is accepted through this website, therefore no refund can arise from using it. The software itself is distributed under the repository licence.'
      ]]
    ]
  },
  disclaimer: {
    title: 'Disclaimer',
    intro:
      'A single page stating plainly what this project is and what it is not, so nobody can claim they were misled.',
    sections: [
      ['1. Not a licensed provider', [
        'YOUPI PG is an independent, experimental research project. It is not affiliated with, endorsed by, sponsored by or certified by NPCI, RBI, any bank, any UPI application or any payment aggregator.'
      ]],
      ['2. Not a production certification', [
        'No security audit, penetration test or compliance certification is claimed. Review the code and commission your own audit before handling real money.'
      ]],
      ['3. Payment confirmation is evidence, not guarantee', [
        'SMS, email and notification parsing can fail or be forged by a determined attacker. Always reconcile against the bank statement, and treat the gateway status as a strong signal rather than a source of truth.'
      ]],
      ['4. Conservative usage guidance', [
        'For experiments, keep usage to no more than 20 payment attempts per day per receiving account unless you have independently verified the applicable bank, UPI app and current NPCI rules. This is a project guideline, not a statement of any universal limit.'
      ]],
      ['5. Regulatory note', [
        'Operating a payment system may require authorisation in your jurisdiction. Using this software does not grant it. Seek qualified legal and compliance advice before accepting third-party merchant payments.'
      ]]
    ]
  }
};

export function renderLegal({ links, slug }) {
  const page = LEGAL_PAGES[slug];
  if (!page) return null;

  const body = `
${pageHero({
    eyebrow: 'Legal',
    title: page.title,
    lede: page.intro
  })}

<section>
  <div class="wrap">
    <div class="callout" style="margin-bottom:28px">
      <strong>Template document</strong>
      <p>${escapeHtml(LEGAL_DISCLAIMER)}</p>
    </div>
    <div class="prose legal-prose">
      ${page.sections.map(([heading, paragraphs]) => legalSection(heading, paragraphs)).join('\n')}
      <p style="color:var(--muted);font-size:.85rem;margin-top:30px">Last updated: ${new Date().toISOString().slice(0, 10)}</p>
    </div>
  </div>
</section>`;

  return shell({
    title: `${page.title} — ${BRAND.name}`,
    description: page.intro,
    body,
    active: '',
    links
  });
}

export const LEGAL_SLUGS = Object.keys(LEGAL_PAGES);
