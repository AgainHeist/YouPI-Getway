/**
 * Single source of truth for every piece of marketing copy on the public site.
 *
 * Pages import from here instead of duplicating strings, so "why", "features",
 * "pricing" and the home page can never drift apart. Nothing in this file is
 * user-supplied, so it is rendered with plain escaping.
 */

export const BRAND = {
  name: process.env.SITE_BRAND_NAME || 'YOUPI PG',
  tagline: 'Payments Infrastructure',
  claim: 'Accept UPI payments. Keep every rupee.',
  description:
    'A self-hosted UPI payment gateway that settles straight into your own bank account. WhatsApp OTP authentication, vector QR checkout and a three-channel bank observation engine — running on your server, under your brand.',
  origin: 'Originally created by Gaurav (github.com/gxurav1710) and now maintained by Zenuxs (zenuxs.in).',
  supportEmail: process.env.SITE_SUPPORT_EMAIL || 'support@youpi.local',
  docsRepo: 'https://github.com/AgainHeist/YouPI-Getway'
};

export const FEATURES = [
  {
    icon: '₹0',
    title: 'Zero gateway fees',
    body: 'No 2–3% cut and no 18% GST on the fee. The money lands straight in your own bank account, so the full amount is yours.',
    group: 'money'
  },
  {
    icon: '⚡',
    title: 'Direct settlement',
    body: 'The customer pays your VPA. There is no pooled nodal account and no T+2 holdback to wait out before you can use the money.',
    group: 'money'
  },
  {
    icon: '💬',
    title: 'WhatsApp OTP gate',
    body: 'A 6-digit code is delivered through WhatsApp before the timer starts, so spoofed phone numbers cannot occupy a payment slot.',
    group: 'checkout'
  },
  {
    icon: '🔍',
    title: 'Bank observation mesh',
    body: 'Android SMS, Gmail alerts and the SMS observer all feed one normaliser that matches credits by amount, account and time window.',
    group: 'detection'
  },
  {
    icon: '🎟️',
    title: 'FIFO single-slot queue',
    body: 'One active payment per receiving account keeps amount-only matching deterministic. Waiting customers get a live queue position.',
    group: 'detection'
  },
  {
    icon: '🎨',
    title: '100% white label',
    body: 'Logo, colours, domain, support details and the checkout copy are all yours. No "powered by" badge anywhere in the flow.',
    group: 'brand'
  },
  {
    icon: '🧾',
    title: 'Till desk built in',
    body: 'Cash at counter and card at POS fall back inside the same checkout, with a cashier dock that approves or declines in real time.',
    group: 'checkout'
  },
  {
    icon: '🔐',
    title: 'Signed webhooks',
    body: 'HMAC-SHA256 over the raw request body, replay-safe delivery ids, retries with backoff and an SSRF guard on merchant endpoints.',
    group: 'security'
  },
  {
    icon: '🛡️',
    title: 'Fraud pipeline',
    body: 'Duplicate-credit detection, late-observation flagging, device binding and manual ban controls give the operator a real kill switch.',
    group: 'security'
  },
  {
    icon: '🗄️',
    title: 'Your own database',
    body: 'A single SQLite file with WAL journalling on your disk. No vendor cloud, no export request, no per-record pricing.',
    group: 'brand'
  },
  {
    icon: '📱',
    title: 'Offline-first detection',
    body: 'The Android observer app keeps working when the laptop sleeps; alerts queue and replay with anti-replay timestamps.',
    group: 'detection'
  },
  {
    icon: '🧩',
    title: 'Framework agnostic SDK',
    body: 'One script tag for plain HTML, plus a programmatic API for React, Vue, Next.js and Nuxt. No build step required.',
    group: 'checkout'
  }
];

export const STEPS = [
  {
    title: 'Create the session',
    body: 'Your site calls POST /api/v1/payments with the amount and order id, and gets back a checkout URL.',
    detail: 'Server-to-server call. The merchant key stays on your server; only the session id reaches the browser.'
  },
  {
    title: 'Authenticate',
    body: 'The customer verifies their mobile over WhatsApp OTP, so the gateway knows who is paying before a slot is held.',
    detail: 'Inbound WhatsApp OTPs are not spoofable like SMS senders, which is what makes the pre-checkout gate useful.'
  },
  {
    title: 'Pay by UPI',
    body: 'A vector QR plus one-tap intents for GPay, PhonePe, Paytm and CRED, with a 5-minute server-authoritative timer.',
    detail: 'The checkout page is served from your own domain; the timer is owned by the server, not by browser JavaScript.'
  },
  {
    title: 'Detect and settle',
    body: 'A matching bank credit inside the verification window flips the session to SUCCESS and fires a signed webhook.',
    detail: 'Detection is independent of the browser: closing the tab never loses a payment.'
  }
];

export const COMPARISON = [
  ['Transaction fee', '2–3% + 18% GST', '0% forever'],
  ['Settlement', 'T+2 to T+3 business days', 'Direct to your bank'],
  ['Branding', 'Provider badge mandatory', 'Fully white label'],
  ['Payment proof', 'Provider webhook only', 'SMS + Gmail + Android observers'],
  ['Offline counter', 'Extra POS hardware', 'Built-in cash / card till'],
  ['Data ownership', 'Vendor cloud', 'Your own SQLite database'],
  ['Approval', 'Not available to every business', 'No aggregator approval needed'],
  ['Payout control', 'Provider schedules payouts', 'Money never leaves your account']
];

export const WHY_POINTS = [
  {
    title: 'The fee is not the only cost',
    body: 'Aggregators take 2–3% plus GST, hold settlement for two to three days, and can freeze an account mid-quarter. For a small merchant that is working capital sitting in somebody else\'s ledger.',
    tag: 'Problem'
  },
  {
    title: 'You already own a bank account',
    body: 'A UPI credit needs no intermediary: the customer pays your VPA and the money is already yours. What a gateway actually adds is the checkout experience and the proof that the payment happened — this project rebuilds those two pieces.',
    tag: 'Insight'
  },
  {
    title: 'Proof without a provider webhook',
    body: 'Instead of waiting for a vendor to tell you money arrived, YOUPI PG reads the same bank alerts you already get — SMS on an Android phone, email in Gmail, or the Google Messages web session — and matches them to the open session.',
    tag: 'Mechanism'
  },
  {
    title: 'What you take on yourself',
    body: 'Running this means you operate a payment system: uptime, backups, reconciliation, dispute handling and the legal questions that come with accepting money. This site is deliberately honest about that instead of hiding it in a footnote.',
    tag: 'Honesty'
  }
];

export const AUDIENCE = [
  { title: 'Small online stores', body: 'A few dozen orders a day, where a 2.5% cut genuinely decides the margin.' },
  { title: 'Local retail counters', body: 'Shops that want a QR plus a cash/card till desk on the same screen as the online store.' },
  { title: 'Developers and tinkerers', body: 'People who want to read the whole payment path instead of trusting a black box.' },
  { title: 'Not yet a fit', body: 'High-volume, compliance-critical or regulated flows: use a licensed aggregator until you have done that diligence.' }
];

export const PRICING = {
  headline: 'Zero gateway commission. Pay for your own infrastructure.',
  sub: 'There is no per-transaction fee in this software. What you pay is whatever your server, domain and WhatsApp session cost you.',
  rows: [
    { item: 'Setup fee', amount: '₹0', note: 'Self-hosted, open codebase' },
    { item: 'Per transaction', amount: '₹0', note: 'No commission, no GST on a fee' },
    { item: 'Settlement delay', amount: 'None', note: 'Customer pays your VPA directly' },
    { item: 'Monthly platform fee', amount: '₹0', note: 'No vendor account required' }
  ],
  costItems: [
    { item: 'Server or VPS', typical: '₹300 – ₹800 / month', note: 'A 1 vCPU / 1 GB box handles a small store' },
    { item: 'Domain name', typical: '₹800 – ₹1,200 / year', note: 'Needed for HTTPS checkout links' },
    { item: 'Cloudflare Tunnel', typical: 'Free tier', note: 'Avoids opening inbound ports' },
    { item: 'WhatsApp device', typical: 'Your existing number', note: 'A spare SIM is safer than your primary line' },
    { item: 'Gmail observer', typical: 'Free tier', note: 'Optional second detection channel' }
  ],
  notes: [
    'Bank charges, UPI limits and account-level restrictions are set by your bank, not by this software.',
    'If you take real customer money, talk to a chartered accountant about GST and to a lawyer about your obligations.'
  ]
};

export const FAQ = [
  {
    q: 'Is this a licensed payment aggregator?',
    a: 'No. YOUPI PG is self-hosted software you run yourself, not a licensed payment aggregator or a bank-approved service. There is no NPCI, RBI or bank certification behind it, and the project does not claim one.'
  },
  {
    q: 'Then how does a payment actually get confirmed?',
    a: 'The customer pays your UPI VPA, and the gateway matches the bank credit alert (Android SMS, Gmail or the Google Messages observer) to the open session by amount, receiving account and time window.'
  },
  {
    q: 'What if two customers pay the same amount at once?',
    a: 'One receiving account only ever has one active payment slot. Everyone else waits in a FIFO queue with a visible position, so amount-only matching stays deterministic.'
  },
  {
    q: 'Can a customer fake a payment?',
    a: 'The browser cannot mark a session paid — only a normalised bank observation inside the verification window can. Screenshots and browser callbacks are never treated as proof.'
  },
  {
    q: 'What happens if the server restarts mid-payment?',
    a: 'Sessions, the queue and pending webhooks are persisted in SQLite with WAL journalling. On boot the recovery engine re-arms live timers, expires stale slots and reschedules undelivered webhooks.'
  },
  {
    q: 'Do I need the Android app?',
    a: 'No. Any one of the three observers is enough to settle a payment; a second and third channel only raise the verification level (L1 → L3).'
  },
  {
    q: 'Does this work outside India?',
    a: 'The checkout is built around UPI (VPA, UPI intents, UPI QR), so it is an India-first product. The bank-alert parsers cover Indian banks and their SMS/email formats.'
  },
  {
    q: 'How many transactions per day is it tested for?',
    a: 'The project guideline is deliberately conservative: keep experiments at or below 20 payment attempts per day per receiving account unless you have independently verified the applicable bank, UPI app and NPCI rules.'
  },
  {
    q: 'Can I charge merchants to use my deployment?',
    a: 'Reselling payment services is a regulated activity. Using this code does not by itself authorise you to operate a payment system — get qualified legal and compliance advice first.'
  },
  {
    q: 'Where does my data live?',
    a: 'In one SQLite file on your own disk (plus an encrypted secrets directory). Nobody can pull it from a vendor cloud because there is no vendor cloud.'
  }
];

export const ABOUT = {
  headline: 'Built in the open, run by you.',
  intro:
    'YOUPI PG started as an experiment: what does a payment gateway actually do once you strip away the brand, the fee and the pooled account? The answer turned out to be three things — a checkout, a proof of payment, and a queue that keeps both honest.',
  paragraphs: [
    'The project is a research and learning exercise, published so other developers can read, test and criticise the whole payment path. Every payment decision in the codebase is meant to be auditable: no hidden service decides that money arrived.',
    'It is deliberately dependency-light — native Node.js, an embedded SQLite file, and a browser bundle you can read in an afternoon — because a payment system you cannot inspect is a payment system you cannot trust.',
    'Today the codebase ships a checkout portal with WhatsApp OTP, three independent bank-observation channels, a till-desk mode for offline counters, a white-label branding engine, a merchant dashboard and 40 automated test suites.'
  ],
  facts: [
    { label: 'Architecture', value: 'Native Node.js + embedded SQLite (WAL)' },
    { label: 'Detection channels', value: 'Android SMS, Gmail API, Google Messages' },
    { label: 'Test suites', value: '40 curated suites' },
    { label: 'Licence', value: 'Commercial — see the repository' }
  ]
};

export const CONTACT = {
  headline: 'Talk to the people who build it.',
  intro:
    'This is a self-hosted product, so most support questions are really engineering questions. The fastest answer usually comes from the repository itself — the docs below are the same guides the maintainers use.',
  channels: [
    {
      title: 'Bug reports & feature requests',
      body: 'Open an issue on the repository with the exact request id, the session id and the relevant log lines. That is the only channel that reaches the maintainers reliably.',
      action: 'Open an issue',
      href: 'https://github.com/AgainHeist/YouPI-Getway/issues'
    },
    {
      title: 'Deployment & integration help',
      body: 'Read the deployment and developer integration guides first; they cover domain setup, tunnel configuration, webhook verification and the SDK contract.',
      action: 'Read the docs',
      href: '/docs'
    },
    {
      title: 'Security reports',
      body: 'If you find a vulnerability, please do not open a public issue. Email the maintainers with steps to reproduce and give them a reasonable window to fix it before disclosure.',
      action: 'Email security',
      href: 'mailto:security@youpi.local'
    }
  ],
  checklist: [
    'What you expected to happen, and what happened instead',
    'The payment / session id (never the webhook secret or OTP)',
    'Your Node.js version and whether you run the Android, Gmail or SMS observer',
    'Relevant lines from the Control Center log, with secrets removed'
  ]
};

export const STATUS_SERVICES = [
  { id: 'website', name: 'Website & docs', probe: 'self' },
  { id: 'payment-api', name: 'Payment API', probe: 'api' },
  { id: 'checkout', name: 'Checkout portal', probe: 'link', urlKey: 'checkout' },
  { id: 'admin', name: 'Merchant dashboard', probe: 'link', urlKey: 'admin' },
  { id: 'store', name: 'Demo store', probe: 'link', urlKey: 'store' }
];

export const TRUST_NOTES = [
  'Server-authoritative state machine — the browser can never mark a payment successful.',
  'HMAC-SHA256 webhook signatures verified over the raw body, with replay protection.',
  'Device binding and fail-closed session access control on the checkout.',
  'Rate limits, OTP cooldowns and a fraud pipeline with manual ban controls.'
];

export const LEGAL_DISCLAIMER =
  'This document is a starting template supplied with the software, not legal advice. Laws differ by jurisdiction and change over time — have a qualified lawyer review and adapt it before you accept real customer payments.';
