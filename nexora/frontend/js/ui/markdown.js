/**
 * Minimal, XSS-safe Markdown renderer for chat + panel bodies.
 * Input is HTML-escaped before any markup is generated, so only the subset
 * below can produce tags.
 */
import { esc } from './dom.js';

export const MATH_SYMBOLS = {
  '\\cup': '∪',
  '\\cap': '∩',
  '\\sum': '∑',
  '\\int': '∫',
  '\\prod': '∏',
  '\\in': '∈',
  '\\notin': '∉',
  '\\subset': '⊂',
  '\\subseteq': '⊆',
  '\\supset': '⊃',
  '\\supseteq': '⊇',
  '\\emptyset': '∅',
  '\\forall': '∀',
  '\\exists': '∃',
  '\\times': '×',
  '\\cdot': '·',
  '\\div': '÷',
  '\\pm': '±',
  '\\mp': '∓',
  '\\le': '≤',
  '\\leq': '≤',
  '\\ge': '≥',
  '\\geq': '≥',
  '\\ne': '≠',
  '\\neq': '≠',
  '\\approx': '≈',
  '\\equiv': '≡',
  '\\infty': '∞',
  '\\to': '→',
  '\\rightarrow': '→',
  '\\Rightarrow': '⇒',
  '\\leftrightarrow': '↔',
  '\\Leftrightarrow': '⇔',
  '\\land': '∧',
  '\\lor': '∨',
  '\\neg': '¬',
  '\\setminus': '∖',
  '\\alpha': 'α',
  '\\beta': 'β',
  '\\gamma': 'γ',
  '\\delta': 'δ',
  '\\epsilon': 'ε',
  '\\theta': 'θ',
  '\\lambda': 'λ',
  '\\mu': 'μ',
  '\\pi': 'π',
  '\\sigma': 'σ',
  '\\phi': 'φ',
  '\\omega': 'ω',
  '\\Delta': 'Δ',
  '\\Sigma': 'Σ',
  '\\Omega': 'Ω',
  '\\sqrt': '√',
  '\\bigcup': '⋃',
  '\\bigcap': '⋂',
};

export function formatFallbackMath(expr, alreadyEscaped = false) {
  let res = alreadyEscaped ? expr : esc(expr);
  res = res.replace(/\\boxed\{([\s\S]*?)\}/g, '$1');
  res = res.replace(/\\text\{([^{}]+)\}/g, '$1');
  res = res.replace(/\\(?:displaystyle|textstyle|scriptstyle|scriptscriptstyle)\s*/g, '');
  res = res.replace(/\\(?:;|quad|qquad|,|!)\s*/g, ' ');
  res = res.replace(/\\frac\{([^{}]+)\}\{([^{}]+)\}/g, '($1 / $2)');

  // Clean up multiline LaTeX environments like aligned, align, gather, cases, array, matrix
  res = res.replace(/\\begin\{(?:aligned|align\*?|gather\*?|array|matrix|pmatrix|bmatrix|cases)\}/g, '');
  res = res.replace(/\\end\{(?:aligned|align\*?|gather\*?|array|matrix|pmatrix|bmatrix|cases)\}/g, '');
  res = res.replace(/\\\\/g, '<br>');
  res = res.replace(/&(?:amp;)?=/g, '=');
  res = res.replace(/&(?:amp;)?(?!(?:lt|gt|amp|quot|#\d+);)/g, ' ');

  for (const [cmd, sym] of Object.entries(MATH_SYMBOLS)) {
    const regex = new RegExp(cmd.replace('\\', '\\\\') + '(?![a-zA-Z])', 'g');
    res = res.replace(regex, sym);
  }
  res = res.replace(/\\\{/g, '{').replace(/\\\}/g, '}');
  res = res.replace(/\\mid/g, '|');
  res = res.replace(/\\,/g, ' ');
  res = res.replace(/\^\{([^{}]+)\}/g, '<sup>$1</sup>');
  res = res.replace(/\^([0-9a-zA-Z+-])/g, '<sup>$1</sup>');
  res = res.replace(/_\{([^{}]+)\}/g, '<sub>$1</sub>');
  res = res.replace(/_([0-9a-zA-Z+-])/g, '<sub>$1</sub>');
  return res.trim();
}

export function renderMathBlock(expr) {
  const cleanExpr = expr.trim();
  if (typeof window !== 'undefined' && window.katex && typeof window.katex.renderToString === 'function') {
    try {
      const rendered = window.katex.renderToString(cleanExpr, { displayMode: true, throwOnError: false });
      return `<div class="math-block" data-raw="${esc(cleanExpr)}">${rendered}</div>`;
    } catch {}
  }
  return `<div class="math-block fallback" data-raw="${esc(cleanExpr)}"><span class="math-display">${formatFallbackMath(cleanExpr, false)}</span></div>`;
}

export function renderInlineMath(expr) {
  const cleanExpr = expr.trim();
  if (typeof window !== 'undefined' && window.katex && typeof window.katex.renderToString === 'function') {
    try {
      const rendered = window.katex.renderToString(cleanExpr, { displayMode: false, throwOnError: false });
      return `<span class="math-inline" data-raw="${esc(cleanExpr)}">${rendered}</span>`;
    } catch {}
  }
  return `<span class="math-inline fallback" data-raw="${esc(cleanExpr)}">${formatFallbackMath(cleanExpr, true)}</span>`;
}

function inline(text) {
  // Escape first: everything below only ever *adds* tags, so untrusted text
  // (model output, task text, repository content) can never inject markup.
  let out = esc(text);

  // inline code first so its contents are not further transformed
  const codeSpans = [];
  out = out.replace(/`([^`\n]+)`/g, (_m, code) => {
    let cleanCode = code;
    if (/\bU\b/.test(cleanCode) && /[A-Za-z]\s+U\s+[A-Za-z]/.test(cleanCode)) {
      cleanCode = cleanCode.replace(/([A-Za-z])\s+U\s+([A-Za-z])/g, '$1 ∪ $2');
    }
    codeSpans.push(cleanCode);
    return `\u0000CODE${codeSpans.length - 1}\u0000`;
  });

  // inline math: $ ... $ or \( ... \) or \[ ... \]
  const mathSpans = [];
  out = out.replace(/(?:(?<!\$)\$(?!\s)([^\$\n]+?)(?<!\s)\$(?!\$)|\\\(([\s\S]*?)\\\)|\\\[([\s\S]*?)\\\])/g, (_m, p1, p2, p3) => {
    if (p3 !== undefined) {
      mathSpans.push(renderMathBlock(p3));
    } else {
      const mathContent = p1 !== undefined ? p1 : p2;
      mathSpans.push(renderInlineMath(mathContent));
    }
    return `\u0000MATH${mathSpans.length - 1}\u0000`;
  });

  out = out.replace(/\*\*\*([^*]+)\*\*\*/g, '<strong><em>$1</em></strong>');
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  out = out.replace(/(^|[\s(])_([^_\n]+)_/g, '$1<em>$2</em>');
  out = out.replace(/~~([^~]+)~~/g, '<del>$1</del>');

  // links: [label](https://...) only, http(s) + relative
  out = out.replace(/\[([^\]\n]+)\]\(((?:https?:\/\/|\/)[^)\s]+)\)/g,
    (_m, label, href) => `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`);

  // Replace standalone common math symbols like \cup, \cap, \sum outside of math delimiters
  for (const [cmd, sym] of Object.entries(MATH_SYMBOLS)) {
    const regex = new RegExp(cmd.replace('\\', '\\\\') + '(?![a-zA-Z])', 'g');
    out = out.replace(regex, sym);
  }

  out = out.replace(/\u0000MATH(\d+)\u0000/g, (_m, i) => mathSpans[Number(i)]);
  out = out.replace(/\u0000CODE(\d+)\u0000/g, (_m, i) => `<code>${codeSpans[Number(i)]}</code>`);
  return out;
}

function renderTable(rows) {
  const cells = rows
    .map((row) => row.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim()));
  if (cells.length < 2) return '';
  const head = cells[0];
  const body = cells.slice(2);
  return (
    '<table><thead><tr>' +
    head.map((c) => `<th>${inline(c)}</th>`).join('') +
    '</tr></thead><tbody>' +
    body.map((row) => '<tr>' + row.map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>').join('') +
    '</tbody></table>'
  );
}

function renderToolCard(trimmed) {
  // Pattern: > (⚡|✓|✕) **(Executing|Finished|Executed) Tool:** `toolName` [args]
  const toolMatch = trimmed.match(/^>\s*(?:([⚡✓✕]|\u26a1))\s*\*\*(Executing|Finished|Executed) Tool:\*\*\s*(?:`([^`\n]+)`|([^\n`]+))(?:\s*(?:`([^`\n]+)`|([^\n`]+)))?([\s\S]*)$/);
  if (!toolMatch) return null;

  const icon = toolMatch[1];
  const action = toolMatch[2];
  const toolName = (toolMatch[3] || toolMatch[4] || '').trim();
  const argsRaw = (toolMatch[5] || toolMatch[6] || '').trim();
  const rest = (toolMatch[7] || '').trim();

  const isExecuting = action === 'Executing' || icon === '⚡' || icon === '\u26a1';
  const isFailed = icon === '✕';
  const statusClass = isExecuting ? 'executing' : (isFailed ? 'failed' : 'success');
  const badgeText = isExecuting ? 'Running' : (isFailed ? 'Failed' : 'Completed');
  const badgeClass = isExecuting ? 'badge-running' : (isFailed ? 'badge-failed' : 'badge-completed');

  let preview = '';
  if (rest) {
    const codeMatch = rest.match(/```(?:[\w+-]*\n)?([\s\S]*?)```/);
    if (codeMatch) {
      preview = codeMatch[1].trim();
    } else {
      const cleaned = rest.replace(/^>\s?/gm, '').trim();
      if (cleaned) preview = cleaned;
    }
  }

  let typeIcon = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`;
  const lower = toolName.toLowerCase();
  if (lower.includes('read') || lower.includes('list')) {
    typeIcon = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`;
  } else if (lower.includes('write')) {
    typeIcon = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>`;
  } else if (lower.includes('test')) {
    typeIcon = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 3v7.3a4 4 0 0 1-.7 2.2L3.6 20a1 1 0 0 0 .9 1.5h15a1 1 0 0 0 .9-1.5l-4.7-7.5a4 4 0 0 1-.7-2.2V3"/><line x1="8" y1="3" x2="16" y2="3"/></svg>`;
  } else if (lower.includes('git')) {
    typeIcon = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="6" y1="9" x2="6" y2="15"/><path d="M18 15a9 9 0 0 0-9-9"/></svg>`;
  } else if (lower.includes('shell')) {
    typeIcon = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>`;
  }

  return (
    `<div class="tool-call-card ${statusClass}">` +
      `<div class="tool-card-header" onclick="this.parentElement.classList.toggle('collapsed')">` +
        `<div class="tool-card-left">` +
          `<span class="tool-icon ${isExecuting ? 'pulsing' : ''}">${typeIcon}</span>` +
          `<span class="tool-name">${esc(toolName)}</span>` +
          (argsRaw ? `<span class="tool-args">${esc(argsRaw)}</span>` : '') +
        `</div>` +
        `<div class="tool-card-right">` +
          `<span class="tool-badge ${badgeClass}">${badgeText}</span>` +
          (preview ? `<span class="tool-chevron">▾</span>` : '') +
        `</div>` +
      `</div>` +
      (preview ? `<div class="tool-card-body"><pre class="tool-terminal"><code>${esc(preview)}</code></pre></div>` : '') +
    `</div>`
  );
}

function renderThoughtBlock(trimmed) {
  const match = trimmed.match(/^(?:<thought>|<thinking>)([\s\S]*?)(?:<\/thought>|<\/thinking>)?$/i);
  if (!match) return null;
  const inner = match[1].trim();
  const sparkleSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/></svg>`;
  return (
    `<details class="thought-accordion">` +
      `<summary class="thought-summary">` +
        `<span class="thought-sparkle">${sparkleSvg}</span>` +
        `<span class="thought-label">Thinking Process</span>` +
        `<span class="thought-chevron">▾</span>` +
      `</summary>` +
      `<div class="thought-body md">${renderMarkdown(inner)}</div>` +
    `</details>`
  );
}

function renderApprovalCard(trimmed) {
  let approvalId = '';
  let tool = '';
  let scope = '';
  let message = '';

  const tagMatch = trimmed.match(/^<approval\s+([^>]+)>([\s\S]*?)<\/approval>$/i);
  if (tagMatch) {
    const attrs = tagMatch[1];
    message = tagMatch[2].trim();
    const idMatch = attrs.match(/approval-id=["']([^"']+)["']/i);
    const toolMatch = attrs.match(/tool=["']([^"']+)["']/i);
    const scopeMatch = attrs.match(/scope=["']([^"']*)["']/i);
    if (idMatch) approvalId = idMatch[1];
    if (toolMatch) tool = toolMatch[1];
    if (scopeMatch) scope = scopeMatch[1];
  } else {
    const mdMatch = trimmed.match(/^>\s*(?:🔒|🛡️)?\s*\*\*Approval Required:\*\*\s*(?:`([^`\n]+)`|([^\n`]+))(?:\s+(?:`([^`\n]+)`|([^\n]+)))?([\s\S]*)$/);
    if (!mdMatch) return null;
    tool = (mdMatch[1] || mdMatch[2] || 'Action').trim();
    scope = (mdMatch[3] || mdMatch[4] || '').trim();
    const rest = (mdMatch[5] || '').trim();
    message = rest.replace(/^>\s?/gm, '').trim() || `Approval required for ${tool}`;
  }

  const shieldSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`;
  const checkSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="vertical-align:middle;margin-right:4px;"><polyline points="20 6 9 17 4 12"/></svg>`;
  const xSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="vertical-align:middle;margin-right:4px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;

  return (
    `<div class="inline-approval-card" data-approval-id="${esc(approvalId)}">` +
      `<div class="approval-header">` +
        `<div class="approval-left">` +
          `<span class="approval-icon">${shieldSvg}</span>` +
          `<div class="approval-title-wrap">` +
            `<span class="approval-title">Policy Approval Required</span>` +
            `<span class="approval-subtitle">${esc(message || 'The agent requested permission for this action')}</span>` +
          `</div>` +
        `</div>` +
        `<span class="approval-badge badge-pending">Action Required</span>` +
      `</div>` +
      `<div class="approval-details">` +
        `<div class="approval-detail-row">` +
          `<span class="detail-label">Tool</span>` +
          `<span class="detail-value mono">${esc(tool || 'system')}</span>` +
        `</div>` +
        (scope ? `<div class="approval-detail-row"><span class="detail-label">Scope</span><span class="detail-value mono">${esc(scope)}</span></div>` : '') +
      `</div>` +
      `<div class="approval-actions">` +
        `<button class="approval-btn approve-btn" data-approval-id="${esc(approvalId)}" data-action="approve">` +
          `${checkSvg}Approve` +
        `</button>` +
        `<button class="approval-btn deny-btn" data-approval-id="${esc(approvalId)}" data-action="deny">` +
          `${xSvg}Reject` +
        `</button>` +
      `</div>` +
    `</div>`
  );
}

/**
 * @param {string} source
 * @returns {string} HTML
 */
export function renderMarkdown(source) {
  if (!source) return '';
  const text = String(source).replace(/\r\n/g, '\n');

  // Extract complete <thought>...</thought> blocks before splitting by paragraphs
  const thoughts = [];
  let processedText = text.replace(/(?:<thought>|<thinking>)([\s\S]*?)(?:<\/thought>|<\/thinking>)/gi, (_m, inner) => {
    const placeholder = `__THOUGHT_PLACEHOLDER_${thoughts.length}__`;
    thoughts.push(inner.trim());
    return `\n\n${placeholder}\n\n`;
  });
  // Strip any stray unclosed or orphan closing tags so they never leak into paragraphs
  processedText = processedText.replace(/<\/?(?:thought|thinking|think|reasoning)>/gi, '');

  const blocks = processedText.split(/\n{2,}/);
  const out = [];

  for (const block of blocks) {
    const trimmed = block.trim();
    if (!trimmed) continue;

    // Thought placeholder
    const placeholderMatch = trimmed.match(/^__THOUGHT_PLACEHOLDER_(\d+)__$/);
    if (placeholderMatch) {
      const idx = parseInt(placeholderMatch[1], 10);
      const inner = thoughts[idx] || '';
      const sparkleSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/></svg>`;
      out.push(
        `<details class="thought-accordion">` +
          `<summary class="thought-summary">` +
            `<span class="thought-sparkle">${sparkleSvg}</span>` +
            `<span class="thought-label">Thinking Process</span>` +
            `<span class="thought-chevron">▾</span>` +
          `</summary>` +
          `<div class="thought-body md">${renderMarkdown(inner)}</div>` +
        `</details>`
      );
      continue;
    }

    // Direct Thought / Chain of Thought block fallback
    const thoughtHtml = renderThoughtBlock(trimmed);
    if (thoughtHtml) {
      out.push(thoughtHtml);
      continue;
    }

    // Tool call interactive card
    const toolCardHtml = renderToolCard(trimmed);
    if (toolCardHtml) {
      out.push(toolCardHtml);
      continue;
    }

    // Inline Policy Approval card
    const approvalCardHtml = renderApprovalCard(trimmed);
    if (approvalCardHtml) {
      out.push(approvalCardHtml);
      continue;
    }

    // Block Math: $$ ... $$ or \[ ... \]
    const blockMathMatch = trimmed.match(/^(?:\$\$([\s\S]*?)\$\$|\\\[([\s\S]*?)\\\])$/);
    if (blockMathMatch) {
      const mathContent = blockMathMatch[1] !== undefined ? blockMathMatch[1] : blockMathMatch[2];
      out.push(renderMathBlock(mathContent.trim()));
      continue;
    }

    // fenced code
    const fence = trimmed.match(/^```([\w+-]*)\n?([\s\S]*?)\n?```$/);
    if (fence) {
      out.push(`<pre><code data-lang="${esc(fence[1] || '')}">${esc(fence[2])}</code></pre>`);
      continue;
    }

    // table
    if (/\|/.test(trimmed) && /^\|?[\s:|-]+\|[\s:|-]*$/.test(trimmed.split('\n')[1] || '')) {
      const table = renderTable(trimmed.split('\n'));
      if (table) { out.push(table); continue; }
    }

    const heading = trimmed.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const level = heading[1].length;
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      continue;
    }

    if (/^(-{3,}|\*{3,})$/.test(trimmed)) { out.push('<hr>'); continue; }

    if (/^>\s?/.test(trimmed)) {
      const text2 = trimmed.replace(/^>\s?/gm, '');
      out.push(`<blockquote>${renderMarkdown(text2)}</blockquote>`);
      continue;
    }

    const bullets = trimmed.match(/^[-*+]\s+([\s\S]+)$/);
    if (bullets) {
      const items = bullets[1].split('\n').filter((l) => /^\s*[-*+]\s+/.test(l))
        .map((l) => `<li>${inline(l.replace(/^\s*[-*+]\s+/, ''))}</li>`).join('');
      if (items) { out.push(`<ul>${items}</ul>`); continue; }
    }

    const ordered = trimmed.match(/^\d+[.)]\s+([\s\S]+)$/);
    if (ordered) {
      const items = ordered[1].split('\n').filter((l) => /^\s*\d+[.)]\s+/.test(l))
        .map((l) => `<li>${inline(l.replace(/^\s*\d+[.)]\s+/, ''))}</li>`).join('');
      if (items) { out.push(`<ol>${items}</ol>`); continue; }
    }

    out.push(`<p>${inline(trimmed).replace(/\n/g, '<br>')}</p>`);
  }

  return out.join('');
}

/** Render then colourise +/- diff lines inside a <pre>. */
export function renderDiff(patch) {
  const lines = esc(patch ?? '').split('\n');
  return lines
    .map((line) => {
      const cls = line.startsWith('+++') || line.startsWith('---') || line.startsWith('diff ') || line.startsWith('index ')
        ? 'diff-hunk'
        : line.startsWith('@@') ? 'diff-hunk'
          : line.startsWith('+') ? 'diff-add'
            : line.startsWith('-') ? 'diff-del'
              : '';
      return `<span class="diff-line ${cls}">${line || ' '}</span>`;
    })
    .join('\n');
}

export { esc };