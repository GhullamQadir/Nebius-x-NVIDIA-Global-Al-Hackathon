/**
 * Toasts — bottom-right stack used for API errors, run lifecycle events and
 * small confirmations.
 */
import { esc } from './dom.js';

let container = null;

function ensureContainer() {
  if (container && document.body.contains(container)) return container;
  container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    container.id = 'toast-container';
    document.body.appendChild(container);
  }
  return container;
}

/**
 * @param {string} message
 * @param {'info'|'success'|'warning'|'error'|'gold'} type
 * @param {{timeout?: number, action?: {label: string, onClick: Function}}} [options]
 */
export function toast(message, type = 'info', options = {}) {
  const { timeout = 4200, action = null } = options;
  const node = document.createElement('div');
  node.className = `toast ${type}`;
  node.setAttribute('role', type === 'error' ? 'alert' : 'status');

  const text = document.createElement('span');
  text.className = 'toast-message';
  text.textContent = message;
  node.appendChild(text);

  if (action) {
    const btn = document.createElement('button');
    btn.className = 'btn btn-sm';
    btn.textContent = action.label;
    btn.addEventListener('click', () => {
      dismiss();
      action.onClick();
    });
    node.appendChild(btn);
  }

  const close = document.createElement('button');
  close.className = 'toast-close';
  close.setAttribute('aria-label', 'Dismiss');
  close.innerHTML = '&times;';
  node.appendChild(close);

  ensureContainer().appendChild(node);

  let timer = null;
  function dismiss() {
    clearTimeout(timer);
    if (!node.isConnected) return;
    node.classList.add('leaving');
    setTimeout(() => node.remove(), 200);
  }
  close.addEventListener('click', dismiss);
  if (timeout > 0) timer = setTimeout(dismiss, timeout);
  node.addEventListener('mouseenter', () => clearTimeout(timer));
  node.addEventListener('mouseleave', () => { if (timeout > 0) timer = setTimeout(dismiss, 1600); });

  return dismiss;
}

toast.success = (m, o) => toast(m, 'success', o);
toast.error = (m, o) => toast(m, 'error', { timeout: 7000, ...o });
toast.warning = (m, o) => toast(m, 'warning', { timeout: 6000, ...o });
toast.info = (m, o) => toast(m, 'info', o);
toast.gold = (m, o) => toast(m, 'gold', o);