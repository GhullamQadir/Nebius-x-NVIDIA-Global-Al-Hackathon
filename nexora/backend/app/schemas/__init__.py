"""
Nexora API Schemas
Pydantic models for request/response validation
"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


# ============================================================
# Enums
# ============================================================

class RunStatus(str, Enum):
    QUEUED = "queued"
    ANALYZING = "analyzing"
    SECURITY_REVIEW = "security_review"
    PLANNING = "planning"
    AWAITING_START = "awaiting_start"
    CONTEXT_BUILD = "context_build"
    MODEL_STEP = "model_step"
    POLICY_CHECK = "policy_check"
    EXECUTING = "executing"
    VALIDATING = "validating"
    REPLANNING = "replanning"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    TIMEOUT_FAILED = "timeout_failed"


class RoutingMode(str, Enum):
    AUTO = "auto"
    FIXED = "fixed"
    MAX = "max"


class PolicyDecision(str, Enum):
    ALLOW = "ALLOW"
    ALLOW_WITH_MONITORING = "ALLOW_WITH_MONITORING"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DENY = "DENY"
    QUARANTINE = "QUARANTINE"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ExecutionStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    ERROR = "error"


class ValidationStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    SKIPPED = "skipped"


class FinalStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    TIMEOUT_FAILED = "timeout_failed"


class SecurityDecision(str, Enum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    NEEDS_APPROVAL = "needs_approval"


class RiskClass(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================
# Base Schemas
# ============================================================

class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TimestampMixin(BaseModel):
    created_at: datetime
    updated_at: Optional[datetime] = None


# ============================================================
# Workspace Schemas
# ============================================================

class WorkspaceBase(BaseSchema):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    repository_url: Optional[str] = Field(None, max_length=500)
    repository_type: str = Field(default="python", max_length=50)
    initial_commit_hash: Optional[str] = Field(None, max_length=64)
    is_active: bool = True


class WorkspaceCreate(WorkspaceBase):
    pass


class WorkspaceUpdate(BaseSchema):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    repository_url: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None


class WorkspaceResponse(WorkspaceBase, TimestampMixin):
    id: UUID


class WorkspaceListResponse(BaseSchema):
    workspaces: List[WorkspaceResponse]
    total: int


# ============================================================
# Budget Profile Schemas
# ============================================================

class BudgetProfileBase(BaseSchema):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    max_steps: int = Field(default=10, ge=1)
    max_tool_calls: int = Field(default=20, ge=1)
    max_retries: int = Field(default=1, ge=0)
    timeout_seconds: int = Field(default=300, ge=30)
    max_input_tokens: int = Field(default=8000, ge=100)
    max_output_tokens: int = Field(default=2000, ge=100)
    is_default: bool = False


class BudgetProfileCreate(BudgetProfileBase):
    pass


class BudgetProfileUpdate(BaseSchema):
    description: Optional[str] = None
    max_steps: Optional[int] = Field(None, ge=1)
    max_tool_calls: Optional[int] = Field(None, ge=1)
    max_retries: Optional[int] = Field(None, ge=0)
    timeout_seconds: Optional[int] = Field(None, ge=30)
    max_input_tokens: Optional[int] = Field(None, ge=100)
    max_output_tokens: Optional[int] = Field(None, ge=100)
    is_default: Optional[bool] = None


class BudgetProfileResponse(BudgetProfileBase, TimestampMixin):
    id: UUID


# ============================================================
# Model Registry Schemas
# ============================================================

class ModelRegistryBase(BaseSchema):
    model_id: str = Field(..., min_length=1, max_length=255)
    display_name: str = Field(..., min_length=1, max_length=255)
    provider: str = Field(default="nebius", max_length=100)
    tier: Optional[str] = Field(None, max_length=50)
    context_capacity: int = Field(..., ge=1000)
    max_output_tokens: int = Field(..., ge=100)
    supports_tools: bool = True
    supports_reasoning: bool = False
    is_enabled: bool = True
    verification_date: Optional[datetime] = None
    terms_reviewed: bool = False


class ModelRegistryCreate(ModelRegistryBase):
    pass


class ModelRegistryUpdate(BaseSchema):
    display_name: Optional[str] = Field(None, min_length=1, max_length=255)
    tier: Optional[str] = Field(None, max_length=50)
    context_capacity: Optional[int] = Field(None, ge=1000)
    max_output_tokens: Optional[int] = Field(None, ge=100)
    supports_tools: Optional[bool] = None
    supports_reasoning: Optional[bool] = None
    is_enabled: Optional[bool] = None
    verification_date: Optional[datetime] = None
    terms_reviewed: Optional[bool] = None


class ModelRegistryResponse(ModelRegistryBase, TimestampMixin):
    id: UUID


# ============================================================
# Run Schemas
# ============================================================

class RunBase(BaseSchema):
    workspace_id: UUID
    task_text: str = Field(..., min_length=1, max_length=25000)
    routing_mode: RoutingMode = RoutingMode.AUTO
    requested_model_id: Optional[UUID] = None
    budget_profile_id: Optional[UUID] = None
    healing_mode: Optional[str] = Field(default="auto", description="Self-healing mode: 'auto', 'on', or 'off'")
    detail_level: Optional[str] = Field(default="auto", description="Verbosity level: 'auto', 'concise', or 'detailed'")


class RunCreate(RunBase):
    # Optional: if set, this prompt continues an existing chat thread
    parent_run_id: Optional[UUID] = None
    healing_mode: Optional[str] = Field(default="auto", description="Self-healing mode: 'auto', 'on', or 'off'")
    detail_level: Optional[str] = Field(default="auto", description="Verbosity level: 'auto', 'concise', or 'detailed'")


class RunUpdate(BaseSchema):
    task_text: Optional[str] = Field(None, min_length=1, max_length=25000)
    routing_mode: Optional[RoutingMode] = None
    requested_model_id: Optional[UUID] = None


class RunResponse(RunBase, TimestampMixin):
    id: UUID
    parent_run_id: Optional[UUID] = None
    snapshot_id: Optional[UUID] = None
    budget_profile_id: UUID
    task_hash: str
    status: RunStatus
    current_stage: Optional[str] = None
    steps_completed: int = 0
    tool_calls_count: int = 0
    retries_count: int = 0
    input_tokens_used: int = 0
    output_tokens_used: int = 0
    total_elapsed_ms: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    result_summary: Optional[Dict[str, Any]] = None
    conversation_history: Optional[List[Dict[str, Any]]] = None


class RunListResponse(BaseSchema):
    runs: List[RunResponse]
    total: int
    page: int
    page_size: int


# ============================================================
# Run Event Schemas
# ============================================================

class RunEventBase(BaseSchema):
    event_type: str
    stage: Optional[str] = None
    message: Optional[str] = None
    # The ORM attribute is ``event_metadata``: ``metadata`` is reserved on
    # declarative models (``Base.metadata``), so the column had to be renamed.
    # Read it via alias while keeping the existing ``metadata`` wire format.
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, validation_alias="event_metadata"
    )


class RunEventResponse(RunEventBase, TimestampMixin):
    id: UUID
    run_id: UUID


# ============================================================
# Task Analysis Schemas
# ============================================================

class TaskAnalysisBase(BaseSchema):
    objective: str
    constraints: List[str] = Field(default_factory=list)
    acceptance_tests: List[str] = Field(default_factory=list)
    risk_class: RiskClass
    likely_artifacts: List[str] = Field(default_factory=list)
    proposed_capabilities: List[str] = Field(default_factory=list)
    analyzer_version: Optional[str] = None


class TaskAnalysisResponse(TaskAnalysisBase, TimestampMixin):
    id: UUID
    run_id: UUID


# ============================================================
# Security Decision Schemas
# ============================================================

class SecurityDecisionBase(BaseSchema):
    decision: SecurityDecision
    reason_codes: List[str] = Field(default_factory=list)
    provenance_summary: Dict[str, Any] = Field(default_factory=dict)
    injection_findings: List[Dict[str, Any]] = Field(default_factory=list)
    risk_level: Optional[str] = None
    gateway_version: Optional[str] = None


class SecurityDecisionResponse(SecurityDecisionBase, TimestampMixin):
    id: UUID
    run_id: UUID


# ============================================================
# Plan Schemas
# ============================================================

class PlanBase(BaseSchema):
    hypothesis: str
    candidate_files: List[str] = Field(default_factory=list)
    candidate_symbols: List[str] = Field(default_factory=list)
    tool_sequence: List[Dict[str, Any]] = Field(default_factory=list)
    test_command: Optional[str] = None
    stop_conditions: List[str] = Field(default_factory=list)
    estimated_tokens: Optional[int] = None
    estimated_time_seconds: Optional[int] = None
    planner_version: Optional[str] = None


class PlanCreate(PlanBase):
    pass


class PlanUpdate(BaseSchema):
    is_accepted: Optional[bool] = None


class PlanResponse(PlanBase, TimestampMixin):
    id: UUID
    run_id: UUID
    is_accepted: bool = False
    accepted_at: Optional[datetime] = None


# ============================================================
# Context Package Schemas
# ============================================================

class ContextPackageBase(BaseSchema):
    step_number: int
    model_id: Optional[UUID] = None
    included_files: List[Dict[str, Any]] = Field(default_factory=list)
    omitted_categories: List[Dict[str, Any]] = Field(default_factory=list)
    ranking_reasons: Dict[str, str] = Field(default_factory=dict)
    cache_hits: int = 0
    estimated_input_tokens: Optional[int] = None
    actual_input_tokens: Optional[int] = None
    compression_ratio: Optional[float] = None
    context_optimizer_version: Optional[str] = None


class ContextPackageResponse(ContextPackageBase, TimestampMixin):
    id: UUID
    run_id: UUID


# ============================================================
# Tool Request Schemas
# ============================================================

class ToolRequestBase(BaseSchema):
    step_number: int
    request_id: str
    tool_name: str
    arguments: Dict[str, Any]
    provenance: str
    expected_risk: Optional[str] = None


class ToolRequestResponse(ToolRequestBase, TimestampMixin):
    id: UUID
    run_id: UUID


# ============================================================
# Policy Decision Schemas
# ============================================================

class PolicyDecisionBase(BaseSchema):
    capability: str
    decision: PolicyDecision
    reason_codes: List[str] = Field(default_factory=list)
    risk_level: Optional[str] = None
    normalized_arguments: Optional[Dict[str, Any]] = None
    target_path: Optional[str] = None
    policy_version: Optional[str] = None
    engine_version: Optional[str] = None


class PolicyDecisionResponse(PolicyDecisionBase, TimestampMixin):
    id: UUID
    run_id: UUID
    tool_request_id: Optional[UUID] = None


# ============================================================
# Approval Schemas
# ============================================================

class ApprovalBase(BaseSchema):
    scope_description: str
    expires_at: datetime


class ApprovalCreate(ApprovalBase):
    policy_decision_id: UUID


class ApprovalUpdate(BaseSchema):
    status: ApprovalStatus


class ApprovalResponse(ApprovalBase, TimestampMixin):
    id: UUID
    run_id: UUID
    policy_decision_id: UUID
    status: ApprovalStatus
    approver_id: Optional[str] = None
    decided_at: Optional[datetime] = None


# ============================================================
# Tool Execution Schemas
# ============================================================

class ToolExecutionBase(BaseSchema):
    tool_name: str
    arguments: Dict[str, Any]
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None
    sandbox_id: Optional[str] = None
    execution_status: ExecutionStatus


class ToolExecutionResponse(ToolExecutionBase, TimestampMixin):
    id: UUID
    run_id: UUID
    tool_request_id: Optional[UUID] = None
    policy_decision_id: Optional[UUID] = None


# ============================================================
# Validation Finding Schemas
# ============================================================

class ValidationFindingBase(BaseSchema):
    step_number: int
    check_type: str
    status: ValidationStatus
    message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    critic_version: Optional[str] = None


class ValidationFindingResponse(ValidationFindingBase, TimestampMixin):
    id: UUID
    run_id: UUID


# ============================================================
# Run Result Schemas
# ============================================================

class RunResultBase(BaseSchema):
    final_status: FinalStatus
    patch_hash: Optional[str] = None
    patch_content: Optional[str] = None
    test_summary: Optional[Dict[str, Any]] = None
    critic_findings: Optional[Dict[str, Any]] = None
    policy_decisions_summary: Optional[Dict[str, Any]] = None
    blocked_actions: Optional[Dict[str, Any]] = None
    limitations: Optional[Dict[str, Any]] = None
    model_used_id: Optional[UUID] = None
    attempts: int = 1
    total_tool_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_elapsed_ms: int = 0
    evidence_report: Optional[Dict[str, Any]] = None


class RunResultResponse(RunResultBase, TimestampMixin):
    id: UUID
    run_id: UUID


# ============================================================
# Audit Event Schemas
# ============================================================

class AuditEventBase(BaseSchema):
    event_type: str
    event_data: Dict[str, Any]


class AuditEventResponse(AuditEventBase, TimestampMixin):
    id: UUID
    run_id: UUID
    event_index: int
    previous_hash: Optional[str] = None
    current_hash: str


# ============================================================
# Loop Detection Schemas
# ============================================================

class LoopDetectionBase(BaseSchema):
    action_hash: str
    action_type: str
    normalized_command: Optional[str] = None
    target_path: Optional[str] = None
    result_class: Optional[str] = None
    attempt_count: int = 1


class LoopDetectionResponse(LoopDetectionBase, TimestampMixin):
    id: UUID
    run_id: UUID


# ============================================================
# Composite Response Schemas (for frontend)
# ============================================================

class RunDetailResponse(BaseSchema):
    """Complete run details for frontend display"""
    run: RunResponse
    task_analysis: Optional[TaskAnalysisResponse] = None
    security_decision: Optional[SecurityDecisionResponse] = None
    plan: Optional[PlanResponse] = None
    context_packages: List[ContextPackageResponse] = Field(default_factory=list)
    tool_requests: List[ToolRequestResponse] = Field(default_factory=list)
    policy_decisions: List[PolicyDecisionResponse] = Field(default_factory=list)
    approvals: List[ApprovalResponse] = Field(default_factory=list)
    tool_executions: List[ToolExecutionResponse] = Field(default_factory=list)
    validation_findings: List[ValidationFindingResponse] = Field(default_factory=list)
    run_result: Optional[RunResultResponse] = None
    audit_events: List[AuditEventResponse] = Field(default_factory=list)
    events: List[RunEventResponse] = Field(default_factory=list)


class StartRunRequest(BaseSchema):
    """Request to start a run after plan acceptance"""
    run_id: UUID


class ApproveActionRequest(BaseSchema):
    """Request to approve/reject an action"""
    approval_id: UUID
    approve: bool


class CancelRunRequest(BaseSchema):
    """Request to cancel a run"""
    run_id: UUID