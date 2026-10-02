"""
Execution context passed from the orchestrator to the worker.

Rules:
- Must NOT contain secrets (API keys, tokens, passwords).
- Must NOT be used as an authorization mechanism.
- Policy decisions are the responsibility of the Security Gateway / Policy Engine.
"""
from __future__ import annotations

from typing import FrozenSet
from pydantic import BaseModel, Field


class ExecutionContext(BaseModel):
    """
    Typed, immutable execution context for a single run.

    Passed from the orchestrator/API layer to the worker.  The worker
    uses this to locate the workspace and know which capabilities were
    approved by the policy layer — it does not re-authorise anything.
    """

    model_config = {"frozen": True}  # immutable after creation

    run_id: str = Field(..., description="Unique identifier of the current run")
    repository_root: str = Field(
        ...,
        description="Workspace-relative or absolute path to the repository root. Must not be empty.",
    )
    capabilities: FrozenSet[str] = Field(
        default_factory=frozenset,
        description="Approved capability tokens (e.g. repo.read, repo.write, test.run). Read-only.",
    )
    timeout_seconds: int = Field(
        900,
        ge=1,
        le=3600,
        description="Maximum wall-clock seconds the worker may run before being terminated.",
    )
