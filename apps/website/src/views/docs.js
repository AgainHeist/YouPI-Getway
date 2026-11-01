import { escapeHtml, renderMarkdown } from '../markdown.js';
import { renderLayout } from './layout.js';

function navList(docs, activeSlug) {
  return docs
    .map(doc => `<a href="/docs/${encodeURIComponent(doc.slug)}"${doc.slug === activeSlug ? ' class="is-active"' : ''}>${escapeHtml(doc.title)}</a>`)
    .join('\n');
}

function docShell({ docs, activeSlug, content, links }) {
  return `<div class="wrap docs-shell">
    <aside class="docs-nav" aria-label="Documentation">
      <h4>Documentation</h4>
      <a href="/docs"${activeSlug ? '' : ' class="is-active"'}>All guides</a>
      ${navList(docs, activeSlug)}
    </aside>
    <article class="docs-body">
      ${content}
    </article>
  </div>`;
}

/** Index page listing every guide in the repository. */
export function renderDocsIndex({ docs, links }) {
  const body = docShell({
    docs,
    activeSlug: null,
    links,
    content: `<h1>Documentation</h1>
      <p>Install the gateway, connect your bank observers, integrate the SDK and run it in production.
      These pages are rendered straight from the repository's <code>docs/</code> folder, so they always match the code you are running.</p>
      <div class="docs-index-grid">
        ${docs.map(doc => `<a class="doc-card" href="/docs/${encodeURIComponent(doc.slug)}">
          <strong>${escapeHtml(doc.title)}</strong>
          <span>${escapeHtml(doc.summary || 'Read the guide')}</span>
        </a>`).join('\n')}
      </div>`
  });

  return renderLayout({
    title: 'Documentation — YOUPI PG',
    description: 'Installation, merchant integration, observers, configuration and operations guides for the YOUPI PG payment gateway.',
    body,
    active: '/docs',
    links
  });
}

/** A single rendered guide. `markdown` is already trusted repo content, but it is sanitised anyway. */
export function renderDoc({ doc, markdown, docs, links }) {
  const body = docShell({
    docs,
    activeSlug: doc.slug,
    links,
    content: renderMarkdown(markdown)
  });

  return renderLayout({
    title: `${doc.title} — YOUPI PG Docs`,
    description: doc.summary || `${doc.title} — YOUPI PG documentation.`,
    body,
    active: '/docs',
    links
  });
}

/** Simple 404 page kept inside the normal chrome so a broken link is not a dead end. */
export function renderNotFound({ docs, links, message = 'That page does not exist.' }) {
  const body = `<div class="wrap" style="padding:90px 24px;text-align:center">
    <span class="eyebrow">404</span>
    <h1 style="font-family:var(--font-display);font-size:2rem;margin:14px 0 10px">${escapeHtml(message)}</h1>
    <p style="color:var(--muted);margin-bottom:26px">The page may have moved — try the documentation index.</p>
    <a class="btn btn-primary" href="/docs">Browse documentation</a>
    <a class="btn btn-outline" href="/" style="margin-left:10px">Back home</a>
  </div>`;

  return renderLayout({
    title: 'Not found — YOUPI PG',
    body,
    active: '',
    links,
    docs
  });
}
