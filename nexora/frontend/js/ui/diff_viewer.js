/**
 * Side-by-Side Visual Diff Viewer for Nexora
 * Parses unified diff patches and renders GitHub-style Split, Unified, and Code views.
 */
import { esc } from './dom.js';

export function parseDiff(patch) {
  if (!patch || typeof patch !== 'string') return [];
  const lines = patch.split('\n');
  const files = [];
  let currentFile = null;
  let currentHunk = null;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith('diff --git ')) {
      const match = line.match(/diff --git a\/(.*?) b\/(.*)/);
      currentFile = {
        from: match ? match[1].trim() : 'original',
        to: match ? match[2].trim() : 'modified',
        hunks: [],
        additions: 0,
        deletions: 0,
      };
      files.push(currentFile);
      currentHunk = null;
      continue;
    }

    if (line.startsWith('--- ') || line.startsWith('+++ ')) {
      continue;
    }

    if (line.startsWith('@@ ')) {
      const hunkMatch = line.match(/@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)/);
      if (hunkMatch) {
        currentHunk = {
          header: line,
          oldStart: parseInt(hunkMatch[1], 10),
          newStart: parseInt(hunkMatch[3], 10),
          lines: [],
        };
        if (!currentFile) {
          currentFile = { from: 'solution.py', to: 'solution.py', hunks: [], additions: 0, deletions: 0 };
          files.push(currentFile);
        }
        currentFile.hunks.push(currentHunk);
      }
      continue;
    }

    if (currentHunk) {
      if (line.startsWith('+')) {
        currentFile.additions++;
        currentHunk.lines.push({ type: 'add', content: line.slice(1) });
      } else if (line.startsWith('-')) {
        currentFile.deletions++;
        currentHunk.lines.push({ type: 'del', content: line.slice(1) });
      } else {
        currentHunk.lines.push({ type: 'ctx', content: line.startsWith(' ') ? line.slice(1) : line });
      }
    }
  }

  // Fallback for raw code without diff headers:
  if (files.length === 0 && patch.trim()) {
    const rawLines = lines;
    const hunk = {
      header: `@@ -0,0 +1,${rawLines.length} @@`,
      oldStart: 0,
      newStart: 1,
      lines: rawLines.map((l) => ({ type: 'add', content: l })),
    };
    files.push({
      from: 'original',
      to: 'solution.py',
      hunks: [hunk],
      additions: rawLines.length,
      deletions: 0,
    });
  }

  return files;
}

export function renderSplitView(files) {
  if (!files || !files.length) {
    return '<div class="diff-empty">No diff changes to display.</div>';
  }

  let html = '';
  for (const file of files) {
    html += `
      <div class="diff-file-block">
        <div class="diff-file-header">
          <span class="diff-file-name"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:4px;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>${esc(file.to || file.from)}</span>
          <div class="diff-stats">
            <span class="diff-badge add">+${file.additions}</span>
            <span class="diff-badge del">-${file.deletions}</span>
          </div>
        </div>
        <div class="diff-split-wrapper">
          <table class="diff-table diff-split-table">
            <thead>
              <tr>
                <th class="diff-gutter-head">Line</th>
                <th class="diff-side-head original">Original (Before)</th>
                <th class="diff-gutter-head">Line</th>
                <th class="diff-side-head modified">Proposed (After)</th>
              </tr>
            </thead>
            <tbody>`;

    for (const hunk of file.hunks) {
      html += `
        <tr class="diff-hunk-row">
          <td colspan="4" class="diff-hunk-cell">${esc(hunk.header)}</td>
        </tr>`;

      let oldLine = hunk.oldStart;
      let newLine = hunk.newStart;

      let i = 0;
      while (i < hunk.lines.length) {
        const item = hunk.lines[i];

        if (item.type === 'ctx') {
          html += `
            <tr class="diff-row diff-ctx-row">
              <td class="diff-line-num" data-line="${oldLine}"></td>
              <td class="diff-code-cell ctx">${esc(item.content)}</td>
              <td class="diff-line-num" data-line="${newLine}"></td>
              <td class="diff-code-cell ctx">${esc(item.content)}</td>
            </tr>`;
          oldLine++;
          newLine++;
          i++;
        } else {
          const dels = [];
          while (i < hunk.lines.length && hunk.lines[i].type === 'del') {
            dels.push(hunk.lines[i]);
            i++;
          }
          const adds = [];
          while (i < hunk.lines.length && hunk.lines[i].type === 'add') {
            adds.push(hunk.lines[i]);
            i++;
          }

          const maxLen = Math.max(dels.length, adds.length);
          for (let rowIdx = 0; rowIdx < maxLen; rowIdx++) {
            const delItem = dels[rowIdx];
            const addItem = adds[rowIdx];

            const leftNum = delItem ? oldLine++ : '';
            const leftCell = delItem
              ? `<td class="diff-line-num del" data-line="${leftNum}"></td><td class="diff-code-cell del"><span class="diff-op">-</span>${esc(delItem.content)}</td>`
              : `<td class="diff-line-num empty"></td><td class="diff-code-cell empty"></td>`;

            const rightNum = addItem ? newLine++ : '';
            const rightCell = addItem
              ? `<td class="diff-line-num add" data-line="${rightNum}"></td><td class="diff-code-cell add"><span class="diff-op">+</span>${esc(addItem.content)}</td>`
              : `<td class="diff-line-num empty"></td><td class="diff-code-cell empty"></td>`;

            html += `<tr class="diff-row diff-change-row">${leftCell}${rightCell}</tr>`;
          }
        }
      }
    }

    html += `</tbody></table></div></div>`;
  }

  return html;
}

export function renderUnifiedView(files) {
  if (!files || !files.length) {
    return '<div class="diff-empty">No diff changes to display.</div>';
  }

  let html = '';
  for (const file of files) {
    html += `
      <div class="diff-file-block">
        <div class="diff-file-header">
          <span class="diff-file-name"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:4px;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>${esc(file.to || file.from)}</span>
          <div class="diff-stats">
            <span class="diff-badge add">+${file.additions}</span>
            <span class="diff-badge del">-${file.deletions}</span>
          </div>
        </div>
        <div class="diff-unified-wrapper">
          <table class="diff-table diff-unified-table">
            <thead>
              <tr>
                <th class="diff-gutter-head" style="width: 48px;">Old</th>
                <th class="diff-gutter-head" style="width: 48px;">New</th>
                <th class="diff-side-head">Changes</th>
              </tr>
            </thead>
            <tbody>`;

    for (const hunk of file.hunks) {
      html += `
        <tr class="diff-hunk-row">
          <td colspan="3" class="diff-hunk-cell">${esc(hunk.header)}</td>
        </tr>`;

      let oldLine = hunk.oldStart;
      let newLine = hunk.newStart;

      for (const item of hunk.lines) {
        if (item.type === 'ctx') {
          html += `
            <tr class="diff-row diff-ctx-row">
              <td class="diff-line-num" data-line="${oldLine++}"></td>
              <td class="diff-line-num" data-line="${newLine++}"></td>
              <td class="diff-code-cell ctx"> ${esc(item.content)}</td>
            </tr>`;
        } else if (item.type === 'del') {
          html += `
            <tr class="diff-row diff-del-row">
              <td class="diff-line-num del" data-line="${oldLine++}"></td>
              <td class="diff-line-num empty"></td>
              <td class="diff-code-cell del"><span class="diff-op">-</span>${esc(item.content)}</td>
            </tr>`;
        } else if (item.type === 'add') {
          html += `
            <tr class="diff-row diff-add-row">
              <td class="diff-line-num empty"></td>
              <td class="diff-line-num add" data-line="${newLine++}"></td>
              <td class="diff-code-cell add"><span class="diff-op">+</span>${esc(item.content)}</td>
            </tr>`;
        }
      }
    }

    html += `</tbody></table></div></div>`;
  }

  return html;
}

export function renderCodeView(code, filename = 'solution.py') {
  const isHtml = filename.endsWith('.html') || /<(!DOCTYPE\s+)?html/i.test(code || '');
  const lines = esc(code || '').split('\n');
  const numbered = lines.map((l, i) => `
    <tr class="diff-row">
      <td class="diff-line-num" data-line="${i + 1}" style="width: 48px;"></td>
      <td class="diff-code-cell ctx" contenteditable="plaintext-only" spellcheck="false" autocomplete="off" autocapitalize="off">${l !== undefined ? l : ''}</td>
    </tr>
  `).join('');

  return `
    <div class="diff-file-block">
      <div class="diff-file-header">
        <span class="diff-file-name"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:4px;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>${esc(filename)}</span>
        <div class="diff-file-actions">
          ${isHtml ? `<button class="diff-btn diff-preview-btn" title="Toggle Live Preview" type="button"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg><span>Live Preview</span></button>` : ''}
          <button class="diff-btn diff-copy-code-btn icon-only" title="Copy code" aria-label="Copy code" type="button"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>
        </div>
      </div>
      <div class="diff-code-wrapper">
        <table class="diff-table diff-code-table">
          <tbody>${numbered}</tbody>
        </table>
      </div>
      ${isHtml ? `
      <div class="diff-preview-wrapper" style="display: none; height: 100%; min-height: 550px; background: #ffffff; border-radius: 4px; overflow: hidden; margin-top: 4px;">
        <iframe class="diff-preview-iframe" sandbox="allow-scripts allow-modals allow-forms" style="width: 100%; height: 100%; min-height: 550px; border: none; background: #ffffff;"></iframe>
      </div>` : ''}
    </div>`;
}

export function renderDiffViewer(patch, cleanCode, activeMode = 'split', filename = 'solution.py') {
  const files = parseDiff(patch);
  let totalAdd = 0;
  let totalDel = 0;
  for (const f of files) {
    totalAdd += f.additions;
    totalDel += f.deletions;
  }

  let bodyHtml = '';
  if (activeMode === 'unified') {
    bodyHtml = renderUnifiedView(files);
  } else if (activeMode === 'code') {
    bodyHtml = renderCodeView(cleanCode || patch, filename);
  } else {
    bodyHtml = renderSplitView(files);
  }

  return `
    <div class="visual-diff-component">
      <div class="diff-toolbar">
        <div class="diff-modes">
          <button class="diff-mode-btn ${activeMode === 'split' ? 'active' : ''}" data-mode="split">Split</button>
          <button class="diff-mode-btn ${activeMode === 'unified' ? 'active' : ''}" data-mode="unified">Unified</button>
          <button class="diff-mode-btn ${activeMode === 'code' ? 'active' : ''}" data-mode="code">Code</button>
        </div>
        <div class="diff-summary-stats">
          <span class="diff-badge add">+${totalAdd}</span>
          <span class="diff-badge del">-${totalDel}</span>
        </div>
      </div>
      <div class="diff-content-scroll">
        ${bodyHtml}
      </div>
    </div>`;
}

function renumberTableLines(table) {
  if (!table) return;
  const lineNums = table.querySelectorAll('.diff-line-num');
  lineNums.forEach((td, i) => {
    td.setAttribute('data-line', (i + 1).toString());
  });
}

function placeCaretAtEnd(el) {
  if (!el) return;
  if (typeof window !== 'undefined' && window.getSelection && document.createRange) {
    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }
}

export function bindDiffViewerEvents(containerEl, rawCode) {
  if (!containerEl) return;

  if (rawCode) {
    containerEl._cleanCode = rawCode;
    if (typeof window !== 'undefined') window.__nexora_clean_code = rawCode;
  }

  // Real-time editable code listeners
  const table = containerEl.querySelector('.diff-code-table');
  if (table && !table._editBound) {
    table._editBound = true;

    // Real-time code synchronization on input
    table.addEventListener('input', () => {
      const cells = table.querySelectorAll('.diff-code-cell');
      const updatedCode = Array.from(cells).map(c => {
        const text = c.innerText !== undefined ? c.innerText : (c.textContent || '');
        return text.replace(/\r?\n$/, '');
      }).join('\n');

      containerEl._cleanCode = updatedCode;
      if (typeof window !== 'undefined') {
        window.__nexora_clean_code = updatedCode;
        if (window.__nexora_app && window.__nexora_app.getActiveEditorTab) {
          const tab = window.__nexora_app.getActiveEditorTab();
          if (tab) tab.code = updatedCode;
        }
      }

      // Update live preview iframe in real time if visible
      const iframe = containerEl.querySelector('.diff-preview-iframe');
      if (iframe && iframe.parentElement && iframe.parentElement.style.display !== 'none') {
        iframe.srcdoc = updatedCode;
      }
    });

    // Handle Enter, Backspace and Tab keys for code editing
    table.addEventListener('keydown', (e) => {
      const cell = e.target.closest('.diff-code-cell');
      if (!cell) return;
      const row = cell.closest('.diff-row');
      if (!row) return;

      if (e.key === 'Tab') {
        e.preventDefault();
        document.execCommand('insertText', false, '  ');
        table.dispatchEvent(new Event('input', { bubbles: true }));
        return;
      }

      if (e.key === 'Enter') {
        e.preventDefault();
        const newRow = document.createElement('tr');
        newRow.className = 'diff-row';
        newRow.innerHTML = `
          <td class="diff-line-num" style="width: 48px;"></td>
          <td class="diff-code-cell ctx" contenteditable="plaintext-only" spellcheck="false" autocomplete="off" autocapitalize="off"></td>
        `;
        row.after(newRow);
        renumberTableLines(table);

        const newCell = newRow.querySelector('.diff-code-cell');
        if (newCell) {
          newCell.focus();
        }
        table.dispatchEvent(new Event('input', { bubbles: true }));
        return;
      }

      if (e.key === 'Backspace' && cell.textContent === '') {
        const rows = table.querySelectorAll('.diff-row');
        if (rows.length > 1) {
          e.preventDefault();
          const prevRow = row.previousElementSibling;
          row.remove();
          renumberTableLines(table);
          if (prevRow) {
            const prevCell = prevRow.querySelector('.diff-code-cell');
            if (prevCell) {
              prevCell.focus();
              placeCaretAtEnd(prevCell);
            }
          }
          table.dispatchEvent(new Event('input', { bubbles: true }));
        }
      }
    });

    // Handle multiline paste into cells
    table.addEventListener('paste', (e) => {
      const cell = e.target.closest('.diff-code-cell');
      if (!cell) return;
      const text = (e.clipboardData || window.clipboardData)?.getData('text');
      if (text && text.includes('\n')) {
        e.preventDefault();
        const lines = text.split(/\r?\n/);
        let currentRow = cell.closest('.diff-row');
        cell.textContent += lines[0];
        for (let i = 1; i < lines.length; i++) {
          const newRow = document.createElement('tr');
          newRow.className = 'diff-row';
          newRow.innerHTML = `
            <td class="diff-line-num" style="width: 48px;"></td>
            <td class="diff-code-cell ctx" contenteditable="plaintext-only" spellcheck="false" autocomplete="off" autocapitalize="off">${esc(lines[i])}</td>
          `;
          currentRow.after(newRow);
          currentRow = newRow;
        }
        renumberTableLines(table);
        table.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
  }

  // Handle Copy Code button
  const copyBtns = containerEl.querySelectorAll('.diff-copy-code-btn');
  copyBtns.forEach(btn => {
    if (btn._bound) return;
    btn._bound = true;
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const codeToCopy = containerEl._cleanCode || (typeof window !== 'undefined' && window.__nexora_clean_code) || '';
      if (!codeToCopy) {
        const cells = containerEl.querySelectorAll('.diff-code-table .diff-code-cell');
        if (cells.length) {
          const extracted = Array.from(cells).map(c => c.textContent).join('\n');
          copyTextToClipboard(extracted, btn);
          return;
        }
      }
      copyTextToClipboard(codeToCopy, btn);
    });
  });

  // Handle Live Preview toggle button
  const previewBtns = containerEl.querySelectorAll('.diff-preview-btn');
  previewBtns.forEach(btn => {
    if (btn._bound) return;
    btn._bound = true;
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const block = btn.closest('.diff-file-block') || containerEl;
      const codeWrapper = block.querySelector('.diff-code-wrapper');
      const previewWrapper = block.querySelector('.diff-preview-wrapper');
      const iframe = block.querySelector('.diff-preview-iframe');
      if (!codeWrapper || !previewWrapper) return;

      const isShowingPreview = previewWrapper.style.display !== 'none';
      if (isShowingPreview) {
        previewWrapper.style.display = 'none';
        codeWrapper.style.display = '';
        btn.classList.remove('active');
        const textSpan = btn.querySelector('span');
        if (textSpan) textSpan.textContent = 'Live Preview';
      } else {
        codeWrapper.style.display = 'none';
        previewWrapper.style.display = 'block';
        btn.classList.add('active');
        const textSpan = btn.querySelector('span');
        if (textSpan) textSpan.textContent = 'Code View';
        if (iframe && !iframe.srcdoc) {
          const raw = containerEl._cleanCode || (typeof window !== 'undefined' && window.__nexora_clean_code) || '';
          iframe.srcdoc = raw;
        }
      }
    });
  });
}

function copyTextToClipboard(text, btnEl) {
  if (!text) return;
  if (typeof navigator !== 'undefined' && navigator.clipboard) {
    navigator.clipboard.writeText(text).then(() => {
      const originalHtml = btnEl ? btnEl.innerHTML : '';
      const originalTitle = btnEl ? btnEl.getAttribute('title') : '';
      if (btnEl) {
        btnEl.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>`;
        btnEl.classList.add('copied');
        btnEl.setAttribute('title', 'Copied!');
      }
      setTimeout(() => {
        if (btnEl) {
          btnEl.innerHTML = originalHtml;
          btnEl.classList.remove('copied');
          btnEl.setAttribute('title', originalTitle || 'Copy code');
        }
      }, 2000);
    });
  }
}


