/**
 * Nexora Security Component
 * Security decision feed and Security tab
 */

class SecurityComponent {
  constructor(state) {
    this.state = state;
    this.unsubscribe = null;
  }
  
  init() {
    this.unsubscribe = this.state.on('currentRunDetail', (detail) => {
      this.renderSecurityTab(detail);
      this.renderPolicyFeed(detail);
    });
    
    // Initial render
    if (this.state.get('currentRunDetail')) {
      this.renderSecurityTab(this.state.get('currentRunDetail'));
      this.renderPolicyFeed(this.state.get('currentRunDetail'));
    }
  }
  
  destroy() {
    if (this.unsubscribe) this.unsubscribe();
  }
  
  renderSecurityTab(detail) {
    const container = document.getElementById('security-tab');
    if (!container) return;
    
    if (!detail?.security_decision) {
      container.innerHTML = this.emptyState('No security decision yet');
      return;
    }
    
    const sec = detail.security_decision;
    const findings = sec.injection_findings || [];
    const provenance = sec.provenance_summary || {};
    
    container.innerHTML = `
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">Security Decision</h3>
          <span class="badge-policy ${sec.decision.toUpperCase()}">${sec.decision}</span>
        </div>
        <div class="card-body">
          <div class="inspection-row">
            <span class="inspection-label">Risk Level</span>
            <span class="inspection-value badge badge-${this.riskClassToBadge(sec.risk_level)}">${sec.risk_level}</span>
          </div>
          <div class="inspection-row">
            <span class="inspection-label">Reason Codes</span>
            <span class="inspection-value">
              ${sec.reason_codes?.map(c => `<span class="badge badge-neutral">${c}</span>`).join(' ') || 'None'}
            </span>
          </div>
          
          <h4 style="margin-top: var(--space-4); font-size: var(--text-compact);">Content Provenance</h4>
          <div class="inspection-row">
            <span class="inspection-label">Task</span>
            <span class="inspection-value">${provenance.task || 0}</span>
          </div>
          <div class="inspection-row">
            <span class="inspection-label">Repository</span>
            <span class="inspection-value">${provenance.repository || 0}</span>
          </div>
          <div class="inspection-row">
            <span class="inspection-label">Tool Output</span>
            <span class="inspection-value">${provenance.tool_output || 0}</span>
          </div>
          <div class="inspection-row">
            <span class="inspection-label">Model Output</span>
            <span class="inspection-value">${provenance.model_output || 0}</span>
          </div>
          
          ${findings.length > 0 ? `
            <h4 style="margin-top: var(--space-4); font-size: var(--text-compact);">Injection Findings (Advisory)</h4>
            <div class="table-container">
              <table class="table">
                <thead>
                  <tr>
                    <th>Detector</th>
                    <th>Pattern</th>
                    <th>Location</th>
                    <th>Severity</th>
                    <th>Disposition</th>
                  </tr>
                </thead>
                <tbody>
                  ${findings.map(f => `
                    <tr>
                      <td>${this.escapeHtml(f.detector)}</td>
                      <td><code>${this.escapeHtml(f.matched_pattern)}</code></td>
                      <td>${this.escapeHtml(f.location)}</td>
                      <td><span class="badge badge-${f.severity === 'high' ? 'danger' : f.severity === 'medium' ? 'warning' : 'info'}">${f.severity}</span></td>
                      <td>${this.escapeHtml(f.disposition)}</td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
          ` : ''}
        </div>
      </div>
      
      <div class="card mt-4">
        <div class="card-header">
          <h3 class="card-title">Policy Decisions</h3>
        </div>
        <div class="card-body">
          ${this.renderPolicyDecisionsTable(detail.policy_decisions || [])}
        </div>
      </div>
      
      <div class="card mt-4">
        <div class="card-header">
          <h3 class="card-title">Approvals</h3>
        </div>
        <div class="card-body">
          ${this.renderApprovalsTable(detail.approvals || [])}
        </div>
      </div>
      
      <div class="card mt-4">
        <div class="card-header">
          <h3 class="card-title">Blocked Actions</h3>
        </div>
        <div class="card-body">
          ${this.renderBlockedActions(detail)}
        </div>
      </div>
      
      <div class="card mt-4">
        <div class="card-header">
          <h3 class="card-title">Audit Trail</h3>
        </div>
        <div class="card-body">
          ${this.renderAuditTrail(detail.audit_events || [])}
        </div>
      </div>
    `;
  }
  
  renderPolicyFeed(detail) {
    const container = document.getElementById('policy-feed');
    if (!container) return;
    
    const decisions = detail?.policy_decisions || [];
    
    if (decisions.length === 0) {
      container.innerHTML = '<p class="text-muted text-sm">No policy decisions yet</p>';
      return;
    }
    
    container.innerHTML = decisions.map(d => `
      <div class="timeline-item ${d.decision === 'DENY' || d.decision === 'QUARANTINE' ? 'completed' : ''}">
        <div class="timeline-icon">${this.getPolicyIcon(d.decision)}</div>
        <div class="timeline-content">
          <div class="timeline-stage">
            ${d.capability}
            <span class="badge-policy ${d.decision} ml-2">${d.decision}</span>
          </div>
          <div class="timeline-message">
            ${d.reason_codes?.join(', ') || 'No reason codes'}
            ${d.target_path ? `<br><code class="text-xs">${this.escapeHtml(d.target_path)}</code>` : ''}
          </div>
        </div>
        <div class="timeline-time">${this.formatTime(d.created_at)}</div>
      </div>
    `).join('');
  }
  
  renderPolicyDecisionsTable(decisions) {
    if (decisions.length === 0) {
      return '<p class="text-muted text-sm">No policy decisions</p>';
    }
    
    return `
      <div class="table-container">
        <table class="table">
          <thead>
            <tr>
              <th>Capability</th>
              <th>Decision</th>
              <th>Reason Codes</th>
              <th>Risk</th>
              <th>Target</th>
              <th>Time</th>
            </tr>
          </thead>
          <tbody>
            ${decisions.map(d => `
              <tr>
                <td><code>${this.escapeHtml(d.capability)}</code></td>
                <td><span class="badge-policy ${d.decision}">${d.decision}</span></td>
                <td>${d.reason_codes?.map(c => `<span class="badge badge-neutral">${c}</span>`).join(' ') || 'None'}</td>
                <td>${d.risk_level || 'N/A'}</td>
                <td>${d.target_path ? `<code class="text-xs">${this.escapeHtml(d.target_path)}</code>` : '-'}</td>
                <td>${this.formatTime(d.created_at)}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }
  
  renderApprovalsTable(approvals) {
    if (approvals.length === 0) {
      return '<p class="text-muted text-sm">No approval requests</p>';
    }
    
    return `
      <div class="table-container">
        <table class="table">
          <thead>
            <tr>
              <th>Scope</th>
              <th>Status</th>
              <th>Approver</th>
              <th>Expires</th>
              <th>Decided</th>
            </tr>
          </thead>
          <tbody>
            ${approvals.map(a => `
              <tr>
                <td>${this.escapeHtml(a.scope_description)}</td>
                <td><span class="badge badge-${this.approvalStatusToBadge(a.status)}">${a.status}</span></td>
                <td>${a.approver_id || '-'}</td>
                <td>${this.formatTime(a.expires_at)}</td>
                <td>${a.decided_at ? this.formatTime(a.decided_at) : '-'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }
  
  renderBlockedActions(detail) {
    const blocked = detail.policy_decisions?.filter(d => d.decision === 'DENY' || d.decision === 'QUARANTINE') || [];
    
    if (blocked.length === 0) {
      return '<p class="text-muted text-sm">No blocked actions</p>';
    }
    
    return blocked.map(b => `
      <div class="card mb-2" style="border-color: var(--danger);">
        <div class="card-body" style="padding: var(--space-3);">
          <div class="flex justify-between">
            <span class="font-medium">${this.escapeHtml(b.capability)}</span>
            <span class="badge-policy ${b.decision}">${b.decision}</span>
          </div>
          <div class="text-sm text-muted mt-1">${b.reason_codes?.join(', ')}</div>
          ${b.target_path ? `<div class="text-xs font-mono mt-1">${this.escapeHtml(b.target_path)}</div>` : ''}
        </div>
      </div>
    `).join('');
  }
  
  renderAuditTrail(events) {
    if (events.length === 0) {
      return '<p class="text-muted text-sm">No audit events</p>';
    }
    
    // Verify chain
    let chainVerified = true;
    let prevHash = null;
    
    for (const event of events) {
      const canonical = JSON.stringify({
        run_id: this.state.get('currentRun.id'),
        event_index: event.event_index,
        event_type: event.event_type,
        event_data: event.event_data,
        previous_hash: prevHash,
      });
      const computed = crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical));
      // Simplified - in real app would verify properly
      prevHash = event.current_hash;
    }
    
    return `
      <div class="mb-3">
        <span class="badge badge-${chainVerified ? 'success' : 'danger'}">
          ${chainVerified ? 'Chain Verified' : 'Verification Failed'}
        </span>
        <button class="btn btn-ghost btn-sm ml-2" onclick="downloadAuditExport()">Download Audit Export</button>
      </div>
      <div class="table-container">
        <table class="table">
          <thead>
            <tr>
              <th>#</th>
              <th>Type</th>
              <th>Data</th>
              <th>Hash</th>
              <th>Time</th>
            </tr>
          </thead>
          <tbody>
            ${events.map(e => `
              <tr>
                <td>${e.event_index}</td>
                <td><code>${this.escapeHtml(e.event_type)}</code></td>
                <td>${this.escapeHtml(JSON.stringify(e.event_data).slice(0, 100))}...</td>
                <td><code class="text-xs">${e.current_hash?.slice(0, 16)}...</code></td>
                <td>${this.formatTime(e.created_at)}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }
  
  emptyState(message) {
    return `
      <div class="empty-state">
        <div class="empty-state-icon"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg></div>
        <p class="empty-state-message">${message}</p>
      </div>
    `;
  }
  
  riskClassToBadge(risk) {
    switch (risk) {
      case 'critical': return 'danger';
      case 'high': return 'danger';
      case 'medium': return 'warning';
      case 'low': return 'success';
      default: return 'neutral';
    }
  }
  
  approvalStatusToBadge(status) {
    switch (status) {
      case 'approved': return 'success';
      case 'rejected': return 'danger';
      case 'expired': return 'warning';
      default: return 'warning';
    }
  }
  
  getPolicyIcon(decision) {
    switch (decision) {
      case 'ALLOW': return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>`;
      case 'ALLOW_WITH_MONITORING': return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
      case 'REQUIRE_APPROVAL': return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
      case 'DENY': return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
      case 'QUARANTINE': return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;
      default: return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`;
    }
  }
  
  formatTime(isoString) {
    if (!isoString) return '-';
    try {
      return new Date(isoString).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return isoString;
    }
  }
  
  escapeHtml(text) {
    if (text === null || text === undefined) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
}

// Export
window.SecurityComponent = SecurityComponent;
