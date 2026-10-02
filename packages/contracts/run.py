from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime, timezone


class RunState(str, Enum):
    QUEUED = "QUEUED"
    ANALYZING = "ANALYZING"
    SECURITY_REVIEW = "SECURITY_REVIEW"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    PLANNING = "PLANNING"
    CONTEXT_BUILD = "CONTEXT_BUILD"
    MODEL_STEP = "MODEL_STEP"
    POLICY_CHECK = "POLICY_CHECK"
    EXECUTING = "EXECUTING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    REPLANNING = "REPLANNING"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class RepositoryTarget(BaseModel):
    source: str = Field(..., description="Repository path or URL, e.g. workspace://repo")
    revision: Optional[str] = Field("HEAD", description="Commit SHA, branch, or tag")


class TaskBudgets(BaseModel):
    max_steps: int = Field(40, ge=1, le=100, description="Maximum agent execution steps")
    max_tool_calls: int = Field(80, ge=1, le=200, description="Maximum allowed tool calls")
    max_retries: int = Field(3, ge=0, le=10, description="Maximum recovery attempts")
    timeout_seconds: int = Field(900, ge=10, le=3600, description="Run timeout in seconds")
    max_input_tokens: int = Field(50000, ge=1000, le=200000, description="Token budget ceiling for prompt context")
    max_output_tokens: int = Field(12000, ge=100, le=32000, description="Token budget ceiling for model completion")


class CreateRunRequest(BaseModel):
    repository: RepositoryTarget = Field(..., description="Target repository details")
    task: str = Field(..., min_length=3, description="Natural language software engineering task")
    acceptance: Optional[List[str]] = Field(default_factory=list, description="Target acceptance tests or commands")
    autonomy: Optional[str] = Field("sandboxed", description="Autonomy profile: e.g. sandboxed, monitored")
    budgets: Optional[TaskBudgets] = Field(default_factory=TaskBudgets, description="Resource and execution budgets")


class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str = "nexora-backend"
    version: str = "0.1.0"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RunResponse(BaseModel):
    run_id: str
    state: RunState
    repository: RepositoryTarget
    task: str
    acceptance: List[str] = []
    autonomy: str = "sandboxed"
    budgets: TaskBudgets
    created_at: str
    updated_at: str
    active_stage: Optional[str] = None
    plan: Optional[Dict[str, Any]] = None
    security_decision: Optional[Dict[str, Any]] = None
    diff: Optional[str] = None
    validation_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class CancelRunResponse(BaseModel):
    run_id: str
    status: str
    message: str
