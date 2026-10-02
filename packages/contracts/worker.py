"""
Worker execution contract and Tool Executor interface.

These are interface definitions only.
No real tool execution, shell access, LLM calls, or sandbox integration.
"""
from __future__ import annotations

from typing import List, Optional
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from packages.contracts.execution_context import ExecutionContext


# ---------------------------------------------------------------------------
# Worker result
# ---------------------------------------------------------------------------

class WorkerResult(BaseModel):
    """Structured result produced by a worker after completing a run."""

    run_id: str = Field(..., description="Matches the ExecutionContext.run_id")
    success: bool = Field(..., description="True if the run completed without fatal errors")
    diff: Optional[str] = Field(None, description="Generated patch/diff if any code was modified")
    test_output: Optional[str] = Field(None, description="Captured pytest / test runner output")
    steps_taken: int = Field(0, ge=0, description="Number of agent steps consumed")
    tool_calls_made: int = Field(0, ge=0, description="Number of tool calls made")
    error: Optional[str] = Field(None, description="Error description if success is False")


# ---------------------------------------------------------------------------
# Worker interface
# ---------------------------------------------------------------------------

@runtime_checkable
class WorkerProtocol(Protocol):
    """
    Contract for a worker that executes a single run.

    Callers:
        Orchestrator passes an ExecutionContext and receives a WorkerResult.

    Rules:
        - Worker must NOT bypass the policy layer.
        - Worker must NOT access the host filesystem outside repository_root.
        - Worker must NOT store secrets in WorkerResult.
        - Model output is untrusted; the worker validates via ToolExecutor only.
    """

    def execute(self, context: ExecutionContext) -> WorkerResult:
        """Execute the run described by *context* and return a result."""
        ...


# ---------------------------------------------------------------------------
# Tool executor interface
# ---------------------------------------------------------------------------

class ToolRequest(BaseModel):
    """A single typed tool invocation request."""

    tool_name: str = Field(..., description="Name of the tool, e.g. repo.read, test.run")
    arguments: dict = Field(default_factory=dict, description="Tool-specific keyword arguments")


class ToolResponse(BaseModel):
    """Typed response returned by a tool after execution."""

    tool_name: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None


@runtime_checkable
class ToolExecutorProtocol(Protocol):
    """
    Abstraction between the worker and concrete tool implementations.

    Worker
      └──► ToolExecutorProtocol
               └──► Future: Tool Router → Policy Engine → Sandbox

    Rules:
        - Must NOT give the model direct host access.
        - Must NOT bypass the policy layer.
        - Must NOT execute shell commands without sandbox isolation.
        - Implementations must validate tool_name against an allow-list.
    """

    def execute_tool(
        self,
        request: ToolRequest,
        context: ExecutionContext,
    ) -> ToolResponse:
        """Execute *request* within the bounds of *context*."""
        ...
