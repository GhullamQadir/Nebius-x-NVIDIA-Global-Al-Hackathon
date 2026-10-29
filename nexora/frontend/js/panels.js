/**
 * Nexora tool panels — the renderers behind the icon rail and the "+" tools
 * menu. Every panel is a pure `render(ctx) -> html` plus an optional
 * `bind(root, ctx)` for interactive rows (approvals, theme pickers, …).
 *
 * `ctx` is the shared `NexoraState` snapshot from js/state.js, extended with
 * live helper functions by js/app.js.
 */
import {
  esc, formatNumber, formatTokens, formatDuration, formatDateTime,
  relativeTime, humanize, tag, truncate, toneFor,
} from './ui/dom.js';
import { renderMarkdown, renderDiff } from './ui/markdown.js';
import { renderDiffViewer, bindDiffViewerEvents } from './ui/diff_viewer.js';

// Lucide-style SVG icon map (clean 1.5px stroke, unified visual weight)
const ICONS = {
  runs: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h4l3 8 4-16 3 8h4"/></svg>`,
  plan: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="12" y1="3" x2="12" y2="21"/></svg>`,
  policy: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 2a7 7 0 0 0-7 7c0 2.38 1.19 4.47 3 5.74V17a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-2.26c1.81-1.27 3-3.36 3-5.74a7 7 0 0 0-7-7z"/></svg>`,
  security: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/></svg>`,
  evidence: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>`,
  patch: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 16c0-2.8 0-4.2.588-5.222.215-.36.496-.5.822-.575h.182c.615-.137 1.25-.278 1.843-.365.82-.122 1.624-.182 2.32-.182h.183c.82 0 1.64.096 2.395.265.744.167 1.47.394 2.083.696.61.302 1.142.683 1.577 1.13.437.447.773.964.97 1.523.198.562.294 1.148.294 1.778v4c0 2.8 0 4.2-.588 5.222-.215.36-.496.5-.822.575h-.182c-.615.137-1.25.278-1.843.365-.82.122-1.624.182-2.32.182h-.183c-.82 0-1.64-.096-2.395-.265-.744-.167-1.47-.394-2.083-.696C5.862 20.147 5.33 19.766 4.895 19.32 4.458 18.873 4.122 18.356 3.924 17.798c-.198-.562-.294-1.148-.294-1.778v-4z"/><path d="M9 17v3l3-3 3 3v-3"/></svg>`,
  tests: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9 12l2 2 4-4"/><circle cx="12" cy="6" r="1"/><circle cx="6" cy="12" r="1"/><circle cx="18" cy="12" r="1"/><circle cx="12" cy="18" r="1"/></svg>`,
  approvals: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>`,
  audit: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 13H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v3zM20 13h-2a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v3zM8 19H6a2 2 0 0 1-2-2v-1a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v1a2 2 0 0 1-2 2zM20 19h-2a2 2 0 0 1-2-2v-1a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v1a2 2 0 0 1-2 2z"/></svg>`,
  router: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2z"/><path d="M3 10h18M16 14l2 2M14 18l2 2"/></svg>`,
  theme: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`,
  settings: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
  new: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>`,
  toggle: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>`,
  empty: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9 12l2 2 4-4"/></svg>`
};

const empty = (icon, title, body) => {
  const svg = ICONS[icon] || `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${icon}</svg>`;
  return `
  <div class="tool-empty">
    <div class="empty-icon">${svg}</div>
    <h3>${esc(title)}</h3>
    <p>${esc(body)}</p>
  </div>`;
};

const tile = (label, value, cls = '') => `
  <div class="stat-tile ${cls}">
    <div class="st-label">${esc(label)}</div>
    <div class="st-value">${value}</div>
  </div>`;

const meter = (label, used, total, gold = false) => {
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const over = total > 0 && used > total;
  return `
    <div class="meter">
      <div class="meter-head"><span>${esc(label)}</span><span>${formatNumber(used)} / ${formatNumber(total)}</span></div>
      <div class="meter-track"><div class="meter-fill ${over ? 'over' : gold ? 'gold' : ''}" style="width:${pct.toFixed(1)}%"></div></div>
    </div>`;
};

const kv = (pairs) => `
  <dl class="kv-grid">
    ${pairs.filter(Boolean).map(([k, v]) => `<dt>${esc(k)}</dt><dd class="mono">${v ?? '—'}</dd>`).join('')}
  </dl>`;

/** Shared ticker so only one countdown interval is alive at a time. */
let countdownTimer = null;
export function startCountdowns(root) {
  if (countdownTimer) clearInterval(countdownTimer);
  const nodes = Array.from(root.querySelectorAll('.countdown[data-expires]'));
  if (!nodes.length) return;
  const tick = () => {
    const now = Date.now();
    nodes.forEach((node) => {
      const expires = new Date(node.dataset.expires).getTime();
      if (Number.isNaN(expires)) return;
      const left = Math.round((expires - now) / 1000);
      if (left <= 0) {
        node.textContent = 'expired';
        node.style.color = 'var(--color-danger)';
        return;
      }
      const m = String(Math.floor(left / 60)).padStart(2, '0');
      const s = String(left % 60).padStart(2, '0');
      node.textContent = `${m}:${s} remaining`;
      node.style.color = left < 60 ? 'var(--color-warning)' : 'var(--fg)';
    });
  };
  tick();
  countdownTimer = setInterval(tick, 1000);
}

/* ========================================================================== */
/* Runs                                                                        */
/* ========================================================================== */
const runsPanel = {
  id: 'runs',
  label: 'Runs',
  icon: ICONS.runs,
  render(ctx) {
    const runs = ctx.runs || [];
    if (!runs.length) {
      return empty('⌁', 'No runs yet', 'Describe a task in the composer to create your first policy-gated run.');
    }
    return `
      <div class="list-rows">
        ${runs.map((run) => `
          <div class="row-card lv-${esc(toneFor(run.status))}" data-run-id="${esc(run.id)}" style="cursor:pointer">
            <div class="row-head">
              <span class="row-title">${esc(truncate(run.task_text, 74))}</span>
              ${tag(run.status)}
            </div>
            <div class="row-sub">
              ${esc(run.id)} · stage ${esc(run.current_stage || '—')} ·
              ${formatNumber(run.steps_completed)} steps · ${formatNumber(run.tool_calls_count)} tool calls ·
              ${relativeTime(run.created_at)}
            </div>
          </div>`).join('')}
      </div>`;
  },
  bind(root, ctx) {
    root.querySelectorAll('[data-run-id]').forEach((node) => {
      node.addEventListener('click', () => ctx.actions.selectRun(node.dataset.runId));
    });
  },
};

/* ========================================================================== */
/* Plan                                                                        */
/* ========================================================================== */
const planPanel = {
  id: 'plan',
  label: 'Plan',
  icon: ICONS.plan,
  render(ctx) {
    const detail = ctx.currentRunDetail;
    if (!detail) return empty('◈', 'No plan yet', 'Start a run — the planner emits a hypothesis, candidate files, tool sequence and stop conditions.');

    const analysis = detail.task_analysis;
    const plan = detail.plan;
    if (!analysis && !plan) return empty('◈', 'Planning not started', 'The planner runs after the security gateway clears the task. Poll the run to watch it appear.');

    const steps = [
      analysis && {
        n: 1,
        title: 'Objective',
        body: analysis.objective || '—',
      },
      analysis && {
        n: 2,
        title: 'Hypothesis',
        body: plan?.hypothesis || '—',
      },
      plan && {
        n: 3,
        title: 'Candidate files',
        body: (plan.candidate_files || []).length
          ? (plan.candidate_files || []).map((f) => `\`${f}\``).join(', ')
          : '—',
      },
      plan && {
        n: 4,
        title: 'Tool sequence',
        body: (plan.tool_sequence || []).length
          ? (plan.tool_sequence || []).map((t) => (typeof t === 'string' ? `\`${t}\`` : `\`${t.tool || t.name || JSON.stringify(t)}\``)).join(' → ')
          : '—',
      },
      plan?.test_command && {
        n: 5,
        title: 'Verification',
        body: `Run \`${plan.test_command}\`${plan.estimated_time_seconds ? ` (est. ${plan.estimated_time_seconds}s)` : ''}`,
      },
    ].filter(Boolean);

    return `
      <div class="admin-card">
        <h3>Task analysis ${analysis ? tag(analysis.risk_class) : ''}</h3>
        ${kv([
          ['Risk class', analysis?.risk_class ? tag(analysis.risk_class) : '—'],
          ['Analyzer', analysis?.analyzer_version ? `<code>${esc(analysis.analyzer_version)}</code>` : '—'],
          ['Planner', plan?.planner_version ? `<code>${esc(plan.planner_version)}</code>` : '—'],
          ['Accepted', plan ? (plan.is_accepted ? tag('approved') : tag('pending')) : '—'],
          ['Est. tokens', plan?.estimated_tokens != null ? formatTokens(plan.estimated_tokens) : '—'],
          ['Stop conditions', (plan?.stop_conditions || []).length ? esc((plan.stop_conditions || []).join('; ')) : '—'],
        ])}
      </div>

      ${analysis?.constraints?.length ? `
        <div class="admin-card">
          <h3>Constraints</h3>
          <ul style="margin:0;padding-left:18px;font-size:11.5px;line-height:1.7">
            ${(analysis.constraints || []).map((c) => `<li>${esc(typeof c === 'string' ? c : JSON.stringify(c))}</li>`).join('')}
          </ul>
        </div>` : ''}

      ${analysis?.acceptance_tests?.length ? `
        <div class="admin-card">
          <h3>Acceptance tests</h3>
          <ul style="margin:0;padding-left:18px;font-size:11.5px;line-height:1.7">
            ${(analysis.acceptance_tests || []).map((c) => `<li>${esc(typeof c === 'string' ? c : JSON.stringify(c))}</li>`).join('')}
          </ul>
        </div>` : ''}

      <div class="admin-card">
        <h3>Execution plan</h3>
        <div class="plan-steps">
          ${steps.map((s) => `
            <div class="plan-step">
              <span class="plan-label">${s.n}</span>
              <div><strong>${esc(s.title)}</strong><p>${s.body}</p></div>
            </div>`).join('')}
        </div>
      </div>`;
  },
};

/* ========================================================================== */
/* Policy                                                                     */
/* ========================================================================== */
const policyPanel = {
  id: 'policy',
  label: 'Policy',
  icon: ICONS.policy,
  render(ctx) {
    const detail = ctx.currentRunDetail;
    const decisions = detail?.policy_decisions || [];
    const summary = detail?.run_result?.policy_decisions_summary;
    const blocked = detail?.run_result?.blocked_actions || [];

    const staticRules = [
      ['ALLOW', 'Repository access scoped to the active workspace.'],
      ['REVIEW', 'Every patch must pass validation before sign-off.'],
      ['TRACE', 'All actions are logged with tool sequence and reason codes.'],
    ];

    return `
      <div class="admin-card">
        <h3>Policy posture</h3>
        <div class="list-rows">
          ${staticRules.map(([level, text]) => `
            <div class="row-card lv-${level === 'ALLOW' ? 'allow' : 'monitor'}">
              <div class="row-head"><span class="row-title">${esc(text)}</span>${tag(level)}</div>
            </div>`).join('')}
        </div>
      </div>

      ${summary ? `
        <div class="admin-card">
          <h3>Decision summary</h3>
          ${kv(Object.entries(summary).map(([k, v]) => [k, esc(typeof v === 'object' ? JSON.stringify(v) : String(v))]))}
        </div>` : ''}

      <div class="admin-card">
        <h3>Decisions ${decisions.length ? `<span class="tag tag-neutral">${decisions.length}</span>` : ''}</h3>
        ${decisions.length ? `
          <div class="list-rows">
            ${decisions.map((d) => `
              <div class="row-card lv-${esc(toneFor(d.decision))}">
                <div class="row-head">
                  <span class="row-title">${esc(d.capability || 'capability')}</span>
                  ${tag(d.decision)}
                </div>
                <div class="row-sub">
                  ${d.risk_level ? `risk ${esc(d.risk_level)} · ` : ''}
                  reason codes: ${esc((d.reason_codes || []).join(', ') || '—')}
                  ${d.target_path ? `<br>target: <code>${esc(d.target_path)}</code>` : ''}
                </div>
                <div class="row-sub">policy ${esc(d.policy_version || '—')} · engine ${esc(d.engine_version || '—')} · ${relativeTime(d.created_at)}</div>
              </div>`).join('')}
          </div>`
          : '<div class="empty-hint">No policy decisions recorded for this run yet.</div>'}
      </div>

      ${blocked.length ? `
        <div class="admin-card">
          <h3>Blocked actions</h3>
          <div class="list-rows">
            ${blocked.map((b) => `<div class="row-card lv-deny"><div class="row-sub">${esc(JSON.stringify(b))}</div></div>`).join('')}
          </div>
        </div>` : ''}`;
  },
};

/* ========================================================================== */
/* Security                                                                   */
/* ========================================================================== */
const securityPanel = {
  id: 'security',
  label: 'Security',
  icon: ICONS.security,
  render(ctx) {
    const detail = ctx.currentRunDetail;
    if (!detail) return empty('security', 'Security review pending', 'The gateway evaluates injection risk, capability scope and provenance before a run starts.');

    const sec = detail.security_decision;
    const injections = sec?.injection_findings || [];

    return `
      <div class="admin-card">
        <h3>Gateway decision</h3>
        ${sec ? `
          ${kv([
            ['Decision', tag(sec.decision)],
            ['Risk level', sec.risk_level ? tag(sec.risk_level) : '—'],
            ['Gateway', sec.gateway_version ? `<code>${esc(sec.gateway_version)}</code>` : '—'],
            ['Reason codes', esc((sec.reason_codes || []).join(', ') || '—')],
          ])}
          ${Object.keys(sec.provenance_summary || {}).length ? `
            <div style="margin-top:10px">${kv(Object.entries(sec.provenance_summary).map(([k, v]) => [k, esc(typeof v === 'object' ? JSON.stringify(v) : String(v))]))}</div>` : ''}
        ` : '<div class="empty-hint">No gateway record for this run.</div>'}
      </div>

      <div class="admin-card">
        <h3>Injection scan ${injections.length ? tag('warning') : tag('pass')}</h3>
        ${injections.length ? `
          <div class="list-rows">
            ${injections.map((f) => `
              <div class="row-card lv-monitor">
                <div class="row-head"><span class="row-title">${esc(f.pattern || f.kind || 'finding')}</span>${tag(f.severity || 'warning')}</div>
                <div class="row-sub">${esc(f.excerpt || f.detail || JSON.stringify(f))}</div>
              </div>`).join('')}
          </div>`
          : '<div class="empty-hint">No prompt-injection patterns detected.</div>'}
      </div>

      <div class="admin-card">
        <h3>Capability requests</h3>
        ${(detail.tool_requests || []).length ? `
          <div class="list-rows">
            ${(detail.tool_requests || []).map((t) => `
              <div class="row-card lv-${esc(toneFor(t.expected_risk || 'pending'))}">
                <div class="row-head">
                  <span class="row-title">${esc(t.tool_name)}</span>
                  ${t.expected_risk ? tag(t.expected_risk) : ''}
                </div>
                <div class="row-sub">step ${t.step_number} · provenance <code>${esc(t.provenance || '—')}</code></div>
                <div class="row-sub"><code>${esc(JSON.stringify(t.arguments || {}))}</code></div>
              </div>`).join('')}
          </div>`
          : '<div class="empty-hint">No tool capabilities requested.</div>'}
      </div>`;
  },
};

/* ========================================================================== */
/* Evidence                                                                   */
/* ========================================================================== */
const evidencePanel = {
  id: 'evidence',
  label: 'Evidence',
  icon: ICONS.evidence,
  render(ctx) {
    const run = ctx.currentRun;
    if (!run) return empty('▦', 'No evidence captured', 'Once a run completes, tokens, timings, patch hash and the evidence report appear here.');

    const detail = ctx.currentRunDetail;
    const result = detail?.run_result;
    const profile = ctx.selectedProfile;
    const report = result?.evidence_report || {};

    const inPct = profile?.max_input_tokens ? (run.input_tokens_used / profile.max_input_tokens) * 100 : 0;
    const outPct = profile?.max_output_tokens ? (run.output_tokens_used / profile.max_output_tokens) * 100 : 0;
    const stepsPct = profile?.max_steps ? (run.steps_completed / profile.max_steps) * 100 : 0;
    const callsPct = profile?.max_tool_calls ? (run.tool_calls_count / profile.max_tool_calls) * 100 : 0;

    return `
      <div class="admin-card">
        <h3>Run metrics</h3>
        <div class="stat-grid">
          ${tile('Input tokens', formatTokens(run.input_tokens_used))}
          ${tile('Output tokens', formatTokens(run.output_tokens_used), 'gold')}
          ${tile('Steps', formatNumber(run.steps_completed))}
          ${tile('Tool calls', formatNumber(run.tool_calls_count))}
          ${tile('Retries', formatNumber(run.retries_count))}
          ${tile('Elapsed', formatDuration(run.total_elapsed_ms))}
          ${tile('Final status', result?.final_status ? tag(result.final_status) : esc(run.status || '—'), (result?.final_status || '').includes('fail') ? 'bad' : 'good')}
          ${tile('Patch hash', result?.patch_hash ? `<code style="font-size:12px">${esc(String(result.patch_hash).slice(0, 14))}</code>` : '—', 'gold')}
        </div>
      </div>

      <div class="admin-card">
        <h3>Budget profile — ${esc(profile?.name || 'none')}</h3>
        <div style="display:flex;flex-direction:column;gap:10px">
          ${profile?.max_input_tokens ? meter('Input token budget', run.input_tokens_used, profile.max_input_tokens) : ''}
          ${profile?.max_output_tokens ? meter('Output token budget', run.output_tokens_used, profile.max_output_tokens, true) : ''}
          ${profile?.max_steps ? meter('Step budget', run.steps_completed, profile.max_steps) : ''}
          ${profile?.max_tool_calls ? meter('Tool-call budget', run.tool_calls_count, profile.max_tool_calls, true) : ''}
        </div>
        <div class="row-sub" style="margin-top:8px">
          in ${inPct.toFixed(0)}% · out ${outPct.toFixed(0)}% · steps ${stepsPct.toFixed(0)}% · calls ${callsPct.toFixed(0)}% of profile limits
        </div>
      </div>

      <div class="admin-card">
        <h3>Context packages</h3>
        ${(detail?.context_packages || []).length ? `
          <div class="list-rows">
            ${(detail.context_packages || []).map((c) => `
              <div class="row-card lv-info">
                <div class="row-head">
                  <span class="row-title">Step ${c.step_number}</span>
                  <span class="tag tag-neutral">${formatTokens(c.estimated_input_tokens ?? 0)} tok</span>
                </div>
                <div class="row-sub">
                  files: ${esc((c.included_files || []).join(', ') || '—')}
                  ${(c.omitted_categories || []).length ? `<br>omitted: ${esc((c.omitted_categories || []).join(', '))}` : ''}
                </div>
                <div class="row-sub">
                  cache hits ${formatNumber(c.cache_hits)} · compression ${c.compression_ratio != null ? `${(c.compression_ratio * 100).toFixed(0)}%` : '—'}
                  · optimizer ${esc(c.context_optimizer_version || '—')}
                </div>
              </div>`).join('')}
          </div>`
          : '<div class="empty-hint">No context packages yet.</div>'}
      </div>

      <div class="admin-card">
        <h3>Evidence report</h3>
        ${Object.keys(report).length
          ? kv(Object.entries(report).map(([k, v]) => [k, esc(typeof v === 'object' ? JSON.stringify(v) : String(v))]))
          : '<div class="empty-hint">No evidence report emitted.</div>'}
      </div>

      ${result?.limitations?.length ? `
        <div class="admin-card">
          <h3>Limitations</h3>
          <ul style="margin:0;padding-left:18px;font-size:11.5px;line-height:1.7">
            ${result.limitations.map((l) => `<li>${esc(typeof l === 'string' ? l : JSON.stringify(l))}</li>`).join('')}
          </ul>
        </div>` : ''}`;
  },
};

/* ========================================================================== */
/* Patch                                                                      */
/* ========================================================================== */
const patchPanel = {
  id: 'patch',
  label: 'Patch',
  icon: ICONS.patch,
  render(ctx) {
    const result = ctx.currentRunDetail?.run_result;
    const patch = result?.patch_content;
    if (!patch) return empty('⧉', 'No patch generated', 'The diff appears once the agent writes inside the sandbox and the critic passes.');
    const files = patch.match(/^\+\+\+ b\/(.*)$/gm) || [];
    return `
      <div class="admin-card">
        <h3>Patch</h3>
        ${kv([
          ['Hash', result.patch_hash ? `<code>${esc(result.patch_hash)}</code>` : '—'],
          ['Files touched', files.length ? files.map((f) => esc(f.replace(/^\+\+\+ b\//, ''))).join(', ') : '—'],
          ['Lines', formatNumber(patch.split('\n').length)],
          ['Final status', tag(result.final_status || 'unknown')],
        ])}
      </div>
      <div style="margin-top: 14px; border-radius: 8px; overflow: hidden; border: 1px solid rgba(255,255,255,0.08);">
        ${renderDiffViewer(patch, patch, 'split')}
      </div>`;
  },
  bind(root) {
    bindDiffViewerEvents(root);
  },
};

/* ========================================================================== */
/* Validation                                                                 */
/* ========================================================================== */
const testsPanel = {
  id: 'tests',
  label: 'Validation',
  icon: ICONS.tests,
  render(ctx) {
    const detail = ctx.currentRunDetail;
    const findings = detail?.validation_findings || [];
    const execs = detail?.tool_executions || [];
    const summary = detail?.run_result?.test_summary;
    const critic = detail?.run_result?.critic_findings;

    if (!findings.length && !execs.length && !summary) {
      return empty('tests', 'No validation yet', 'Test runs, lint output and critic findings stream in during the validating stage.');
    }

    const pass = findings.filter((f) => String(f.status).toLowerCase() === 'pass').length;

    return `
      ${summary ? `
        <div class="admin-card">
          <h3>Test summary</h3>
          ${kv(Object.entries(summary).map(([k, v]) => [k, esc(typeof v === 'object' ? JSON.stringify(v) : String(v))]))}
        </div>` : ''}

      <div class="admin-card">
        <h3>Findings ${findings.length ? `<span class="tag tag-${pass === findings.length ? 'allow' : 'monitor'}">${pass}/${findings.length} pass</span>` : ''}</h3>
        ${findings.length ? `
          <div class="list-rows">
            ${findings.map((f) => `
              <div class="row-card lv-${esc(toneFor(f.status))}">
                <div class="row-head">
                  <span class="row-title">${esc(f.check_type)}</span>
                  ${tag(f.status)}
                </div>
                <div class="row-sub">step ${f.step_number} · ${esc(f.message || '—')}</div>
                ${f.details && Object.keys(f.details).length ? `<div class="row-sub"><code>${esc(JSON.stringify(f.details))}</code></div>` : ''}
              </div>`).join('')}
          </div>` : '<div class="empty-hint">No validation findings recorded.</div>'}
      </div>

      ${critic ? `
        <div class="admin-card">
          <h3>Critic</h3>
          ${kv(Object.entries(critic).map(([k, v]) => [k, esc(typeof v === 'object' ? JSON.stringify(v) : String(v))]))}
        </div>` : ''}

      <div class="admin-card">
        <h3>Tool executions</h3>
        ${execs.length ? `
          <div class="list-rows">
            ${execs.map((x) => `
              <details class="row-card lv-${esc(toneFor(x.execution_status))}">
                <summary style="cursor:pointer;display:flex;align-items:center;gap:8px;justify-content:space-between">
                  <span class="row-title">${esc(x.tool_name)}</span>
                  ${tag(x.execution_status)}
                </summary>
                <div class="row-sub">
                  ${formatDuration(x.duration_ms)} · exit ${x.exit_code ?? '—'} · sandbox ${esc(x.sandbox_id || '—')}
                </div>
                ${x.stdout ? `<pre class="code-block" style="padding:8px;margin-top:6px;font-size:11px">${esc(x.stdout)}</pre>` : ''}
                ${x.stderr ? `<pre class="code-block" style="padding:8px;margin-top:6px;font-size:11px">${esc(x.stderr)}</pre>` : ''}
              </details>`).join('')}
          </div>` : '<div class="empty-hint">No tool executions yet.</div>'}
      </div>`;
  },
};

/* ========================================================================== */
/* Approvals                                                                  */
/* ========================================================================== */
const approvalsPanel = {
  id: 'approvals',
  label: 'Approvals',
  icon: ICONS.approvals,
  render(ctx) {
    const approvals = ctx.currentRunDetail?.approvals || [];
    if (!approvals.length) {
      return empty('approvals', 'No approvals pending', 'When the policy engine returns REQUIRE_APPROVAL the action lands here for a human decision.');
    }
    const pending = approvals.filter((a) => a.status === 'pending');
    return `
      <div class="admin-card">
        <h3>Approval queue ${pending.length ? `<span class="tag tag-pending">${pending.length} pending</span>` : `<span class="tag tag-allow">all resolved</span>`}</h3>
        <div class="list-rows">
          ${approvals.map((a) => `
            <div class="row-card lv-${esc(toneFor(a.status))}" data-approval-id="${esc(a.id)}">
              <div class="row-head">
                <span class="row-title">${esc(a.scope_description || 'action')}</span>
                ${tag(a.status)}
              </div>
              <div class="row-sub">
                id ${esc(a.id)} · decision ${esc(a.policy_decision_id || '—')}
              </div>
              <div class="row-sub">
                ${a.status === 'pending'
    ? `expires <span class="countdown" data-expires="${esc(a.expires_at)}">${esc(formatDateTime(a.expires_at))}</span>`
    : `decided ${esc(formatDateTime(a.decided_at))}${a.approver_id ? ` by ${esc(a.approver_id)}` : ''}`}
              </div>
              ${a.status === 'pending' ? `
                <div class="row-actions">
                  <button class="btn btn-sm btn-primary" data-approve="1">Approve</button>
                  <button class="btn btn-sm btn-danger" data-approve="0">Reject</button>
                </div>` : ''}
            </div>`).join('')}
        </div>
      </div>`;
  },
  bind(root, ctx) {
    startCountdowns(root);
    root.querySelectorAll('[data-approve]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const card = btn.closest('[data-approval-id]');
        const approvalId = card?.dataset.approvalId;
        if (!approvalId) return;
        btn.disabled = true;
        try {
          await ctx.actions.decideApproval(approvalId, btn.dataset.approve === '1');
        } finally {
          btn.disabled = false;
        }
      });
    });
  },
};

/* ========================================================================== */
/* Audit                                                                      */
/* ========================================================================== */

/** Reconstruct the canonical event digest and compare it to the stored hash. */
async function sha256Hex(text) {
  if (!globalThis.crypto?.subtle) return null;
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Verify the audit hash chain: each event's digest must match the stored
 * current_hash and link back to the previous event's hash.
 */
export async function verifyAuditChain(auditEvents, runId) {
  const errors = [];
  let previousHash = null;
  let checked = 0;

  for (const event of auditEvents) {
    const canonical = JSON.stringify({
      run_id: runId,
      event_index: event.event_index,
      event_type: event.event_type,
      event_data: event.event_data,
      previous_hash: previousHash,
    });
    const computed = await sha256Hex(canonical);
    if (computed) {
      checked += 1;
      if (computed !== event.current_hash) {
        errors.push(`Digest mismatch at index ${event.event_index}`);
      }
    }
    if (event.previous_hash !== previousHash) {
      errors.push(`Previous-hash mismatch at index ${event.event_index}`);
    }
    previousHash = event.current_hash;
  }
  return { verified: errors.length === 0, errors, checked, final_hash: previousHash };
}

export function downloadAuditExport(runId, auditEvents) {
  const payload = {
    run_id: runId,
    exported_at: new Date().toISOString(),
    total_events: auditEvents.length,
    events: auditEvents.map((e) => ({
      event_index: e.event_index,
      event_type: e.event_type,
      event_data: e.event_data,
      previous_hash: e.previous_hash,
      current_hash: e.current_hash,
      timestamp: e.created_at,
    })),
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `Nexora-audit-${runId}-${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

const auditPanel = {
  id: 'audit',
  label: 'Audit',
  icon: ICONS.audit,
  render(ctx) {
    const events = ctx.currentRunDetail?.audit_events || [];
    const timeline = ctx.currentRunDetail?.events || [];
    const runId = ctx.currentRun?.id;
    if (!events.length && !timeline.length) {
      return empty('audit', 'No audit trail', 'Hash-chained audit events are emitted for every state transition and tool call.');
    }
    return `
      ${events.length ? `
        <div class="admin-card">
          <h3>Chain integrity</h3>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn btn-sm btn-gold" data-audit-action="verify" ${runId ? '' : 'disabled'}>Verify hash chain</button>
            <button class="btn btn-sm" data-audit-action="export" ${runId ? '' : 'disabled'}>Export JSON</button>
          </div>
          <div id="chain-result" style="margin-top:10px"></div>
        </div>` : ''}

      ${timeline.length ? `
        <div class="admin-card">
          <h3>Event timeline</h3>
          <div class="timeline">
            ${timeline.map((e) => `
              <div class="timeline-item">
                <div class="timeline-icon">•</div>
                <div class="timeline-content">
                  <div class="timeline-stage">${esc(e.event_type)}</div>
                  <div class="timeline-message">${esc(e.message || '—')}</div>
                  <div class="timeline-meta">${esc(e.stage || '—')} · ${formatDateTime(e.created_at)}</div>
                </div>
              </div>`).join('')}
          </div>
        </div>` : ''}

      <div class="admin-card">
        <h3>Hash chain ${events.length ? `<span class="tag tag-neutral">${events.length} events</span>` : ''}</h3>
        ${events.length ? `
          <div class="timeline">
            ${events.map((e) => `
              <div class="timeline-item completed">
                <div class="timeline-icon">#</div>
                <div class="timeline-content">
                  <div class="timeline-stage">${esc(e.event_type)}</div>
                  <div class="timeline-meta">idx ${e.event_index} · ${formatDateTime(e.created_at)}</div>
                  <div class="row-sub"><code>${esc(String(e.current_hash || '').slice(0, 28))}</code></div>
                  ${e.previous_hash ? `<div class="timeline-meta">prev <code>${esc(String(e.previous_hash).slice(0, 20))}</code></div>` : ''}
                  <details><summary style="cursor:pointer;font-size:10.5px;color:var(--color-muted)">payload</summary>
                    <pre class="code-block" style="padding:8px;margin-top:6px;font-size:10.5px">${esc(JSON.stringify(e.event_data || {}, null, 2))}</pre>
                  </details>
                </div>
              </div>`).join('')}
          </div>` : '<div class="empty-hint">No audit events recorded.</div>'}
      </div>`;
  },
  bind(root, ctx) {
    root.querySelectorAll('[data-audit-action]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const runId = ctx.currentRun?.id;
        const events = ctx.currentRunDetail?.audit_events || [];
        const out = root.querySelector('#chain-result');
        btn.disabled = true;
        try {
          if (btn.dataset.auditAction === 'export') {
            downloadAuditExport(runId, events);
            if (out) out.innerHTML = `<span class="tag tag-allow">exported ${events.length} events</span>`;
          } else {
            if (out) out.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
            const result = await verifyAuditChain(events, runId);
            if (out) {
              out.innerHTML = result.verified
                ? `<span class="tag tag-allow">chain verified</span> <span class="row-sub">${result.checked} digest${result.checked === 1 ? '' : 's'} recomputed · head <code>${esc(String(result.final_hash || '').slice(0, 20))}</code></span>`
                : `<span class="tag tag-deny">chain broken</span><ul style="margin:6px 0 0;padding-left:18px;font-size:11px">${result.errors.slice(0, 8).map((e) => `<li>${esc(e)}</li>`).join('')}</ul>`;
            }
          }
        } finally {
          btn.disabled = false;
        }
      });
    });
  },
};

/* ========================================================================== */
/* Router — standalone packages/* layer                                        */
/* ========================================================================== */
const routerPanel = {
  id: 'router',
  label: 'Router',
  icon: ICONS.router,
  render(ctx) {
    const pkg = ctx.packageRouting;
    if (!pkg) {
      return empty('⇄', 'Package layer not loaded', 'Reload the data to fetch /api/v1/packages/routing from the standalone packages.');
    }

    const providers = pkg.providers || [];
    const decisions = pkg.decisions || [];
    const nebius = providers.find((p) => p.name === 'nebius');
    const tierMap = Object.entries(pkg.router?.tier_map || {}).map(([k, v]) => `${k} → ${v}`).join(' · ');

    return `
      <div class="admin-card">
        <h3>Standalone packages ${tag('imported')}</h3>
        <div class="list-rows">
          ${(pkg.packages || []).map((p) => `
            <div class="row-card lv-info">
              <div class="row-head"><span class="row-title mono">${esc(p)}</span>${tag('active')}</div>
            </div>`).join('')}
        </div>
        <div class="row-sub" style="margin-top:8px">
          router <code>${esc(pkg.router?.class || '—')}</code><br>
          tier map ${esc(tierMap || '—')}
        </div>
      </div>

      <div class="admin-card">
        <h3>Provider adapters</h3>
        <div class="list-rows">
          ${providers.map((p) => `
            <div class="row-card lv-${p.configured ? 'allow' : 'monitor'}">
              <div class="row-head">
                <span class="row-title mono">${esc(p.adapter)}</span>
                ${tag(p.configured ? 'configured' : 'not configured')}
              </div>
              <div class="row-sub">
                ${esc(p.kind)} adapter${p.base_url ? ` · <code>${esc(p.base_url)}</code>` : ''}
                ${p.timeout_ms != null ? ` · timeout ${formatNumber(p.timeout_ms)} ms` : ''}
              </div>
              <div class="row-sub">models: ${esc((p.available_models || []).join(', ') || '—')}</div>
              ${p.note ? `<div class="row-sub">${esc(p.note)}</div>` : ''}
            </div>`).join('')}
        </div>
      </div>

      <div class="admin-card">
        <h3>Tier decisions ${tag(decisions.length, 'tag-neutral')}</h3>
        <div class="list-rows">
          ${decisions.map((d) => `
            <div class="row-card lv-info">
              <div class="row-head">
                <span class="row-title">${esc(d.task_complexity)} → ${esc(d.registry_display_name || d.registry_model_id || 'no registry row')}</span>
                ${tag(d.provider)}
              </div>
              <div class="row-sub">package picked <code>${esc(d.package_model_id)}</code></div>
              <div class="row-sub">
                reason <code>${esc(d.routing_reason)}</code> ·
                tier ${esc(d.package_tier || '—')} → ${esc(d.registry_tier || '—')}
              </div>
              ${(d.alternatives_considered || []).length
    ? `<div class="row-sub">alternatives: ${esc(d.alternatives_considered.join(', '))}</div>`
    : ''}
            </div>`).join('')}
        </div>
      </div>

      <div class="admin-card">
        <h3>Live adapter check</h3>
        <div class="row-sub" style="margin-bottom:8px">
          Sends one request through <code>packages/nebius_adapter</code> and prints the provider-neutral
          <code>ModelResponse</code> (tokens, latency, routing reason).
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn btn-sm" data-pkg-run="nebius" ${nebius?.configured ? '' : 'disabled'}>Run Nebius completion</button>
          <button class="btn btn-sm" data-pkg-refresh>Refresh routing</button>
        </div>
        <div id="pkg-complete-result" style="margin-top:10px"></div>
      </div>`;
  },
  bind(root, ctx) {
    const out = root.querySelector('#pkg-complete-result');

    root.querySelectorAll('[data-pkg-run]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const provider = btn.dataset.pkgRun;
        btn.disabled = true;
        if (out) out.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
        try {
          const res = await ctx.actions.completeViaPackage({
            prompt: 'Summarise why this tier was selected, in one sentence.',
            provider,
            task_complexity: 'moderate',
          });
          if (out) {
            out.innerHTML = `
              <div class="admin-card" style="padding:10px">
                ${kv([
                  ['Provider', tag(res.provider)],
                  ['Model used', `<code>${esc(res.model_used)}</code>`],
                  ['Routing reason', `<code>${esc(res.routing_reason)}</code>`],
                  ['Tokens', `${formatNumber(res.input_tokens)} in · ${formatNumber(res.output_tokens)} out · ${formatNumber(res.total_tokens)} total`],
                  ['Latency', `${Number(res.latency_ms || 0).toFixed(1)} ms`],
                  ['Finish reason', esc(res.finish_reason)],
                  ['Registry row', `<code>${esc(res.routing_decision?.registry_model_id || '—')}</code>`],
                ])}
                ${res.content ? `<pre class="code-block" style="padding:8px;margin-top:6px;font-size:11px">${esc(res.content)}</pre>` : ''}
              </div>`;
          }
        } catch (err) {
          if (out) out.innerHTML = `<span class="tag tag-deny">${esc(err?.message || String(err))}</span>`;
        } finally {
          btn.disabled = false;
        }
      });
    });

    root.querySelector('[data-pkg-refresh]')?.addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        await ctx.actions.reloadPackageRouting();
      } catch (err) {
        if (out) out.innerHTML = `<span class="tag tag-deny">${esc(err?.message || String(err))}</span>`;
      } finally {
        btn.disabled = false;
      }
    });
  },
};

export const PANELS = [
  runsPanel,
];

export const PANEL_MAP = Object.fromEntries(PANELS.map((p) => [p.id, p]));

/** Rail buttons flag which panel is currently showing. */
export function setActivePanel(id) {
  document.querySelectorAll('[data-tool]').forEach((node) => {
    node.classList.toggle('active-section', node.dataset.tool === id);
  });
}

export { empty, tile, meter, kv, tag, humanize, formatNumber, renderMarkdown, ICONS };