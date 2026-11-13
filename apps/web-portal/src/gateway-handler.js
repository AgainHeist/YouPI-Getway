import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import {
  getDatabase,
  runMigrations,
  MerchantRepository,
  ReceivingAccountRepository,
  PaymentSessionRepository
} from '@youpi/db';
import {
  getAdminToken,
  getObserverToken,
  getCoinStoreWebhookSecret,
  safeEqual,
  toRupeesString,
  PaymentStatus
} from '@youpi/common';
import { createPaymentApp } from '../../payment-api/src/index.js';
import { CheckoutServer } from '../../checkout-portal/src/server.js';
import { CoinWalletStoreServer } from '../../coin-wallet-store/src/server.js';
import { AdminServer } from '../../merchant-admin/src/server.js';
import { HelpServer } from '../../payment-help/src/server.js';
import { renderMarkdown, escapeHtml } from './markdown.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, '../../..');

const WEB_SECURITY_HEADERS = Object.freeze({
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Content-Security-Policy': "default-src 'self' data: blob:; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; script-src 'self' 'unsafe-inline'; frame-src 'self'; base-uri 'none'; form-action 'self'; object-src 'none'"
});

const DOCS_CATALOG = [
  { slug: 'overview', title: 'Platform Overview (README)', file: 'README.md' },
  { slug: 'architecture', title: 'System Architecture V2', file: 'ARCHITECTURE.md' },
  { slug: 'installation', title: 'Installation Guide', file: 'docs/INSTALLATION.md' },
  { slug: 'deployment', title: 'Deployment & SSL Guide', file: 'docs/DEPLOYMENT.md' },
  { slug: 'developer-integration', title: 'Developer SDK Integration', file: 'docs/DEVELOPER_INTEGRATION.md' },
  { slug: 'merchant-integration', title: 'Merchant Setup Guide', file: 'docs/MERCHANT_INTEGRATION.md' },
  { slug: 'white-label', title: 'White-Label Customization', file: 'docs/WHITE_LABEL.md' },
  { slug: 'android-observer', title: 'Android SMS Observer App', file: 'docs/ANDROID_MOBILE_APP.md' },
  { slug: 'observers-setup', title: 'SMS & Gmail Observers', file: 'docs/OBSERVERS_SETUP.md' },
  { slug: 'google-cloud-oauth', title: 'Google Cloud OAuth2 Setup', file: 'docs/google_cloud_console_setup_guide.md' },
  { slug: 'configuration', title: 'Environment Configuration', file: 'docs/CONFIGURATION.md' },
  { slug: 'troubleshooting', title: 'Operations & Troubleshooting', file: 'docs/OPERATIONS_TROUBLESHOOTING.md' }
];

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.woff2': 'font/woff2',
  '.yaml': 'text/yaml; charset=utf-8',
  '.apk': 'application/vnd.android.package-archive',
  '.sha256': 'text/plain; charset=utf-8'
};

let runtimePromise = null;

function listenLoopback(server) {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const addr = server.address();
      if (typeof server.unref === 'function') {
        server.unref();
      }
      resolve(typeof addr === 'object' && addr ? addr.port : 0);
    });
  });
}

function injectDemoBridge(html) {
  if (process.env.YOUPI_DEMO_MODE !== 'true') return html;
  if (!html || html.includes('/site/demo-bridge.js')) return html;
  const tag = '\n  <script src="/site/demo-bridge.js"></script>\n</body>';
  if (html.includes('</body>')) {
    return html.replace('</body>', tag);
  }
  return html + '\n<script src="/site/demo-bridge.js"></script>';
}

function dispatchWithBridgeInjection(server, req, res) {
  if (process.env.YOUPI_DEMO_MODE !== 'true' || req.method !== 'GET') {
    server.emit('request', req, res);
    return;
  }

  let isHtml = false;
  let statusCode = 200;
  let capturedHeaders = null;
  const chunks = [];
  const origWriteHead = res.writeHead.bind(res);
  const origWrite = res.write.bind(res);
  const origEnd = res.end.bind(res);

  res.writeHead = function (code, reasonOrHeaders, maybeHeaders) {
    statusCode = code;
    const hdrs = (typeof reasonOrHeaders === 'object' && reasonOrHeaders !== null)
      ? { ...reasonOrHeaders }
      : (maybeHeaders ? { ...maybeHeaders } : {});
    const ct = String(hdrs['Content-Type'] || hdrs['content-type'] || '').toLowerCase();
    if (ct.includes('text/html')) {
      isHtml = true;
      delete hdrs['Content-Length'];
      delete hdrs['content-length'];
      capturedHeaders = hdrs;
      return res;
    }
    return origWriteHead(code, reasonOrHeaders, maybeHeaders);
  };

  res.write = function (chunk, encoding, cb) {
    if (isHtml) {
      if (chunk) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk), typeof encoding === 'string' ? encoding : 'utf8'));
      if (typeof encoding === 'function') encoding();
      else if (typeof cb === 'function') cb();
      return true;
    }
    return origWrite(chunk, encoding, cb);
  };

  res.end = function (chunk, encoding, cb) {
    if (isHtml) {
      if (chunk && typeof chunk !== 'function') {
        chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk), typeof encoding === 'string' ? encoding : 'utf8'));
      }
      const rawHtml = Buffer.concat(chunks).toString('utf8');
      const modified = injectDemoBridge(rawHtml);
      origWriteHead(statusCode, capturedHeaders || { 'Content-Type': 'text/html; charset=utf-8' });
      return origEnd(modified, 'utf8', typeof chunk === 'function' ? chunk : (typeof encoding === 'function' ? encoding : cb));
    }
    return origEnd(chunk, encoding, cb);
  };

  server.emit('request', req, res);
}

/**
 * Initializes the unified single-process YOUPI PG Web + Gateway runtime.
 */
export async function getUnifiedGatewayRuntime(options = {}) {
  if (runtimePromise && !options.customDb) {
    return runtimePromise;
  }

  const init = async () => {
    process.env.YOUPI_UNIFIED_WEB = 'true';

    const db = options.customDb || getDatabase();
    runMigrations(db);

    // Ensure coin-wallet-store webhook secret matches default merchant if not customized
    const merchantId = '00000000-0000-0000-0000-000000000001';
    const storeSecret = getCoinStoreWebhookSecret();

    // 1. Create and bind internal loopback PaymentApp so all internal service-to-service
    //    requests (CheckoutServer, CoinWalletStore, AdminServer) execute natively in <0.5ms.
    const paymentApp = createPaymentApp(options.customDb ? db : null);
    const apiPort = await listenLoopback(paymentApp.rawServer);
    process.env.PAYMENT_API_PORT = String(apiPort);
    process.env.PAYMENT_API_INTERNAL_URL = `http://127.0.0.1:${apiPort}`;
    process.env.BASE_PAYMENT_API_URL = `http://127.0.0.1:${apiPort}`;

    // 2. Create and bind internal loopback CheckoutServer
    const checkoutApp = new CheckoutServer({ apiBaseUrl: `http://127.0.0.1:${apiPort}` });
    const checkoutHttp = checkoutApp.createServer();
    const checkoutPort = await listenLoopback(checkoutHttp);
    process.env.CHECKOUT_PORT = String(checkoutPort);

    // 3. Create Store, Admin, and Help servers
    const publicSiteUrl = (
      process.env.COIN_STORE_PUBLIC_URL ||
      (process.env.VERCEL_PROJECT_PRODUCTION_URL ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}` : '') ||
      (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : '') ||
      `http://localhost:${process.env.PORT || 3080}`
    ).replace(/\/+$/, '');

    // Wire store webhook URL to internal unified store server so signed webhooks credit wallet coins automatically
    const storeApp = new CoinWalletStoreServer({
      gatewayApiUrl: `http://127.0.0.1:${apiPort}`,
      merchantId,
      webhookSecret: storeSecret,
      publicBaseUrl: publicSiteUrl
    });
    const storeHttp = storeApp.createServer();
    const storePort = await listenLoopback(storeHttp);

    try {
      const mRepo = new MerchantRepository(db);
      const m = mRepo.findById(merchantId);
      if (m && (!m.webhookUrl || m.webhookUrl.includes('localhost:5000'))) {
        db.execute('UPDATE merchants SET webhook_secret = ?, webhook_url = ? WHERE id = ?', [
          storeSecret,
          `http://127.0.0.1:${storePort}/api/webhook`,
          merchantId
        ]);
      }
    } catch {}

    const adminApp = new AdminServer({ db, apiBaseUrl: `http://127.0.0.1:${apiPort}` });
    const adminHttp = adminApp.createServer();

    const helpApp = new HelpServer({ db, apiBaseUrl: `http://127.0.0.1:${apiPort}` });
    const helpHttp = helpApp.createServer();

    const landingTemplate = fs.readFileSync(path.join(__dirname, 'views', 'landing.html'), 'utf8');
    const docsTemplate = fs.readFileSync(path.join(__dirname, 'views', 'docs.html'), 'utf8');
    const apiDocsTemplate = fs.readFileSync(path.join(__dirname, 'views', 'api-docs.html'), 'utf8');

    const startedAt = new Date().toISOString();

    return {
      db,
      apiPort,
      checkoutPort,
      storePort,
      paymentApp,
      checkoutHttp,
      storeApp,
      storeHttp,
      adminHttp,
      helpHttp,
      landingTemplate,
      docsTemplate,
      apiDocsTemplate,
      startedAt,
      async close() {
        try { paymentApp.destroy(); } catch {}
        await Promise.allSettled([
          new Promise(r => paymentApp.rawServer.close(() => r())),
          new Promise(r => checkoutHttp.close(() => r())),
          new Promise(r => storeHttp.close(() => r()))
        ]);
      }
    };
  };

  if (options.customDb) {
    return init();
  }
  runtimePromise = init();
  return runtimePromise;
}

function tryServeStatic(pathname, method, res) {
  if (method !== 'GET' && method !== 'HEAD') return false;

  const staticRoots = [
    { prefix: '/site/', dir: path.join(__dirname, '..', 'public', 'site') },
    { prefix: '/assets/', dir: path.join(repoRoot, 'apps', 'coin-wallet-store', 'public', 'assets') },
    { prefix: '/assets/', dir: path.join(repoRoot, 'docs', 'assets') },
    { prefix: '/icons/', dir: path.join(repoRoot, 'apps', 'checkout-portal', 'public', 'icons') },
    { prefix: '/fonts/', dir: path.join(repoRoot, 'apps', 'merchant-admin', 'public', 'fonts') }
  ];

  if (pathname === '/favicon.svg' || pathname === '/og-banner.svg') {
    const filePath = path.join(__dirname, '..', 'public', pathname.slice(1));
    if (fs.existsSync(filePath)) {
      res.writeHead(200, {
        'Content-Type': 'image/svg+xml',
        'Cache-Control': 'public, max-age=86400',
        'X-Content-Type-Options': 'nosniff'
      });
      if (method === 'HEAD') { res.end(); return true; }
      fs.createReadStream(filePath).pipe(res);
      return true;
    }
  }

  if (pathname === '/css/checkout.css') {
    const f = path.join(repoRoot, 'apps', 'checkout-portal', 'public', 'css', 'checkout.css');
    if (fs.existsSync(f)) {
      res.writeHead(200, { 'Content-Type': 'text/css; charset=utf-8', 'Cache-Control': 'public, max-age=3600' });
      if (method === 'HEAD') { res.end(); return true; }
      fs.createReadStream(f).pipe(res);
      return true;
    }
  }

  if (pathname === '/css/store.css') {
    const f = path.join(repoRoot, 'apps', 'coin-wallet-store', 'public', 'css', 'store.css');
    if (fs.existsSync(f)) {
      res.writeHead(200, { 'Content-Type': 'text/css; charset=utf-8', 'Cache-Control': 'public, max-age=3600' });
      if (method === 'HEAD') { res.end(); return true; }
      fs.createReadStream(f).pipe(res);
      return true;
    }
  }

  if (pathname === '/js/store.js') {
    const f = path.join(repoRoot, 'apps', 'coin-wallet-store', 'public', 'js', 'store.js');
    if (fs.existsSync(f)) {
      res.writeHead(200, { 'Content-Type': 'application/javascript; charset=utf-8', 'Cache-Control': 'no-cache' });
      if (method === 'HEAD') { res.end(); return true; }
      fs.createReadStream(f).pipe(res);
      return true;
    }
  }

  if (pathname === '/openapi.yaml') {
    const f = path.join(repoRoot, 'openapi.yaml');
    if (fs.existsSync(f)) {
      res.writeHead(200, {
        'Content-Type': 'text/yaml; charset=utf-8',
        'Access-Control-Allow-Origin': '*',
        'X-Content-Type-Options': 'nosniff'
      });
      if (method === 'HEAD') { res.end(); return true; }
      fs.createReadStream(f).pipe(res);
      return true;
    }
  }

  if (pathname === '/youpi-sms-gateway.apk' || pathname === '/youpi-sms-gateway.apk.sha256') {
    const fname = path.basename(pathname);
    const candidates = [
      path.join(repoRoot, 'apps', 'android-observer-app', fname),
      path.join(repoRoot, 'apps', 'merchant-admin', 'public', fname),
      path.join(repoRoot, 'apps', 'payment-api', 'public', fname)
    ];
    for (const candidate of candidates) {
      if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
        const stat = fs.statSync(candidate);
        const ext = path.extname(fname).toLowerCase();
        const headers = {
          'Content-Type': MIME_TYPES[ext] || 'application/octet-stream',
          'Content-Length': stat.size,
          'Access-Control-Allow-Origin': '*',
          'X-Content-Type-Options': 'nosniff'
        };
        if (ext === '.apk') {
          headers['Content-Disposition'] = 'attachment; filename="youpi-sms-gateway.apk"';
        }
        res.writeHead(200, headers);
        if (method === 'HEAD') { res.end(); return true; }
        fs.createReadStream(candidate).pipe(res);
        return true;
      }
    }
  }

  for (const entry of staticRoots) {
    if (pathname.startsWith(entry.prefix)) {
      const relReq = pathname.slice(entry.prefix.length);
      const safeTarget = path.resolve(entry.dir, relReq);
      const relCheck = path.relative(entry.dir, safeTarget);
      if (relCheck && !relCheck.startsWith('..') && !path.isAbsolute(relCheck) && fs.existsSync(safeTarget) && fs.statSync(safeTarget).isFile()) {
        const ext = path.extname(safeTarget).toLowerCase();
        res.writeHead(200, {
          'Content-Type': MIME_TYPES[ext] || 'application/octet-stream',
          'Cache-Control': ext === '.js' || ext === '.css' ? 'no-cache' : 'public, max-age=86400',
          'Access-Control-Allow-Origin': '*',
          'X-Content-Type-Options': 'nosniff'
        });
        if (method === 'HEAD') { res.end(); return true; }
        fs.createReadStream(safeTarget).pipe(res);
        return true;
      }
    }
  }

  return false;
}

function readJsonBody(req, maxBytes = 64 * 1024) {
  if (req.body && typeof req.body === 'object' && !Buffer.isBuffer(req.body)) {
    return Promise.resolve(req.body);
  }
  return new Promise((resolve, reject) => {
    let raw = '';
    let tooBig = false;
    req.on('data', chunk => {
      if (tooBig) return;
      raw += chunk;
      if (raw.length > maxBytes) {
        tooBig = true;
        raw = '';
        reject(new Error('Request body too large'));
      }
    });
    req.on('end', () => {
      if (tooBig) return;
      if (!raw.trim()) { resolve({}); return; }
      try { resolve(JSON.parse(raw)); } catch { reject(new Error('Invalid JSON')); }
    });
    req.on('error', reject);
  });
}

function sendJson(res, status, data) {
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff'
  });
  res.end(JSON.stringify(data));
}

function checkBearerAdmin(req) {
  const match = /^Bearer\s+(.+)$/i.exec(req.headers?.authorization || '');
  return Boolean(match && safeEqual(match[1].trim(), getAdminToken()));
}

/**
 * Creates a request handler `(req, res) => Promise<void>` suitable for both
 * Vercel Serverless Functions (`api/index.js`) and standalone HTTP servers.
 */
export function createUnifiedGatewayHandler(runtimeOptions = {}) {
  return async function unifiedHandler(req, res) {
    const rt = await getUnifiedGatewayRuntime(runtimeOptions);
    const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);
    const pathname = url.pathname;
    const method = (req.method || 'GET').toUpperCase();

    if (method === 'OPTIONS') {
      res.writeHead(204, {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization, Idempotency-Key, X-Merchant-Id, X-Merchant-Key, X-Device-Id, X-Device-Token, X-Device-Signature, X-Device-Payload, X-Timestamp, X-Signature, X-Gateway-Signature, X-Gateway-Event, X-Gateway-Delivery-Id, X-Gateway-Timestamp'
      });
      res.end();
      return;
    }

    // 1. Fast static asset handling
    if (tryServeStatic(pathname, method, res)) {
      return;
    }

    // 2. Live Platform Telemetry: GET /api/platform/status
    if (pathname === '/api/platform/status' && method === 'GET') {
      const mRepo = new MerchantRepository(rt.db);
      const aRepo = new ReceivingAccountRepository(rt.db);
      const merchant = mRepo.findById('00000000-0000-0000-0000-000000000001') || mRepo.findAll()[0];
      const account = merchant ? aRepo.findActiveForMerchant(merchant.id) : null;
      const totalRow = rt.db.queryOne('SELECT COUNT(*) AS cnt FROM payment_sessions');
      const queueRow = account
        ? rt.db.queryOne("SELECT COUNT(*) AS cnt FROM payment_sessions WHERE receiving_account_id = ? AND status = 'QUEUED'", [account.id])
        : { cnt: 0 };

      sendJson(res, 200, {
        status: 'UP',
        platform: 'YOUPI PG V2 Unified Gateway',
        runtime: process.env.VERCEL ? 'vercel-serverless' : 'node-host',
        demoSandbox: process.env.YOUPI_DEMO_MODE === 'true',
        merchantName: merchant?.businessName || 'YOUPI Store',
        appName: merchant?.branding?.appName || 'YOUPI PG',
        receivingVpa: account?.upiId || 'merchant@upi',
        isSlotBusy: Boolean(account?.isSlotBusy),
        queueDepth: Number(queueRow?.cnt || 0),
        totalSessions: Number(totalRow?.cnt || 0),
        walletCoins: rt.storeApp.walletCoins,
        startedAt: rt.startedAt
      });
      return;
    }

    // 3. Cloud Sandbox Helpers (Active strictly when YOUPI_DEMO_MODE === 'true')
    if (pathname === '/api/demo/admin-unlock' && method === 'POST') {
      if (process.env.YOUPI_DEMO_MODE !== 'true') {
        sendJson(res, 403, { error: 'Demo unlock is disabled in strict production mode.' });
        return;
      }
      sendJson(res, 200, { success: true, token: getAdminToken() });
      return;
    }

    if (pathname === '/api/demo/simulate-payment' && method === 'POST') {
      if (process.env.YOUPI_DEMO_MODE !== 'true') {
        sendJson(res, 403, { error: 'Sandbox payment simulator is disabled.' });
        return;
      }
      try {
        const body = await readJsonBody(req);
        const paymentId = String(body.paymentId || '').trim();
        if (!paymentId) {
          sendJson(res, 400, { error: 'paymentId is required' });
          return;
        }
        const sRepo = new PaymentSessionRepository(rt.db);
        let session = sRepo.findById(paymentId);
        if (!session) {
          sendJson(res, 404, { error: 'Payment session not found' });
          return;
        }

        if (session.status === PaymentStatus.SUCCESS) {
          sendJson(res, 200, { success: true, alreadyPaid: true, status: session.status, utr: session.utr || 'VERIFIED' });
          return;
        }

        // If buyer hasn't bound customer yet on INITIATED or QUEUED, ensure slot is active so attribution succeeds cleanly
        if (session.status === PaymentStatus.INITIATED || session.status === PaymentStatus.QUEUED) {
          if (session.receivingAccountId) {
            rt.paymentApp.context.queueEngine.enqueueOrActivate(session.id, session.receivingAccountId);
            session = sRepo.findById(paymentId);
          }
        }

        if (session.status !== PaymentStatus.ACTIVE && session.status !== PaymentStatus.PROCESSING) {
          sendJson(res, 409, {
            error: `Session is currently ${session.status}. Please ensure this slot is active first.`
          });
          return;
        }

        const amountStr = toRupeesString(session.amountPaise);
        const utr = String(crypto.randomInt(100000000000, 999999999999));
        const recvAccountId = session.receivingAccountId;
        const obsHeaders = {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${getObserverToken()}`
        };

        // Channel 1: Bank SMS Credit Observation
        await fetch(`http://127.0.0.1:${rt.apiPort}/api/v1/pollers/events`, {
          method: 'POST',
          headers: obsHeaders,
          body: JSON.stringify({
            source: 'SMS_GATEWAY',
            receivingAccountId: recvAccountId,
            amountPaise: session.amountPaise.toString(),
            amount: amountStr,
            utr,
            rawText: `Dear Customer, A/C *4821 credited by Rs ${amountStr} on ${new Date().toISOString().slice(0, 10)} by UPI/buyer@okaxis/Ref ${utr} - HDFC Bank`,
            observedAt: new Date().toISOString()
          })
        });

        // Channel 2: Bank Gmail Alert Observation -> Upgrades to Level 2 Dual Verification & settles to SUCCESS immediately
        const gmailRes = await fetch(`http://127.0.0.1:${rt.apiPort}/api/v1/pollers/events`, {
          method: 'POST',
          headers: obsHeaders,
          body: JSON.stringify({
            source: 'GMAIL',
            receivingAccountId: recvAccountId,
            amountPaise: session.amountPaise.toString(),
            amount: amountStr,
            utr,
            rawText: `Dear Customer, INR ${amountStr} credited to HDFC Bank A/C *4821. UPI Ref: ${utr}`,
            observedAt: new Date().toISOString()
          })
        });
        const gmailJson = await gmailRes.json().catch(() => ({}));
        const updated = sRepo.findById(paymentId);

        sendJson(res, 200, {
          success: updated?.status === PaymentStatus.SUCCESS,
          status: updated?.status || session.status,
          utr,
          amount: amountStr,
          verificationLevel: updated?.verificationLevel || gmailJson?.attribution?.verificationLevel || 2
        });
      } catch (err) {
        sendJson(res, 500, { error: err.message || 'Simulation failed' });
      }
      return;
    }

    // 4. Unified Cloud Supervisor Endpoints for /admin Supervisor Tab
    if (pathname.startsWith('/api/services') || pathname === '/api/logs/stream') {
      if (!checkBearerAdmin(req)) {
        sendJson(res, 401, { error: 'Unauthorized', code: 'AUTH_REQUIRED' });
        return;
      }
      if (pathname === '/api/logs/stream') {
        res.writeHead(200, {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Connection': 'keep-alive',
          'X-Content-Type-Options': 'nosniff'
        });
        const bootLine = JSON.stringify({
          service: 'unified-web-gateway',
          stream: 'stdout',
          line: `[${new Date().toISOString()}] YOUPI PG V2 Unified Cloud Gateway active (SQLite WAL + Loopback Core :${rt.apiPort})`,
          timestamp: Date.now()
        });
        res.write(`data: ${bootLine}\n\n`);
        const hb = setInterval(() => {
          try { res.write(': keepalive\n\n'); } catch { clearInterval(hb); }
        }, 15000);
        if (hb.unref) hb.unref();
        req.on('close', () => clearInterval(hb));
        return;
      }

      const services = [
        { id: 'web-portal', name: 'Unified Website & Router', port: Number(process.env.PORT || 443), status: 'RUNNING', pid: process.pid, startedAt: rt.startedAt },
        { id: 'payment-api', name: 'Payment Core REST & SSE Engine', port: rt.apiPort, status: 'RUNNING', pid: process.pid, startedAt: rt.startedAt },
        { id: 'checkout-portal', name: 'White-Label Checkout Portal', port: rt.checkoutPort, status: 'RUNNING', pid: process.pid, startedAt: rt.startedAt },
        { id: 'merchant-admin', name: 'Merchant & Cashier Hub', port: Number(process.env.PORT || 443), status: 'RUNNING', pid: process.pid, startedAt: rt.startedAt },
        { id: 'coin-wallet-store', name: 'YOUPI Showcase Storefront', port: rt.storePort, status: 'RUNNING', pid: process.pid, startedAt: rt.startedAt },
        { id: 'payment-help', name: 'Customer Support Portal', port: Number(process.env.PORT || 443), status: 'RUNNING', pid: process.pid, startedAt: rt.startedAt }
      ];
      sendJson(res, 200, { services, mode: 'unified-cloud' });
      return;
    }

    // 5. Official Flagship Homepage: GET /
    if (pathname === '/' && (method === 'GET' || method === 'HEAD')) {
      const mRepo = new MerchantRepository(rt.db);
      const aRepo = new ReceivingAccountRepository(rt.db);
      const merchant = mRepo.findById('00000000-0000-0000-0000-000000000001') || mRepo.findAll()[0];
      const account = merchant ? aRepo.findActiveForMerchant(merchant.id) : null;
      const totalRow = rt.db.queryOne('SELECT COUNT(*) AS cnt FROM payment_sessions');

      const html = rt.landingTemplate
        .replaceAll('{{DEFAULT_VPA}}', escapeHtml(account?.upiId || 'merchant@upi'))
        .replaceAll('{{TOTAL_SESSIONS}}', escapeHtml(String(totalRow?.cnt ?? 0)));

      res.writeHead(200, {
        'Content-Type': 'text/html; charset=utf-8',
        'Cache-Control': 'no-cache',
        ...WEB_SECURITY_HEADERS
      });
      if (method === 'HEAD') { res.end(); return; }
      res.end(html);
      return;
    }

    // 6. Interactive Documentation Hub: GET /docs or /docs/:slug
    if ((pathname === '/docs' || pathname.startsWith('/docs/')) && (method === 'GET' || method === 'HEAD')) {
      const requestedSlug = pathname === '/docs'
        ? 'overview'
        : decodeURIComponent(pathname.slice('/docs/'.length)).replace(/\/+$/, '') || 'overview';
      const activeDoc = DOCS_CATALOG.find(d => d.slug === requestedSlug) || DOCS_CATALOG[0];

      let rawMd = '# Document Not Found';
      try {
        const mdPath = path.join(repoRoot, activeDoc.file);
        if (fs.existsSync(mdPath)) {
          rawMd = fs.readFileSync(mdPath, 'utf8');
        }
      } catch {}

      const navHtml = DOCS_CATALOG.map(doc => {
        const activeClass = doc.slug === activeDoc.slug ? ' active' : '';
        return `<a href="/docs/${escapeHtml(doc.slug)}" class="docs-nav-item${activeClass}">${escapeHtml(doc.title)}</a>`;
      }).join('\n');

      const contentHtml = renderMarkdown(rawMd);
      const rendered = rt.docsTemplate
        .replaceAll('{{DOC_TITLE}}', escapeHtml(activeDoc.title))
        .replace('{{DOCS_NAV_HTML}}', navHtml)
        .replace('{{DOC_CONTENT_HTML}}', contentHtml);

      res.writeHead(200, {
        'Content-Type': 'text/html; charset=utf-8',
        'Cache-Control': 'no-cache',
        ...WEB_SECURITY_HEADERS
      });
      if (method === 'HEAD') { res.end(); return; }
      res.end(rendered);
      return;
    }

    // 7. Interactive OpenAPI & REST Explorer: GET /api-docs
    if (pathname === '/api-docs' && (method === 'GET' || method === 'HEAD')) {
      res.writeHead(200, {
        'Content-Type': 'text/html; charset=utf-8',
        'Cache-Control': 'no-cache',
        ...WEB_SECURITY_HEADERS
      });
      if (method === 'HEAD') { res.end(); return; }
      res.end(rt.apiDocsTemplate);
      return;
    }

    // 8. Merchant Admin Dashboard & Admin Tickets: /admin, /api/admin/tickets
    if (pathname === '/admin' || pathname === '/api/admin/tickets' || pathname === '/api/v1/admin/sms-gateway/download-apk') {
      dispatchWithBridgeInjection(rt.adminHttp, req, res);
      return;
    }

    // 9. Customer Support / Help Portal: /help, /support
    if (pathname === '/help' || pathname === '/support') {
      dispatchWithBridgeInjection(rt.helpHttp, req, res);
      return;
    }

    // 10. Checkout Portal & Universal Browser SDK: /checkout/*, /youpi.js, /sdk/*, /ping
    if (
      pathname.startsWith('/checkout/') ||
      pathname === '/youpi.js' ||
      pathname.startsWith('/sdk/') ||
      pathname === '/ping'
    ) {
      dispatchWithBridgeInjection(rt.checkoutHttp, req, res);
      return;
    }

    // 11. Showcase Storefront, Coin Wallet, Order Outcome Pages & Store APIs
    if (
      pathname === '/store' ||
      pathname === '/wallet' ||
      pathname === '/order-success' || pathname === '/success' ||
      pathname === '/order-failed' || pathname === '/failed' ||
      pathname === '/order-suspicious' || pathname === '/suspicious' ||
      pathname === '/order-expired' || pathname === '/expired' ||
      pathname === '/order-cancelled' || pathname === '/cancelled' ||
      pathname === '/api/wallet-balance' ||
      pathname === '/api/checkout' ||
      pathname === '/api/verify-payment' ||
      pathname === '/api/webhook' ||
      pathname === '/webhook'
    ) {
      dispatchWithBridgeInjection(rt.storeHttp, req, res);
      return;
    }

    // 12. Payment Core REST & SSE API: /api/v1/*, /health
    if (pathname.startsWith('/api/v1/') || pathname === '/health') {
      if (!req.headers['x-merchant-id']) {
        req.headers['x-merchant-id'] = '00000000-0000-0000-0000-000000000001';
      }
      rt.paymentApp.rawServer.emit('request', req, res);
      return;
    }

    // 13. Branded 404 Fallback
    res.writeHead(404, {
      'Content-Type': 'text/html; charset=utf-8',
      ...WEB_SECURITY_HEADERS
    });
    res.end(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>404 Not Found — YOUPI PG V2</title>
  <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
  <link rel="stylesheet" href="/site/styles.css" />
</head>
<body>
  <div class="container" style="min-height:85vh;display:grid;place-items:center;text-align:center;padding:40px 20px;">
    <div style="max-width:520px;">
      <span class="eyebrow">HTTP 404</span>
      <h1 style="font-family:var(--font-display);font-size:2.4rem;margin:8px 0 12px;">Route Not Found</h1>
      <p style="color:var(--text-secondary);margin:0 0 24px;">The requested path <code>${escapeHtml(pathname)}</code> does not exist on this YOUPI PG V2 gateway instance.</p>
      <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap;">
        <a href="/" class="btn btn-primary">← Return to YOUPI Website</a>
        <a href="/store" class="btn btn-outline">Open Demo Store</a>
        <a href="/docs" class="btn btn-outline">Read Docs</a>
      </div>
    </div>
  </div>
</body>
</html>`);
  };
}
