"""
Mock worker for use in tests and integration verification.

This implementation:
- Does NOT call any LLM or Nemotron.
- Does NOT execute shell commands.
- Does NOT modify repository files.
- Does NOT access the host or external network.
- Does NOT bypass the policy layer.
- Returns a deterministic, hardcoded result.

Purpose: prove that ExecutionContext → WorkerProtocol → WorkerResult pipeline works.
"""
from __future__ import annotations

from packages.contracts.execution_context import ExecutionContext
from packages.contracts.worker import WorkerProtocol, WorkerResult


class MockWorker:
    """
    Deterministic mock implementation of WorkerProtocol.

    Always returns success=True with a fixed synthetic diff.
    Suitable for unit tests and Day 2 integration verification only.
    """

    # Deterministic outputs — never changes between calls
    _MOCK_DIFF = (
        "--- a/src/example.py\n"
        "+++ b/src/example.py\n"
        "@@ -1,4 +1,5 @@\n"
        " def handler(req):\n"
        "+    if req is None:\n"
        "+        raise ValueError('request must not be None')\n"
        "     return process(req)\n"
    )
    _MOCK_TEST_OUTPUT = (
        "collected 3 items\n"
        "tests/test_handler.py::test_handler_ok PASSED\n"
        "tests/test_handler.py::test_handler_none_raises PASSED\n"
        "tests/test_handler.py::test_handler_type PASSED\n"
        "3 passed in 0.02s\n"
    )

    def execute(self, context: ExecutionContext) -> WorkerResult:
        """
        Return a fixed deterministic WorkerResult.
        Ignores context content — no side effects.
        """
        return WorkerResult(
            run_id=context.run_id,
            success=True,
            diff=self._MOCK_DIFF,
            test_output=self._MOCK_TEST_OUTPUT,
            steps_taken=3,
            tool_calls_made=5,
            error=None,
        )


# Type-check that MockWorker structurally satisfies WorkerProtocol
assert isinstance(MockWorker(), WorkerProtocol), "MockWorker must satisfy WorkerProtocol"
