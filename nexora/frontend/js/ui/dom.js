/**
 * Tiny DOM helpers shared by the Nexora UI modules.
 */

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/** Escape a value for safe interpolation into innerHTML. */
export function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Create an element from a tag, props and children. */
export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) node.setAttribute(key, '');
    else node.setAttribute(key, value);
  }
  (Array.isArray(children) ? children : [children]).forEach((child) => {
    if (child === null || child === undefined || child === false) return;
    node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  });
  return node;
}

export function on(target, event, handler, options) {
  if (!target) return () => {};
  target.addEventListener(event, handler, options);
  return () => target.removeEventListener(event, handler, options);
}

/** Event delegation: fire when the click target (or an ancestor) matches `selector`. */
export function delegate(root, event, selector, handler) {
  return on(root, event, (e) => {
    const match = e.target.closest(selector);
    if (match && root.contains(match)) handler(e, match);
  });
}

export function debounce(fn, wait = 180) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

export function formatNumber(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString('en-US');
}

export function formatTokens(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return String(n);
}

export function formatDuration(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n) || n <= 0) return '—';
  if (n < 1000) return `${Math.round(n)}ms`;
  const s = n / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s % 60)}s`;
}

export function parseDate(value) {
  if (!value) return null;
  if (value instanceof Date) return value;
  let str = String(value).trim();
  if (!str) return null;
  // Convert SQLite space separator "YYYY-MM-DD HH:MM:SS" to ISO "T"
  str = str.replace(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?)/, '$1T$2');
  // If no timezone offset (Z, +HH:MM, -HH:MM), treat as UTC timestamp
  if (!/(?:Z|[+-]\d{2}(?::?\d{2})?)$/i.test(str)) {
    str += 'Z';
  }
  const d = new Date(str);
  return Number.isNaN(d.getTime()) ? new Date(value) : d;
}

export function formatDateTime(value) {
  if (!value) return '—';
  const d = parseDate(value);
  if (!d || Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

export function relativeTime(value) {
  if (!value) return '—';
  const d = parseDate(value);
  if (!d || Number.isNaN(d.getTime())) return String(value);
  const diff = Date.now() - d.getTime();
  const abs = Math.abs(diff);
  const min = 60_000, hour = 3.6e6, day = 8.64e7;
  if (abs < min) return 'just now';
  if (abs < hour) return `${Math.max(1, Math.round(abs / min))}m ago`;
  if (abs < day) return `${Math.max(1, Math.round(abs / hour))}h ago`;
  if (abs < day * 30) return `${Math.max(1, Math.round(abs / day))}d ago`;
  return d.toLocaleDateString();
}

/** Collapse a snake_case / kebab-case enum into a readable token. */
export function humanize(value) {
  if (!value) return '—';
  return String(value)
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^./, (c) => c.toUpperCase());
}

/** Map an enum value onto one of the .tag-* tone classes. */
export function toneFor(value) {
  const v = String(value ?? '').toLowerCase();
  if (['allow', 'allowed', 'pass', 'passed', 'success', 'approved', 'completed', 'ok'].includes(v)) return 'allow';
  if (['allow_with_monitoring', 'monitor', 'monitoring', 'warn', 'warning', 'pending', 'awaiting', 'awaiting_start', 'awaiting_approval', 'needs_approval', 'require_approval', 'review'].includes(v)) return 'monitor';
  if (['deny', 'denied', 'blocked', 'fail', 'failed', 'error', 'rejected', 'cancelled', 'cancel_requested', 'timeout_failed', 'timeout', 'interrupted'].includes(v)) return 'deny';
  if (['quarantine', 'queued', 'running', 'active'].includes(v)) return 'quarantine';
  if (['skipped', 'skip'].includes(v)) return 'skip';
  return 'info';
}

export function tag(value, extraClass = '') {
  return `<span class="tag tag-${toneFor(value)} ${extraClass}">${esc(humanize(value))}</span>`;
}

/** Shorten free-form text for list rows. */
export function truncate(value, max = 68) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}