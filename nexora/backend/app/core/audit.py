"""
Nexora Audit Log
Append-only, hash-chained audit trail
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from nexora.backend.app.models import AuditEvent as AuditEventModel
from nexora.backend.app.schemas import AuditEventBase as AuditEventSchema
from nexora.backend.config.settings import get_settings

settings = get_settings()


@dataclass
class AuditEntry:
    """Single audit log entry"""
    event_index: int
    event_type: str
    event_data: Dict[str, Any]
    previous_hash: Optional[str]
    current_hash: str
    timestamp: datetime


class AuditLog:
    """
    Audit Log - append-only, hash-chained record.
    
    Every model decision, tool request, policy decision, approval,
    execution result, and stop reason is recorded.
    
    Hash chain provides tamper evidence.
    """
    
    def __init__(self, run_id: str, algorithm: str = "sha256"):
        self.run_id = run_id
        self.algorithm = algorithm
        self._entries: List[AuditEntry] = []
        self._last_hash: Optional[str] = None
        self._event_index = 0
    
    def append(
        self,
        event_type: str,
        event_data: Dict[str, Any],
    ) -> AuditEntry:
        """
        Append an event to the audit log.
        
        Args:
            event_type: Type of event (e.g., "model_decision", "tool_request", "policy_decision")
            event_data: Event payload (must be JSON serializable)
            
        Returns:
            Created audit entry
        """
        self._event_index += 1
        
        # Create canonical representation for hashing
        canonical = {
            "run_id": self.run_id,
            "event_index": self._event_index,
            "event_type": event_type,
            "event_data": event_data,
            "previous_hash": self._last_hash,
        }
        
        # Compute hash
        canonical_json = json.dumps(canonical, sort_keys=True, separators=(',', ':'))
        current_hash = hashlib.new(self.algorithm, canonical_json.encode()).hexdigest()
        
        entry = AuditEntry(
            event_index=self._event_index,
            event_type=event_type,
            event_data=event_data,
            previous_hash=self._last_hash,
            current_hash=current_hash,
            timestamp=datetime.now(),
        )
        
        self._entries.append(entry)
        self._last_hash = current_hash
        
        return entry
    
    def get_entries(self) -> List[AuditEntry]:
        """Get all entries"""
        return self._entries.copy()
    
    def get_entry(self, index: int) -> Optional[AuditEntry]:
        """Get entry by index (1-based)"""
        if 1 <= index <= len(self._entries):
            return self._entries[index - 1]
        return None
    
    def verify_chain(self) -> Dict[str, Any]:
        """
        Verify the hash chain integrity.
        
        Returns:
            Verification result with status and any errors
        """
        errors = []
        previous_hash = None
        
        for i, entry in enumerate(self._entries):
            # Reconstruct canonical
            canonical = {
                "run_id": self.run_id,
                "event_index": entry.event_index,
                "event_type": entry.event_type,
                "event_data": entry.event_data,
                "previous_hash": previous_hash,
            }
            
            canonical_json = json.dumps(canonical, sort_keys=True, separators=(',', ':'))
            computed_hash = hashlib.new(self.algorithm, canonical_json.encode()).hexdigest()
            
            if computed_hash != entry.current_hash:
                errors.append(f"Hash mismatch at index {entry.event_index}")
            
            if entry.previous_hash != previous_hash:
                errors.append(f"Previous hash mismatch at index {entry.event_index}")
            
            previous_hash = entry.current_hash
        
        return {
            "verified": len(errors) == 0,
            "total_entries": len(self._entries),
            "errors": errors,
            "final_hash": self._last_hash,
        }
    
    def export(self) -> Dict[str, Any]:
        """Export audit log for download"""
        return {
            "run_id": self.run_id,
            "algorithm": self.algorithm,
            "entries": [
                {
                    "event_index": e.event_index,
                    "event_type": e.event_type,
                    "event_data": e.event_data,
                    "previous_hash": e.previous_hash,
                    "current_hash": e.current_hash,
                    "timestamp": e.timestamp.isoformat(),
                }
                for e in self._entries
            ],
            "verification": self.verify_chain(),
        }
    
    def to_schema(self, entry: AuditEntry) -> AuditEventSchema:
        """Convert to API schema"""
        return AuditEventSchema(
            id=self.run_id,  # Will be replaced with actual UUID
            run_id=self.run_id,
            event_index=entry.event_index,
            event_type=entry.event_type,
            event_data=entry.event_data,
            previous_hash=entry.previous_hash,
            current_hash=entry.current_hash,
            created_at=entry.timestamp,
        )


# Event types for consistency
class AuditEventType:
    RUN_CREATED = "run_created"
    TASK_ANALYSIS = "task_analysis"
    SECURITY_DECISION = "security_decision"
    PLAN_CREATED = "plan_created"
    PLAN_ACCEPTED = "plan_accepted"
    CONTEXT_BUILT = "context_built"
    MODEL_INFERENCE = "model_inference"
    TOOL_REQUEST = "tool_request"
    POLICY_DECISION = "policy_decision"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVAL_EXPIRED = "approval_expired"
    TOOL_EXECUTION = "tool_execution"
    VALIDATION = "validation"
    LOOP_DETECTED = "loop_detected"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_BLOCKED = "run_blocked"
    RUN_CANCELLED = "run_cancelled"
    RUN_TIMEOUT = "run_timeout"
    ERROR = "error"


def get_audit_log(run_id: str) -> AuditLog:
    """Create new audit log for a run"""
    return AuditLog(run_id, settings.AUDIT_HASH_ALGORITHM)
