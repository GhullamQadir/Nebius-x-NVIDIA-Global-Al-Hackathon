/**
 * Shell chrome — sidebar collapse/persistence, rail + sidebar resizers,
 * mobile drawer behaviour and the Ctrl+K command palette.
 */
import { $, $$, on, delegate, esc } from './dom.js';

const SIDEBAR_KEY = 'nexora-sidebar-width';
const RAIL_KEY = 'nexora-rail-width';
const COLLAPSED_KEY = 'nexora-sidebar-collapsed';

class Shell {
  constructor() {
    this.body = document.body;
    this.sidebar = $('#sidebar');
    this.rail = $('#icon-rail');
    this.commands = [];
  }

  init() {
    this.restoreSizes();
    this.restoreCollapsed();
    this.bindToggle();
    this.bindResizers();
    this.bindCmdk();
    this.bindGlobalKeys();
    this.syncCollapseUI();
  }

  /* ---------------------------------------------------------- sizing */
  restoreSizes() {
    const sidebarW = Number(localStorage.getItem(SIDEBAR_KEY));
    if (sidebarW >= 190 && sidebarW <= 460) {
      document.documentElement.style.setProperty('--sidebar-w', `${sidebarW}px`);
    }
    const railW = Number(localStorage.getItem(RAIL_KEY));
    if (railW >= 38 && railW <= 90) {
      document.documentElement.style.setProperty('--icon-rail-w', `${railW}px`);
    }
  }

  restoreCollapsed() {
    if (localStorage.getItem(COLLAPSED_KEY) === '1') this.body.classList.add('sidebar-collapsed');
  }

  collapse(value) {
    const next = value ?? !this.body.classList.contains('sidebar-collapsed');
    this.body.classList.toggle('sidebar-collapsed', next);
    try { localStorage.setItem(COLLAPSED_KEY, next ? '1' : '0'); } catch { /* ignore */ }
    this.syncCollapseUI();
    window.dispatchEvent(new CustomEvent('nexora:layout'));
    return next;
  }

  syncCollapseUI() {
    const collapsed = this.body.classList.contains('sidebar-collapsed');
    const btn = $('#hamburger-btn');
    if (btn) btn.setAttribute('aria-expanded', String(!collapsed));
    const collapseBtn = $('#btn-collapse-sidebar');
    if (collapseBtn) collapseBtn.title = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
  }

  bindToggle() {
    on($('#hamburger-btn'), 'click', () => this.collapse());
    on($('#btn-collapse-sidebar'), 'click', () => this.collapse());
    on($('#sidebar-brand'), 'click', () => {
      document.getElementById('rail-new-run')?.click();
    });
  }

  bindResizers() {
    const dragHandle = (handleId, cssVar, key, min, max) => {
      const handle = $(`#${handleId}`);
      if (!handle) return;
      on(handle, 'mousedown', (e) => {
        e.preventDefault();
        handle.classList.add('dragging');
        const target = handleId === 'rail-resize-handle' ? this.rail : this.sidebar;
        target?.classList.add('resizing');
        const move = (ev) => {
          const raw = handleId === 'rail-resize-handle' ? ev.clientX : ev.clientX - this.rail.getBoundingClientRect().width;
          const width = handleId === 'rail-resize-handle' ? ev.clientX : ev.clientX;
          const clamped = Math.min(Math.max(width, min), max);
          document.documentElement.style.setProperty(cssVar, `${clamped}px`);
          if (handleId === 'rail-resize-handle' && this.rail) {
            this.rail.style.width = `${clamped}px`;
          }
          void raw;
        };
        const up = () => {
          handle.classList.remove('dragging');
          target?.classList.remove('resizing');
          window.removeEventListener('mousemove', move);
          window.removeEventListener('mouseup', up);
          const final = parseInt(
            getComputedStyle(document.documentElement).getPropertyValue(cssVar),
            10,
          );
          if (Number.isFinite(final)) {
            try { localStorage.setItem(key, String(final)); } catch { /* ignore */ }
          }
        };
        window.addEventListener('mousemove', move);
        window.addEventListener('mouseup', up);
      });
    };
    dragHandle('rail-resize-handle', '--icon-rail-w', RAIL_KEY, 38, 90);
    dragHandle('sidebar-resize-handle', '--sidebar-w', SIDEBAR_KEY, 190, 460);
  }

  /* ---------------------------------------------------------- command palette */
  registerCommands(list) {
    this.commands = list || [];
  }

  bindCmdk() {
    this.overlay = $('#cmdk-overlay');
    this.input = $('#cmdk-input');
    this.list = $('#cmdk-list');
    this.selected = 0;
    this.filtered = [];

    on($('#chat-search-btn'), 'click', (e) => {
      e?.stopPropagation?.();
      e?.preventDefault?.();
      try { this.toggleCmdk(); } catch { this.openCmdk(); }
    });
    on(this.overlay, 'mousedown', (e) => { if (e.target === this.overlay) this.closeCmdk(); });

    on(this.input, 'input', () => this.renderCmdk());
    on(this.input, 'keydown', (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); this.moveSelection(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); this.moveSelection(-1); }
      else if (e.key === 'Enter') {
        e.preventDefault();
        const cmd = this.filtered[this.selected];
        if (cmd) { this.closeCmdk(); cmd.run(); }
      } else if (e.key === 'Escape') {
        e.preventDefault();
        this.closeCmdk();
      }
    });
  }

  openCmdk() {
    try { window.NexoraApp?.registerCommands?.(); } catch { /* palette must still open */ }
    if (!this.overlay || !this.input) return;
    this.overlay.classList.remove('hidden');
    this.input.value = '';
    this.selected = 0;
    this.renderCmdk();
    setTimeout(() => this.input.focus(), 20);
  }

  closeCmdk() {
    this.overlay.classList.add('hidden');
  }

  toggleCmdk() {
    if (this.overlay.classList.contains('hidden')) this.openCmdk();
    else this.closeCmdk();
  }

  renderCmdk() {
    const query = this.input.value.trim().toLowerCase();
    this.filtered = this.commands.filter((cmd) => {
      if (!query) return true;
      return `${cmd.label} ${cmd.group || ''} ${cmd.keywords || ''}`.toLowerCase().includes(query);
    });
    this.selected = 0;

    if (!this.filtered.length) {
      this.list.innerHTML = '<div class="cmdk-empty">No matching commands.</div>';
      return;
    }

    this.list.innerHTML = this.filtered.map((cmd, i) => `
      <button class="cmdk-item ${cmd.gold ? 'gold' : ''} ${i === this.selected ? 'sel' : ''}" data-cmd-index="${i}">
        <span class="ico">${cmd.icon || '◆'}</span>
        <span class="grow">${esc(cmd.label)}</span>
        <span class="hint">${esc(cmd.hint || cmd.group || '')}</span>
      </button>
    `).join('');

    delegate(this.list, 'click', '.cmdk-item', (_e, node) => {
      const cmd = this.filtered[Number(node.dataset.cmdIndex)];
      if (cmd) { this.closeCmdk(); cmd.run(); }
    });
  }

  moveSelection(delta) {
    if (!this.filtered.length) return;
    this.selected = (this.selected + delta + this.filtered.length) % this.filtered.length;
    $$('.cmdk-item', this.list).forEach((node, i) => {
      node.classList.toggle('sel', i === this.selected);
    });
    this.list.children[this.selected]?.scrollIntoView({ block: 'nearest' });
  }

  bindGlobalKeys() {
    on(document, 'keydown', (e) => {
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        this.toggleCmdk();
      } else if (mod && e.key.toLowerCase() === 'b') {
        e.preventDefault();
        this.collapse();
      } else if (mod && e.key === 'Enter') {
        e.preventDefault();
        document.getElementById('send-btn')?.click();
      }
    });
  }
}

export const shell = new Shell();