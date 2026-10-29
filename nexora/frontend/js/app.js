/**
 * Nexora — application orchestrator.
 *
 * Wires the continueus-style shell (icon rail + sidebar + chat composer +
 * tool modals) to the Nexora /api/v1 backend. No backend behaviour is changed
 * here; this file only reads and drives the documented API surface.
 */
import './state.js';
import './api.js';

import {
  $, $$, on, delegate, esc, formatNumber, formatTokens, formatDuration,
  formatDateTime, relativeTime, humanize, tag, truncate,
} from './ui/dom.js';
import { theme, initThemeChrome } from './ui/theme.js';
import { modals } from './ui/modal.js';
import { shell } from './ui/shell.js';
import { toast } from './ui/toast.js';
import { renderMarkdown } from './ui/markdown.js';
import { PANELS, PANEL_MAP, setActivePanel, ICONS } from './panels.js?v=12';
import { renderDiffViewer, renderCodeView, bindDiffViewerEvents } from './ui/diff_viewer.js';

/* ========================================================================== */
const SAMPLE_TASKS = {
  calculator: 'Fix the empty-input failure in the calculator logic and add a regression test for the edge case.',
  api: 'Repair the API validation bug in the request schema and keep the error semantics backward compatible.',
  cli: 'Correct the CLI argument parsing issue and ensure the help text stays accurate for the new flag flow.',
};

/**
 * Provider that owns auto routing. Mirrors PRIMARY_PROVIDER in
 * backend/app/core/provider_registry.py — the registry dispatches strictly on
 * ModelRegistry.provider, so anything else is a secondary provider that has to
 * be selected explicitly in fixed mode.
 */
const PRIMARY_PROVIDER = 'nebius';
const LEGACY_MOCK_MARKER = 'No NEBIUS_API_KEY found. Mock response for:';
const INTERNAL_OUTPUT_PREFIX = /^\s*(?:here(?:'s| is) (?:(?:my|a|the) )?(?:thinking process|reasoning|analysis)|analysis\s*:|chain of thought\s*:|let me think(?: through| step by step)?)/i;

const isPrimaryProvider = (model) => (model.provider || PRIMARY_PROVIDER) === PRIMARY_PROVIDER;

const TERMINAL = ['completed', 'failed', 'blocked', 'cancelled', 'timeout_failed', 'interrupted'];
const ACTIVE = [
  'queued', 'analyzing', 'security_review', 'planning', 'awaiting_start',
  'context_build', 'model_step', 'policy_check', 'executing', 'validating',
  'replanning', 'awaiting_approval', 'cancel_requested',
];

/* ========================================================================== */
class NexoraApp {
  constructor() {
    this.state = window.NexoraState;
    this.messages = [];
    this.activePanel = 'runs';
    this.pollTimer = null;
    this.pollMs = 2000;
    this.autoStart = true;
    this.showTimestamps = true;
    this.compactFeed = false;
    this.apiBase = '/api/v1';
    this.health = null;
    this.attachments = [];
    this.attachedFiles = [];
    this.historyEl = $('#chat-history');
    this.chatEl = $('#chat-container');
    // Virtual scroll state for 60fps long-conversation rendering
    this.virtualScrollEnabled = true;
    this.virtualItemHeight = 120; // average msg height
    this.virtualBuffer = 3; // items to render beyond viewport
    this.virtualStart = 0;
    // Tracks the run ID of the current active chat thread.
    // When set, subsequent submits will send parent_run_id = activeThreadRunId
    // so the backend continues the same conversation thread.
    this.activeThreadRunId = null;
    this.draftChatTitle = '';
    this.conversationSearchTimer = null;
    this.conversationSearchRequest = 0;
    this.currentStreamAbortController = null;
    this.isCancelling = false;
    this.detailLevel = localStorage.getItem('nexora_detail_level') || 'auto';
    this.activeView = localStorage.getItem('nexora_active_view') || 'split';
  }

  /* ================================================================ boot */
  async init() {
    window.__nexora_app = this;
    this.setupDefaults();
    shell.init();
    initThemeChrome();
    this.setupModals();
    this.bindComposer();
    this.bindRailAndTools();
    this.bindSidebar();
    this.bindTopNav();
    this.bindGlobalKeys();
    this.registerCommands();
    this.initResizers();
    this.initCustomTheme();
    this.applyViewMode(this.activeView);
    this.initEditorTabs();

    await this.bootstrapData();
    this.renderAll();
    this.initVirtualScroll();
    this.dismissLoader();
  }

  setupDefaults() {
    const saved = (() => {
      try { return JSON.parse(localStorage.getItem('nexora-prefs') || '{}'); } catch { return {}; }
    })();
    Object.assign(this, {
      pollMs: Number(saved.pollMs) || 2000,
      autoStart: saved.autoStart !== false,
      showTimestamps: saved.showTimestamps !== false,
      compactFeed: !!saved.compactFeed,
    });
    this.persistPrefs();
  }

  persistPrefs() {
    try {
      localStorage.setItem('nexora-prefs', JSON.stringify({
        pollMs: this.pollMs,
        autoStart: this.autoStart,
        showTimestamps: this.showTimestamps,
        compactFeed: this.compactFeed,
      }));
    } catch { /* ignore */ }
  }

  dismissLoader() {
    $('#app-loader')?.classList.add('done');
  }

  /* ================================================================ data */
  async bootstrapData() {
    this.bodyBusy(true);
    await this.probeApiBase();
    try {
      this.health = await window.NexoraApi.health();
      this.setConnection(true, this.health?.service || 'Nexora-backend');
    } catch {
      this.health = null;
      this.setConnection(false, 'API unreachable');
    }

    const results = await Promise.allSettled([
      this.loadWorkspaces(),
      this.loadModels(),
      this.loadBudgetProfiles(),
      this.loadRuns(),
      this.loadPackageRouting(),
    ]);
    const failed = results.filter((r) => r.status === 'rejected');
    if (failed.length) {
      toast(`Some data failed to load (${failed.length}). Showing defaults.`, 'warning');
    }
    this.bodyBusy(false);
  }

  /**
  * Prefer the same-origin development proxy, then fall back to a standalone
  * static server talking directly to the API. `?api=` overrides everything.
   */
  async probeApiBase() {
    if (new URLSearchParams(window.location.search).get('api')) {
      this.apiBase = window.NexoraApi.baseUrl;
      return;
    }
    const suffix = '/api/v1';
    const port = window.location.port || (window.location.protocol === 'https:' ? '443' : '80');
    const candidates = [`${window.location.origin}${suffix}`];

    // Static server on a dev port → try the backend port first so the happy
    // path never issues a doomed same-origin request.
    if (!['80', '443'].includes(port)) {
      for (const backendPort of ['8001', '8000']) {
        if (backendPort === port) continue;
        candidates.push(`${window.location.protocol}//${window.location.hostname}:${backendPort}${suffix}`);
      }
    }

    for (const base of candidates) {
      try {
        await new window.ApiClient(base).request('/health');
        this.apiBase = window.NexoraApi.setBaseUrl(base);
        if (base !== `${window.location.origin}${suffix}`) toast(`API base → ${base}`, 'info');
        return;
      } catch {
        /* try the next candidate */
      }
    }
    this.apiBase = window.NexoraApi.baseUrl;
  }

  async loadWorkspaces() {
    const data = await window.NexoraApi.workspaces.list({ active_only: true });
    const workspaces = data.workspaces || [];
    this.state.set('workspaces', workspaces);
    const workspace = workspaces[0] || null;
    this.state.set('selectedWorkspaceId', workspace?.id || null);
    await this.loadWorkspaceFiles();
  }

  async loadModels() {
    const models = await window.NexoraApi.models.list(true);
    this.state.set('models', models || []);
    this.state.set('enabledModels', (models || []).filter((m) => m.is_enabled));
  }

  /**
   * Pull the standalone packages/* layer (contracts + model_router +
   * nebius_adapter) as the backend sees it, so the Router panel can show the
   * package tier decisions next to the ModelRegistry rows they resolve to.
   */
  async loadPackageRouting() {
    // Package routing (mock provider) disabled — real inference uses Nebius API directly
    this.state.set('packageRouting', null);
  }

  async loadBudgetProfiles() {
    const profiles = await window.NexoraApi.budgetProfiles.list();
    this.state.set('budgetProfiles', profiles || []);
    const def = profiles.find((p) => p.is_default) || profiles[0] || null;
    this.state.set('defaultBudgetProfile', def);
    const remembered = localStorage.getItem('nexora-profile');
    const match = profiles.find((p) => p.id === remembered);
    this.state.set('selectedBudgetProfileId', (match || def)?.id || null);
  }

  async loadRuns() {
    const data = await window.NexoraApi.runs.list({ page_size: 40 });
    this.state.set('runs', data.runs || []);
  }

  bodyBusy(busy) {
    document.body.classList.toggle('is-loading', busy);
  }

  setConnection(online, label) {
    const dot = $('#conn-dot');
    const text = $('#conn-text');
    const meta = $('#conn-meta');
    if (dot) dot.className = `conn-dot ${online ? 'online' : 'offline'}`;
    if (text) text.textContent = online ? label : label;
    if (meta) meta.textContent = `${this.apiBase} · ${new Date().toLocaleTimeString()}`;
  }

  /* ================================================================ sidebar */
  bindSidebar() {
    $$('.sample-task').forEach((btn) => on(btn, 'click', () => {
      const text = SAMPLE_TASKS[btn.dataset.sample];
      if (!text) return;
      const input = $('#message');
      input.value = text;
      this.autoGrow(input);
      this.updateGhost();
      input.focus();
      toast('Sample task loaded into the composer.', 'info');
    }));

    on($('#rail-new-run'), 'click', () => this.newRun());
    on($('#new-chat-btn'), 'click', () => this.newRun());
    on($('#welcome-start-btn'), 'click', () => $('#message')?.focus());
    on($('#budget-chip'), 'click', () => this.cycleBudgetProfile());

    const searchInput = $('#cmdk-input');
    on(searchInput, 'input', () => {
      clearTimeout(this.conversationSearchTimer);
      const query = searchInput.value.trim();
      const requestId = ++this.conversationSearchRequest;
      if (!query) {
        this.registerCommands();
        shell.renderCmdk();
        return;
      }

      this.conversationSearchTimer = setTimeout(async () => {
        try {
          const result = await window.NexoraApi.runs.list({ q: query, page_size: 100 });
          if (requestId !== this.conversationSearchRequest || searchInput.value.trim() !== query) return;
          // Backend content search + client-side conversation-name matches
          // (custom titles) so renamed chats stay findable by name.
          const merged = new Map();
          for (const run of result.runs || []) merged.set(run.id, run);
          for (const run of this.state.get('runs') || []) {
            if (!run || merged.has(run.id)) continue;
            const title = this.displayRunTitle(run);
            if (title && title.toLowerCase().includes(query.toLowerCase())) merged.set(run.id, run);
          }
          this.registerCommands([...merged.values()]);
          shell.renderCmdk();
        } catch (error) {
          if (requestId !== this.conversationSearchRequest) return;
          this.registerCommands();
          shell.renderCmdk();
          toast(`Conversation search failed: ${error.message}`, 'error');
        }
      }, 220);
    });


    // Delegate inline policy approvals click
    delegate(document, 'click', '.approval-btn', async (e, btn) => {
      const approvalId = btn.getAttribute('data-approval-id');
      const action = btn.getAttribute('data-action');
      const card = btn.closest('.inline-approval-card');
      if (!approvalId) return;

      btn.disabled = true;
      const isApprove = action === 'approve';

      try {
        const run = this.state.get('currentRun');
        if (run) {
          await window.NexoraApi.runs.approve(run.id, approvalId, isApprove);
        } else {
          await window.NexoraApi.approvals.decide(approvalId, isApprove);
        }
        toast(isApprove ? 'Action approved.' : 'Action rejected.', isApprove ? 'success' : 'warning');
        if (card) {
          const actionsDiv = card.querySelector('.approval-actions');
          const badge = card.querySelector('.approval-badge');
          if (actionsDiv) {
            const checkSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="vertical-align:middle;margin-right:4px;"><polyline points="20 6 9 17 4 12"/></svg>`;
            const xSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="vertical-align:middle;margin-right:4px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
            actionsDiv.innerHTML = `<span class="approval-status-done ${isApprove ? 'status-approved' : 'status-rejected'}">${isApprove ? checkSvg + 'Approved' : xSvg + 'Rejected'}</span>`;
          }
          if (badge) {
            badge.className = `approval-badge ${isApprove ? 'badge-completed' : 'badge-failed'}`;
            badge.textContent = isApprove ? 'Approved' : 'Rejected';
          }
        }
      } catch (err) {
        btn.disabled = false;
        toast(`Approval action failed: ${err.message}`, 'error');
      }
    });
  }


  cycleBudgetProfile() {
    const list = this.state.get('budgetProfiles') || [];
    if (!list.length) return toast('No budget profiles available.', 'warning');
    const idx = list.findIndex((p) => p.id === this.state.get('selectedBudgetProfileId'));
    const next = list[(idx + 1) % list.length];
    this.state.set('selectedBudgetProfileId', next.id);
    try { localStorage.setItem('nexora-profile', next.id); } catch { /* ignore */ }
    this.updateComposerChips();
    toast(`Budget profile: ${next.name}`, 'gold');
  }

  /* ================================================================ chat persistence */
  getCustomTitles() {
    try { return JSON.parse(localStorage.getItem('nexora_chat_titles') || '{}'); } catch { return {}; }
  }

  setCustomTitle(runId, title) {
    const titles = this.getCustomTitles();
    if (title) titles[runId] = title;
    else delete titles[runId];
    try { localStorage.setItem('nexora_chat_titles', JSON.stringify(titles)); } catch { }
  }

  getDeletedRunIds() {
    try { return JSON.parse(localStorage.getItem('nexora_deleted_runs') || '[]'); } catch { return []; }
  }

  markRunDeleted(runId) {
    const ids = this.getDeletedRunIds();
    if (!ids.includes(runId)) {
      ids.push(runId);
      try { localStorage.setItem('nexora_deleted_runs', JSON.stringify(ids)); } catch { }
    }
  }

  getThreads(runs) {
    if (!runs || !runs.length) return [];
    const runMap = new Map();
    for (const r of runs) runMap.set(r.id, r);

    const findRootId = (run) => {
      let curr = run;
      const seen = new Set();
      while (curr && curr.parent_run_id && !seen.has(curr.id)) {
        seen.add(curr.id);
        const parent = runMap.get(curr.parent_run_id);
        if (!parent) break;
        curr = parent;
      }
      return curr.id;
    };

    const threadMap = new Map();
    for (const run of runs) {
      const rootId = findRootId(run);
      if (!threadMap.has(rootId)) {
        threadMap.set(rootId, {
          rootId,
          rootRun: runMap.get(rootId) || run,
          latestRun: run,
          runs: [],
        });
      }
      const thread = threadMap.get(rootId);
      thread.runs.push(run);
      const runTime = Date.parse(run.updated_at || run.created_at || '') || 0;
      const latestTime = Date.parse(thread.latestRun.updated_at || thread.latestRun.created_at || '') || 0;
      if (runTime > latestTime) thread.latestRun = run;
    }
    return Array.from(threadMap.values());
  }

  promptRenameRun(runId) {
    if (!runId && !this.state.get('currentRun')) {
      const newTitle = window.prompt('Name this chat conversation:', this.draftChatTitle || 'New chat');
      if (newTitle === null) return;
      this.draftChatTitle = newTitle.trim();
      this.updateHeaderStats();
      toast(this.draftChatTitle ? 'Chat renamed.' : 'Chat name cleared.', 'success');
      return;
    }

    const rawList = this.state.get('runs') || [];
    const threads = this.getThreads(rawList);
    const targetThread = threads.find((t) => t.rootId === runId || t.latestRun.id === runId || t.runs.some((r) => r.id === runId));
    const targetId = targetThread ? targetThread.rootId : runId;
    const run = (this.state.get('runs') || []).find((r) => r.id === targetId) || this.state.get('currentRun');
    if (!run) return;
    const currentTitle = this.getCustomTitles()[targetId] || run.task_text;
    const newTitle = window.prompt('Rename chat conversation:', currentTitle);
    if (newTitle !== null) {
      const trimmed = newTitle.trim();
      if (trimmed) {
        this.setCustomTitle(targetId, trimmed);
        toast('Chat renamed.', 'success');
      } else {
        this.setCustomTitle(targetId, null);
      }
      this.renderRunsList();
      this.updateHeaderStats();
    }
  }

  deleteRun(runId) {
    const rawList = this.state.get('runs') || [];
    const threads = this.getThreads(rawList);
    const targetThread = threads.find((t) => t.rootId === runId || t.latestRun.id === runId || t.runs.some((r) => r.id === runId));
    if (targetThread) {
      for (const r of targetThread.runs) {
        this.markRunDeleted(r.id);
      }
    } else {
      this.markRunDeleted(runId);
    }
    toast('Chat removed.', 'warning');
    const currentRun = this.state.get('currentRun');
    if (currentRun && (currentRun.id === runId || targetThread?.runs.some((r) => r.id === currentRun.id))) {
      this.newRun();
    } else {
      this.renderRunsList();
    }
  }

  renderRunsList() {
    const host = $('#nav-runs');
    if (!host) return;
    const deletedIds = this.getDeletedRunIds();
    const rawList = this.state.get('runs') || [];
    const list = rawList.filter((r) => !deletedIds.includes(r.id));
    const currentRun = this.state.get('currentRun');
    const currentId = currentRun?.id;
    const activeThreadId = this.activeThreadRunId;

    const threads = this.getThreads(list);
    const count = $('#runs-count');
    if (count) count.textContent = String(threads.length);

    if (!threads.length) {
      host.innerHTML = '<div class="empty-hint" style="padding:8px 10px; font-size:11px; color:var(--text-dim);">No chats yet — describe a task to start one.</div>';
      return;
    }
    const titles = this.getCustomTitles();
    host.innerHTML = threads.slice(0, 30).map((thread) => {
      const root = thread.rootRun;
      const latest = thread.latestRun;
      const displayTitle = titles[thread.rootId] || titles[latest.id] || root.task_text;
      const isThreadActive = (currentId && thread.runs.some((r) => r.id === currentId)) ||
        (activeThreadId && thread.runs.some((r) => r.id === activeThreadId));
      const isFail = ['failed', 'cancelled', 'cancel_requested', 'interrupted', 'timeout_failed', 'error'].includes(latest.status);
      const isDone = ['completed', 'success', 'done'].includes(latest.status);
      const statusIcon = isDone
        ? `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="status-icon done"><polyline points="20 6 9 17 4 12"/></svg>`
        : isFail
          ? `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="status-icon fail"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`
          : `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="status-icon chat"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`;
      const turnCount = thread.runs.length;
      const turnBadge = turnCount > 1
        ? `<span class="thread-turn-badge" style="font-size:9.5px; opacity:0.8; margin-left:4px; padding:1px 5px; border-radius:4px; background:rgba(255,255,255,0.08);">${turnCount} msgs</span>`
        : '';

      return `
      <div class="list-item-wrapper ${isThreadActive ? 'active' : ''}" data-run-id="${esc(latest.id)}" data-root-id="${esc(thread.rootId)}">
        <button class="list-item" title="${esc(root.task_text)}">
          <span class="lead-ico">${statusIcon}</span>
          <span class="grow" style="display:flex;align-items:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
            ${esc(truncate(displayTitle, 20))}
            ${turnBadge}
          </span>
          <span class="item-meta">${esc(relativeTime(latest.updated_at || latest.created_at || root.created_at))}</span>
        </button>
        <div class="run-item-actions">
          <button class="run-action-btn rename-btn" title="Rename chat" aria-label="Rename chat">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
          </button>
          <button class="run-action-btn delete-btn" title="Remove chat" aria-label="Remove chat">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
          </button>
        </div>
      </div>`;
    }).join('');
  }

  bindRunsList() {
    const host = $('#nav-runs');
    if (!host) return;
    delegate(host, 'click', '.list-item', (_e, node) => {
      const wrapper = node.closest('.list-item-wrapper');
      if (wrapper) this.selectRun(wrapper.dataset.runId);
    });
    delegate(host, 'click', '.rename-btn', (e, node) => {
      e.stopPropagation();
      const wrapper = node.closest('.list-item-wrapper');
      if (wrapper) this.promptRenameRun(wrapper.dataset.runId);
    });
    delegate(host, 'click', '.delete-btn', (e, node) => {
      e.stopPropagation();
      const wrapper = node.closest('.list-item-wrapper');
      if (wrapper) this.deleteRun(wrapper.dataset.runId);
    });
  }

  bindTopNav() {
    on($('#rename-chat-btn'), 'click', () => {
      const run = this.state.get('currentRun');
      if (run) this.promptRenameRun(run.id);
      else toast('No active chat to rename.', 'warning');
    });

    on($('#delete-chat-btn'), 'click', () => {
      const run = this.state.get('currentRun');
      if (run) this.deleteRun(run.id);
      else this.clearChat(true);
    });

    on($('#new-chat-btn'), 'click', () => {
      this.newRun();
    });

    // Chat export dropdown
    const exportBtn = $('#export-chat-btn');
    const exportMenu = $('#export-menu');
    if (exportBtn && exportMenu) {
      on(exportBtn, 'click', (e) => {
        e.stopPropagation();
        exportMenu.classList.toggle('hidden');
      });
      const mdBtn = $('#export-md-btn');
      if (mdBtn) {
        on(mdBtn, 'click', (e) => {
          e.stopPropagation();
          exportMenu.classList.add('hidden');
          this.exportMarkdown();
        });
      }
      const jsonBtn = $('#export-json-btn');
      if (jsonBtn) {
        on(jsonBtn, 'click', (e) => {
          e.stopPropagation();
          exportMenu.classList.add('hidden');
          this.exportJSON();
        });
      }
      const csvBtn = $('#export-csv-btn');
      if (csvBtn) {
        on(csvBtn, 'click', (e) => {
          e.stopPropagation();
          exportMenu.classList.add('hidden');
          this.exportCSV();
        });
      }
      const pdfBtn = $('#export-pdf-btn');
      if (pdfBtn) {
        on(pdfBtn, 'click', (e) => {
          e.stopPropagation();
          exportMenu.classList.add('hidden');
          this.exportPDF();
        });
      }
      on(document, 'click', (e) => {
        if (!exportMenu.classList.contains('hidden') && !exportMenu.contains(e.target) && !exportBtn.contains(e.target)) {
          exportMenu.classList.add('hidden');
        }
      });
    }

    // View mode segmented buttons
    $$('.view-switch-btn').forEach((btn) => {
      on(btn, 'click', () => {
        const view = btn.dataset.view || 'split';
        this.applyViewMode(view);
      });
    });
  }

  updateHeaderStats() {
    const run = this.state.get('currentRun');
    const detail = this.state.get('currentRunDetail');
    const titleEl = $('#chat-title-text');
    const tokensPill = $('#telemetry-tokens-pill');
    const tokensText = $('#telemetry-tokens-text');
    const attemptPill = $('#telemetry-attempt-pill');
    const attemptText = $('#telemetry-attempt-text');

    if (!run) {
      if (titleEl) titleEl.textContent = truncate(this.draftChatTitle || 'New chat', 22);
      if (tokensPill) tokensPill.style.display = 'none';
      if (attemptPill) attemptPill.style.display = 'none';
      return;
    }

    const titles = this.getCustomTitles();
    const thread = this.getThreads(this.state.get('runs') || [])
      .find((item) => item.runs.some((threadRun) => threadRun.id === run.id));
    const displayTitle = titles[thread?.rootId] || titles[run.id] || thread?.rootRun.task_text || run.task_text;
    if (titleEl) titleEl.textContent = truncate(displayTitle, 22);

    const profile = (this.state.get('budgetProfiles') || []).find((p) => p.id === run.budget_profile_id)
      || this.state.get('defaultBudgetProfile');
    const maxTokens = profile?.max_output_tokens ? (profile.max_output_tokens + (profile.max_input_tokens || 8000)) : 20000;
    const totalUsed = (run.input_tokens_used || 0) + (run.output_tokens_used || 0);
    const remaining = Math.max(0, maxTokens - totalUsed);

    if (tokensPill && tokensText) {
      tokensPill.style.display = totalUsed > 0 ? 'inline-flex' : 'none';
      tokensText.textContent = `${formatTokens(totalUsed)} used (${formatTokens(remaining)} left)`;
      tokensPill.title = `${formatNumber(run.input_tokens_used || 0)} in / ${formatNumber(run.output_tokens_used || 0)} out tokens · ${formatNumber(remaining)} remaining of ${formatNumber(maxTokens)} budget`;
    }

    const attempts = run.result_summary?.attempts || detail?.run_result?.attempts || 1;
    const selfHealed = Boolean(run.result_summary?.self_healed || detail?.run_result?.critic_findings?.self_healed);

    if (attemptPill && attemptText) {
      attemptPill.style.display = 'inline-flex';
      if (selfHealed) {
        attemptText.innerHTML = `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:3px;"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>Healed (att ${attempts})`;
        attemptPill.classList.add('brand');
        attemptPill.title = `Self-healing activated and verified in attempt ${attempts}`;
      } else {
        attemptText.textContent = `${attempts} ${attempts === 1 ? 'attempt' : 'attempts'}`;
        attemptPill.classList.remove('brand');
        attemptPill.title = `Execution completed in ${attempts} attempt(s)`;
      }
    }
  }

  /* ================================================================ composer */
  bindComposer() {
    const input = $('#message');
    const ghost = $('#message-ghost');
    const send = $('#send-btn');

    on(input, 'input', () => { this.autoGrow(input); this.updateGhost(); });
    on(input, 'keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        this.submit();
      }
    });
    on($('#attach-file-btn'), 'click', () => $('#task-file-input')?.click());
    on($('#task-file-input'), 'change', async (e) => {
      const files = Array.from(e.target.files || []);
      e.target.value = '';
      for (const file of files) {
        await this.addAttachedFile(file);
      }
    });

    // Drag-and-drop files onto composer or chat history
    const dropZones = [$('#chat-input-bar'), $('#chat-container')].filter(Boolean);
    dropZones.forEach((zone) => {
      zone.addEventListener('dragover', (e) => {
        e.preventDefault();
        zone.classList.add('drag-over');
      });
      zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
      zone.addEventListener('drop', async (e) => {
        e.preventDefault();
        zone.classList.remove('drag-over');
        const files = Array.from(e.dataTransfer?.files || []);
        for (const file of files) {
          await this.addAttachedFile(file);
        }
      });
    });

    // Output Verbosity Selector (Auto, Concise, Detailed)
    const vBtn = $('#verbosity-btn');
    const vMenu = $('#verbosity-menu');
    const vLabel = $('#verbosity-label');
    const updateVerbosityUI = (mode) => {
      this.detailLevel = mode;
      try { localStorage.setItem('nexora_detail_level', mode); } catch (_) { }
      if (vLabel) {
        vLabel.textContent = mode === 'concise' ? 'Concise' : mode === 'detailed' ? 'Detailed' : 'Auto';
      }
      if (vMenu) {
        vMenu.querySelectorAll('.verbosity-option').forEach((opt) => {
          opt.classList.toggle('active', opt.dataset.verbosity === mode);
        });
      }
    };
    updateVerbosityUI(this.detailLevel);

    if (vBtn && vMenu) {
      on(vBtn, 'click', (e) => {
        e.stopPropagation();
        vMenu.classList.toggle('hidden');
        if (mpMenu) mpMenu.classList.add('hidden');
        if ($('#healing-mode-menu')) $('#healing-mode-menu').classList.add('hidden');
      });
      delegate(vMenu, 'click', '.verbosity-option', (_e, node) => {
        const mode = node.dataset.verbosity || 'auto';
        updateVerbosityUI(mode);
        vMenu.classList.add('hidden');
        toast(`Output verbosity: ${mode === 'auto' ? 'Auto (Balanced)' : mode === 'concise' ? 'Concise (Direct)' : 'Detailed (Deep)'}`, 'info');
      });
      on(document, 'click', (e) => {
        if (!vMenu.classList.contains('hidden') && !vMenu.contains(e.target) && !vBtn.contains(e.target)) {
          vMenu.classList.add('hidden');
        }
      });
    }

    on(send, 'click', () => {
      const run = this.state.get('currentRun');
      if (run && ['queued', 'awaiting_start'].includes(run.status)) this.startRun(run.id);
      else if (this.isRunActive()) this.stopRun();
      else this.submit();
    });

    this.updateGhost(ghost, input);



    // model picker
    const mpBtn = $('#model-picker-btn');
    const mpMenu = $('#model-picker-menu');
    on(mpBtn, 'click', (e) => {
      e.stopPropagation();
      mpMenu.classList.toggle('hidden');
      $('#model-picker-search')?.focus();
    });
    on($('#model-picker-search'), 'input', () => this.renderModelPicker());
    on($('#model-picker-refresh'), 'click', async (e) => {
      e.stopPropagation();
      await this.loadModels();
      this.renderModelPicker();
      toast('Model registry reloaded.', 'success');
    });
    delegate(mpMenu, 'click', '.model-picker-item', (_e, node) => {
      const modelId = node.dataset.modelId;
      if (modelId === 'auto') {
        this.state.set('routingMode', 'auto');
        this.state.set('selectedModelId', null);
      } else if (modelId === 'max') {
        this.state.set('routingMode', 'max');
        this.state.set('selectedModelId', null);
      } else {
        this.state.set('routingMode', 'fixed');
        this.state.set('selectedModelId', modelId || null);
      }
      mpMenu.classList.add('hidden');
      this.renderModelPickerLabel();
      this.renderModelPicker();
      const model = (this.state.get('models') || []).find((item) => item.id === modelId);
      if (modelId === 'auto') toast('Auto routing', 'info');
      else if (modelId === 'max') toast('Max mode: task-aware model selection', 'info');
      else toast(model ? `Model target: ${model.display_name}` : 'Fixed model', 'info');
    });
    on(document, 'click', (e) => {
      if (!mpMenu.classList.contains('hidden') && !mpMenu.contains(e.target) && !mpBtn.contains(e.target)) {
        mpMenu.classList.add('hidden');
      }
    });

    // self-healing mode selector
    this.healingMode = localStorage.getItem('nexora_healing_mode') || 'auto';
    const hmBtn = $('#healing-mode-btn');
    const hmMenu = $('#healing-mode-menu');
    const hmLabel = $('#healing-mode-label');

    const updateHealingUI = (mode) => {
      this.healingMode = mode;
      localStorage.setItem('nexora_healing_mode', mode);
      if (hmLabel) {
        if (mode === 'on') hmLabel.textContent = 'Healing: On';
        else if (mode === 'off') hmLabel.textContent = 'Healing: Off';
        else hmLabel.textContent = 'Auto Healing';
      }
      if (hmMenu) {
        hmMenu.querySelectorAll('.healing-option').forEach((opt) => {
          opt.classList.toggle('active', opt.dataset.healingMode === mode);
        });
      }
    };
    updateHealingUI(this.healingMode);

    if (hmBtn && hmMenu) {
      on(hmBtn, 'click', (e) => {
        e.stopPropagation();
        hmMenu.classList.toggle('hidden');
        if (mpMenu) mpMenu.classList.add('hidden');
      });
      delegate(hmMenu, 'click', '.healing-option', (_e, node) => {
        const mode = node.dataset.healingMode || 'auto';
        updateHealingUI(mode);
        hmMenu.classList.add('hidden');
        toast(`Healing mode: ${mode === 'auto' ? 'Auto (Smart)' : mode === 'on' ? 'Always On' : 'Off (Fast)'}`, 'info');
      });
      on(document, 'click', (e) => {
        if (!hmMenu.classList.contains('hidden') && !hmMenu.contains(e.target) && !hmBtn.contains(e.target)) {
          hmMenu.classList.add('hidden');
        }
      });
    }

    // tools overflow
    const toolsBtn = $('#overflow-plus-btn');
    const toolsMenu = $('#overflow-menu');
    on(toolsBtn, 'click', (e) => {
      e.stopPropagation();
      toolsMenu.classList.toggle('hidden');
      toolsBtn.classList.toggle('expanded', !toolsMenu.classList.contains('hidden'));
      toolsBtn.setAttribute('aria-expanded', String(!toolsMenu.classList.contains('hidden')));
    });
    delegate(toolsMenu, 'click', '.overflow-menu-item', (_e, node) => {
      toolsMenu.classList.add('hidden');
      toolsBtn.classList.remove('expanded');
      const tool = node.dataset.toolAction;
      if (tool === 'new') this.newRun();
      else if (tool === 'toggle-sidebar') shell.collapse();
      else this.openPanel(tool);
    });
    on(document, 'click', (e) => {
      if (!toolsMenu.classList.contains('hidden') && !toolsMenu.contains(e.target) && !toolsBtn.contains(e.target)) {
        toolsMenu.classList.add('hidden');
        toolsBtn.classList.remove('expanded');
      }
    });

    this.renderOverflowMenu();
    this.bindPinnedBar();
  }

  autoGrow(input) {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, window.innerHeight * 0.4)}px`;
  }

  updateGhost(ghost = $('#message-ghost'), input = $('#message')) {
    if (!ghost || !input) return;
    const placeholder = input.placeholder || '';
    const value = input.value;
    if (value.length >= (placeholder.length * 0.6)) {
      ghost.textContent = '';
      return;
    }
    const typed = value.length;
    ghost.innerHTML = `${esc(value)}<span style="opacity:.45">${esc(placeholder.slice(typed))}</span>`;
  }

  /* ---------------------------------------------------------- model picker */
  renderModelPicker() {
    const list = $('#model-picker-list');
    if (!list) return;
    const models = this.state.get('models') || [];
    const query = ($('#model-picker-search')?.value || '').trim().toLowerCase();
    const mode = this.state.get('routingMode') || 'auto';

    const entries = [
      { id: 'auto', name: 'Auto route', meta: 'Router selects the best-fit model for each step (tier-based).', gold: true },
      { id: 'max', name: 'Max', meta: 'Analyzes task and picks the strongest suitable model (tools, reasoning, context).', gold: true },
      ...models.filter((model) => !query || `${model.display_name} ${model.tier} ${model.provider}`.toLowerCase().includes(query))
        .slice()
        .sort((a, b) => Number(isPrimaryProvider(b)) - Number(isPrimaryProvider(a)))
        .map((model) => ({
          id: model.id,
          name: model.display_name,
          meta: [
            model.provider,
            isPrimaryProvider(model) ? null : 'secondary',
            `tier ${model.tier}`,
            `${formatTokens(model.context_capacity)} ctx`,
            model.is_enabled ? null : 'disabled',
          ].filter(Boolean).join(' · '),
          disabled: !model.is_enabled,
        })),
    ].filter((entry) => !query || `${entry.name} ${entry.meta}`.toLowerCase().includes(query));

    if (!entries.length) {
      list.innerHTML = '<div class="cmdk-empty">No models match.</div>';
      return;
    }

    const selected = this.state.get('selectedModelId');
    let activeKey;
    if (mode === 'fixed') activeKey = selected;
    else if (mode === 'max') activeKey = 'max';
    else activeKey = selected || 'auto';

    // Secondary providers are fixed targets; auto routing stays on Nebius.
    const secondary = models.filter((m) => !isPrimaryProvider(m) && m.is_enabled);
    const secondaryNote = mode === 'auto' && secondary.length
      ? `<div class="cmdk-empty">${secondary.length} secondary model${secondary.length > 1 ? 's' : ''} `
      + `(${esc([...new Set(secondary.map((m) => m.provider))].join(', '))}) — selecting one uses fixed routing.</div>`
      : '';

    list.innerHTML = entries.map((e) => `
      <button class="model-picker-item ${e.id === activeKey ? 'selected' : ''}" data-model-id="${esc(e.id)}" ${e.disabled ? 'disabled' : ''}>
        <span class="mp-name" ${e.gold ? 'style="color:var(--gold)"' : ''}>${esc(e.name)}</span>
        <span class="mp-meta">${esc(e.meta)}</span>
      </button>`).join('') + secondaryNote;
  }

  renderModelPickerLabel() {
    const label = $('#model-picker-label');
    if (!label) return;
    const mode = this.state.get('routingMode') || 'auto';
    const models = this.state.get('models') || [];
    const id = this.state.get('selectedModelId');
    const model = models.find((m) => m.id === id);
    if (mode === 'auto') {
      label.textContent = 'Auto route';
      label.title = `Router selects the best-fit ${PRIMARY_PROVIDER} model`;
      return;
    }
    if (mode === 'max') {
      label.textContent = 'Max';
      label.title = 'Task-aware: analyzes request and selects strongest suitable model';
      return;
    }
    label.textContent = model ? model.display_name : 'Pick model';
    label.title = model
      ? `${model.model_id} · ${model.provider || PRIMARY_PROVIDER}${isPrimaryProvider(model) ? '' : ' (secondary)'}`
      : 'No model selected';
  }

  /* ---------------------------------------------------------- tools menus */
  renderOverflowMenu() {
    const menu = $('#overflow-menu');
    if (!menu) return;
    const items = [
      { tool: 'runs', icon: ICONS.runs, label: 'Runs' },
      { tool: 'plan', icon: ICONS.plan, label: 'Execution plan' },
      { tool: 'policy', icon: ICONS.policy, label: 'Policy decisions', gold: true },
      { tool: 'security', icon: ICONS.security, label: 'Security review', gold: true },
      { tool: 'approvals', icon: ICONS.approvals, label: 'Approvals', gold: true },
      { tool: 'patch', icon: ICONS.patch, label: 'Patch diff' },
      { tool: 'tests', icon: ICONS.tests, label: 'Validation' },
      { tool: 'evidence', icon: ICONS.evidence, label: 'Evidence & metrics' },
      { tool: 'audit', icon: ICONS.audit, label: 'Audit trail' },
      { sep: true },
      { tool: 'new', icon: ICONS.new, label: 'New run', hint: 'Ctrl+N' },
      { tool: 'toggle-sidebar', icon: ICONS.toggle, label: 'Toggle sidebar', hint: 'Ctrl+B' },
    ];
    menu.innerHTML = items.map((i) => {
      if (i.sep) return '<div class="overflow-menu-sep"></div>';
      const pending = i.tool === 'approvals' ? this.pendingApprovalCount() : 0;
      return `
        <button class="overflow-menu-item" data-tool-action="${i.tool}">
          <span class="ico" ${i.gold ? 'style="color:var(--gold)"' : ''}>${i.icon}</span>
          <span class="grow">${esc(i.label)}</span>
          ${pending ? `<span class="tag tag-pending">${pending}</span>` : ''}
          ${i.hint ? `<span class="kbd-hint">${esc(i.hint)}</span>` : ''}
        </button>`;
    }).join('');
  }

  renderPinnedBar() {
    const bar = $('#pinned-tools-bar');
    if (!bar) return;
    if (!this.pinned) this.pinned = new Set();
    const pinned = ['policy', 'security', 'approvals'];
    bar.innerHTML = pinned.map((id) => {
      const panel = PANEL_MAP[id];
      const on = this.pinned.has(id);
      return `<button class="pinned-chip ${on ? 'on' : ''}" data-pin="${id}" title="Pin ${esc(panel?.label || id)}">${esc(panel?.icon || '◆')} ${esc(panel?.label || id)}</button>`;
    }).join('');
  }

  bindPinnedBar() {
    const bar = $('#pinned-tools-bar');
    if (!bar) return;
    delegate(bar, 'click', '.pinned-chip', (_e, node) => {
      const id = node.dataset.pin;
      if (!this.pinned) this.pinned = new Set();
      if (this.pinned.has(id)) this.pinned.delete(id);
      else this.pinned.add(id);
      this.renderPinnedBar();
    });
  }

  /* ================================================================ modals */
  setupModals() {
    const root = $('#tool-modal');
    modals.register('tool', root, {
      // `onOpen` fires the first time the modal is shown, `onRefresh` on every
      // later `open()` while it is already up. Both must honour the requested
      // panel: ModalManager.open() dispatches to onRefresh (not onOpen) once the
      // modal is open, so without it switching panels from the icon rail, the
      // keyboard shortcuts or the command palette is a silent no-op.
      onOpen: (id) => this.renderToolModal(id),
      onRefresh: (id) => this.renderToolModal(id),
    });
    modals.bindGlobalKeys();

    on($('#tool-modal-close'), 'click', () => modals.close('tool'));
    on($('#tool-modal-prev'), 'click', () => this.cyclePanel(-1));
    on($('#tool-modal-next'), 'click', () => this.cyclePanel(1));
    delegate($('#tool-modal-tabs'), 'click', '.admin-tab', (_e, node) => {
      this.renderToolModal(node.dataset.tab);
    });
    delegate($('#tool-modal-footer'), 'click', '[data-modal-close]', () => modals.close('tool'));
  }

  panelOrder() {
    return ['runs'];
  }

  cyclePanel(delta) {
    const order = this.panelOrder();
    const idx = order.indexOf(this.activePanel);
    const next = order[(idx + delta + order.length) % order.length];
    this.renderToolModal(next);
  }

  openPanel(id) {
    this.activePanel = id;
    setActivePanel(PANEL_MAP[id] ? id : null);
    modals.open('tool', id);
    if (PANEL_MAP[id]) setActivePanel(id);
  }

  viewModel() {
    const profileId = this.state.get('selectedBudgetProfileId');
    const profiles = this.state.get('budgetProfiles') || [];
    return {
      state: this.state,
      runs: this.state.get('runs') || [],
      currentRun: this.state.get('currentRun'),
      currentRunDetail: this.state.get('currentRunDetail'),
      selectedProfile: profiles.find((p) => p.id === profileId) || this.state.get('defaultBudgetProfile'),
      workspaces: this.state.get('workspaces') || [],
      models: this.state.get('models') || [],
      packageRouting: this.state.get('packageRouting'),
      health: this.health,
      apiBase: this.apiBase,
      pollMs: this.pollMs,
      autoStart: this.autoStart,
      showTimestamps: this.showTimestamps,
      compactFeed: this.compactFeed,
      actions: {
        selectRun: (id) => this.selectRun(id),
        decideApproval: (id, approve) => this.decideApproval(id, approve),
        refresh: () => this.bootstrapData(),
        reloadRuns: () => this.loadRuns(),
        clearChat: () => this.clearChat(),
        reloadPackageRouting: async () => {
          await this.loadPackageRouting();
          this.renderToolModal();
        },
        completeViaPackage: (payload) => window.NexoraApi.packages.complete(payload),
      },
    };
  }

  renderToolModal(forceId = null) {
    const id = forceId || this.activePanel;
    this.activePanel = id;
    const body = $('#tool-modal-body');
    const tabs = $('#tool-modal-tabs');
    const title = $('#tool-modal-title');
    const subtitle = $('#tool-modal-subtitle');
    if (!body) return;

    // tabs
    tabs.innerHTML = this.panelOrder().map((pid) => {
      const panel = PANEL_MAP[pid];
      if (!panel) return '';
      return `<button class="admin-tab ${pid === id ? 'active' : ''}" data-tab="${pid}">${panel.icon} <span>${esc(panel.label)}</span></button>`;
    }).join('');

    const panel = PANEL_MAP[id];
    title.innerHTML = panel
      ? `<span>${panel.icon}</span> ${esc(panel.label)}`
      : '<span>◆</span> Runs';
    const run = this.state.get('currentRun');
    subtitle.textContent = run ? `${truncate(run.task_text, 46)} · ${run.status}` : 'no active run';

    if (panel) {
      const ctx = this.viewModel();
      body.innerHTML = panel.render(ctx);
      panel.bind?.(body, ctx);
    }

    $('#tool-modal-footer').innerHTML = '';
    if (panel && (id === 'runs')) {
      $('#tool-modal-footer').innerHTML = '<button class="btn btn-sm" data-modal-close>Close</button>';
    }

    setActivePanel(PANEL_MAP[id] ? id : null);
    body.scrollTop = 0;
  }

  setPreference(key, value) {
    if (key === 'pollMs') this.pollMs = value;
    if (key === 'autoStart') this.autoStart = value;
    if (key === 'showTimestamps') this.showTimestamps = value;
    if (key === 'compactFeed') {
      this.compactFeed = value;
      this.historyEl.classList.toggle('compact-feed', value);
    }
    this.persistPrefs();
    if (key === 'pollMs' && this.isRunActive()) {
      this.restartPolling(this.state.get('currentRun').id);
    }
  }

  async runSettingsAction(action) {
    if (action === 'refresh') {
      await this.bootstrapData();
      this.renderAll();
      toast('Reloaded models and profiles.', 'success');
    } else if (action === 'reload-runs') {
      await this.loadRuns();
      this.renderRunsList();
      this.renderToolModal();
      toast('Runs reloaded.', 'success');
    } else if (action === 'clear-chat') {
      this.clearChat();
      toast('Chat transcript cleared.', 'info');
    }
  }

  applyThemeClasses() {
    document.body.classList.toggle('hc', !!theme.settings.highContrast);
  }

  /* ================================================================ rail */
  bindRailAndTools() {
    delegate(document, 'click', '[data-tool]', (_e, node) => {
      this.openPanel(node.dataset.tool);
    });
    this.bindRunsList();
  }

  bindGlobalKeys() {
    on(document, 'keydown', (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.target.matches('input, textarea')) return;
      const map = { 1: 'runs' };
      if (map[e.key]) {
        e.preventDefault();
        this.openPanel(map[e.key]);

      } else if (e.key.toLowerCase() === 'n') {
        e.preventDefault();
        this.newRun();
      }
    });
  }

  displayRunTitle(run) {
    const titles = this.getCustomTitles();
    const thread = this.getThreads([run]).find((t) => t.runs.some((x) => x.id === run.id));
    const rootId = thread?.rootId || run.id;
    const rootRun = thread?.rootRun || run;
    const title = titles[rootId] || titles[run.id] || rootRun.task_text || run.task_text;
    return title ? String(title) : `Chat ${String(run.id || '').slice(0, 8)}`;
  }

  registerCommands(runsOverride) {
    const runs = runsOverride || this.state.get('runs') || [];
    const titles = this.getCustomTitles();
    const chatCommands = runs.map((r) => {
      const thread = this.getThreads([...runs, ...(this.state.get('runs') || [])])
        .find((item) => item.runs.some((threadRun) => threadRun.id === r.id));
      const rootId = thread?.rootId || r.id;
      const title = titles[rootId] || titles[r.id] || thread?.rootRun.task_text || r.task_text || `Chat ${r.id.slice(0, 8)}`;
      const historyText = Array.isArray(r.conversation_history)
        ? r.conversation_history.map((turn) => turn.content || '').join(' ')
        : '';
      return {
        label: `Jump to: ${truncate(title, 36)}`,
        group: 'chat',
        keywords: `${r.task_text || ''} ${historyText} ${r.id}`,
        icon: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`,
        hint: relativeTime(r.created_at),
        run: () => this.selectRun(r.id),
      };
    });

    shell.registerCommands([
      { label: 'New run', group: 'action', icon: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>`, hint: 'Ctrl+N', run: () => this.newRun() },
      { label: 'Toggle sidebar', group: 'action', icon: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>`, hint: 'Ctrl+B', run: () => shell.collapse() },
      ...chatCommands,
      ...this.panelOrder().map((id) => {
        const panel = PANEL_MAP[id];
        return {
          label: `Open ${panel ? panel.label : id}`,
          group: 'panel',
          icon: panel ? panel.icon : '◆',
          run: () => this.openPanel(id),
        };
      }),
      { label: 'Reload model registry', group: 'data', icon: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`, run: async () => { await this.loadModels(); this.renderModelPickerLabel(); toast('Models reloaded.', 'success'); } },
      { label: 'Reload runs', group: 'data', icon: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`, run: async () => { await this.loadRuns(); this.renderRunsList(); toast('Runs reloaded.', 'success'); } },
      { label: 'Cancel active run', group: 'action', icon: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/></svg>`, run: () => this.stopRun() },
    ]);
  }

  /* ================================================================ ui helpers */
  formatFileSize(bytes) {
    if (!bytes || bytes < 1024) return `${bytes || 0} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  getFileIcon(filename) {
    const ext = (filename || '').split('.').pop().toLowerCase();
    if (['zip', 'rar', 'tar', 'gz', 'tgz'].includes(ext)) {
      return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>`;
    }
    if (['pdf'].includes(ext)) {
      return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`;
    }
    if (['doc', 'docx'].includes(ext)) {
      return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`;
    }
    if (['json', 'jsonl', 'csv', 'tsv', 'yaml', 'yml', 'xml', 'toml'].includes(ext)) {
      return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>`;
    }
    if (['py', 'js', 'ts', 'jsx', 'tsx', 'html', 'css', 'scss', 'c', 'h', 'cpp', 'hpp', 'cc', 'cs', 'go', 'rs', 'java', 'kt', 'scala', 'rb', 'php', 'sh', 'bash', 'zsh', 'ps1', 'bat', 'sql', 'r', 'swift', 'dart', 'lua'].includes(ext)) {
      return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>`;
    }
    return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>`;
  }

  renderAttachedFiles() {
    const bar = $('#attached-files-bar');
    if (!bar) return;
    if (!this.attachedFiles.length) {
      bar.innerHTML = '';
      bar.classList.add('hidden');
      return;
    }
    bar.classList.remove('hidden');
    bar.innerHTML = this.attachedFiles.map((f, i) => `
      <span class="attached-file-pill" title="${esc(f.name)} (${this.formatFileSize(f.size)})">
        <span class="pill-icon">${this.getFileIcon(f.name)}</span>
        <span class="pill-name">${esc(f.name)}</span>
        <span class="pill-size">(${this.formatFileSize(f.size)})</span>
        <button class="pill-del-btn" data-del-file="${i}" title="Remove file" aria-label="Remove file">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </span>
    `).join('');

    bar.querySelectorAll('[data-del-file]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = Number(btn.dataset.delFile);
        this.attachedFiles.splice(idx, 1);
        this.renderAttachedFiles();
      });
    });
  }

  async addAttachedFile(file) {
    if (!file) return;
    const MAX_SIZE = 10 * 1024 * 1024; // 10 MB Limit
    if (file.size > MAX_SIZE) {
      const sizeMb = (file.size / (1024 * 1024)).toFixed(1);
      return toast(`File "${file.name}" exceeds maximum allowed limit of 10 MB (${sizeMb} MB).`, 'error');
    }
    if (this.attachedFiles.some((f) => f.name === file.name && f.size === file.size)) {
      return toast(`File "${file.name}" is already attached.`, 'info');
    }

    this.attachedFiles.push({
      file,
      name: file.name,
      size: file.size,
      type: file.type || '',
    });
    this.renderAttachedFiles();
    toast(`Attached ${file.name} (${this.formatFileSize(file.size)})`, 'info');
  }

  exportMarkdown() {
    if (!this.messages.length) return toast('No conversation to export.', 'warning');
    const header = `# Nexora Chat Export\n_Exported on ${new Date().toLocaleString()} · ${this.messages.length} messages_\n\n---\n\n`;
    const body = this.messages.map((m) => {
      const role = m.role === 'user' ? '### 👤 User' : '### 🤖 Nexora AI';
      const time = m.at ? `*(${formatDateTime(m.at)})*` : '';
      return `${role} ${time}\n\n${(m.text || '').trim()}\n`;
    }).join('\n---\n\n');
    const mdContent = header + body;
    const blob = new Blob([mdContent], { type: 'text/markdown;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nexora-chat-${Date.now()}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast('Exported conversation as Markdown (.md).', 'success');
  }

  exportJSON() {
    if (!this.messages.length) return toast('No conversation to export.', 'warning');
    const data = {
      app: 'Nexora AI Coding Agent',
      exported_at: new Date().toISOString(),
      message_count: this.messages.length,
      messages: this.messages.map((m) => ({
        id: m.id,
        role: m.role,
        role_label: m.roleLabel || (m.role === 'user' ? 'User' : 'Nexora AI'),
        timestamp: m.at,
        content: m.text,
        tokens: m.tokens || 0,
        model: m.model || 'auto',
      })),
    };
    const jsonContent = JSON.stringify(data, null, 2);
    const blob = new Blob([jsonContent], { type: 'application/json;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nexora-chat-${Date.now()}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast('Exported conversation as JSON (.json).', 'success');
  }

  exportCSV() {
    if (!this.messages.length) return toast('No conversation to export.', 'warning');
    const headers = ['Timestamp', 'Role', 'Content', 'Tokens', 'Model'];
    const rows = this.messages.map((m) => {
      const time = m.at || new Date().toISOString();
      const role = m.role === 'user' ? 'User' : 'Nexora AI';
      const content = (m.text || '').replace(/"/g, '""');
      const tokens = (m.tokens || 0);
      const model = (m.model || 'auto');
      return `"${time}","${role}","${content}","${tokens}","${model}"`;
    });
    const csvContent = [headers.join(','), ...rows].join('\r\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nexora-chat-${Date.now()}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast('Exported conversation as CSV.', 'success');
  }

  exportPDF() {
    if (!this.messages.length) return toast('No conversation to export.', 'warning');
    const printWin = window.open('', '_blank', 'width=900,height=800');
    if (!printWin) return toast('Pop-up blocked. Please allow pop-ups to print.', 'warning');

    const renderedMessages = this.messages.map((m) => {
      const role = m.role === 'user' ? 'User Prompt' : 'Nexora Assistant';
      const roleClass = m.role === 'user' ? 'user' : 'ai';
      const time = m.at ? formatDateTime(m.at) : '';
      return `
        <div class="msg ${roleClass}">
          <div class="msg-header">
            <strong>${esc(role)}</strong>
            <span class="msg-time">${esc(time)}</span>
          </div>
          <div class="msg-body">${renderMarkdown(m.text || '')}</div>
        </div>
      `;
    }).join('');

    printWin.document.write(`
      <!DOCTYPE html>
      <html>
      <head>
        <title>Nexora Chat Export - ${new Date().toLocaleDateString()}</title>
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
        <style>
          body { font-family: 'Inter', system-ui, sans-serif; font-size: 13px; color: #1e293b; margin: 0; padding: 40px; }
          .export-header { border-bottom: 2px solid #6366f1; padding-bottom: 16px; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; }
          .logo { font-size: 20px; font-weight: 700; color: #6366f1; }
          .meta { font-size: 11px; color: #64748b; }
          .msg { margin-bottom: 20px; padding: 14px 18px; border-radius: 8px; border: 1px solid #e2e8f0; break-inside: avoid; }
          .msg.user { background: #f8fafc; border-left: 4px solid #6366f1; }
          .msg.ai { background: #ffffff; border-left: 4px solid #10b981; }
          .msg-header { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 8px; color: #475569; }
          .msg-body { line-height: 1.6; }
          pre, code { font-family: 'JetBrains Mono', monospace; font-size: 12px; }
          pre { background: #f1f5f9; padding: 12px; border-radius: 6px; overflow-x: auto; border: 1px solid #e2e8f0; }
          @media print {
            body { padding: 0; }
          }
        </style>
      </head>
      <body>
        <div class="export-header">
          <div class="logo">Nexora AI Coding Agent</div>
          <div class="meta">Exported on ${new Date().toLocaleString()} · ${this.messages.length} messages</div>
        </div>
        <div class="chat-flow">${renderedMessages}</div>
        <script>
          window.addEventListener('DOMContentLoaded', () => {
            setTimeout(() => { window.print(); }, 400);
          });
        </script>
      </body>
      </html>
    `);
    printWin.document.close();
  }

  applyViewMode(mode = 'split') {
    this.activeView = mode;
    document.body.classList.remove('view-split', 'view-chat', 'view-project');
    document.body.classList.add(`view-${mode}`);
    try { localStorage.setItem('nexora_active_view', mode); } catch (_) { }

    $$('.view-switch-btn').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.view === mode);
    });
    this.scrollToBottom();
  }

  initResizers() {
    const sidebar = $('#sidebar');
    const mainArea = $('#main-area');
    const resizerSidebar = $('#resizer-sidebar');
    const resizerEditor = $('#resizer-editor');

    // Dynamically adjust top-nav icons based on main-area width (via ResizeObserver)
    if (mainArea && typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver((entries) => {
        for (const entry of entries) {
          const w = entry.contentRect.width;
          mainArea.classList.toggle('nav-compact', w < 580);
          mainArea.classList.toggle('nav-mini', w < 400);
        }
      });
      ro.observe(mainArea);
    }

    // Restore saved widths
    const savedSidebarWidth = localStorage.getItem('nexora_sidebar_width');
    if (savedSidebarWidth && sidebar) {
      sidebar.style.width = `${Math.min(480, Math.max(180, Number(savedSidebarWidth)))}px`;
    }
    const savedMainAreaWidth = localStorage.getItem('nexora_main_area_width') || localStorage.getItem('nexora_resizer_chat_width');
    if (savedMainAreaWidth && !isNaN(Number(savedMainAreaWidth)) && mainArea) {
      const w = Math.min(850, Math.max(340, Number(savedMainAreaWidth)));
      mainArea.style.width = `${w}px`;
      mainArea.classList.toggle('nav-compact', w < 580);
      mainArea.classList.toggle('nav-mini', w < 400);
    }

    // Sidebar resizer drag
    if (resizerSidebar && sidebar) {
      let isDragging = false;
      resizerSidebar.addEventListener('mousedown', () => {
        isDragging = true;
        resizerSidebar.classList.add('is-dragging');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';

        const onMouseMove = (moveEvt) => {
          if (!isDragging) return;
          const newWidth = Math.min(480, Math.max(180, moveEvt.clientX));
          sidebar.style.width = `${newWidth}px`;
        };
        const onMouseUp = () => {
          if (!isDragging) return;
          isDragging = false;
          resizerSidebar.classList.remove('is-dragging');
          document.body.style.cursor = '';
          document.body.style.userSelect = '';
          window.removeEventListener('mousemove', onMouseMove);
          window.removeEventListener('mouseup', onMouseUp);
          try { localStorage.setItem('nexora_sidebar_width', parseInt(sidebar.style.width, 10)); } catch (_) { }
        };
        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', onMouseUp);
      });
    }

    // Editor/Chat resizer drag
    if (resizerEditor && mainArea) {
      let isDragging = false;
      resizerEditor.addEventListener('mousedown', () => {
        isDragging = true;
        resizerEditor.classList.add('is-dragging');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';

        const onMouseMove = (moveEvt) => {
          if (!isDragging) return;
          const newWidth = Math.min(850, Math.max(340, window.innerWidth - moveEvt.clientX));
          mainArea.style.width = `${newWidth}px`;
          mainArea.classList.toggle('nav-compact', newWidth < 580);
          mainArea.classList.toggle('nav-mini', newWidth < 400);
        };
        const onMouseUp = () => {
          if (!isDragging) return;
          isDragging = false;
          resizerEditor.classList.remove('is-dragging');
          document.body.style.cursor = '';
          document.body.style.userSelect = '';
          window.removeEventListener('mousemove', onMouseMove);
          window.removeEventListener('mouseup', onMouseUp);
          try {
            localStorage.setItem('nexora_main_area_width', parseInt(mainArea.style.width, 10));
            localStorage.setItem('nexora_resizer_chat_width', parseInt(mainArea.style.width, 10));
          } catch (_) { }
        };
        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', onMouseUp);
      });
    }
  }

  initCustomTheme() {
    const modal = $('#theme-font-modal');
    const openBtn = $('#theme-settings-btn');
    const closeBtn = $('#theme-modal-close');

    // Appearance Font Stack Mappings
    const UI_FONT_MAP = {
      'Anthropic Sans': `'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`,
      'System': `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`,
      'OpenDyslexic': `'OpenDyslexic', 'Atkinson Hyperlegible', sans-serif`,
      'Inter': `'Inter', system-ui, sans-serif`,
      'Outfit': `'Outfit', sans-serif`,
      'Geist': `'Geist', -apple-system, BlinkMacSystemFont, sans-serif`,
      'Roboto': `'Roboto', sans-serif`,
    };

    const MONO_FONT_MAP = {
      'JetBrains Mono': `'JetBrains Mono', monospace`,
      'Fira Code': `'Fira Code', monospace`,
      'Source Code Pro': `'Source Code Pro', monospace`,
      'Consolas': `'Consolas', 'Courier New', monospace`,
    };

    const CHAT_SIZE_MAP = {
      'small': '11.5px',
      'medium': '13px',
      'large': '15px',
    };

    const CHAT_WIDTH_MAP = {
      'narrow': '680px',
      'medium': '860px',
      'wide': '1200px',
    };

    // Helper: Hex to HSL & HSL to Hex
    const hexToHsl = (hex) => {
      let c = hex.replace('#', '');
      if (c.length === 3) c = c.split('').map((x) => x + x).join('');
      const num = parseInt(c, 16);
      let r = (num >> 16) / 255, g = ((num >> 8) & 255) / 255, b = (num & 255) / 255;
      const max = Math.max(r, g, b), min = Math.min(r, g, b);
      let h = 0, s = 0, l = (max + min) / 2;
      if (max !== min) {
        const d = max - min;
        s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
        switch (max) {
          case r: h = (g - b) / d + (g < b ? 6 : 0); break;
          case g: h = (b - r) / d + 2; break;
          case b: h = (r - g) / d + 4; break;
        }
        h = Math.round(h * 60);
      }
      return { h, s: Math.round(s * 100), l: Math.round(l * 100) };
    };

    const hslToHex = (h, s, l) => {
      s /= 100;
      l /= 100;
      const a = s * Math.min(l, 1 - l);
      const f = (n) => {
        const k = (n + h / 30) % 12;
        const color = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
        return Math.round(255 * color).toString(16).padStart(2, '0');
      };
      return `#${f(0)}${f(8)}${f(4)}`;
    };

    // Custom Theme State
    let customTheme = {
      hue: 200,
      sat: 40,
      light: 59,
      mode: 'dark',
      name: 'Midnight Slate',
    };

    try {
      const savedTheme = localStorage.getItem('nexora_custom_theme');
      if (savedTheme) Object.assign(customTheme, JSON.parse(savedTheme));
      const savedLightMode = localStorage.getItem('nexora_light_mode');
      if (savedLightMode === 'true') {
        customTheme.mode = 'light';
      }
    } catch (_) { }

    // Apply Custom Theme Engine to Document Root
    const applyThemeEngine = (themeState) => {
      const { hue, sat, light, mode } = themeState;
      const root = document.documentElement;

      // Handle Light/Dark Mode
      if (mode === 'light') {
        root.classList.add('light');
        root.dataset.palette = 'light';
        root.style.setProperty('--bg-main', `hsl(${hue}, 20%, 98%)`);
        root.style.setProperty('--bg-sidebar', `#ffffff`);
        root.style.setProperty('--bg-input', `#ffffff`);
        root.style.setProperty('--border', `hsl(${hue}, 18%, 89%)`);
        root.style.setProperty('--border-light', `hsl(${hue}, 22%, 82%)`);
        root.style.setProperty('--text-light', `#0f172a`);
        root.style.setProperty('--text-dim', `hsl(${hue}, 15%, 45%)`);
        root.style.setProperty('--brand', `hsl(${hue}, ${Math.max(68, sat)}%, 44%)`);
        root.style.setProperty('--brand-glow', `hsla(${hue}, ${sat}%, 44%, 0.25)`);
      } else {
        root.classList.remove('light');
        delete root.dataset.palette;
        // Midnight Slate Dark Palette (#06141B, #11212D, #253745, #4A5C6A, #9BA8AB, #CCD0CF)
        root.style.setProperty('--bg-sidebar', '#06141B');
        root.style.setProperty('--bg-main', '#11212D');
        root.style.setProperty('--bg-input', '#253745');
        root.style.setProperty('--border', '#253745');
        root.style.setProperty('--border-light', '#4A5C6A');
        root.style.setProperty('--text-dim', '#9BA8AB');
        root.style.setProperty('--text-light', '#CCD0CF');
        root.style.setProperty('--brand', `hsl(${hue}, ${sat}%, ${light}%)`);
        root.style.setProperty('--brand-glow', `hsla(${hue}, ${sat}%, ${light}%, 0.35)`);
      }

      // Update Preview Canvas Elements
      const hex = hslToHex(hue, sat, mode === 'light' ? 44 : light);
      const canvas = $('#custom-theme-canvas');
      const innerSwatch = $('#canvas-inner-swatch');
      const heroRing = $('#canvas-hero-ring');
      const canvasDot = $('#canvas-dot');
      const colorName = $('#canvas-color-name');
      const hexDisplay = $('#canvas-hex-display');
      const hueSlider = $('#wavy-hue-slider');
      const nativeColor = $('#custom-native-color');
      const rotaryDial = $('#hue-rotary-dial');

      if (innerSwatch) innerSwatch.style.background = hex;
      if (heroRing) heroRing.style.boxShadow = `0 6px 20px rgba(0,0,0,0.4), 0 0 16px ${hex}66`;
      if (canvasDot) canvasDot.style.background = hex;
      if (colorName) colorName.textContent = themeState.name || 'Midnight Slate';
      if (hexDisplay) hexDisplay.textContent = hex;
      if (hueSlider) hueSlider.value = String(hue);
      if (nativeColor) nativeColor.value = hex;
      if (rotaryDial) rotaryDial.style.transform = `rotate(${hue}deg)`;
      if (canvas) {
        if (mode === 'light') {
          canvas.style.backgroundColor = `hsl(${hue}, 25%, 97%)`;
        } else {
          canvas.style.backgroundColor = '#06141B';
        }
      }

      // Sync active state on mode buttons
      $$('.mode-pill-btn').forEach((b) => {
        b.classList.toggle('active', b.dataset.themeMode === mode);
      });

      // Save to localStorage
      try {
        localStorage.setItem('nexora_custom_theme', JSON.stringify({ hue, sat, light, mode, name: themeState.name }));
        localStorage.setItem('nexora_light_mode', mode === 'light' ? 'true' : 'false');
      } catch (_) { }
    };

    // Restore Appearance Settings
    const restoreAppearanceSettings = () => {
      // 1. Interface Font
      const savedUiFont = localStorage.getItem('nexora_font_ui') || 'Anthropic Sans';
      const fontUiVal = UI_FONT_MAP[savedUiFont] || `'${savedUiFont}', system-ui, sans-serif`;
      document.documentElement.style.setProperty('--font-ui', fontUiVal);
      document.body.style.fontFamily = fontUiVal;
      $$('[data-ui-font]').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.uiFont === savedUiFont);
      });

      // 2. Code Font
      const savedMonoFont = localStorage.getItem('nexora_font_mono') || 'JetBrains Mono';
      const fontMonoVal = MONO_FONT_MAP[savedMonoFont] || `'${savedMonoFont}', monospace`;
      document.documentElement.style.setProperty('--font-mono', fontMonoVal);
      $$('[data-mono-font]').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.monoFont === savedMonoFont);
      });

      // 3. Transcript Text Size
      const savedChatSize = localStorage.getItem('nexora_chat_size') || 'medium';
      const sizeVal = CHAT_SIZE_MAP[savedChatSize] || '13px';
      document.documentElement.style.setProperty('--chat-font-size', sizeVal);
      $$('[data-chat-size]').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.chatSize === savedChatSize);
      });

      // 4. Transcript Width
      const savedChatWidth = localStorage.getItem('nexora_chat_width') || 'medium';
      const widthVal = CHAT_WIDTH_MAP[savedChatWidth] || '860px';
      document.documentElement.style.setProperty('--chat-max-width', widthVal);
      const chatHist = $('#chat-history');
      if (chatHist) chatHist.style.maxWidth = widthVal;
      const chatInputBar = $('#chat-input-bar');
      if (chatInputBar) chatInputBar.style.maxWidth = widthVal;
      $$('[data-chat-width]').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.chatWidth === savedChatWidth);
      });

      // 5. Default Transcript View
      const savedTranscriptView = localStorage.getItem('nexora_transcript_view') || 'normal';
      $$('[data-transcript-view]').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.transcriptView === savedTranscriptView);
      });
      if (savedTranscriptView === 'thinking') {
        $$('.thought-accordion').forEach((el) => { el.open = true; });
      }
    };

    // Apply restored settings initially
    restoreAppearanceSettings();
    applyThemeEngine(customTheme);

    // Event Bindings
    if (openBtn && modal) {
      openBtn.addEventListener('click', () => {
        modal.classList.remove('hidden');
        applyThemeEngine(customTheme);
      });
      closeBtn?.addEventListener('click', () => modal.classList.add('hidden'));
      modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.classList.add('hidden');
      });

      // Modal Tab Switching: Appearance vs Custom Theme
      $$('.settings-tab-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
          const tab = btn.dataset.settingsTab;
          $$('.settings-tab-btn').forEach((b) => b.classList.remove('active'));
          btn.classList.add('active');

          const paneApp = $('#pane-appearance');
          const paneTheme = $('#pane-custom-theme');
          if (paneApp && paneTheme) {
            paneApp.classList.toggle('hidden', tab !== 'appearance');
            paneTheme.classList.toggle('hidden', tab !== 'custom-theme');
          }
        });
      });

      // Appearance: Interface Font Picker
      $$('[data-ui-font]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const font = btn.dataset.uiFont;
          $$('[data-ui-font]').forEach((b) => b.classList.remove('active'));
          btn.classList.add('active');
          const val = UI_FONT_MAP[font] || `'${font}', system-ui, sans-serif`;
          document.documentElement.style.setProperty('--font-ui', val);
          document.body.style.fontFamily = val;
          try { localStorage.setItem('nexora_font_ui', font); } catch (_) { }
          toast(`Interface font: ${font}`, 'info');
        });
      });

      // Appearance: Code Font Picker
      $$('[data-mono-font]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const font = btn.dataset.monoFont;
          $$('[data-mono-font]').forEach((b) => b.classList.remove('active'));
          btn.classList.add('active');
          const val = MONO_FONT_MAP[font] || `'${font}', monospace`;
          document.documentElement.style.setProperty('--font-mono', val);
          try { localStorage.setItem('nexora_font_mono', font); } catch (_) { }
          toast(`Code font: ${font}`, 'info');
        });
      });

      // Appearance: Transcript Text Size
      $$('[data-chat-size]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const size = btn.dataset.chatSize;
          $$('[data-chat-size]').forEach((b) => b.classList.remove('active'));
          btn.classList.add('active');
          const val = CHAT_SIZE_MAP[size] || '13px';
          document.documentElement.style.setProperty('--chat-font-size', val);
          try { localStorage.setItem('nexora_chat_size', size); } catch (_) { }
          toast(`Text scale: ${size}`, 'info');
        });
      });

      // Appearance: Transcript Width
      $$('[data-chat-width]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const width = btn.dataset.chatWidth;
          $$('[data-chat-width]').forEach((b) => b.classList.remove('active'));
          btn.classList.add('active');
          const val = CHAT_WIDTH_MAP[width] || '860px';
          document.documentElement.style.setProperty('--chat-max-width', val);
          const chatHist = $('#chat-history');
          if (chatHist) chatHist.style.maxWidth = val;
          const chatInputBar = $('#chat-input-bar');
          if (chatInputBar) chatInputBar.style.maxWidth = val;
          try { localStorage.setItem('nexora_chat_width', width); } catch (_) { }
          toast(`Transcript width: ${width}`, 'info');
        });
      });

      // Appearance: Default Transcript View
      $$('[data-transcript-view]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const view = btn.dataset.transcriptView;
          $$('[data-transcript-view]').forEach((b) => b.classList.remove('active'));
          btn.classList.add('active');
          try { localStorage.setItem('nexora_transcript_view', view); } catch (_) { }
          if (view === 'thinking') {
            $$('.thought-accordion').forEach((el) => { el.open = true; });
          } else if (view === 'normal') {
            $$('.thought-accordion').forEach((el) => { el.open = false; });
          }
          toast(`Transcript view: ${view}`, 'info');
        });
      });

      // Custom Theme: Mode Switcher (System, Light, Dark)
      $$('[data-theme-mode]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const mode = btn.dataset.themeMode;
          if (mode === 'system') {
            const prefersLight = window.matchMedia('(prefers-color-scheme: light)').matches;
            customTheme.mode = prefersLight ? 'light' : 'dark';
          } else {
            customTheme.mode = mode;
          }
          applyThemeEngine(customTheme);
          toast(`Mode: ${customTheme.mode}`, 'info');
        });
      });

      // Custom Theme: Swatch Circles Row
      $$('.swatch-circle').forEach((swatch) => {
        swatch.addEventListener('click', () => {
          $$('.swatch-circle').forEach((s) => s.classList.remove('active'));
          swatch.classList.add('active');
          customTheme.hue = parseInt(swatch.dataset.hue || '239', 10);
          customTheme.sat = parseInt(swatch.dataset.sat || '84', 10);
          customTheme.light = parseInt(swatch.dataset.light || '67', 10);
          customTheme.name = swatch.dataset.name || swatch.title || 'Custom Swatch';
          applyThemeEngine(customTheme);
          toast(`Color applied: ${customTheme.name}`, 'info');
        });
      });

      // Swatches Row Scroll Arrows
      const swatchesRow = $('#swatches-row');
      $('#swatch-arrow-prev')?.addEventListener('click', () => {
        swatchesRow?.scrollBy({ left: -100, behavior: 'smooth' });
      });
      $('#swatch-arrow-next')?.addEventListener('click', () => {
        swatchesRow?.scrollBy({ left: 100, behavior: 'smooth' });
      });

      // Custom Theme: Wavy Hue Slider
      const hueSlider = $('#wavy-hue-slider');
      if (hueSlider) {
        hueSlider.addEventListener('input', (e) => {
          customTheme.hue = parseInt(e.target.value, 10);
          customTheme.name = `Hue ${customTheme.hue}°`;
          $$('.swatch-circle').forEach((s) => s.classList.remove('active'));
          applyThemeEngine(customTheme);
        });
      }

      // Custom Theme: Native Color Picker
      const nativeColor = $('#custom-native-color');
      if (nativeColor) {
        nativeColor.addEventListener('input', (e) => {
          const hsl = hexToHsl(e.target.value);
          customTheme.hue = hsl.h;
          customTheme.sat = hsl.s;
          customTheme.light = hsl.l;
          customTheme.name = e.target.value.toUpperCase();
          $$('.swatch-circle').forEach((s) => s.classList.remove('active'));
          applyThemeEngine(customTheme);
        });
      }

      // Quick Actions on Canvas: Contrast Inc, Dec, Randomize
      $('#canvas-contrast-inc')?.addEventListener('click', () => {
        customTheme.sat = Math.min(100, customTheme.sat + 8);
        applyThemeEngine(customTheme);
        toast(`Saturation increased: ${customTheme.sat}%`, 'info');
      });
      $('#canvas-contrast-dec')?.addEventListener('click', () => {
        customTheme.sat = Math.max(30, customTheme.sat - 8);
        applyThemeEngine(customTheme);
        toast(`Saturation reduced: ${customTheme.sat}%`, 'info');
      });
      $('#canvas-random-hue')?.addEventListener('click', () => {
        customTheme.hue = Math.floor(Math.random() * 360);
        customTheme.name = `Random Hue ${customTheme.hue}°`;
        $$('.swatch-circle').forEach((s) => s.classList.remove('active'));
        applyThemeEngine(customTheme);
        toast(`Color shifted: ${customTheme.hue}°`, 'info');
      });

      // Reset Defaults
      $('#reset-custom-theme-btn')?.addEventListener('click', () => {
        customTheme = { hue: 200, sat: 40, light: 59, mode: 'dark', name: 'Midnight Slate' };
        $$('.swatch-circle').forEach((s) => {
          s.classList.toggle('active', s.dataset.name === 'Midnight Slate');
        });
        applyThemeEngine(customTheme);
        toast('Theme reset to Midnight Slate defaults.', 'info');
      });

      // Rotary dial interactive rotation
      const rotaryDial = $('#hue-rotary-dial');
      if (rotaryDial) {
        rotaryDial.addEventListener('click', () => {
          customTheme.hue = (customTheme.hue + 25) % 360;
          customTheme.name = `Hue ${customTheme.hue}°`;
          $$('.swatch-circle').forEach((s) => s.classList.remove('active'));
          applyThemeEngine(customTheme);
          toast(`Hue rotated: ${customTheme.hue}°`, 'info');
        });
      }

      // Sync Header Quick Theme Toggle Button
      const quickThemeToggle = $('#theme-toggle-btn');
      if (quickThemeToggle) {
        quickThemeToggle.addEventListener('click', () => {
          customTheme.mode = customTheme.mode === 'light' ? 'dark' : 'light';
          applyThemeEngine(customTheme);
          toast(`Switched to ${customTheme.mode} mode`, 'info');
        });
      }
    }
  }

  /* ================================================================ chat */
  pushMessage(role, text, meta = {}) {
    const msg = { id: `m${Date.now().toString(36)}${(this.messages.length + 1).toString(36)}`, role, text, at: new Date().toISOString(), ...meta };
    this.messages.push(msg);
    if (this.virtualScrollEnabled && !meta.streaming) {
      this.renderVisibleRange();
    } else {
      this.renderMessage(msg, true);
    }
    return msg;
  }

  clearChat(quiet = false) {
    this.messages = [];
    this.virtualStart = 0;
    if (this.historyEl) {
      this.historyEl.innerHTML = '';
      this.historyEl.style.paddingTop = '0';
      this.historyEl.style.paddingBottom = '0';
    }
    this.chatEl.classList.add('welcome-active');
  }

  buildEvidenceCardHtml(evidence, msgId) {
    return '';
  }

  bindEvidenceToggles(node) { }

  buildMsgMetaBar(runId) {
    const run = this.state.get('currentRun');
    const detail = this.state.get('currentRunDetail');
    if (!run || run.id !== runId) return '';
    const totalUsed = (run.input_tokens_used || 0) + (run.output_tokens_used || 0);
    const profile = (this.state.get('budgetProfiles') || []).find((p) => p.id === run.budget_profile_id)
      || this.state.get('defaultBudgetProfile');
    const maxTokens = profile?.max_output_tokens ? (profile.max_output_tokens + (profile.max_input_tokens || 8000)) : 20000;
    const remaining = Math.max(0, maxTokens - totalUsed);
    const attempts = run.result_summary?.attempts || detail?.run_result?.attempts || 1;
    const selfHealed = Boolean(run.result_summary?.self_healed || detail?.run_result?.critic_findings?.self_healed);

    return `
      <div class="msg-meta-bar">
        ${totalUsed > 0 ? `<span class="meta-pill" title="${formatNumber(run.input_tokens_used || 0)} in / ${formatNumber(run.output_tokens_used || 0)} out"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:3px;"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg><strong>${formatTokens(totalUsed)}</strong> used · <strong>${formatTokens(remaining)}</strong> remaining</span>` : ''}
        <span class="meta-pill">${selfHealed ? `<span style="color:#34d399; font-weight:600; display:inline-flex; align-items:center; gap:3px;"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>Auto-healed (att ${attempts})</span>` : `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:3px;"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="6" r="6"/><circle cx="12" cy="2" r="2"/></svg>${attempts} attempt${attempts > 1 ? 's' : ''}`}</span>
        ${run.total_elapsed_ms ? `<span class="meta-pill"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:3px;"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>${formatDuration(run.total_elapsed_ms)}</span>` : ''}
      </div>`;
  }

  renderMessage(msg, animate = false) {
    if (!this.historyEl) return;
    const node = document.createElement('div');
    const cls = msg.role === 'user' ? 'msg-user' : msg.role === 'system' ? 'msg-system' : 'msg-ai';
    const gold = msg.gold ? ' msg-gold' : '';
    node.className = `msg ${cls}${gold}`;
    node.dataset.msgId = msg.id || '';

    const roleLabel = msg.role === 'user' ? 'You' : (msg.roleLabel || 'Nexora');

    const toolsHtml = msg.role === 'user'
      ? `<div class="msg-tools">
           <button class="msg-tool-btn edit-msg-btn" title="Edit prompt and re-run">
             <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
             <span>Edit</span>
           </button>
           <button class="msg-tool-btn copy-msg-btn" title="Copy prompt">
             <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
             <span>Copy</span>
           </button>
         </div>`
      : `<div class="msg-tools">
           <button class="msg-tool-btn copy-msg-btn" title="Copy response">
             <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
             <span>Copy</span>
           </button>
           <button class="msg-tool-btn retry-msg-btn" title="Regenerate response">
             <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
             <span>Retry</span>
           </button>
         </div>`;

    const actions = msg.actions?.length
      ? `<div class="msg-actions">${msg.actions.map((a, i) => `<button class="btn btn-sm ${a.variant || ''}" data-msg-action="${esc(msg.id)}:${i}">${esc(a.label)}</button>`).join('')}</div>`
      : '';

    const stamp = this.showTimestamps && msg.at
      ? `<div class="timestamp">${esc(formatDateTime(msg.at))}</div>`
      : '';

    const evidenceHtml = msg.evidence ? this.buildEvidenceCardHtml(msg.evidence, msg.id) : '';
    let metaBarHtml = '';
    if (msg.role !== 'user' && !msg.streaming && msg.runId) {
      metaBarHtml = this.buildMsgMetaBar(msg.runId);
    }

    node.innerHTML = `
      <div class="msg-header">
        <div class="role">${esc(roleLabel)}</div>
        ${toolsHtml}
      </div>
      <div class="body md">${renderMarkdown(msg.text)}</div>
      ${metaBarHtml}
      ${evidenceHtml}
      ${actions}${stamp}`;

    if (!animate) node.style.animation = 'none';
    this.historyEl.appendChild(node);
    this.chatEl.classList.remove('welcome-active');
    this.scrollToBottom();
    this.bindMessageActions(node, msg);
    this.bindEvidenceToggles(node);
  }

  updateMessage(id, text, meta = {}) {
    const msg = this.messages.find((m) => m.id === id);
    if (!msg) return null;
    if (text !== undefined) msg.text = text;
    Object.assign(msg, meta);

    // Streaming updates use direct DOM manipulation; non-streaming uses virtual re-render
    if (this.virtualScrollEnabled && !meta.streaming) {
      this.renderVisibleRange();
    } else {
      const node = this.historyEl.querySelector(`[data-msg-id="${CSS.escape(id)}"]`);
      if (node) {
        if (meta.roleLabel) {
          const roleEl = node.querySelector('.role');
          if (roleEl) roleEl.textContent = meta.roleLabel;
        }
        const bodyEl = node.querySelector('.body');
        if (bodyEl) {
          if (meta.streaming) {
            bodyEl.innerHTML = renderMarkdown(msg.text) + ' <span class="streaming-cursor"></span>';
          } else {
            bodyEl.innerHTML = renderMarkdown(msg.text);
          }
        }
        if (meta.streaming === false && msg.role !== 'user' && msg.runId) {
          let bar = node.querySelector('.msg-meta-bar');
          const metaHtml = this.buildMsgMetaBar(msg.runId);
          if (bar && metaHtml) {
            bar.outerHTML = metaHtml;
          } else if (!bar && metaHtml) {
            node.querySelector('.body')?.insertAdjacentHTML('afterend', metaHtml);
          }
          this.updateHeaderStats();
        }
        if (meta.evidence) {
          msg.evidence = meta.evidence;
          const oldCard = node.querySelector('.evidence-card');
          const cardHtml = this.buildEvidenceCardHtml(meta.evidence, msg.id);
          if (oldCard) {
            oldCard.outerHTML = cardHtml;
          } else {
            node.querySelector('.body')?.insertAdjacentHTML('afterend', cardHtml);
          }
          this.bindEvidenceToggles(node);
        }
        if (meta.actions) {
          const actions = `<div class="msg-actions">${msg.actions.map((a, i) => `<button class="btn btn-sm ${a.variant || ''}" data-msg-action="${esc(msg.id)}:${i}">${esc(a.label)}</button>`).join('')}</div>`;
          const existing = node.querySelector('.msg-actions');
          if (existing) existing.outerHTML = actions;
          else node.querySelector('.timestamp')?.insertAdjacentHTML('beforebegin', actions);
          this.bindMessageActions(node, msg);
        }
      }
    }
    this.scrollToBottom();
    return msg;
  }

  bindMessageActions(node, msg) {
    node.querySelectorAll('[data-msg-action]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const idx = Number(btn.dataset.msgAction.split(':')[1]);
        msg.actions?.[idx]?.onClick?.();
      });
    });

    node.querySelector('.edit-msg-btn')?.addEventListener('click', () => {
      const input = $('#message');
      if (input) {
        input.value = msg.text;
        this.autoGrow(input);
        this.updateGhost();
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
        toast('Loaded prompt for editing.', 'info');
      }
    });

    node.querySelector('.copy-msg-btn')?.addEventListener('click', () => {
      navigator.clipboard.writeText(msg.text || '').then(() => {
        toast('Copied to clipboard!', 'success');
      }).catch(() => {
        toast('Failed to copy', 'error');
      });
    });

    node.querySelector('.retry-msg-btn')?.addEventListener('click', () => {
      const userMsg = [...this.messages].reverse().find((m) => m.role === 'user');
      if (userMsg && userMsg.text) {
        const input = $('#message');
        if (input) input.value = userMsg.text;
        this.submit();
      }
    });
  }

  scrollToBottom() {
    if (!this.historyEl) return;
    requestAnimationFrame(() => { this.historyEl.scrollTop = this.historyEl.scrollHeight; });
  }

  /* ================================================================ virtual scroll */
  initVirtualScroll() {
    if (!this.virtualScrollEnabled || !this.historyEl) return;
    this.historyEl.addEventListener('scroll', (e) => {
      requestAnimationFrame(() => this.renderVisibleRange());
    }, { passive: true });
    // initial render
    this.renderVisibleRange();
  }

  renderVisibleRange() {
    if (!this.virtualScrollEnabled || !this.historyEl || this.messages.length === 0) return;
    const { scrollTop, clientHeight, scrollHeight } = this.historyEl;
    const itemHeight = this.virtualItemHeight;
    const buffer = this.virtualBuffer * itemHeight;

    const start = Math.floor((scrollTop - buffer) / itemHeight);
    const end = Math.ceil((scrollTop + clientHeight + buffer) / itemHeight);

    const newStart = Math.max(0, start);
    const newEnd = Math.min(this.messages.length - 1, end);

    // If range hasn't changed meaningfully, skip re-render
    if (this.virtualStart === newStart && this.messages.length === this.historyEl.children.length) return;

    this.virtualStart = newStart;

    // Simple approach: render all but let CSS handle it; for true virtualization
    // we only render visible range. Here we render visible + buffer.
    const visible = this.messages.slice(newStart, newEnd + 1);
    const frag = document.createDocumentFragment();
    visible.forEach((msg) => {
      const node = this.buildMessageNode(msg);
      frag.appendChild(node);
    });

    // Only replace if we're not mid-stream (avoid flicker on active stream)
    const streaming = this.historyEl.querySelector('[streaming]');
    if (!streaming) {
      this.historyEl.innerHTML = '';
      this.historyEl.appendChild(frag);
      // Offset padding so scroll position stays correct
      this.historyEl.style.paddingTop = `${newStart * itemHeight}px`;
      this.historyEl.style.paddingBottom = `${(this.messages.length - newEnd - 1) * itemHeight}px`;
    }
  }

  buildMessageNode(msg) {
    // Lightweight node builder for virtual scroll (mirrors renderMessage structure)
    const node = document.createElement('div');
    const cls = msg.role === 'user' ? 'msg-user' : msg.role === 'system' ? 'msg-system' : 'msg-ai';
    node.className = `msg ${cls}`;
    node.dataset.msgId = msg.id || '';
    const roleLabel = msg.role === 'user' ? 'You' : (msg.roleLabel || 'Nexora');
    node.innerHTML = `
      <div class="msg-header">
        <div class="role">${esc(roleLabel)}</div>
      </div>
      <div class="body md">${renderMarkdown(msg.text || '')}</div>
    `;
    return node;
  }

  /* ================================================================ run lifecycle */
  async submit() {
    const input = $('#message');
    const text = (input.value || '').trim();
    const workspaceId = this.state.get('selectedWorkspaceId');

    if (this.isRunActive()) return toast('A run is already active — stop it first.', 'warning');
    if (!text) { input.focus(); return toast('Describe the task first.', 'error'); }
    if (!workspaceId) { toast('The local demo repository is unavailable. Reload the app to initialize it.', 'error'); return; }
    document.body.classList.remove('response-mode');

    const mode = this.state.get('routingMode') || 'auto';
    const modelId = this.state.get('selectedModelId');
    const profileId = this.state.get('selectedBudgetProfileId') || this.state.get('defaultBudgetProfile')?.id;
    input.value = '';
    this.autoGrow(input);
    this.updateGhost();

    let fullTaskText = text;
    if (this.attachedFiles && this.attachedFiles.length > 0) {
      const rawFiles = this.attachedFiles.map((f) => f.file).filter(Boolean);
      let uploadResults = [];

      if (rawFiles.length > 0 && window.NexoraApi?.workspaces?.uploadFiles) {
        toast(`Processing ${rawFiles.length} uploaded file(s)...`, 'info');
        try {
          const resp = await window.NexoraApi.workspaces.uploadFiles(workspaceId, rawFiles);
          uploadResults = resp.files || [];
        } catch (uploadErr) {
          console.warn('Backend file extraction failed, using filename reference:', uploadErr);
          toast(`Upload error: ${uploadErr.message || uploadErr}`, 'warning');
        }
      }

      if (uploadResults.length > 0) {
        const fileSummaries = uploadResults.map((f) => {
          if (f.error) {
            return `--- File: ${f.filename} (Notice: ${f.error}) ---`;
          }
          if (f.category === 'archive') {
            const fileList = (f.extracted_files || []).slice(0, 30).map((n) => `  - ${n}`).join('\n');
            const more = (f.extracted_files && f.extracted_files.length > 30) ? `\n  ... and ${f.extracted_files.length - 30} more files` : '';
            return `--- Archive: ${f.filename} (${f.original_size} bytes) ---\n${f.summary}\nSandbox Location: ${f.sandbox_path || 'uploads/'}\nExtracted Files:\n${fileList}${more}`;
          }
          if (f.category === 'document') {
            const preview = f.text_content ? f.text_content.slice(0, 8000) : '';
            return `--- Document: ${f.filename} (${f.original_size} bytes) ---\n${f.summary}\n${preview}`;
          }
          // Code / Data / Text files
          const preview = f.text_content ? f.text_content.slice(0, 10000) : '';
          return `--- File: ${f.filename} (${f.original_size} bytes, ${f.category}) ---\n${preview}`;
        }).join('\n\n');

        fullTaskText = `[Attached Project Files & Context:\n${fileSummaries}\n]\n\nTask:\n${text}`;
      } else {
        const names = this.attachedFiles.map((f) => `${f.name} (${this.formatFileSize(f.size)})`).join(', ');
        fullTaskText = `[Context Files Attached: ${names}]\n\nTask:\n${text}`;
      }

      this.attachedFiles = [];
      this.renderAttachedFiles();
    }

    this.pushMessage('user', text);
    const aiMsg = this.pushMessage('ai', '', { roleLabel: 'Nexora', streaming: true });

    const payload = {
      workspace_id: workspaceId,
      task_text: fullTaskText,
      routing_mode: mode === 'fixed' ? 'fixed' : 'auto',
      requested_model_id: mode === 'fixed' && modelId ? modelId : null,
      budget_profile_id: profileId || null,
      // If we have an active thread, continue it instead of creating a new run
      parent_run_id: this.activeThreadRunId || null,
      healing_mode: this.healingMode || 'auto',
      detail_level: this.detailLevel || 'auto',
    };

    try {
      const run = await window.NexoraApi.runs.create(payload);
      if (!payload.parent_run_id && this.draftChatTitle) {
        this.setCustomTitle(run.id, this.draftChatTitle);
        this.draftChatTitle = '';
      }
      aiMsg.runId = run.id;
      this.state.set('currentRun', run);

      // Remember this run as the active thread root for subsequent follow-ups.
      // Always update to the latest child run ID so the chain stays linear.
      this.activeThreadRunId = run.id;
      this._updateThreadBadge();

      await this.selectRun(run.id, { silent: true });

      if (this.autoStart) {
        await this.streamRun(run.id, aiMsg.id);
      }
      await this.loadRuns();
      this.renderRunsList();
    } catch (error) {
      this.updateMessage(aiMsg.id, `**Run creation failed**\n\n\`${error.message}\``, { streaming: false });
      toast(`Run creation failed: ${error.message}`, 'error');
    }
  }

  /** Show/hide the "Continuing thread" badge next to the composer. */
  _updateThreadBadge() {
    let badge = $('#thread-badge');
    if (!badge) {
      const composer = $('#composer') || document.querySelector('.composer-row') || document.querySelector('.composer');
      if (composer) {
        badge = document.createElement('div');
        badge.id = 'thread-badge';
        badge.style.cssText = 'font-size:11px;color:var(--accent,#7c6af7);padding:2px 6px;background:var(--glass-bg,rgba(124,106,247,.12));border-radius:8px;margin:2px 0 4px 2px;display:inline-flex;align-items:center;gap:4px;';
        composer.insertAdjacentElement('beforebegin', badge);
      }
    }
    if (badge) {
      if (this.activeThreadRunId) {
        badge.innerHTML = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg><span>Continuing thread &nbsp;<code style="font-size:10px">${esc(this.activeThreadRunId.slice(0, 8))}</code></span>`;
        badge.style.display = 'inline-flex';
      } else {
        badge.style.display = 'none';
      }
    }
  }


  describeRun(run) {
    const model = (this.state.get('models') || []).find((m) => m.id === run.requested_model_id);
    const lines = [
      `Run \`${run.id.slice(0, 8)}\` initialized.`,
      `- **Status** — ${tag(run.status)}`,
      `- **Routing** — ${run.routing_mode}${model ? ` (${model.display_name})` : ''}`,
    ];
    return lines.join('\n');
  }

  isRunActive() {
    const status = this.state.get('currentRun')?.status;
    return ACTIVE.includes(status);
  }

  async streamRun(runId, pendingMsgId = null) {
    let accumulatedContent = '';
    let aiMsg = null;
    this.currentStreamAbortController = new AbortController();

    try {
      if (pendingMsgId) {
        aiMsg = this.messages.find((m) => m.id === pendingMsgId);
      }
      if (!aiMsg) {
        aiMsg = this.messages.find((m) => m.runId === runId && m.role === 'ai');
      }
      if (!aiMsg) {
        aiMsg = this.pushMessage('ai', '', {
          roleLabel: 'Nexora',
          runId: runId,
          streaming: true,
        });
      } else {
        aiMsg.runId = runId;
        this.updateMessage(aiMsg.id, '', {
          roleLabel: 'Nexora',
          streaming: true,
        });
      }

      this.updateRunStatusUI();

      let thoughtBuffer = '';
      let messageBuffer = '';

      for await (const { event, data } of window.NexoraApi.runs.stream(runId, this.currentStreamAbortController.signal)) {
        if (event === 'delta') {
          const chunk = data?.content || '';
          messageBuffer += chunk;
          const displayContent = (thoughtBuffer ? `<thought>\n${thoughtBuffer}\n</thought>\n\n` : '') + messageBuffer;
          accumulatedContent = displayContent;
          this.updateMessage(aiMsg.id, displayContent, {
            roleLabel: 'Nexora',
            streaming: true,
          });
        } else if (event === 'thought') {
          const thoughtChunk = (data?.content || '').trim();
          if (thoughtChunk) {
            thoughtBuffer += (thoughtBuffer ? '\n' : '') + thoughtChunk;
            const displayContent = `<thought>\n${thoughtBuffer}\n</thought>\n\n` + messageBuffer;
            accumulatedContent = displayContent;
            this.updateMessage(aiMsg.id, displayContent, {
              roleLabel: 'Nexora',
              streaming: true,
            });
          }
        } else if (event === 'tool_start') {
          const toolName = data?.tool || 'tool';
          const args = data?.arguments && Object.keys(data.arguments).length > 0 ? JSON.stringify(data.arguments) : '';
          const toolCard = `\n\n> ⚡ **Executing Tool:** \`${toolName}\` ${args ? `\`${truncate(args, 60)}\`` : ''}\n\n`;
          accumulatedContent += toolCard;
          this.updateMessage(aiMsg.id, accumulatedContent, {
            roleLabel: 'Nexora',
            streaming: true,
          });
        } else if (event === 'tool_result') {
          const toolName = data?.tool || 'tool';
          const statusIcon = data?.exit_code === 0 ? '✓' : '✕';
          const out = (data?.stdout || data?.stderr || '').trim();
          const preview = out ? `\n\`\`\`\n${truncate(out, 400)}\n\`\`\`\n` : '';
          const replacement = `\n\n> ${statusIcon} **Finished Tool:** \`${toolName}\`${preview}\n\n`;

          const executingPattern = new RegExp(`\n*> ⚡ \\*\\*Executing Tool:\\*\\* \`${toolName}\`[^\n]*\n*`, 'g');
          if (executingPattern.test(accumulatedContent)) {
            accumulatedContent = accumulatedContent.replace(executingPattern, replacement);
          } else {
            accumulatedContent += replacement;
          }

          this.updateMessage(aiMsg.id, accumulatedContent, {
            roleLabel: 'Nexora',
            streaming: true,
          });
        } else if (event === 'healing') {
          const healingMsg = data?.message || 'Auto-correcting verification issue...';
          toast(healingMsg, 'info');
          this.updateRunStatusUI();
        } else if (event === 'approval_required') {
          const approvalId = data?.approval_id || '';
          const tool = data?.tool || 'Action';
          const scope = data?.scope || '';
          const msg = data?.message || `Approval required for ${tool}`;
          accumulatedContent += `\n\n<approval approval-id="${approvalId}" tool="${tool}" scope="${scope}">${msg}</approval>\n\n`;
          this.updateMessage(aiMsg.id, accumulatedContent, {
            roleLabel: 'Nexora',
            streaming: true,
          });
        } else if (event === 'status') {
          this.updateRunStatusUI();
        } else if (event === 'done') {
          break;
        } else if (event === 'error') {
          console.warn('Stream notice:', data?.message);
        }
      }

      this.currentStreamAbortController = null;

      // Fetch final run detail for telemetry & evidence
      const detail = await window.NexoraApi.runs.get(runId);
      this.state.set('currentRunDetail', detail);
      this.state.set('currentRun', detail.run);

      const run = detail.run;
      const resp = run.result_summary;
      let cleanContent = resp?.content || messageBuffer || accumulatedContent;

      const toolCallsMatch = accumulatedContent.match(/(> (?:⚡|\u26a1|✓|✕) [^\n]+(?:\n```[\s\S]*?```\n)?\n*)+/g);
      if (toolCallsMatch && !cleanContent.includes('Finished Tool:')) {
        cleanContent = toolCallsMatch.join('\n\n') + '\n\n' + cleanContent;
      }

      const badgeIdx = cleanContent.indexOf('> 🛡️ **Self-Healing Verified:**');
      if (badgeIdx !== -1) {
        const stripped = cleanContent.slice(0, badgeIdx).trim();
        if (stripped.length > 0) cleanContent = stripped;
      }

      if (INTERNAL_OUTPUT_PREFIX.test(cleanContent)) {
        cleanContent = cleanContent.replace(INTERNAL_OUTPUT_PREFIX, '').trim();
      }

      // Clean any stray reasoning tags that might have leaked from model text
      cleanContent = cleanContent
        .replace(/<thought>[\s\S]*?<\/thought>/gi, '')
        .replace(/<\/?(?:thought|thinking|think|reasoning)>/gi, '')
        .trim();

      if (thoughtBuffer) {
        cleanContent = `<thought>\n${thoughtBuffer}\n</thought>\n\n` + cleanContent;
      }

      if (!cleanContent.trim()) {
        cleanContent = resp?.content || messageBuffer || accumulatedContent || 'Execution completed.';
      }

      this.updateMessage(aiMsg.id, cleanContent, {
        roleLabel: 'Nexora',
        streaming: false,
      });

      this.afterRunUpdate();
      await this.loadRuns();
      this.renderRunsList();
      await this.loadWorkspaceFiles();
      return detail.run;
    } catch (err) {
      const isAborted = err.name === 'AbortError' || this.isCancelling || this.currentStreamAbortController?.signal?.aborted;
      this.currentStreamAbortController = null;

      if (isAborted) {
        console.log('Stream explicitly cancelled by user.');
        if (aiMsg) {
          const finalStopped = (accumulatedContent ? accumulatedContent + '\n\n' : '') + '*(Generation stopped by user)*';
          this.updateMessage(aiMsg.id, finalStopped, { streaming: false });
        }
        const current = this.state.get('currentRun');
        if (current) {
          this.state.set('currentRun', { ...current, status: 'cancelled' });
        }
        this.updateRunStatusUI();
        return null;
      }

      console.warn('Streaming interrupted, falling back to standard execution:', err);
      if (aiMsg) {
        this.updateMessage(aiMsg.id, accumulatedContent || '`Executing run…`', { streaming: false });
      }
      return await this.startRun(runId);
    }
  }

  async startRun(runId) {
    const currentRun = this.state.get('currentRun');
    if (currentRun?.id === runId && currentRun.status === 'awaiting_start') {
      this.startPolling(runId);
    }

    try {
      const run = await window.NexoraApi.runs.start(runId);
      this.state.set('currentRun', run);
      const detail = await window.NexoraApi.runs.get(runId);
      this.state.set('currentRunDetail', detail);
      this.state.set('currentRun', detail.run);

      if (TERMINAL.includes(detail.run.status)) {
        this.stopPolling();
        const error = detail.run.error_message;
        toast(
          error ? truncate(error, 140) : `Run ${detail.run.status}.`,
          detail.run.status === 'completed' ? 'success' : error ? 'error' : 'warning',
        );
      } else {
        if (this.isRunActive()) this.startPolling(runId);
        else this.stopPolling();
      }
      this.afterRunUpdate();
      await this.loadRuns();
      this.renderRunsList();
      return run;
    } catch (error) {
      toast(`Could not start run: ${error.message}`, 'error');
      return null;
    }
  }

  async stopRun() {
    const run = this.state.get('currentRun');
    if (!run) return toast('No active run to cancel.', 'warning');

    this.isCancelling = true;
    if (this.currentStreamAbortController) {
      try {
        this.currentStreamAbortController.abort();
      } catch (_) { }
      this.currentStreamAbortController = null;
    }

    this.stopPolling();

    // Immediately mark run as cancelled in local state so Send button reverts to send mode
    this.state.set('currentRun', { ...run, status: 'cancelled' });
    this.updateRunStatusUI();

    // Mark any active streaming message as stopped immediately
    const activeAiMsg = [...this.messages].reverse().find((m) => m.role === 'ai' && m.streaming);
    if (activeAiMsg) {
      const text = (activeAiMsg.text ? activeAiMsg.text + '\n\n' : '') + '*(Generation stopped by user)*';
      this.updateMessage(activeAiMsg.id, text, { streaming: false });
    }

    toast('Generation stopped immediately.', 'warning');

    // Notify backend to cancel the executing asyncio task
    try {
      await window.NexoraApi.runs.cancel(run.id);
    } catch (error) {
      console.warn('Backend cancel notice (may already be finished):', error.message);
    }

    this.isCancelling = false;
    await this.loadRuns();
    this.renderRunsList();
  }

  async selectRun(runId, options = {}) {
    if (!runId) return null;
    try {
      const detail = await window.NexoraApi.runs.get(runId);
      this.state.set('currentRunDetail', detail);
      this.state.set('currentRun', detail.run);

      // Keep activeThreadRunId locked to this run so follow-up prompts in the chat box
      // automatically continue this thread without starting a new chat.
      this.activeThreadRunId = detail.run.id;
      this._updateThreadBadge();

      if (!options.silent) {
        this.clearChat(true);

        const history = detail.run.conversation_history;
        if (Array.isArray(history) && history.length > 0) {
          // Render the entire multi-turn thread in order
          for (let i = 0; i < history.length; i++) {
            const turn = history[i];
            if (turn.role === 'user') {
              this.pushMessage('user', turn.content);
            } else if (turn.role === 'assistant') {
              let clean = turn.content || '';
              const badgeIdx = clean.indexOf('> 🛡️ **Self-Healing Verified:**');
              if (badgeIdx !== -1) {
                const stripped = clean.slice(0, badgeIdx).trim();
                if (stripped.length > 0) clean = stripped;
              }
              if (INTERNAL_OUTPUT_PREFIX.test(clean)) clean = clean.replace(INTERNAL_OUTPUT_PREFIX, '').trim();
              clean = clean.replace(/<\/?(?:thought|thinking|think|reasoning)>/gi, '').trim();
              if (!clean.trim()) clean = turn.content || '';

              if (i === history.length - 1 && Array.isArray(detail.tool_executions) && detail.tool_executions.length > 0 && !clean.includes('Tool:')) {
                const toolCards = detail.tool_executions.map(te => {
                  const statusIcon = te.execution_status === 'success' || te.exit_code === 0 ? '✓' : '✕';
                  const out = (te.stdout || te.stderr || '').trim();
                  const preview = out ? `\n\`\`\`\n${truncate(out, 260)}\n\`\`\`\n` : '';
                  return `> ${statusIcon} **Executed Tool:** \`${te.tool_name || 'tool'}\`${preview}`;
                }).join('\n\n');
                clean = toolCards + '\n\n' + clean;
              }

              this.pushMessage('ai', clean, {
                roleLabel: 'Nexora',
                runId: (i === history.length - 1) ? detail.run.id : null,
              });
            }
          }
        } else {
          // Fallback for single/legacy runs
          this.pushMessage('user', detail.run.task_text);
          const response = detail.run.result_summary;
          if (response?.type === 'assistant_response' && typeof response.content === 'string') {
            let clean = response.content;
            const badgeIdx = clean.indexOf('> 🛡️ **Self-Healing Verified:**');
            if (badgeIdx !== -1) {
              const stripped = clean.slice(0, badgeIdx).trim();
              if (stripped.length > 0) clean = stripped;
            }
            if (INTERNAL_OUTPUT_PREFIX.test(clean)) clean = clean.replace(INTERNAL_OUTPUT_PREFIX, '').trim();
            clean = clean.replace(/<\/?(?:thought|thinking|think|reasoning)>/gi, '').trim();
            if (!clean.trim()) clean = response.content || '';

            if (Array.isArray(detail.tool_executions) && detail.tool_executions.length > 0 && !clean.includes('Tool:')) {
              const toolCards = detail.tool_executions.map(te => {
                const statusIcon = te.execution_status === 'success' || te.exit_code === 0 ? '✓' : '✕';
                const out = (te.stdout || te.stderr || '').trim();
                const preview = out ? `\n\`\`\`\n${truncate(out, 260)}\n\`\`\`\n` : '';
                return `> ${statusIcon} **Executed Tool:** \`${te.tool_name || 'tool'}\`${preview}`;
              }).join('\n\n');
              clean = toolCards + '\n\n' + clean;
            }

            this.pushMessage('ai', clean, {
              roleLabel: 'Nexora',
              runId: detail.run.id,
            });
          }
        }
      }

      if (this.isRunActive()) this.startPolling(runId);
      else this.stopPolling();
      this.afterRunUpdate();
      return detail;
    } catch (error) {
      if (!options.silent) toast(`Could not load run: ${error.message}`, 'error');
      return null;
    }
  }

  startPolling(runId) {
    this.stopPolling();
    this.pollTimer = setInterval(async () => {
      if (document.hidden) return;
      try {
        const detail = await window.NexoraApi.runs.get(runId);
        this.state.set('currentRunDetail', detail);
        this.state.set('currentRun', detail.run);

        this.afterRunUpdate();

        if (TERMINAL.includes(detail.run.status)) {
          this.stopPolling();
          toast(`Run ${detail.run.status}.`, detail.run.status === 'completed' ? 'success' : 'warning');
          this.loadRuns().then(() => this.renderRunsList());
        }
      } catch (error) {
        console.error('poll failed', error);
      }
    }, this.pollMs);
    this.updateRunStatusUI();
  }

  restartPolling(runId) {
    if (this.isRunActive()) this.startPolling(runId);
  }

  stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
    this.updateRunStatusUI();
  }

  afterRunUpdate() {
    this.updateRunStatusUI();
    this.updateCost();
    this.updateRailBadges();
    this.updateHeaderStats();
    this.updateIdePane();
    this.renderRunResponse(this.state.get('currentRunDetail'));
    this.renderRunsList();
    if (modals.isOpen('tool')) this.renderToolModal();
  }

  renderRunResponse(detail) {
    const run = detail?.run;
    const response = run?.result_summary;
    if (response?.type !== 'assistant_response' || typeof response.content !== 'string') return;
    if (this.messages.some((message) => message.runId === run.id && message.role === 'ai')) return;

    let cleanContent = response.content;
    const hasPatchContent = Boolean(detail?.run_result?.patch_content);
    if (hasPatchContent && cleanContent) {
      const stripped = cleanContent.replace(/```(?:[a-zA-Z0-9_-]+)?\r?\n[\s\S]*?```/g, '').trim();
      if (stripped.length > 5) {
        cleanContent = stripped;
      }
    }
    const badgeIdx = cleanContent.indexOf('> 🛡️ **Self-Healing Verified:**');
    if (badgeIdx !== -1) {
      const stripped = cleanContent.slice(0, badgeIdx).trim();
      if (stripped.length > 0) cleanContent = stripped;
    }

    if (INTERNAL_OUTPUT_PREFIX.test(cleanContent)) {
      cleanContent = cleanContent.replace(INTERNAL_OUTPUT_PREFIX, '').trim();
    }

    cleanContent = cleanContent.replace(/<\/?(?:thought|thinking|think|reasoning)>/gi, '').trim();
    if (!cleanContent.trim()) cleanContent = response.content || '';

    // Check if the last assistant message already has this text (avoid duplicate bubble)
    const lastAi = [...this.messages].reverse().find((m) => m.role === 'ai');
    if (lastAi && lastAi.text && lastAi.text.trim() === cleanContent.trim()) {
      lastAi.runId = run.id;
      return;
    }

    this.pushMessage('ai', cleanContent, {
      roleLabel: 'Nexora',
      runId: run.id,
    });
  }

  /* ================================================================ Multi-Tab IDE */
  initEditorTabs() {
    this.editorTabs = [
      { id: 'tab-1', filename: 'solution.py', code: '', isDefault: true }
    ];
    this.activeEditorTabId = 'tab-1';
    this.bindEditorTabEvents();
    this.renderEditorTabs();
  }

  getActiveEditorTab() {
    return this.editorTabs.find(t => t.id === this.activeEditorTabId) || this.editorTabs[0];
  }

  bindEditorTabEvents() {
    const listEl = document.getElementById('ide-tab-list');
    const addBtn = document.getElementById('ide-new-tab-btn');
    const previewBtn = document.getElementById('ide-live-preview-btn');
    const copyBtn = document.getElementById('ide-copy-code-btn');
    const copyText = document.getElementById('ide-copy-code-text');
    const previewText = document.getElementById('ide-live-preview-text');
    const idePane = document.getElementById('ide-pane');

    if (addBtn) {
      addBtn.onclick = () => this.addBlankTab();
    }

    if (listEl) {
      listEl.onclick = (e) => {
        const closeBtn = e.target.closest('.ide-tab-close-btn');
        if (closeBtn) {
          e.stopPropagation();
          const tabId = closeBtn.dataset.closeId;
          this.closeEditorTab(tabId);
          return;
        }
        const tabEl = e.target.closest('.ide-tab');
        if (tabEl) {
          const tabId = tabEl.dataset.tabId;
          if (tabId && tabId !== this.activeEditorTabId) {
            this.switchEditorTab(tabId);
          }
        }
      };

      // Double-click on tab name to rename
      listEl.ondblclick = (e) => {
        const titleEl = e.target.closest('.ide-tab-filename');
        const tabEl = e.target.closest('.ide-tab');
        if (titleEl && tabEl) {
          const tabId = tabEl.dataset.tabId;
          const tab = this.editorTabs.find(t => t.id === tabId);
          if (!tab) return;
          const currentName = tab.filename;
          const newName = prompt('Enter new file name:', currentName);
          if (newName && newName.trim() && newName.trim() !== currentName) {
            tab.filename = newName.trim();
            tab.isDefault = false;
            this.renderEditorTabs();
            this.renderActiveTabContent();
          }
        }
      };
    }

    // Single unified Live Preview button in tabs bar
    if (previewBtn) {
      previewBtn.onclick = () => {
        const container = document.getElementById('ide-content') || document.querySelector('.ide-content');
        if (!container) return;
        const codeWrapper = container.querySelector('.diff-code-wrapper');
        const previewWrapper = container.querySelector('.diff-preview-wrapper');
        const iframe = container.querySelector('.diff-preview-iframe');
        if (!codeWrapper || !previewWrapper) return;

        const isShowingPreview = previewWrapper.style.display !== 'none';
        if (isShowingPreview) {
          previewWrapper.style.display = 'none';
          codeWrapper.style.display = '';
          previewBtn.classList.remove('active');
          if (previewText) previewText.textContent = 'Live Preview';
        } else {
          codeWrapper.style.display = 'none';
          previewWrapper.style.display = 'block';
          previewBtn.classList.add('active');
          if (previewText) previewText.textContent = 'Code View';
          if (iframe) {
            const activeTab = this.getActiveEditorTab();
            const raw = activeTab?.code || window.__nexora_clean_code || '';
            iframe.srcdoc = raw;
          }
        }
      };
    }

    // Single unified Copy Code button in tabs bar
    if (copyBtn) {
      copyBtn.onclick = () => {
        const activeTab = this.getActiveEditorTab();
        const codeToCopy = activeTab?.code || window.__nexora_clean_code || '';
        if (codeToCopy) {
          navigator.clipboard.writeText(codeToCopy).then(() => {
            if (copyText) copyText.textContent = '✓ Copied!';
            copyBtn.classList.add('copied');
            setTimeout(() => {
              if (copyText) copyText.textContent = 'Copy Code';
              copyBtn.classList.remove('copied');
            }, 2000);
          }).catch(() => {
            toast('Failed to copy to clipboard', 'error');
          });
        }
      };
    }

    // Scoped Ctrl+A for center coding section
    if (idePane) {
      idePane.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
          e.preventDefault();
          e.stopPropagation();

          const activeTab = this.getActiveEditorTab();
          const codeToCopy = activeTab?.code || window.__nexora_clean_code || '';
          if (codeToCopy) {
            navigator.clipboard.writeText(codeToCopy).then(() => {
              toast('✓ Copied code from center editor', 'info');
            }).catch(() => {});
          }

          const targetEl = document.querySelector('.ide-content .diff-code-table') || document.querySelector('.ide-content pre') || document.querySelector('#ide-code-block');
          if (targetEl && window.getSelection) {
            const sel = window.getSelection();
            const range = document.createRange();
            range.selectNodeContents(targetEl);
            sel.removeAllRanges();
            sel.addRange(range);
          }
        }
      });
    }
  }

  renderEditorTabs() {
    const listEl = document.getElementById('ide-tab-list');
    if (!listEl) return;
    listEl.innerHTML = this.editorTabs.map(tab => {
      const isActive = tab.id === this.activeEditorTabId;
      const canClose = this.editorTabs.length > 1;
      return `
        <div class="ide-tab ${isActive ? 'active' : ''}" data-tab-id="${tab.id}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
          <span class="ide-tab-filename" title="Double click to rename">${esc(tab.filename)}</span>
          ${canClose ? `<button class="ide-tab-close-btn" data-close-id="${tab.id}" title="Close tab">✕</button>` : ''}
        </div>
      `;
    }).join('');
  }

  switchEditorTab(tabId) {
    this.activeEditorTabId = tabId;
    this.renderEditorTabs();
    this.renderActiveTabContent();
  }

  renderActiveTabContent() {
    const ideContainer = document.querySelector('.ide-content');
    if (!ideContainer) return;
    const activeTab = this.getActiveEditorTab();
    if (!activeTab) return;

    window.__nexora_clean_code = activeTab.code || '';

    // Check if HTML or previewable
    const previewBtn = document.getElementById('ide-live-preview-btn');
    const isHtml = activeTab.filename.endsWith('.html') || /<(!DOCTYPE\s+)?html/i.test(activeTab.code || '');
    if (previewBtn) {
      previewBtn.style.display = isHtml ? 'flex' : 'none';
      previewBtn.classList.remove('active');
      const previewText = document.getElementById('ide-live-preview-text');
      if (previewText) previewText.textContent = 'Live Preview';
    }

    // Always render code view so user can directly edit lines in place
    ideContainer.innerHTML = renderCodeView(activeTab.code || '', activeTab.filename);
    bindDiffViewerEvents(ideContainer, activeTab.code || '');
  }

  setEditorTabCode(filename, code) {
    if (!filename) filename = 'solution.py';
    let tab = this.editorTabs.find(t => t.filename.toLowerCase() === filename.toLowerCase());
    if (!tab) {
      const defaultTab = this.editorTabs.find(t => t.isDefault && (!t.code || !t.code.trim()));
      if (defaultTab) {
        defaultTab.filename = filename;
        defaultTab.code = code;
        defaultTab.isDefault = false;
        tab = defaultTab;
      } else {
        const newId = 'tab-' + Date.now();
        tab = { id: newId, filename, code, isDefault: false };
        this.editorTabs.push(tab);
      }
    } else {
      tab.code = code;
    }
    this.activeEditorTabId = tab.id;
    this.renderEditorTabs();
    this.renderActiveTabContent();
  }

  addBlankTab() {
    const count = this.editorTabs.length + 1;
    const newId = 'tab-' + Date.now();
    const newTab = {
      id: newId,
      filename: `untitled-${count}.py`,
      code: '',
      isDefault: false
    };
    this.editorTabs.push(newTab);
    this.activeEditorTabId = newId;
    this.renderEditorTabs();
    this.renderActiveTabContent();

    setTimeout(() => {
      const firstCell = document.querySelector('.ide-content .diff-code-cell');
      if (firstCell) {
        firstCell.focus();
      }
    }, 50);
  }

  closeEditorTab(tabId) {
    if (this.editorTabs.length <= 1) return;
    const idx = this.editorTabs.findIndex(t => t.id === tabId);
    if (idx === -1) return;
    this.editorTabs.splice(idx, 1);
    if (this.activeEditorTabId === tabId) {
      const nextTab = this.editorTabs[Math.max(0, idx - 1)] || this.editorTabs[0];
      this.activeEditorTabId = nextTab.id;
    }
    this.renderEditorTabs();
    this.renderActiveTabContent();
  }

  updateIdePane() {
    const detail = this.state.get('currentRunDetail');
    if (!detail) return;

    const ideContainer = document.querySelector('.ide-content');
    if (!ideContainer) return;

    let code = detail.run_result?.patch_content;
    const hasResponse = detail.run?.result_summary?.type === 'assistant_response';
    const respContent = detail.run?.result_summary?.content || '';

    // Fallback: If patch_content is empty but result_summary has a code block or raw CSS/HTML code
    if (!code && respContent) {
      const codeBlockMatch = respContent.match(/```(?:[a-zA-Z0-9_-]+)?\r?\n([\s\S]*?)```/);
      if (codeBlockMatch) {
        code = codeBlockMatch[1].trim();
      } else if (respContent.includes('{') && respContent.includes('}') && (respContent.includes('/*') || respContent.includes(':'))) {
        code = respContent.trim();
      } else if (respContent.toLowerCase().includes('<!doctype') || respContent.includes('<html') || (respContent.includes('<div') && respContent.includes('</div>'))) {
        code = respContent.trim();
      }
    }

    if (code?.includes(LEGACY_MOCK_MARKER)) {
      this.setEditorTabCode('provider-not-configured.txt', '# This run contains a legacy placeholder response.\n# Configure NEBIUS_API_KEY and create a new run.');
      return;
    }

    if (code) {
      let filename = "solution.py";
      const match = code.match(/diff --git a\/(.*?) b\//);
      if (match && match[1]) {
        filename = match[1];
      } else {
        const cLower = code.toLowerCase().trim();
        if (/<(!DOCTYPE\s+)?html/i.test(code) || /<html\b/i.test(code)) {
          filename = "index.html";
        } else if (/<svg\b/i.test(code)) {
          filename = "graphic.svg";
        } else if ((cLower.startsWith("/*") || cLower.includes("@keyframes") || cLower.includes("body {") || cLower.includes(":root")) && !code.includes("def ")) {
          filename = "styles.css";
        } else if (/\b(function|const|let|var|import)\b/.test(code) && code.includes('=>')) {
          filename = "app.js";
        }
      }

      // Clean out diff headers so only pure source code is shown in code view
      let cleanCode = code
        .replace(/^diff --git a\/.*? b\/.*?\n/m, '')
        .replace(/^--- a\/.*?\n/m, '')
        .replace(/^\+\+\+ b\/.*?\n/m, '')
        .replace(/^@@.*?@@\n/m, '')
        .trim();

      if (INTERNAL_OUTPUT_PREFIX.test(cleanCode)) {
        cleanCode = cleanCode.replace(INTERNAL_OUTPUT_PREFIX, '').trim();
      }

      const finalCode = cleanCode || code;
      this.setEditorTabCode(filename, finalCode);
    } else {
      const status = detail.run?.status || 'idle';
      const workingStatuses = ['idle', 'queued', 'planning', 'context_build', 'model_step', 'executing', 'awaiting_start', 'awaiting_approval'];
      if (workingStatuses.includes(status)) {
        if (!this.editorTabs || !this.editorTabs.some(t => t.code && t.code.trim())) {
          ideContainer.innerHTML = '<pre><code id="ide-code-block"># Nexora is generating code...\n# Please wait a moment.</code></pre>';
        }
      }
    }
  }

  updateRunStatusUI() {
    const run = this.state.get('currentRun');
    const pill = $('#chat-status');
    const send = $('#send-btn');
    const metaTitle = $('#chat-meta-title');
    const bar = $('#chat-input-bar');

    if (pill) {
      const status = run?.status || 'idle';
      pill.textContent = run ? `${status}${run.current_stage ? ` · ${run.current_stage}` : ''}` : 'idle';
      pill.className = 'chat-status-pill';
      if (TERMINAL.includes(status)) pill.classList.add(status === 'completed' ? 'st-ok' : 'st-bad');
      else if (status !== 'idle') pill.classList.add('st-running');
    }

    if (send) {
      const waitingForStart = ['queued', 'awaiting_start'].includes(run?.status);
      const active = this.isRunActive() && !waitingForStart;
      send.classList.toggle('stop-mode', active);
      const actionLabel = waitingForStart
        ? (run.status === 'queued' ? 'Start run' : 'Accept plan and execute')
        : active ? 'Cancel run' : 'Run task';
      send.title = actionLabel;
      send.setAttribute('aria-label', actionLabel);
      send.innerHTML = active
        ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>'
        : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>';
    }

    if (metaTitle) {
      metaTitle.textContent = run ? truncate(run.task_text, 58) : 'Nexora · secure coding agent';
      metaTitle.title = run ? run.task_text : '';
    }

    if (bar) bar.classList.toggle('glow-gold', run?.status === 'awaiting_approval');
    document.body.classList.toggle('policy-locked', run?.status === 'awaiting_start');
  }

  updateCost() {
    const run = this.state.get('currentRun');
    const chip = $('#chat-cost');
    if (!chip) return;
    const total = (run?.input_tokens_used || 0) + (run?.output_tokens_used || 0);
    if (!run || !total) { chip.hidden = true; return; }
    chip.hidden = false;
    chip.textContent = `${formatTokens(total)} tok`;
    chip.title = `${formatNumber(run.input_tokens_used)} in · ${formatNumber(run.output_tokens_used)} out · ${formatDuration(run.total_elapsed_ms)}`;
  }

  pendingApprovalCount() {
    const approvals = this.state.get('currentRunDetail')?.approvals || [];
    return approvals.filter((a) => a.status === 'pending').length;
  }

  updateRailBadges() {
    const pending = this.pendingApprovalCount();
    const btn = document.querySelector('[data-tool="approvals"]');
    if (btn) btn.classList.toggle('rail-badge', pending > 0);
    const security = document.querySelector('[data-tool="security"]');
    if (security) {
      const decision = this.state.get('currentRunDetail')?.security_decision?.decision;
      security.classList.toggle('rail-badge', ['blocked', 'needs_approval'].includes(decision));
      security.classList.toggle('rail-badge-hot', decision === 'needs_approval');
    }
    this.renderOverflowMenu();
  }

  async decideApproval(approvalId, approve) {
    const run = this.state.get('currentRun');
    if (!run) return toast('No active run.', 'warning');
    try {
      await window.NexoraApi.runs.approve(run.id, approvalId, approve);
      toast(approve ? 'Action approved.' : 'Action rejected.', approve ? 'success' : 'warning');
      await this.selectRun(run.id, { silent: true });
      this.startPolling(run.id);
    } catch (error) {
      toast(`Approval failed: ${error.message}`, 'error');
    }
  }

  newRun() {
    this.draftChatTitle = '';
    this.state.set('currentRun', null);
    this.state.set('currentRunDetail', null);
    document.body.classList.remove('response-mode');
    this.stopPolling();
    // Clear the active thread so the next submit starts a fresh conversation
    this.activeThreadRunId = null;
    this._updateThreadBadge();
    this.clearChat(true);
    const input = $('#message');
    if (input) {
      input.value = '';
      this.autoGrow(input);
      this.updateGhost();
    }
    input?.focus();
    this.renderRunsList();
    this.updateRunStatusUI();
    this.updateHeaderStats();
  }

  /* ================================================================ render */
  updateComposerChips() {
    const profile = (this.state.get('budgetProfiles') || [])
      .find((p) => p.id === this.state.get('selectedBudgetProfileId'))
      || this.state.get('defaultBudgetProfile');
    const budget = $('#budget-chip');
    if (budget) {
      budget.textContent = profile ? profile.name : 'No profile';
      budget.title = profile ? `${profile.max_steps} steps · ${profile.max_tool_calls} tool calls · ${profile.max_input_tokens} in / ${profile.max_output_tokens} out tokens` : 'Select a budget profile';
    }
  }

  renderAll() {
    this.renderRunsList();
    this.renderModelPicker();
    this.renderModelPickerLabel();
    this.renderOverflowMenu();
    this.renderPinnedBar();
    this.updateComposerChips();
    this.updateRunStatusUI();
    this.updateCost();
    this.updateRailBadges();
    this.updateHeaderStats();
    this.applyThemeClasses();
    this.historyEl.classList.toggle('compact-feed', this.compactFeed);
    this.renderWelcomeTip();
    if (modals.isOpen('tool')) this.renderToolModal();
  }

  renderWelcomeTip() {
    const tip = $('#welcome-tip');
    if (!tip) return;
    const tips = [
      'Tip: Ctrl+K opens the command palette.',
      'Tip: Ctrl+B toggles the sidebar.',
      'Tip: Ctrl+Enter submits the composer without leaving the keyboard.',
      'Tip: Keys 1–9 jump straight to a tool panel.',
      'Tip: Shift+Enter adds a line break.',
    ];
    tip.textContent = tips[Math.floor(Math.random() * tips.length)];
  }
}

/* ========================================================================== */
/* boot                                                                       */
/* ========================================================================== */
let app = null;

function boot() {
  app = new NexoraApp();
  window.NexoraApp = app;
  app.init().catch((error) => {
    console.error('Nexora failed to start', error);
    toast(`Startup error: ${error.message}`, 'error');
    $('#app-loader')?.classList.add('done');
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}

export { NexoraApp, SAMPLE_TASKS };