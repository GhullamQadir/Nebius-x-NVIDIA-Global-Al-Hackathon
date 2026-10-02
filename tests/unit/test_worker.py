"""
Tests for WorkerProtocol, ToolExecutorProtocol, and MockWorker.
No real tool execution, shell, LLM, or network access in these tests.
"""
import pytest
from packages.contracts.execution_context import ExecutionContext
from packages.contracts.worker import (
    WorkerProtocol,
    ToolExecutorProtocol,
    WorkerResult,
    ToolRequest,
    ToolResponse,
)
from apps.worker.mock_worker import MockWorker


# ---------------------------------------------------------------------------
# WorkerResult contract
# ---------------------------------------------------------------------------

def test_worker_result_has_expected_structure():
    """WorkerResult exposes required fields."""
    result = WorkerResult(
        run_id="run_abc",
        success=True,
        diff="--- a/f.py\n+++ b/f.py\n",
        test_output="1 passed",
        steps_taken=2,
        tool_calls_made=4,
    )
    assert result.run_id == "run_abc"
    assert result.success is True
    assert isinstance(result.diff, str)
    assert isinstance(result.steps_taken, int)
    assert isinstance(result.tool_calls_made, int)


def test_worker_result_failure_carries_error():
    """WorkerResult can represent failure with an error message."""
    result = WorkerResult(run_id="run_fail", success=False, error="sandbox timeout")
    assert result.success is False
    assert result.error == "sandbox timeout"


# ---------------------------------------------------------------------------
# MockWorker — protocol compliance
# ---------------------------------------------------------------------------

def test_mock_worker_satisfies_protocol():
    """MockWorker must structurally satisfy WorkerProtocol."""
    worker = MockWorker()
    assert isinstance(worker, WorkerProtocol)


def _make_context(run_id: str = "run_test001") -> ExecutionContext:
    return ExecutionContext(
        run_id=run_id,
        repository_root="workspace://test-repo",
        capabilities=frozenset(["repo.read", "repo.write", "test.run"]),
        timeout_seconds=120,
    )


def test_mock_worker_accepts_execution_context():
    """MockWorker.execute() accepts a valid ExecutionContext without error."""
    worker = MockWorker()
    ctx = _make_context()
    result = worker.execute(ctx)
    assert result is not None


def test_mock_worker_returns_worker_result():
    """MockWorker.execute() returns a WorkerResult instance."""
    worker = MockWorker()
    result = worker.execute(_make_context())
    assert isinstance(result, WorkerResult)


def test_mock_worker_run_id_matches_context():
    """WorkerResult.run_id must match ExecutionContext.run_id."""
    worker = MockWorker()
    ctx = _make_context("run_specific_123")
    result = worker.execute(ctx)
    assert result.run_id == "run_specific_123"


def test_mock_worker_returns_success():
    """MockWorker always returns success=True."""
    worker = MockWorker()
    result = worker.execute(_make_context())
    assert result.success is True


def test_mock_worker_deterministic_output():
    """Two identical calls produce identical results."""
    worker = MockWorker()
    ctx = _make_context("run_determ")
    r1 = worker.execute(ctx)
    r2 = worker.execute(ctx)
    assert r1.diff == r2.diff
    assert r1.test_output == r2.test_output
    assert r1.steps_taken == r2.steps_taken
    assert r1.tool_calls_made == r2.tool_calls_made


def test_mock_worker_diff_is_string():
    """Returned diff is a non-empty string."""
    worker = MockWorker()
    result = worker.execute(_make_context())
    assert isinstance(result.diff, str)
    assert len(result.diff) > 0


def test_mock_worker_no_error():
    """MockWorker returns no error on success."""
    worker = MockWorker()
    result = worker.execute(_make_context())
    assert result.error is None


# ---------------------------------------------------------------------------
# ToolExecutorProtocol — interface contract
# ---------------------------------------------------------------------------

class _StubToolExecutor:
    """Minimal no-op ToolExecutor for testing the Protocol definition."""

    def execute_tool(self, request: ToolRequest, context: ExecutionContext) -> ToolResponse:
        return ToolResponse(tool_name=request.tool_name, success=True, output="stub-output")


def test_stub_tool_executor_satisfies_protocol():
    """A minimal implementation satisfies ToolExecutorProtocol."""
    executor = _StubToolExecutor()
    assert isinstance(executor, ToolExecutorProtocol)


def test_tool_request_model():
    """ToolRequest is a valid Pydantic model."""
    req = ToolRequest(tool_name="repo.read", arguments={"path": "src/main.py"})
    assert req.tool_name == "repo.read"
    assert req.arguments["path"] == "src/main.py"


def test_tool_response_model_success():
    """ToolResponse captures success with output."""
    resp = ToolResponse(tool_name="repo.read", success=True, output="file content")
    assert resp.success is True
    assert resp.output == "file content"
    assert resp.error is None


def test_tool_response_model_failure():
    """ToolResponse captures failure with error."""
    resp = ToolResponse(tool_name="repo.write", success=False, error="permission denied")
    assert resp.success is False
    assert resp.error == "permission denied"


def test_stub_executor_returns_tool_response():
    """Stub executor returns a ToolResponse."""
    executor = _StubToolExecutor()
    ctx = _make_context()
    req = ToolRequest(tool_name="repo.read", arguments={"path": "src/"})
    resp = executor.execute_tool(req, ctx)
    assert isinstance(resp, ToolResponse)
    assert resp.tool_name == "repo.read"
