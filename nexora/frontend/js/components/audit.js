/**
 * Nexora Audit Component
 * Audit list and export functionality
 */

class AuditComponent {
  constructor(state) {
    this.state = state;
  }
  
  static downloadAuditExport(runId, auditEvents) {
    const exportData = {
      run_id: runId,
      exported_at: new Date().toISOString(),
      total_events: auditEvents.length,
      events: auditEvents.map(e => ({
        event_index: e.event_index,
        event_type: e.event_type,
        event_data: e.event_data,
        previous_hash: e.previous_hash,
        current_hash: e.current_hash,
        timestamp: e.created_at,
      })),
    };
    
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `Nexora-audit-${runId}-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }
  
  static verifyChain(auditEvents, runId) {
    if (auditEvents.length === 0) return { verified: true, errors: [] };
    
    const errors = [];
    let previousHash = null;
    
    for (const event of auditEvents) {
      // Reconstruct canonical representation
      const canonical = {
        run_id: runId,
        event_index: event.event_index,
        event_type: event.event_type,
        event_data: event.event_data,
        previous_hash: previousHash,
      };
      
      const canonicalJson = JSON.stringify(canonical);
      
      // Compute hash (using Web Crypto API)
      // Note: This is async, simplified for display
      // In production, use crypto.subtle.digest
      
      if (event.previous_hash !== previousHash) {
        errors.push(`Previous hash mismatch at index ${event.event_index}`);
      }
      
      previousHash = event.current_hash;
    }
    
    return {
      verified: errors.length === 0,
      errors,
      final_hash: previousHash,
    };
  }
  
  static async computeHash(data) {
    const encoder = new TextEncoder();
    const dataBuffer = encoder.encode(data);
    const hashBuffer = await crypto.subtle.digest('SHA-256', dataBuffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  }
  
  static async verifyChainAsync(auditEvents, runId) {
    const errors = [];
    let previousHash = null;
    
    for (const event of auditEvents) {
      const canonical = {
        run_id: runId,
        event_index: event.event_index,
        event_type: event.event_type,
        event_data: event.event_data,
        previous_hash: previousHash,
      };
      
      const canonicalJson = JSON.stringify(canonical);
      const computedHash = await this.computeHash(canonicalJson);
      
      if (computedHash !== event.current_hash) {
        errors.push(`Hash mismatch at index ${event.event_index}`);
      }
      
      if (event.previous_hash !== previousHash) {
        errors.push(`Previous hash mismatch at index ${event.event_index}`);
      }
      
      previousHash = event.current_hash;
    }
    
    return {
      verified: errors.length === 0,
      errors,
      final_hash: previousHash,
    };
  }
}

// Global function for inline onclick
window.downloadAuditExport = function() {
  const detail = window.NexoraState?.get('currentRunDetail');
  const run = window.NexoraState?.get('currentRun');
  if (detail && run) {
    AuditComponent.downloadAuditExport(run.id, detail.audit_events || []);
  }
};

window.AuditComponent = AuditComponent;
