"""
Nexora Approval Manager
Scoped, expiring approvals for elevated actions
"""
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from nexora.backend.app.models import ApprovalStatus
from nexora.backend.app.schemas import ApprovalBase as ApprovalSchema


class ApprovalError(Exception):
    """Approval-related errors"""
    pass


def fingerprint_scope(
    capability: Optional[str],
    arguments: Optional[Dict[str, Any]],
) -> str:
    """Return a stable fingerprint for the scoped action an approval covers.

    The fingerprint binds an approval to the exact capability and normalised
    arguments it was granted for. A later request whose arguments differ
    produces a different fingerprint and therefore cannot reuse the approval,
    even if it reuses the same approval (or tool-request) identifier.
    """
    payload = {
        "capability": capability,
        "arguments": arguments if isinstance(arguments, dict) else {},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class ApprovalRequest:
    """Request for approval"""
    run_id: str
    policy_decision_id: str
    scope_description: str
    expires_in_seconds: int = 300  # 5 minutes default
    # One consistent, server-owned identifier for the request being gated.
    # ``policy_decision_id`` remains the policy-decision row id (the DB foreign
    # key); ``tool_request_id`` is the value the orchestrator uses to look the
    # approval up again on re-evaluation. Keeping both on the record removes
    # the previous key mismatch without touching the table's foreign key.
    tool_request_id: Optional[str] = None
    scope_fingerprint: Optional[str] = None


@dataclass
class ApprovalRecord:
    """Stored approval record"""
    id: str
    run_id: str
    policy_decision_id: str
    scope_description: str
    expires_at: datetime
    status: ApprovalStatus
    approver_id: Optional[str] = None
    decided_at: Optional[datetime] = None
    created_at: datetime = None
    tool_request_id: Optional[str] = None
    scope_fingerprint: Optional[str] = None
    consumed_at: Optional[datetime] = None


class ApprovalManager:
    """
    Approval Manager - handles scoped, expiring approvals.
    
    Key rules:
    - Approvals are scoped to ONE action
    - Approvals expire (default 5 minutes)
    - Silence is NEVER approval
    - Expired/rejected approval blocks the action
    - High-risk actions never auto-approved
    - An approval is bound to its run, tool request, and argument fingerprint
    - An approval is single-use: it is consumed on execution (no replay)
    """

    #: Expose the scope fingerprint helper for callers that create approvals.
    fingerprint_scope = staticmethod(fingerprint_scope)
    
    def __init__(self, default_expiry_seconds: int = 300):
        self.default_expiry_seconds = default_expiry_seconds
        self._approvals: Dict[str, ApprovalRecord] = {}
    
    def request_approval(self, request: ApprovalRequest) -> ApprovalRecord:
        """
        Create a new approval request.
        
        Args:
            request: Approval request details
            
        Returns:
            Created approval record
        """
        approval_id = str(uuid.uuid4())
        expires_at = datetime.now() + timedelta(seconds=request.expires_in_seconds)
        
        record = ApprovalRecord(
            id=approval_id,
            run_id=request.run_id,
            policy_decision_id=request.policy_decision_id,
            scope_description=request.scope_description,
            expires_at=expires_at,
            status=ApprovalStatus.PENDING,
            created_at=datetime.now(),
            tool_request_id=request.tool_request_id,
            scope_fingerprint=request.scope_fingerprint,
        )
        
        self._approvals[approval_id] = record
        return record
    
    def get_approval(self, approval_id: str) -> Optional[ApprovalRecord]:
        """Get approval by ID"""
        return self._approvals.get(approval_id)
    
    def get_pending_for_run(self, run_id: str) -> List[ApprovalRecord]:
        """Get all pending approvals for a run"""
        return [
            a for a in self._approvals.values()
            if a.run_id == run_id and a.status == ApprovalStatus.PENDING
        ]
    
    def decide(
        self,
        approval_id: str,
        approve: bool,
        approver_id: str,
        expected_run_id: Optional[str] = None,
    ) -> ApprovalRecord:
        """
        Record approval decision.
        
        Args:
            approval_id: Approval to decide
            approve: True to approve, False to reject
            approver_id: Trusted identifier of the approver (never a client
                supplied value and never a hard-coded placeholder).
            expected_run_id: When supplied, the approval must belong to this
                run or the decision is refused.
            
        Returns:
            Updated approval record
            
        Raises:
            ApprovalError: If approval not found, already decided, expired,
                owned by another run, or the approver identity is empty.
        """
        if not isinstance(approver_id, str) or not approver_id.strip():
            raise ApprovalError("Approver identity is required")

        record = self._approvals.get(approval_id)
        if not record:
            raise ApprovalError(f"Approval not found: {approval_id}")
        
        if record.status != ApprovalStatus.PENDING:
            raise ApprovalError(f"Approval already decided: {record.status.value}")
        
        if expected_run_id is not None and record.run_id != expected_run_id:
            raise ApprovalError("Approval does not belong to this run")
        
        # Check expiry
        if datetime.now() > record.expires_at:
            record.status = ApprovalStatus.EXPIRED
            record.decided_at = datetime.now()
            raise ApprovalError("Approval has expired")
        
        if approve:
            record.status = ApprovalStatus.APPROVED
        else:
            record.status = ApprovalStatus.REJECTED
        
        record.approver_id = approver_id
        record.decided_at = datetime.now()
        
        return record
    
    def check_expired(self) -> List[ApprovalRecord]:
        """Check and mark expired approvals"""
        now = datetime.now()
        expired = []
        
        for record in self._approvals.values():
            if record.status == ApprovalStatus.PENDING and now > record.expires_at:
                record.status = ApprovalStatus.EXPIRED
                record.decided_at = now
                expired.append(record)
        
        return expired
    
    def is_approved(self, approval_id: str) -> bool:
        """Check if approval was granted, is current, and not yet consumed."""
        record = self._approvals.get(approval_id)
        if not record:
            return False
        
        if record.status != ApprovalStatus.APPROVED:
            return False

        # A spent approval must never authorise another execution.
        if record.consumed_at is not None:
            return False
        
        # Double-check expiry
        if datetime.now() > record.expires_at:
            record.status = ApprovalStatus.EXPIRED
            return False
        
        return True

    def _record_state(self, record: ApprovalRecord) -> str:
        """Resolve the caller-facing approval state for a record.

        Only ``approved`` (and neither expired nor consumed) authorises an
        action; every other value keeps the action paused or denied.
        """
        if record.status == ApprovalStatus.APPROVED:
            if record.consumed_at is not None:
                return "consumed"
            if datetime.now() > record.expires_at:
                record.status = ApprovalStatus.EXPIRED
                return "expired"
            return "approved"
        if record.status == ApprovalStatus.PENDING:
            if datetime.now() > record.expires_at:
                return "expired"
            return "pending"
        return record.status.value

    def get_approval_state(self, policy_decision_id: str) -> Optional[str]:
        """Get approval state for a policy decision"""
        for record in self._approvals.values():
            if record.policy_decision_id == policy_decision_id:
                return self._record_state(record)
        return None

    def _find_by_tool_request(
        self,
        tool_request_id: str,
        run_id: Optional[str] = None,
    ) -> Optional[ApprovalRecord]:
        """Find the approval bound to a server-owned tool-request identifier."""
        for record in self._approvals.values():
            if record.tool_request_id != tool_request_id:
                continue
            if run_id is not None and record.run_id != run_id:
                continue
            return record
        return None

    def get_approval_state_for_tool_request(
        self,
        tool_request_id: str,
        run_id: Optional[str] = None,
    ) -> Optional[str]:
        """Get approval state keyed by the tool request it gates.

        This is the single, consistent lookup used by the orchestrator: the
        record is stored and retrieved by the same server-owned identifier, so
        a granted approval is actually found on re-evaluation.
        """
        record = self._find_by_tool_request(tool_request_id, run_id)
        if record is None:
            return None
        return self._record_state(record)

    def consume(
        self,
        approval_id: str,
        *,
        run_id: Optional[str] = None,
        tool_request_id: Optional[str] = None,
        scope_fingerprint: Optional[str] = None,
    ) -> bool:
        """Atomically spend an approval so it cannot authorise a second run.

        Returns ``True`` only when the approval is currently valid *and*
        matches every supplied binding (run, tool request, argument
        fingerprint). Returns ``False`` for missing, rejected, expired,
        already-consumed, or scope-mismatched approvals.
        """
        record = self._approvals.get(approval_id)
        if record is None:
            return False
        if record.status != ApprovalStatus.APPROVED:
            return False
        if record.consumed_at is not None:
            return False
        if datetime.now() > record.expires_at:
            record.status = ApprovalStatus.EXPIRED
            return False
        if run_id is not None and record.run_id != run_id:
            return False
        if tool_request_id is not None and record.tool_request_id != tool_request_id:
            return False
        if scope_fingerprint is not None and record.scope_fingerprint != scope_fingerprint:
            return False

        record.consumed_at = datetime.now()
        return True

    def consume_for_tool_request(
        self,
        tool_request_id: str,
        run_id: Optional[str] = None,
        scope_fingerprint: Optional[str] = None,
    ) -> bool:
        """Spend the approval bound to a tool request, if one exists.

        Returns ``True`` when there is nothing to consume (an ordinary,
        non-gated action) or when the matching approval is successfully spent.
        Returns ``False`` when a gated approval exists but cannot be validly
        consumed (expired, already spent, wrong run, or arguments changed);
        callers must treat ``False`` as a denial.
        """
        # Look the record up by the server-owned tool-request id first, then
        # require the run to match. A gated approval that belongs to another run
        # must fail closed rather than be silently treated as "nothing to
        # consume" (which would let a cross-run reference slip through).
        record = self._find_by_tool_request(tool_request_id)
        if record is None:
            return True
        if run_id is not None and record.run_id != run_id:
            return False
        return self.consume(
            record.id,
            run_id=run_id,
            tool_request_id=tool_request_id,
            scope_fingerprint=scope_fingerprint,
        )
    
    def to_schema(self, record: ApprovalRecord) -> ApprovalSchema:
        """Convert to API schema"""
        return ApprovalSchema(
            id=record.id,
            run_id=record.run_id,
            policy_decision_id=record.policy_decision_id,
            scope_description=record.scope_description,
            expires_at=record.expires_at,
            status=record.status,
            approver_id=record.approver_id,
            decided_at=record.decided_at,
            created_at=record.created_at,
        )


# Global instance
_approval_manager: Optional[ApprovalManager] = None


def get_approval_manager() -> ApprovalManager:
    """Get or create approval manager"""
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = ApprovalManager()
    return _approval_manager
