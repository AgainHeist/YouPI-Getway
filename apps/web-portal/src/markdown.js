/**
 * Zero-dependency, XSS-safe Markdown-to-HTML renderer for YOUPI PG Documentation Hub.
 */

const HTML_MAP = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
};

export function escapeHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, ch => HTML_MAP[ch]);
}

function formatInline(raw) {
  const codeSpans = [];
  let text = String(raw || '').replace(/`([^`]+)`/g, (_, code) => {
    const idx = codeSpans.length;
    codeSpans.push(`<code>${escapeHtml(code)}</code>`);
    return `\u0000CODE_${idx}\u0000`;
  });

  text = escapeHtml(text);

  // Links [label](url) - allow only http(s), relative /, or #anchor
  text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, href) => {
    const trimmed = href.trim();
    if (/^(https?:\/\/|\/|#)/i.test(trimmed)) {
      const ext = /^https?:\/\//i.test(trimmed) ? ' target="_blank" rel="noopener"' : '';
      return `<a href="${trimmed}" style="color:var(--emerald-400);text-decoration:underline;"${ext}>${label}</a>`;
    }
    return label;
  });

  // Bold & italic
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/\*([^*]+)\*/g, '<em>$1</em>');

  // Restore inline code spans
  text = text.replace(/\u0000CODE_(\d+)\u0000/g, (_, idx) => codeSpans[Number(idx)] || '');
  return text;
}

export function renderMarkdown(markdown) {
  const cleaned = String(markdown || '')
    // Strip raw HTML alignment wrappers / badges at top of README while keeping markdown clean
    .replace(/<\/?(div|p|br|sub|img)[^>]*>/gi, '');

  const lines = cleaned.split(/\r?\n/);
  const out = [];
  let inCode = false;
  let codeLang = '';
  let codeBuf = [];
  let inList = false;
  let listType = 'ul';
  let tableRows = [];

  function flushList() {
    if (inList) {
      out.push(`</${listType}>`);
      inList = false;
    }
  }

  function flushTable() {
    if (tableRows.length === 0) return;
    if (tableRows.length >= 2 && /^\|?[\s:-]+\|/.test(tableRows[1])) {
      const parseCells = row =>
        row.replace(/^\||\|$/g, '').split('|').map(c => formatInline(c.trim()));
      const headers = parseCells(tableRows[0]);
      const body = tableRows.slice(2).map(parseCells);
      out.push('<table><thead><tr>' + headers.map(h => `<th>${h}</th>`).join('') + '</tr></thead><tbody>');
      for (const r of body) {
        out.push('<tr>' + r.map(c => `<td>${c}</td>`).join('') + '</tr>');
      }
      out.push('</tbody></table>');
    } else {
      for (const r of tableRows) {
        out.push(`<p>${formatInline(r)}</p>`);
      }
    }
    tableRows = [];
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (line.trim().startsWith('```')) {
      flushList();
      flushTable();
      if (!inCode) {
        inCode = true;
        codeLang = line.trim().slice(3).trim();
        codeBuf = [];
      } else {
        inCode = false;
        out.push(`<pre><code data-lang="${escapeHtml(codeLang)}">${escapeHtml(codeBuf.join('\n'))}</code></pre>`);
        codeBuf = [];
      }
      continue;
    }

    if (inCode) {
      codeBuf.push(line);
      continue;
    }

    // Table row detection
    if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
      flushList();
      tableRows.push(line.trim());
      continue;
    } else {
      flushTable();
    }

    const trimmed = line.trim();
    if (!trimmed) {
      flushList();
      continue;
    }

    if (/^---+$/.test(trimmed)) {
      flushList();
      out.push('<hr style="border:0;border-top:1px solid var(--border-subtle);margin:26px 0;" />');
      continue;
    }

    const headingMatch = /^(#{1,4})\s+(.+)$/.exec(trimmed);
    if (headingMatch) {
      flushList();
      const level = headingMatch[1].length;
      const slug = headingMatch[2].toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      out.push(`<h${level} id="${escapeHtml(slug)}">${formatInline(headingMatch[2])}</h${level}>`);
      continue;
    }

    if (trimmed.startsWith('>')) {
      flushList();
      const quoteBody = trimmed.replace(/^>\s*(\[!IMPORTANT\]|\[!NOTE\]|\[!WARNING\])?\s*/i, '');
      if (quoteBody) {
        out.push(`<blockquote>${formatInline(quoteBody)}</blockquote>`);
      }
      continue;
    }

    const ulMatch = /^[-*]\s+(.+)$/.exec(trimmed);
    if (ulMatch) {
      if (!inList || listType !== 'ul') {
        flushList();
        inList = true;
        listType = 'ul';
        out.push('<ul>');
      }
      out.push(`<li>${formatInline(ulMatch[1])}</li>`);
      continue;
    }

    const olMatch = /^\d+\.\s+(.+)$/.exec(trimmed);
    if (olMatch) {
      if (!inList || listType !== 'ol') {
        flushList();
        inList = true;
        listType = 'ol';
        out.push('<ol>');
      }
      out.push(`<li>${formatInline(olMatch[1])}</li>`);
      continue;
    }

    flushList();
    out.push(`<p>${formatInline(trimmed)}</p>`);
  }

  flushList();
  flushTable();
  if (inCode && codeBuf.length > 0) {
    out.push(`<pre><code>${escapeHtml(codeBuf.join('\n'))}</code></pre>`);
  }

  return out.join('\n');
}
