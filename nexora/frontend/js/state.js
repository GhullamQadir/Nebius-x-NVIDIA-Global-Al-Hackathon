/**
 * Nexora State Management
 * Centralized application state with event system
 */

class StateManager {
  constructor() {
    this.state = {
      // Current run
      currentRun: null,
      currentRunDetail: null,
      
      // Workspaces
      workspaces: [],
      selectedWorkspaceId: null,
      
      // Models
      models: [],
      packageRouting: null,
      
      // Budget profiles
      budgetProfiles: [],
      defaultBudgetProfile: null,
      
      // UI State
      activeTab: 'task',
      inspectionOpen: false,
      loading: false,
      error: null,
      
      // Real-time
      pollingInterval: null,
      wsConnection: null,
    };
    
    this.listeners = new Map();
    this.pollingCallbacks = new Set();
  }
  
  // ============================================================
  // Core State Methods
  // ============================================================
  
  get(key) {
    const keys = key.split('.');
    let value = this.state;
    for (const k of keys) {
      if (value === undefined || value === null) return undefined;
      value = value[k];
    }
    return value;
  }
  
  set(key, value) {
    const keys = key.split('.');
    let obj = this.state;
    for (let i = 0; i < keys.length - 1; i++) {
      if (!obj[keys[i]]) obj[keys[i]] = {};
      obj = obj[keys[i]];
    }
    const oldValue = obj[keys[keys.length - 1]];
    obj[keys[keys.length - 1]] = value;
    
    if (oldValue !== value) {
      this.emit(key, value, oldValue);
    }
  }
  
  update(key, updater) {
    const current = this.get(key);
    const next = typeof updater === 'function' ? updater(current) : updater;
    this.set(key, next);
  }
  
  // ============================================================
  // Event System
  // ============================================================
  
  on(key, callback) {
    if (!this.listeners.has(key)) {
      this.listeners.set(key, new Set());
    }
    this.listeners.get(key).add(callback);
    
    // Return unsubscribe function
    return () => this.off(key, callback);
  }
  
  off(key, callback) {
    if (this.listeners.has(key)) {
      this.listeners.get(key).delete(callback);
    }
  }
  
  emit(key, newValue, oldValue) {
    if (this.listeners.has(key)) {
      this.listeners.get(key).forEach(callback => {
        try {
          callback(newValue, oldValue, key);
        } catch (e) {
          console.error(`State listener error for ${key}:`, e);
        }
      });
    }
    
    // Also emit wildcard
    if (this.listeners.has('*')) {
      this.listeners.get('*').forEach(callback => {
        try {
          callback(key, newValue, oldValue);
        } catch (e) {
          console.error('Wildcard listener error:', e);
        }
      });
    }
  }
  
  // ============================================================
  // Derived State / Computed
  // ============================================================
  
  get selectedWorkspace() {
    const id = this.state.selectedWorkspaceId;
    if (!id) return null;
    return this.state.workspaces.find(w => w.id === id);
  }
  
  get currentRunStatus() {
    return this.state.currentRun?.status || null;
  }
  
  get isRunActive() {
    const status = this.currentRunStatus;
    if (!status) return false;
    const activeStatuses = [
      'queued', 'analyzing', 'security_review', 'planning',
      'awaiting_start', 'context_build', 'model_step',
      'policy_check', 'executing', 'validating', 'replanning',
      'awaiting_approval', 'cancel_requested'
    ];
    return activeStatuses.includes(status);
  }
  
  get isRunTerminal() {
    const status = this.currentRunStatus;
    if (!status) return false;
    const terminalStatuses = [
      'completed', 'failed', 'blocked', 'cancelled', 'timeout_failed'
    ];
    return terminalStatuses.includes(status);
  }
  
  get pendingApprovals() {
    if (!this.state.currentRunDetail?.approvals) return [];
    return this.state.currentRunDetail.approvals.filter(a => a.status === 'pending');
  }
  
  // ============================================================
  // Run Polling
  // ============================================================
  
  startPolling(runId, interval = 2000) {
    this.stopPolling();
    
    const poll = async () => {
      try {
        const detail = await window.NexoraApi.runs.get(runId);
        this.set('currentRunDetail', detail);
        this.set('currentRun', detail.run);
        
        // Check if terminal
        if (this.isRunTerminal) {
          this.stopPolling();
          this.emit('run:completed', detail);
        }
        
        // Notify polling callbacks
        this.pollingCallbacks.forEach(cb => cb(detail));
      } catch (e) {
        console.error('Polling error:', e);
      }
    };
    
    // Initial poll
    poll();
    
    // Set interval
    this.state.pollingInterval = setInterval(poll, interval);
  }
  
  stopPolling() {
    if (this.state.pollingInterval) {
      clearInterval(this.state.pollingInterval);
      this.state.pollingInterval = null;
    }
  }
  
  onPoll(callback) {
    this.pollingCallbacks.add(callback);
    return () => this.pollingCallbacks.delete(callback);
  }
  
  // ============================================================
  // Actions
  // ============================================================
  
  async loadWorkspaces() {
    try {
      this.set('loading', true);
      const response = await window.NexoraApi.workspaces.list({ active_only: true });
      this.set('workspaces', response.workspaces);
      
      // Auto-select first workspace if none selected
      if (!this.state.selectedWorkspaceId && response.workspaces.length > 0) {
        this.set('selectedWorkspaceId', response.workspaces[0].id);
      }
    } catch (e) {
      this.set('error', e.message);
    } finally {
      this.set('loading', false);
    }
  }
  
  async loadModels() {
    try {
      const models = await window.NexoraApi.models.list(true);
      this.set('models', models);
    } catch (e) {
      console.error('Failed to load models:', e);
    }
  }
  
  async loadBudgetProfiles() {
    try {
      const profiles = await window.NexoraApi.budgetProfiles.list();
      this.set('budgetProfiles', profiles);
      const defaultProfile = profiles.find(p => p.is_default);
      this.set('defaultBudgetProfile', defaultProfile);
    } catch (e) {
      console.error('Failed to load budget profiles:', e);
    }
  }
  
  async createRun(taskData) {
    try {
      this.set('loading', true);
      this.set('error', null);
      
      const run = await window.NexoraApi.runs.create(taskData);
      this.set('currentRun', run);
      
      // Load full detail
      const detail = await window.NexoraApi.runs.get(run.id);
      this.set('currentRunDetail', detail);
      
      // Start polling
      this.startPolling(run.id);
      
      return run;
    } catch (e) {
      this.set('error', e.message);
      throw e;
    } finally {
      this.set('loading', false);
    }
  }
  
  async startRun(runId) {
    try {
      const run = await window.NexoraApi.runs.start(runId);
      this.set('currentRun', run);
      return run;
    } catch (e) {
      this.set('error', e.message);
      throw e;
    }
  }
  
  async approveAction(runId, approvalId, approve) {
    try {
      const approval = await window.NexoraApi.runs.approve(runId, approvalId, approve);
      // Refresh run detail
      const detail = await window.NexoraApi.runs.get(runId);
      this.set('currentRunDetail', detail);
      this.set('currentRun', detail.run);
      return approval;
    } catch (e) {
      this.set('error', e.message);
      throw e;
    }
  }
  
  async cancelRun(runId) {
    try {
      const run = await window.NexoraApi.runs.cancel(runId);
      this.set('currentRun', run);
      return run;
    } catch (e) {
      this.set('error', e.message);
      throw e;
    }
  }
  
  clearCurrentRun() {
    this.stopPolling();
    this.set('currentRun', null);
    this.set('currentRunDetail', null);
    this.set('activeTab', 'task');
  }
  
  setActiveTab(tab) {
    this.set('activeTab', tab);
  }
  
  toggleInspection() {
    this.set('inspectionOpen', !this.state.inspectionOpen);
  }
  
  clearError() {
    this.set('error', null);
  }
}

// Singleton instance
const state = new StateManager();

// Make globally available
window.NexoraState = state;

export { state, StateManager };
