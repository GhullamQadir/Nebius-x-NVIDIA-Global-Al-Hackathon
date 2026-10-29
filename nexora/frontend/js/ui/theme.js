/**
 * Nexora theme controller — light/dark, density, text scale, background pattern
 * and the neon blue / gold accent intensities.
 *
 * Reads/writes `nexora-theme` in localStorage and toggles classes on <html>
 * exactly the way the Odysseus shell expects:
 *   .light | .density-* | .ui-scale-* | .bg-pattern-* | .glow-*
 */
import { $, $$, on } from './dom.js';

const KEY = 'nexora-theme';

const DEFAULTS = {
  mode: 'dark',
  density: 'default',
  textSize: 'default',
  bgPattern: 'none',
  bgIntensity: 40,
  bgSize: 100,
  glow: 55,
  goldGlow: 45,
  reducedMotion: false,
  highContrast: false,
};

const PATTERNS = ['none', 'dots', 'grid', 'synapse'];

class ThemeController {
  constructor() {
    this.settings = { ...DEFAULTS, ...this.read() };
    this.listeners = new Set();
    this.systemQuery = window.matchMedia('(prefers-color-scheme: light)');
  }

  read() {
    try {
      const raw = localStorage.getItem(KEY);
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  }

  write() {
    try {
      localStorage.setItem(KEY, JSON.stringify(this.settings));
    } catch {
      /* storage unavailable — theme still applies for this session */
    }
  }

  subscribe(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  /** Apply everything to the document. Safe to call repeatedly. */
  apply() {
    const root = document.documentElement;
    const s = this.settings;

    root.classList.toggle('light', s.mode === 'light');
    root.classList.remove('density-compact', 'density-spacious');
    if (s.density === 'compact') root.classList.add('density-compact');
    if (s.density === 'spacious') root.classList.add('density-spacious');

    root.classList.remove('ui-scale-125');
    if (s.textSize === 'large') root.classList.add('ui-scale-125');

    root.classList.remove('bg-pattern-dots', 'bg-pattern-grid', 'bg-pattern-synapse');
    if (s.bgPattern !== 'none' && PATTERNS.includes(s.bgPattern)) {
      root.classList.add(`bg-pattern-${s.bgPattern}`);
    }

    root.style.setProperty('--bg-effect-intensity', String(Math.max(0, Math.min(1, s.bgIntensity / 100))));
    root.style.setProperty('--bg-pattern-size', String(s.bgSize));

    root.style.setProperty('--glow-alpha', String(Math.max(0, Math.min(1, s.glow / 100))));
    root.style.setProperty('--gold-glow-alpha', String(Math.max(0, Math.min(1, s.goldGlow / 100))));
    root.style.setProperty('--motion-scale', s.reducedMotion ? '0' : '1');

    root.classList.toggle('hc', !!s.highContrast);
    root.classList.toggle('no-motion', !!s.reducedMotion);

    this.write();
    this.listeners.forEach((fn) => fn(this.settings));
  }

  set(patch) {
    Object.assign(this.settings, patch || {});
    this.apply();
    return this.settings;
  }

  toggleMode() {
    const next = this.settings.mode === 'dark' ? 'light' : 'dark';
    this.set({ mode: next });
    return next;
  }

  cyclePattern() {
    const idx = PATTERNS.indexOf(this.settings.bgPattern);
    const next = PATTERNS[(idx + 1) % PATTERNS.length];
    this.set({ bgPattern: next });
    return next;
  }

  followSystem() {
    const prefersLight = this.systemQuery.matches;
    this.set({ mode: prefersLight ? 'light' : 'dark' });
  }

  /** Header/sidebar status text for the current mode. */
  get label() {
    return this.settings.mode === 'light' ? 'Light' : 'Dark';
  }
}

export const theme = new ThemeController();

/** Wire the rail/sidebar theme buttons to the controller. */
export function initThemeChrome() {
  const buttons = $$('[data-theme-toggle]');
  buttons.forEach((btn) => on(btn, 'click', () => theme.toggleMode()));
  const cycle = $('[data-theme-cycle-pattern]');
  if (cycle) on(cycle, 'click', () => theme.cyclePattern());
  theme.apply();
}

export { PATTERNS };