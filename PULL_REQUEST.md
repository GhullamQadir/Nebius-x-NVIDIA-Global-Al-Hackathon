## Purpose

Implements the complete Day 2 backend foundation for the Backend / Task Orchestration workstream (Azizullah).

This PR delivers all interfaces, contracts, and foundational logic required for teammates to build their modules independently. No real agent execution, LLM calls, sandbox, or external integrations are introduced.

Specifically:
- Completes the FastAPI skeleton with `GET /v1/health` returning `{"status": "ok"}`.
- Implements full run lifecycle routes: `POST /v1/runs`, `GET /v1/runs/{run_id}`, `POST /v1/runs/{run_id}/cancel`.
- Implements and enforces the 11-stage run state machine with terminal-state protection.
- Defines `TaskAnalyzerProtocol` (Protocol interface) alongside the rule-based implementation.
- Defines typed `ExecutionContext` (run_id, repository_root, capabilities, timeout) — no secrets.
- Defines `WorkerProtocol` and `WorkerResult` contracts for the worker execution layer.
- Defines `ToolExecutorProtocol`, `ToolRequest`, `ToolResponse` — abstraction between worker and future Tool Router / Policy / Sandbox.
- Implements `MockWorker` — deterministic, no LLM, no shell, no file I/O — for pipeline verification.

## Files changed

**New files:**
- `packages/contracts/execution_context.py` — typed immutable `ExecutionContext`
- `packages/contracts/worker.py` — `WorkerProtocol`, `ToolExecutorProtocol`, `WorkerResult`, `ToolRequest`, `ToolResponse`
- `apps/worker/mock_worker.py` — deterministic `MockWorker` implementing `WorkerProtocol`
- `tests/unit/test_execution_context.py` — 12 tests for ExecutionContext
- `tests/unit/test_worker.py` — 16 tests for Worker/ToolExecutor interfaces and MockWorker

**Modified files:**
- `apps/api/routes_health.py` — `status` changed from `"healthy"` to `"ok"` per spec
- `apps/orchestrator/state_machine.py` — fixed `cancel_run` to raise `InvalidStateTransitionError` on terminal states (was silently returning 200)
- `packages/task_analyzer/analyzer.py` — added `TaskAnalyzerProtocol` (Protocol) alongside existing `TaskAnalyzer`
- `tests/unit/test_health.py` — updated to assert `status == "ok"`, added response structure test
- `tests/unit/test_api_runs.py` — expanded from 8 to 18 tests: unique run_id, valid autonomy values, all invalid request cases, 404 cancel, 409 terminal cancel
- `tests/unit/test_state_machine.py` — expanded from 4 to 16 tests: all cancellable states, terminal protection, invalid transitions, policy denial

## Contract/API impact

**Endpoints (no breaking changes to existing routes):**

| Method | Path | Change |
|---|---|---|
| `GET` | `/v1/health` | `status` value changed from `"healthy"` to `"ok"` — spec alignment |
| `POST` | `/v1/runs` | No change to request/response schema |
| `GET` | `/v1/runs/{run_id}` | No change |
| `POST` | `/v1/runs/{run_id}/cancel` | Now correctly returns **409 Conflict** for terminal-state runs (was silently 200) |

**New contracts (additive, no breaking changes):**

- `ExecutionContext` — `packages/contracts/execution_context.py`
- `WorkerProtocol`, `ToolExecutorProtocol`, `WorkerResult`, `ToolRequest`, `ToolResponse` — `packages/contracts/worker.py`
- `TaskAnalyzerProtocol` — added to `packages/task_analyzer/analyzer.py`

## Security impact

- No real tool execution introduced.
- No secrets added anywhere (ExecutionContext explicitly excludes secret fields; verified by test).
- No model authorization introduced — `TaskAnalyzer` only proposes capabilities; Policy Engine decides.
- No host access introduced — `MockWorker` makes zero system calls.
- `ToolExecutorProtocol` is an abstraction only; no concrete shell/filesystem/network implementation.
- `ExecutionContext` is frozen (immutable) and contains no secret fields — verified by `test_execution_context_no_secrets`.
- Terminal-state cancel now correctly raises 409 instead of silently returning 200 — prevents misleading success signals on cancelled runs.

## Tests executed

```
python -m pytest tests/unit -v
# 69 passed, 1 warning in 0.69s

python scratch/manual_test.py
# All 6 live API calls verified:
#   GET  /v1/health            -> 200  {"status": "ok"}
#   POST /v1/runs              -> 201  run_id assigned, state=QUEUED
#   GET  /v1/runs/{run_id}     -> 200  correct state and task
#   GET  /v1/runs/run_unknown  -> 404  (correct)
#   POST /v1/runs/{run_id}/cancel -> 200 status=CANCELLED
#   POST /v1/runs/{run_id}/cancel (again) -> 409 (terminal-state rejection)
```

Server started with: `python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8001`

No ruff or mypy configured in the repository — not installed, not run.

## Reviewer requested

- **Ghulam Qadir** (Co-Lead / Integration Lead) — primary reviewer for all shared contracts and run lifecycle
- **Asif** (Security & Policy Lead) — please review security impact section and `ExecutionContext` design

## Known limitations

- `InMemoryRunStore` is intentionally used — no persistence layer exists in the repository yet.
- Real worker execution is not implemented — `MockWorker` is deterministic stub only.
- Real `ToolExecutorProtocol` implementation not included — Tool Router / Policy / Sandbox integration is a future step (Yash / Asif workstream).
- Nemotron / Nebius Token Factory integration is not part of this task.
- Sandbox execution is not part of this task.
- `advance` route (mock pipeline step-forward) was introduced in Day 2 for demo/testing; not part of the public spec — can be removed or protected before final submission.
