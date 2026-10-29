/**
 * Modal manager — one open-at-a-time stack over any element carrying
 * `data-modal="<name>"`. Handles Esc, backdrop dismissal, focus restore,
 * Escape-priority stacking and draggable headers.
 */
import { $, $$, on } from './dom.js';

class ModalManager {
  constructor() {
    /** @type {Map<string, {root: HTMLElement, onOpen?: Function, onClose?: Function}>} */
    this.registry = new Map();
    /** @type {string[]} */
    this.stack = [];
    this.restoreFocus = null;
    this.drag = null;
  }

  register(name, root, hooks = {}) {
    if (!root) return;
    this.registry.set(name, { root, ...hooks });
    const backdrop = root;
    on(backdrop, 'mousedown', (e) => {
      if (e.target === backdrop) this.close(name);
    });
    const closeBtn = root.querySelector('[data-modal-close]');
    if (closeBtn) on(closeBtn, 'click', () => this.close(name));
    this.makeDraggable(root);
  }

  isOpen(name) {
    return this.stack[this.stack.length - 1] === name;
  }

  get top() {
    return this.stack[this.stack.length - 1] || null;
  }

  open(name, payload = null) {
    const entry = this.registry.get(name);
    if (!entry) return false;
    if (this.isOpen(name)) {
      entry.onRefresh?.(payload);
      return true;
    }
    this.restoreFocus = document.activeElement;
    entry.root.classList.remove('hidden');
    entry.root.setAttribute('aria-hidden', 'false');
    this.stack.push(name);
    document.body.classList.add('modal-open');
    entry.onOpen?.(payload);
    const focusTarget = entry.root.querySelector('[autofocus], input, textarea, button:not([data-modal-close])');
    if (focusTarget) setTimeout(() => focusTarget.focus(), 30);
    return true;
  }

  close(name = null) {
    const target = name || this.top;
    if (!target) return false;
    const idx = this.stack.lastIndexOf(target);
    if (idx === -1) return false;
    this.stack.splice(idx, 1);
    const entry = this.registry.get(target);
    entry?.root.classList.add('hidden');
    entry?.root.setAttribute('aria-hidden', 'true');
    entry?.onClose?.();
    if (!this.stack.length) {
      document.body.classList.remove('modal-open');
      if (this.restoreFocus && document.body.contains(this.restoreFocus)) {
        this.restoreFocus.focus?.();
      }
      this.restoreFocus = null;
    }
    return true;
  }

  closeAll() {
    while (this.stack.length) this.close(this.top);
  }

  toggle(name, payload = null) {
    if (this.isOpen(name)) this.close(name);
    else this.open(name, payload);
  }

  /** Make a modal draggable by its `[data-drag-handle]` (or `.modal-header`). */
  makeDraggable(root) {
    const handle = root.querySelector('[data-drag-handle]') || root.querySelector('.modal-header');
    const content = root.querySelector('.modal-content, .cmdk');
    if (!handle || !content) return;

    on(handle, 'mousedown', (e) => {
      if (e.target.closest('button, input, select, textarea, a')) return;
      const rect = content.getBoundingClientRect();
      this.drag = {
        dx: e.clientX - rect.left,
        dy: e.clientY - rect.top,
        w: rect.width,
      };
      content.style.position = 'fixed';
      content.style.margin = '0';
      content.style.left = `${rect.left}px`;
      content.style.top = `${rect.top}px`;
      content.style.right = 'auto';
      content.style.width = `${rect.width}px`;
      document.body.style.userSelect = 'none';
    });

    on(window, 'mousemove', (e) => {
      if (!this.drag) return;
      const pad = 8;
      const x = Math.min(Math.max(e.clientX - this.drag.dx, -this.drag.w + 120), window.innerWidth - pad);
      const y = Math.min(Math.max(e.clientY - this.drag.dy, pad), window.innerHeight - pad);
      content.style.left = `${x}px`;
      content.style.top = `${y}px`;
    });

    on(window, 'mouseup', () => {
      if (!this.drag) return;
      this.drag = null;
      document.body.style.userSelect = '';
      content.style.position = '';
      content.style.left = '';
      content.style.top = '';
      content.style.right = '';
      content.style.width = '';
    });
  }

  bindGlobalKeys() {
    on(document, 'keydown', (e) => {
      if (e.key !== 'Escape') return;
      if (this.stack.length) {
        e.stopPropagation();
        this.close(this.top);
      }
    }, true);
  }
}

export const modals = new ModalManager();
export { $$ };