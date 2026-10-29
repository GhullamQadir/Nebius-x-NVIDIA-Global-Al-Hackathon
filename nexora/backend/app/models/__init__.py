"""
Nexora Database Models
SQLAlchemy ORM models mapping to the database schema
"""
import enum
import uuid
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# Use String for UUID to be compatible with both PostgreSQL and SQLite
UUID = String(36)


def generate_uuid() -> str:
    return str(uuid.uuid4())


if TYPE_CHECKING:
    from nexora.backend.app.models import (
        Workspace,
        RepositorySnapshot,
        BudgetProfile,
        ModelRegistry,
        Run,
        RunEvent,
        TaskAnalysis,
        SecurityDecisionModel,
        Plan,
        ContextPackage,
        ToolRequest,
        PolicyDecisionModel,
        Approval,
        ToolExecution,
        ValidationFinding,
        RunResult,
        AuditEvent,
        LoopDetection,
    )


class Base(DeclarativeBase):
    """Base class for all models"""
    pass


class RunStatus(str, enum.Enum):
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


class RoutingMode(str, enum.Enum):
    AUTO = "auto"
    FIXED = "fixed"
    MAX = "max"


class PolicyDecision(str, enum.Enum):
    ALLOW = "ALLOW"
    ALLOW_WITH_MONITORING = "ALLOW_WITH_MONITORING"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DENY = "DENY"
    QUARANTINE = "QUARANTINE"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ExecutionStatus(str, enum.Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    ERROR = "error"


class ValidationStatus(str, enum.Enum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    SKIPPED = "skipped"


class FinalStatus(str, enum.Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    TIMEOUT_FAILED = "timeout_failed"


class SecurityDecision(str, enum.Enum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    NEEDS_APPROVAL = "needs_approval"


class RiskClass(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================
# Models
# ============================================================

class Workspace(Base):
    __tablename__ = "workspaces"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    repository_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    repository_type: Mapped[str] = mapped_column(String(50), default="python")
    initial_commit_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    
    snapshots = relationship("RepositorySnapshot", back_populates="workspace", cascade="all, delete-orphan")
    runs = relationship("Run", back_populates="workspace", cascade="all, delete-orphan")


class RepositorySnapshot(Base):
    __tablename__ = "repository_snapshots"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=generate_uuid)
    workspace_id: Mapped[str] = mapped_column(UUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    commit_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    branch_name: Mapped[str] = mapped_column(String(255), default="main")
    snapshot_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    workspace: Mapped["Workspace"] = relationship(back_populates="snapshots")
    runs: Mapped[List["Run"]] = relationship(back_populates="snapshot")
    
    __table_args__ = (UniqueConstraint("workspace_id", "commit_hash", name="uq_workspace_commit"),)


class BudgetProfile(Base):
    __tablename__ = "budget_profiles"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    max_steps: Mapped[int] = mapped_column(Integer, default=10)
    max_tool_calls: Mapped[int] = mapped_column(Integer, default=20)
    max_retries: Mapped[int] = mapped_column(Integer, default=1)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    max_input_tokens: Mapped[int] = mapped_column(Integer, default=8000)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=2000)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    
    runs: Mapped[List["Run"]] = relationship(back_populates="budget_profile")


class ModelRegistry(Base):
    __tablename__ = "model_registry"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=generate_uuid)
    model_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), default="nebius")
    tier: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    context_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_reasoning: Mapped[bool] = mapped_column(Boolean, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    verification_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    terms_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    
    runs: Mapped[List["Run"]] = relationship(back_populates="requested_model")
    context_packages: Mapped[List["ContextPackage"]] = relationship(back_populates="model")
    run_results: Mapped[List["RunResult"]] = relationship(back_populates="model_used")


class Run(Base):
    __tablename__ = "runs"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=generate_uuid)
    workspace_id: Mapped[str] = mapped_column(UUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    snapshot_id: Mapped[Optional[str]] = mapped_column(UUID, ForeignKey("repository_snapshots.id", ondelete="SET NULL"), nullable=True)
    budget_profile_id: Mapped[str] = mapped_column(UUID, ForeignKey("budget_profiles.id"), nullable=False)
    # parent_run_id links follow-up prompts in the same chat thread
    parent_run_id: Mapped[Optional[str]] = mapped_column(UUID, ForeignKey("runs.id", ondelete="SET NULL"), nullable=True)
    task_text: Mapped[str] = mapped_column(Text, nullable=False)
    task_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    routing_mode: Mapped[RoutingMode] = mapped_column(Enum(RoutingMode), default=RoutingMode.AUTO, nullable=False)
    requested_model_id: Mapped[Optional[str]] = mapped_column(UUID, ForeignKey("model_registry.id"), nullable=True)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.QUEUED, nullable=False)
    current_stage: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    steps_completed: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls_count: Mapped[int] = mapped_column(Integer, default=0)
    retries_count: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    total_elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # conversation_history: ordered list of {"role": ..., "content": ...} dicts
    # representing the full multi-turn thread rooted at this run (or its root).
    conversation_history: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    
    workspace: Mapped["Workspace"] = relationship(back_populates="runs")
    snapshot: Mapped[Optional["RepositorySnapshot"]] = relationship(back_populates="runs")
    budget_profile: Mapped["BudgetProfile"] = relationship(back_populates="runs")
    requested_model: Mapped[Optional["ModelRegistry"]] = relationship(back_populates="runs")
    # Self-referential: thread children
    parent: Mapped[Optional["Run"]] = relationship("Run", remote_side="Run.id", foreign_keys="Run.parent_run_id", back_populates="children")
    children: Mapped[List["Run"]] = relationship("Run", foreign_keys="Run.parent_run_id", back_populates="parent")
    
    events: Mapped[List["RunEvent"]] = relationship(back_populates="run", cascade="all, delete-orphan", order_by="RunEvent.created_at")
    task_analysis: Mapped[Optional["TaskAnalysis"]] = relationship(back_populates="run", uselist=False, cascade="all, delete-orphan")
    security_decision: Mapped[Optional["SecurityDecisionModel"]] = relationship(back_populates="run", uselist=False, cascade="all, delete-orphan")
    plan: Mapped[Optional["Plan"]] = relationship(back_populates="run", uselist=False, cascade="all, delete-orphan")
    context_packages: Mapped[List["ContextPackage"]] = relationship(back_populates="run", cascade="all, delete-orphan", order_by="ContextPackage.step_number")
    tool_requests: Mapped[List["ToolRequest"]] = relationship(back_populates="run", cascade="all, delete-orphan", order_by="ToolRequest.step_number")
    policy_decisions: Mapped[List["PolicyDecisionModel"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    approvals: Mapped[List["Approval"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    tool_executions: Mapped[List["ToolExecution"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    validation_findings: Mapped[List["ValidationFinding"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    run_result: Mapped[Optional["RunResult"]] = relationship(back_populates="run", uselist=False, cascade="all, delete-orphan")
    audit_events: Mapped[List["AuditEvent"]] = relationship(back_populates="run", cascade="all, delete-orphan", order_by="AuditEvent.event_index")
    loop_detections: Mapped[List["LoopDetection"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("ix_runs_workspace_id", "workspace_id"),
        Index("ix_runs_status", "status"),
        Index("ix_runs_created_at", "created_at"),
        Index("ix_runs_parent_run_id", "parent_run_id"),
    )


class RunEvent(Base):
    __tablename__ = "run_events"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(UUID, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    stage: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    event_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    run: Mapped["Run"] = relationship(back_populates="events")
    
    __table_args__ = (Index("ix_run_events_run_id", "run_id"),)


class TaskAnalysis(Base):
    __tablename__ = "task_analyses"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(UUID, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    constraints: Mapped[dict] = mapped_column(JSON, default=list)
    acceptance_tests: Mapped[dict] = mapped_column(JSON, default=list)
    risk_class: Mapped[RiskClass] = mapped_column(Enum(RiskClass), nullable=False)
    likely_artifacts: Mapped[dict] = mapped_column(JSON, default=list)
    proposed_capabilities: Mapped[dict] = mapped_column(JSON, default=list)
    analyzer_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    run: Mapped["Run"] = relationship(back_populates="task_analysis")


class SecurityDecisionModel(Base):
    __tablename__ = "security_decisions"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(UUID, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    decision: Mapped[SecurityDecision] = mapped_column(Enum(SecurityDecision), nullable=False)
    reason_codes: Mapped[dict] = mapped_column(JSON, default=list)
    provenance_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    injection_findings: Mapped[dict] = mapped_column(JSON, default=list)
    risk_level: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    gateway_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    run: Mapped["Run"] = relationship(back_populates="security_decision")


class Plan(Base):
    __tablename__ = "plans"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(UUID, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_files: Mapped[dict] = mapped_column(JSON, default=list)
    candidate_symbols: Mapped[dict] = mapped_column(JSON, default=list)
    tool_sequence: Mapped[dict] = mapped_column(JSON, default=list)
    test_command: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    stop_conditions: Mapped[dict] = mapped_column(JSON, default=list)
    estimated_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_time_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    planner_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    run: Mapped["Run"] = relationship(back_populates="plan")


class ContextPackage(Base):
    __tablename__ = "context_packages"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(UUID, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    model_id: Mapped[Optional[str]] = mapped_column(UUID, ForeignKey("model_registry.id"), nullable=True)
    included_files: Mapped[dict] = mapped_column(JSON, default=list)
    omitted_categories: Mapped[dict] = mapped_column(JSON, default=list)
    ranking_reasons: Mapped[dict] = mapped_column(JSON, default=dict)
    cache_hits: Mapped[int] = mapped_column(Integer, default=0)
    estimated_input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    actual_input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    compression_ratio: Mapped[Optional[float]] = mapped_column(Integer, nullable=True)  # stored as int * 100
    context_optimizer_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    run: Mapped["Run"] = relationship(back_populates="context_packages")
    model: Mapped[Optional["ModelRegistry"]] = relationship(back_populates="context_packages")


class ToolRequest(Base):
    __tablename__ = "tool_requests"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(UUID, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    arguments: Mapped[dict] = mapped_column(JSON, nullable=False)
    provenance: Mapped[str] = mapped_column(String(50), nullable=False)
    expected_risk: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    run: Mapped["Run"] = relationship(back_populates="tool_requests")
    policy_decisions: Mapped[List["PolicyDecisionModel"]] = relationship(back_populates="tool_request")
    tool_executions: Mapped[List["ToolExecution"]] = relationship(back_populates="tool_request")


class PolicyDecisionModel(Base):
    __tablename__ = "policy_decisions"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(UUID, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    tool_request_id: Mapped[Optional[str]] = mapped_column(UUID, ForeignKey("tool_requests.id", ondelete="SET NULL"), nullable=True)
    capability: Mapped[str] = mapped_column(String(100), nullable=False)
    decision: Mapped[PolicyDecision] = mapped_column(Enum(PolicyDecision), nullable=False)
    reason_codes: Mapped[dict] = mapped_column(JSON, default=list)
    risk_level: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    normalized_arguments: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    target_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    policy_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    engine_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    run: Mapped["Run"] = relationship(back_populates="policy_decisions")
    tool_request: Mapped[Optional["ToolRequest"]] = relationship(back_populates="policy_decisions")
    approvals: Mapped[List["Approval"]] = relationship(back_populates="policy_decision")
    tool_executions: Mapped[List["ToolExecution"]] = relationship(back_populates="policy_decision")
    
    __table_args__ = (Index("ix_policy_decisions_run_id", "run_id"),)


class Approval(Base):
    __tablename__ = "approvals"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(UUID, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    policy_decision_id: Mapped[str] = mapped_column(UUID, ForeignKey("policy_decisions.id", ondelete="CASCADE"), nullable=False)
    scope_description: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(Enum(ApprovalStatus), default=ApprovalStatus.PENDING, nullable=False)
    approver_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    run: Mapped["Run"] = relationship(back_populates="approvals")
    policy_decision: Mapped["PolicyDecisionModel"] = relationship(back_populates="approvals")
    
    __table_args__ = (Index("ix_approvals_run_id", "run_id"), Index("ix_approvals_status", "status"),)


class ToolExecution(Base):
    __tablename__ = "tool_executions"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(UUID, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    tool_request_id: Mapped[Optional[str]] = mapped_column(UUID, ForeignKey("tool_requests.id", ondelete="SET NULL"), nullable=True)
    policy_decision_id: Mapped[Optional[str]] = mapped_column(UUID, ForeignKey("policy_decisions.id", ondelete="SET NULL"), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    arguments: Mapped[dict] = mapped_column(JSON, nullable=False)
    stdout: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stderr: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sandbox_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    execution_status: Mapped[ExecutionStatus] = mapped_column(Enum(ExecutionStatus), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    run: Mapped["Run"] = relationship(back_populates="tool_executions")
    tool_request: Mapped[Optional["ToolRequest"]] = relationship(back_populates="tool_executions")
    policy_decision: Mapped[Optional["PolicyDecisionModel"]] = relationship(back_populates="tool_executions")
    
    __table_args__ = (Index("ix_tool_executions_run_id", "run_id"),)


class ValidationFinding(Base):
    __tablename__ = "validation_findings"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(UUID, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    check_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[ValidationStatus] = mapped_column(Enum(ValidationStatus), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    critic_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    run: Mapped["Run"] = relationship(back_populates="validation_findings")
    
    __table_args__ = (Index("ix_validation_findings_run_id", "run_id"),)


class RunResult(Base):
    __tablename__ = "run_results"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(UUID, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    final_status: Mapped[FinalStatus] = mapped_column(Enum(FinalStatus), nullable=False)
    patch_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    patch_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    test_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    critic_findings: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    policy_decisions_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    blocked_actions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    limitations: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    model_used_id: Mapped[Optional[str]] = mapped_column(UUID, ForeignKey("model_registry.id"), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    total_tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    evidence_report: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    run: Mapped["Run"] = relationship(back_populates="run_result")
    model_used: Mapped[Optional["ModelRegistry"]] = relationship(back_populates="run_results")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(UUID, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    event_index: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    current_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    run: Mapped["Run"] = relationship(back_populates="audit_events")
    
    __table_args__ = (
        UniqueConstraint("run_id", "event_index", name="uq_run_event_index"),
        Index("ix_audit_events_run_id", "run_id"),
    )


class LoopDetection(Base):
    __tablename__ = "loop_detections"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(UUID, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    action_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized_command: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_class: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    last_attempt_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    run: Mapped["Run"] = relationship(back_populates="loop_detections")
    
    __table_args__ = (Index("ix_loop_detections_run_id", "run_id"),)
