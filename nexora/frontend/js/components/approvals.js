/**
 * Nexora Approvals Component
 * Approval dialog and inline card
 */

class ApprovalsComponent {
  constructor(state) {
    this.state = state;
    this.unsubscribe = null;
    this.currentApprovalId = null;
  }
  
  init() {
    this.unsubscribe = this.state.on('currentRunDetail', (detail) => {
      this.checkForPendingApproval(detail);
    });
    
    // Initial check
    if (this.state.get('currentRunDetail')) {
      this.checkForPendingApproval(this.state.get('currentRunDetail'));
    }
  }
  
  destroy() {
    if (this.unsubscribe) this.unsubscribe();
    this.hideDialog();
  }
  
  checkForPendingApproval(detail) {
    const pending = detail?.approvals?.filter(a => a.status === 'pending') || [];
    
    if (pending.length > 0) {
      // Show the first pending approval
      this.showDialog(pending[0]);
      this.renderInlineCard(pending[0]);
    } else {
      this.hideDialog();
      this.clearInlineCard();
    }
  }
  
  showDialog(approval) {
    this.currentApprovalId = approval.id;
    
    // Remove existing dialog
    this.hideDialog();
    
    const overlay = document.createElement('div');
    overlay.className = 'dialog-overlay';
    overlay.id = 'approval-dialog-overlay';
    overlay.innerHTML = this.renderDialog(approval);
    document.body.appendChild(overlay);
    
    // Focus management
    const dialog = overlay.querySelector('.dialog');
    const firstFocusable = dialog.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    if (firstFocusable) {
      // For high-risk, focus the explanation heading instead
      const heading = dialog.querySelector('h2');
      if (heading) heading.focus();
    }
    
    // Escape to close (without deciding)
    overlay.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        this.hideDialog();
      }
    });
    
    // Click overlay to close (without deciding)
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) {
        this.hideDialog();
      }
    });
    
    // Add event listeners
    overlay.querySelector('[data-action="approve"]').addEventListener('click', () => this.decide(true));
    overlay.querySelector('[data-action="reject"]').addEventListener('click', () => this.decide(false));
    
    // Start countdown
    this.startCountdown(approval.expires_at);
  }
  
  hideDialog() {
    const overlay = document.getElementById('approval-dialog-overlay');
    if (overlay) {
      overlay.remove();
    }
    this.currentApprovalId = null;
  }
  
  renderDialog(approval) {
    const expiresAt = new Date(approval.expires_at);
    const now = new Date();
    const remainingMs = expiresAt - now;
    const remainingSeconds = Math.max(0, Math.ceil(remainingMs / 1000));
    
    return `
      <div class="dialog approval-dialog" role="dialog" aria-modal="true" aria-labelledby="approval-title">
        <div class="dialog-header">
          <h2 id="approval-title" class="dialog-title">Approval Required</h2>
        </div>
        <div class="dialog-body">
          <div class="approval-warning">
            <svg class="approval-warning-icon" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
              <line x1="12" y1="9" x2="12" y2="13"></line>
              <line x1="12" y1="17" x2="12.01" y2="17"></line>
            </svg>
            <div>
              <strong>This action needs your approval</strong>
              <p class="text-sm text-muted mt-1">The policy engine requires explicit approval for this action.</p>
            </div>
          </div>
          
          <div class="approval-details">
            <div class="approval-detail-row">
              <span class="approval-detail-label">Action</span>
              <span class="approval-detail-value">${this.escapeHtml(approval.scope_description)}</span>
            </div>
            <div class="approval-detail-row">
              <span class="approval-detail-label">Expires</span>
              <span class="approval-detail-value approval-expiry" id="approval-countdown">${this.formatCountdown(remainingSeconds)}</span>
            </div>
            <div class="approval-detail-row">
              <span class="approval-detail-label">If rejected or expired</span>
              <span class="approval-detail-value text-danger">The run will stop safely.</span>
            </div>
          </div>
        </div>
        <div class="dialog-footer">
          <button class="btn btn-secondary" data-action="reject">Reject</button>
          <button class="btn btn-primary" data-action="approve">Approve This Action</button>
        </div>
      </div>
    `;
  }
  
  renderInlineCard(approval) {
    const container = document.getElementById('approval-inline');
    if (!container) return;
    
    const expiresAt = new Date(approval.expires_at);
    const remainingMs = expiresAt - new Date();
    const remainingSeconds = Math.max(0, Math.ceil(remainingMs / 1000));
    
    container.innerHTML = `
      <div class="card" style="border-left: 4px solid var(--warning);">
        <div class="card-body" style="padding: var(--space-4);">
          <div class="flex justify-between items-start mb-3">
            <div>
              <div class="flex items-center gap-2 mb-1">
                <span class="badge badge-warning">Awaiting Approval</span>
                <span class="text-sm text-muted approval-countdown-inline" data-expires="${approval.expires_at}">${this.formatCountdown(remainingSeconds)}</span>
              </div>
              <p class="text-sm text-muted">${this.escapeHtml(approval.scope_description)}</p>
            </div>
            <div class="flex gap-2">
              <button class="btn btn-primary btn-sm" data-approval-id="${approval.id}" data-action="approve">Approve</button>
              <button class="btn btn-secondary btn-sm" data-approval-id="${approval.id}" data-action="reject">Reject</button>
            </div>
          </div>
        </div>
      </div>
    `;
    
    // Add event listeners
    container.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const approvalId = e.target.dataset.approvalId;
        const action = e.target.dataset.action;
        this.decide(action === 'approve', approvalId);
      });
    });
  }
  
  clearInlineCard() {
    const container = document.getElementById('approval-inline');
    if (container) container.innerHTML = '';
  }
  
  async decide(approve, approvalId = null) {
    const id = approvalId || this.currentApprovalId;
    if (!id) return;
    
    const run = this.state.get('currentRun');
    if (!run) return;
    
    try {
      await this.state.approveAction(run.id, id, approve);
      this.hideDialog();
      this.clearInlineCard();
    } catch (e) {
      console.error('Approval decision failed:', e);
    }
  }
  
  startCountdown(expiresAt) {
    const updateCountdown = () => {
      const remainingMs = new Date(expiresAt) - new Date();
      const remainingSeconds = Math.max(0, Math.ceil(remainingMs / 1000));
      
      // Update dialog
      const dialogCountdown = document.getElementById('approval-countdown');
      if (dialogCountdown) {
        dialogCountdown.textContent = this.formatCountdown(remainingSeconds);
      }
      
      // Update inline
      const inlineCountdown = document.querySelector('.approval-countdown-inline');
      if (inlineCountdown) {
        inlineCountdown.textContent = this.formatCountdown(remainingSeconds);
      }
      
      if (remainingSeconds <= 0) {
        this.hideDialog();
        this.clearInlineCard();
      }
    };
    
    updateCountdown();
    this.countdownInterval = setInterval(updateCountdown, 1000);
  }
  
  stopCountdown() {
    if (this.countdownInterval) {
      clearInterval(this.countdownInterval);
      this.countdownInterval = null;
    }
  }
  
  formatCountdown(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `Expires in ${mins}:${secs.toString().padStart(2, '0')}`;
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

window.ApprovalsComponent = ApprovalsComponent;
