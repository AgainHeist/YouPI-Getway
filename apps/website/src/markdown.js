/**
 * Minimal, dependency-free Markdown renderer for the YOUPI PG documentation portal.
 *
 * The portal serves the repository's own `docs/*.md` files, so the input is trusted
 * content — but it is still escaped first and only a fixed allow-list of inline rules
 * is applied. That way a doc that one day contains an HTML snippet or a `javascript:`
 * link can never turn into stored XSS on the public site.
 *
 * Supported: headings, paragraphs, fenced code, inline code, bold, italic, links,
 * ordered/unordered lists, blockquotes, horizontal rules and GitHub-style tables.
 */

const ESCAPES = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
};

export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, ch => ESCAPES[ch]);
}

/** Only http(s), mailto and site-relative links survive; everything else is dropped. */
function safeHref(rawHref) {
  const href = String(rawHref || '').trim();
  if (!href) return null;
  if (/^(https?:\/\/|mailto:|\/|#)/i.test(href)) return href;
  return null;
}

function renderInline(text) {
  let out = escapeHtml(text);

  // `code` first so its content is not re-processed by the emphasis rules.
  const codeSlots = [];
  out = out.replace(/`([^`]+)`/g, (_m, code) => {
    codeSlots.push(`<code>${code}</code>`);
    return `\u0000CODE${codeSlots.length - 1}\u0000`;
  });

  out = out.replace(/\[([^\]]+)\]\(([^()\s]*(?:\([^()]*\))?[^()\s]*)\)/g, (match, label, href) => {
    const safe = safeHref(href.replace(/&amp;/g, '&'));
    if (!safe) return label;
    const external = /^https?:\/\//i.test(safe);
    const attrs = external ? ' target="_blank" rel="noopener noreferrer"' : '';
    return `<a href="${escapeHtml(safe)}"${attrs}>${label}</a>`;
  });

  out = out
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/\u0000CODE(\d+)\u0000/g, (_m, i) => codeSlots[Number(i)]);

  return out;
}

function splitTableRow(line) {
  return line
    .replace(/^\s*\|/, '')
    .replace(/\|\s*$/, '')
    .split('|')
    .map(cell => cell.trim());
}

function isTableDivider(line) {
  return /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(line) && line.includes('-');
}

/**
 * @param {string} markdown
 * @returns {string} sanitised HTML
 */
export function renderMarkdown(markdown) {
  const lines = String(markdown || '').replace(/\r\n/g, '\n').split('\n');
  const html = [];
  let i = 0;

  const listStack = []; // 'ul' | 'ol'
  const closeLists = (toDepth = 0) => {
    while (listStack.length > toDepth) html.push(`</${listStack.pop()}>`);
  };

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    if (/^\s*```/.test(line)) {
      closeLists();
      const lang = line.replace(/^\s*```/, '').trim();
      const buffer = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) {
        buffer.push(lines[i]);
        i++;
      }
      i++; // closing fence
      const cls = lang ? ` class="language-${escapeHtml(lang.replace(/[^a-z0-9+#-]/gi, ''))}"` : '';
      html.push(`<pre><code${cls}>${escapeHtml(buffer.join('\n'))}</code></pre>`);
      continue;
    }

    // Blank line
    if (!line.trim()) {
      closeLists();
      i++;
      continue;
    }

    // Horizontal rule
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      closeLists();
      html.push('<hr>');
      i++;
      continue;
    }

    // Heading
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      closeLists();
      const level = heading[1].length;
      const text = renderInline(heading[2].trim());
      const id = heading[2]
        .toLowerCase()
        .replace(/`/g, '')
        .replace(/[^a-z0-9\s-]/g, '')
        .trim()
        .replace(/\s+/g, '-');
      html.push(`<h${level} id="${escapeHtml(id)}">${text}</h${level}>`);
      i++;
      continue;
    }

    // Table
    if (line.includes('|') && i + 1 < lines.length && isTableDivider(lines[i + 1])) {
      closeLists();
      const header = splitTableRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) {
        rows.push(splitTableRow(lines[i]));
        i++;
      }
      const head = header.map(cell => `<th>${renderInline(cell)}</th>`).join('');
      const body = rows
        .map(cells => `<tr>${cells.map(cell => `<td>${renderInline(cell)}</td>`).join('')}</tr>`)
        .join('');
      html.push(`<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`);
      continue;
    }

    // Blockquote
    if (/^\s*>\s?/.test(line)) {
      closeLists();
      const buffer = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        buffer.push(lines[i].replace(/^\s*>\s?/, ''));
        i++;
      }
      html.push(`<blockquote>${renderMarkdown(buffer.join('\n'))}</blockquote>`);
      continue;
    }

    // Lists
    const ordered = line.match(/^\s*\d+\.\s+(.*)$/);
    const unordered = line.match(/^\s*[-*+]\s+(.*)$/);
    if (ordered || unordered) {
      const wanted = ordered ? 'ol' : 'ul';
      if (listStack[listStack.length - 1] !== wanted) {
        closeLists();
        listStack.push(wanted);
        html.push(`<${wanted}>`);
      }
      html.push(`<li>${renderInline((ordered || unordered)[1])}</li>`);
      i++;
      continue;
    }

    // Paragraph: consume until a blank line or a block-level construct starts.
    closeLists();
    const paragraph = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^\s*(#{1,6}\s|```|>\s?|[-*+]\s|\d+\.\s)/.test(lines[i]) &&
      !/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(lines[i])
    ) {
      paragraph.push(lines[i].trim());
      i++;
    }
    if (paragraph.length) html.push(`<p>${renderInline(paragraph.join(' '))}</p>`);
  }

  closeLists();
  return html.join('\n');
}

/** Extracts the first H1 as the document title and the first paragraph as its summary. */
export function extractDocMeta(markdown) {
  const lines = String(markdown || '').replace(/\r\n/g, '\n').split('\n');
  let title = '';
  let summary = '';
  for (const line of lines) {
    const heading = line.match(/^#\s+(.*)$/);
    if (heading && !title) {
      title = heading[1].replace(/[*`]/g, '').trim();
      continue;
    }
    if (title && !summary && line.trim() && !/^[#>|-]/.test(line.trim())) {
      summary = line.replace(/[*`]/g, '').trim().slice(0, 190);
      break;
    }
  }
  return { title, summary };
}
