import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { extractDocMeta } from './markdown.js';
import { renderLanding } from './views/landing.js';
import { renderDocsIndex, renderDoc, renderNotFound } from './views/docs.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const appDir = path.resolve(__dirname, '..');
const repoRoot = path.resolve(appDir, '../..');
const publicDir = path.join(appDir, 'public');
const docsDir = path.join(repoRoot, 'docs');

/**
 * Public marketing site + documentation portal.
 *
 * Deliberately has no database dependency: it must be able to render (and to say
 * "gateway unreachable") even when the payment API is down. The only live data it shows
 * is the payment API health probe, fetched server-side so the browser never needs CORS.
 */
export class WebsiteServer {
  /**
   * @param {{
   *   paymentApiUrl?: string,
   *   links?: { admin?: string, store?: string, help?: string },
   *   docsDir?: string,
   *   publicDir?: string,
   *   healthTimeoutMs?: number
   * }} [options]
   */
  constructor(options = {}) {
    this.paymentApiUrl = options.paymentApiUrl || process.env.BASE_PAYMENT_API_URL || 'http://localhost:6100';
    this.docsDir = options.docsDir || docsDir;
    this.publicDir = options.publicDir || publicDir;
    this.healthTimeoutMs = options.healthTimeoutMs ?? 1200;
    this.links = {
      admin: options.links?.admin || process.env.BASE_ADMIN_URL || 'http://localhost:6001',
      store: options.links?.store || process.env.BASE_DEMO_STORE_URL || 'http://localhost:5000',
      help: options.links?.help || process.env.BASE_HELP_URL || 'http://localhost:3000'
    };
    this.docCache = null;
  }

  /** Lists `docs/*.md` with title + summary, cached for the process lifetime. */
  listDocs() {
    if (this.docCache) return this.docCache;
    let entries = [];
    try {
      entries = fs.readdirSync(this.docsDir).filter(file => file.toLowerCase().endsWith('.md'));
    } catch {
      entries = [];
    }
    const docs = entries
      .map(file => {
        const slug = file.replace(/\.md$/i, '');
        let markdown = '';
        try {
          markdown = fs.readFileSync(path.join(this.docsDir, file), 'utf8');
        } catch {
          return null;
        }
        const { title, summary } = extractDocMeta(markdown);
        return { slug, title: title || slug, summary };
      })
      .filter(Boolean)
      .sort((a, b) => a.title.localeCompare(b.title));

    this.docCache = docs;
    return docs;
  }

  /** Resolves a slug to a file inside docsDir, rejecting anything that escapes it. */
  resolveDocPath(slug) {
    if (!/^[A-Za-z0-9._-]+$/.test(slug) || slug.includes('..')) return null;
    const candidate = path.resolve(this.docsDir, `${slug}.md`);
    const base = path.resolve(this.docsDir);
    if (!candidate.startsWith(base + path.sep)) return null;
    return fs.existsSync(candidate) ? candidate : null;
  }

  /** Probes the payment API health endpoint; never throws. */
  async getGatewayStatus() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.healthTimeoutMs);
    const startedAt = Date.now();
    try {
      const res = await fetch(`${this.paymentApiUrl}/health`, { signal: controller.signal });
      const latencyMs = Date.now() - startedAt;
      if (!res.ok) return { state: 'down', latencyMs };
      const payload = await res.json().catch(() => ({}));
      return { state: payload.status === 'UP' ? 'up' : 'down', latencyMs };
    } catch {
      return { state: 'down', latencyMs: null };
    } finally {
      clearTimeout(timer);
    }
  }

  /** Lightweight counters for the hero strip — failures degrade to zeros, never throw. */
  async getPublicStats() {
    try {
      const res = await fetch(`${this.paymentApiUrl}/health`, {
        signal: AbortSignal.timeout(this.healthTimeoutMs)
      });
      const payload = await res.json().catch(() => ({}));
      const recovery = payload.recoveryStats || {};
      const payments = Number(recovery.expiredCount || 0) + Number(recovery.promotedCount || 0);
      return { payments, merchants: 1 };
    } catch {
      return { payments: 0, merchants: 1 };
    }
  }

  serveStatic(req, res, pathname) {
    const relative = decodeURIComponent(pathname.replace(/^\/+/, ''));
    if (relative.includes('..')) return false;
    const file = path.resolve(this.publicDir, relative);
    if (!file.startsWith(path.resolve(this.publicDir) + path.sep)) return false;
    if (!fs.existsSync(file) || !fs.statSync(file).isFile()) return false;

    const ext = path.extname(file).toLowerCase();
    const types = {
      '.css': 'text/css; charset=utf-8',
      '.js': 'text/javascript; charset=utf-8',
      '.svg': 'image/svg+xml',
      '.woff2': 'font/woff2',
      '.png': 'image/png',
      '.jpg': 'image/jpeg',
      '.ico': 'image/x-icon'
    };
    const type = types[ext];
    if (!type) return false;

    const body = fs.readFileSync(file);
    res.writeHead(200, {
      'Content-Type': type,
      'Content-Length': body.length,
      'Cache-Control': ext === '.woff2' ? 'public, max-age=31536000, immutable' : 'public, max-age=300',
      ...WebsiteServer.securityHeaders()
    });
    res.end(body);
    return true;
  }

  /**
   * The site is never framed and ships no third-party assets, so the CSP can stay tight.
   * `frame-ancestors 'none'` matters: the checkout portal is the only page meant to be embedded.
   */
  static securityHeaders() {
    return {
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'strict-origin-when-cross-origin',
      'X-Frame-Options': 'DENY',
      'Content-Security-Policy':
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; " +
        "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
    };
  }

  sendHtml(res, statusCode, html) {
    res.writeHead(statusCode, {
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'no-store',
      ...WebsiteServer.securityHeaders()
    });
    res.end(html);
  }

  sendJson(res, statusCode, payload) {
    res.writeHead(statusCode, {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      ...WebsiteServer.securityHeaders()
    });
    res.end(JSON.stringify(payload));
  }

  createServer() {
    return http.createServer(async (req, res) => {
      let pathname = '/';
      try {
        // Fixed base: the Host header is attacker-controlled.
        pathname = new URL(req.url, 'http://localhost').pathname;
      } catch {
        this.sendJson(res, 400, { error: 'Malformed request URL' });
        return;
      }

      const method = (req.method || 'GET').toUpperCase();
      if (method !== 'GET' && method !== 'HEAD') {
        this.sendJson(res, 405, { error: 'Method not allowed' });
        return;
      }

      try {
        if (pathname === '/health') {
          const status = await this.getGatewayStatus();
          this.sendJson(res, 200, { status: 'UP', service: 'website', gateway: status });
          return;
        }

        if (pathname === '/robots.txt') {
          res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
          res.end('User-agent: *\nDisallow: /health\n');
          return;
        }

        if (this.serveStatic(req, res, pathname)) return;

        const docs = this.listDocs();

        if (pathname === '/' || pathname === '/index.html') {
          const [status, stats] = await Promise.all([this.getGatewayStatus(), this.getPublicStats()]);
          this.sendHtml(res, 200, renderLanding({ status, stats, docs, links: this.links }));
          return;
        }

        if (pathname === '/docs' || pathname === '/docs/') {
          this.sendHtml(res, 200, renderDocsIndex({ docs, links: this.links }));
          return;
        }

        const docMatch = pathname.match(/^\/docs\/([^/]+)\/?$/);
        if (docMatch) {
          const slug = docMatch[1];
          const file = this.resolveDocPath(slug);
          if (!file) {
            this.sendHtml(res, 404, renderNotFound({ docs, links: this.links, message: 'Guide not found.' }));
            return;
          }
          const markdown = fs.readFileSync(file, 'utf8');
          const meta = extractDocMeta(markdown);
          const doc = { slug, title: meta.title || slug, summary: meta.summary };
          this.sendHtml(res, 200, renderDoc({ doc, markdown, docs, links: this.links }));
          return;
        }

        this.sendHtml(res, 404, renderNotFound({ docs, links: this.links }));
      } catch (err) {
        console.error('[Website] Request failed:', err);
        this.sendJson(res, 500, { error: 'Internal Server Error' });
      }
    });
  }
}
