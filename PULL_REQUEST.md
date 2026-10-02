## Purpose
Implements the Day 2 milestone for Backend and Task Orchestration (Azizullah):
- Sets up the core FastAPI application skeleton and exposes the `GET /v1/health` endpoint.
- Implements placeholder run lifecycle endpoints: create run (`POST /v1/runs`), inspect run (`GET /v1/runs/{run_id}`), cancel run (`POST /v1/runs/{run_id}/cancel`), list runs (`GET /v1/runs`), and demo stage advancement (`POST /v1/runs/{run_id}/advance`).
- Implements the formal 11-stage execution state machine (`apps/orchestrator/state_machine.py`) with transition validation and a thread-safe `InMemoryRunStore`.
- Implements the Task Analyzer interface (`packages/task_analyzer/analyzer.py`) that normalizes tasks into structured objectives and proposed capabilities.
- Delivers an interactive, dark-mode dashboard UI (`frontend/index.html`) mounted directly onto FastAPI to visualize the live 11-stage pipeline, active stage pulse, and task analysis.

## Files changed
- `apps/api/main.py`: Main FastAPI application, CORS configuration, route inclusion, and static UI file mounting.
- `apps/api/routes_health.py`: Health check router exposing `GET /v1/health`.
- `apps/api/routes_runs.py`: Run routes for create, read, cancel, list, and mock advance.
- `apps/orchestrator/state_machine.py`: 11-stage state machine transitions, invariants, and `InMemoryRunStore`.
- `packages/contracts/run.py`: Pydantic contracts for `RunState`, `CreateRunRequest`, `RunResponse`, `TaskBudgets`, and `HealthResponse`.
- `packages/task_analyzer/analyzer.py`: `TaskAnalyzer` and `TaskAnalysisResult` capability extraction logic.
- `frontend/index.html`: Responsive dashboard with live health monitoring, task creation form, 11-stage pipeline tracker, and JSON terminal inspector.
- `tests/unit/test_health.py`: Unit tests for health endpoint.
- `tests/unit/test_api_runs.py`: Unit tests for valid/invalid run creation, retrieval, listing, and cancellation.
- `tests/unit/test_state_machine.py`: Invariant validation, illegal transition checks, terminal state lockdown, and policy denial.
- `tests/unit/test_task_analyzer.py`: Capability deduction, risk classification, and test parsing.
- `.gitignore`: Standard Python cache and test artifact ignores.

## Contract/API impact
Introduces the initial public API endpoints under `/v1`:
- `GET /v1/health`: Returns `HealthResponse` (`status="healthy"`, `service="nexora-backend"`, `version="0.1.0"`).
- `POST /v1/runs`: Accepts `CreateRunRequest`, validates payload and budgets, and returns `201 Created` with a new `RunResponse` in `QUEUED` state.
- `GET /v1/runs/{run_id}`: Returns current state, active stage, and generated artifacts.
- `POST /v1/runs/{run_id}/cancel`: Moves active run to `CANCELLED` state.
- `GET /v1/runs`: Returns array of all runs.
All schemas strictly adhere to the contracts defined in `architecture.pdf` Section 8.1 & 8.2.

## Security impact
- Strict request schema validation via Pydantic v2 (rejects empty task, missing repo, or out-of-boundary budgets with HTTP 422).
- Security policy checks embedded in the state machine (`SECURITY_REVIEW`, `POLICY_CHECK`, `AWAITING_APPROVAL`, `BLOCKED`).
- Task Analyzer adheres to the non-negotiable rule: it only proposes required capabilities for later policy evaluation and never grants authorization itself.
- Tasks referencing credentials or destructive actions are flagged as `high` risk.

## Tests executed
Executed the full unit test suite with `pytest -v tests/unit`:
- 16 tests collected, **16 passed in 0.78s**.
  - `tests/unit/test_api_runs.py::test_create_run_valid_request` PASSED
  - `tests/unit/test_api_runs.py::test_create_run_invalid_empty_task` PASSED (422 validation)
  - `tests/unit/test_api_runs.py::test_create_run_missing_repository` PASSED (422 validation)
  - `tests/unit/test_api_runs.py::test_create_run_invalid_budget_boundaries` PASSED (422 validation)
  - `tests/unit/test_api_runs.py::test_get_run_existing` PASSED
  - `tests/unit/test_api_runs.py::test_get_run_not_found` PASSED (404 verification)
  - `tests/unit/test_api_runs.py::test_cancel_run_success` PASSED (state becomes CANCELLED)
  - `tests/unit/test_api_runs.py::test_list_runs` PASSED
  - `tests/unit/test_health.py::test_get_health` PASSED
  - `tests/unit/test_state_machine.py::test_valid_state_transitions` PASSED
  - `tests/unit/test_state_machine.py::test_invalid_state_transitions` PASSED (raises InvalidStateTransitionError)
  - `tests/unit/test_state_machine.py::test_terminal_states_cannot_transition` PASSED
  - `tests/unit/test_state_machine.py::test_run_store_lifecycle_and_policy_denial` PASSED (BLOCKED transition)
  - `tests/unit/test_task_analyzer.py::test_task_analyzer_code_modification` PASSED
  - `tests/unit/test_task_analyzer.py::test_task_analyzer_high_risk_flagging` PASSED
  - `tests/unit/test_task_analyzer.py::test_task_analyzer_read_only_low_risk` PASSED
- Verified live HTTP server execution:
  - `GET /v1/health` -> HTTP 200 `{'status': 'healthy', ...}`
  - `POST /v1/runs` -> HTTP 201 `run_id` returned with initial analysis
  - `GET /` -> HTTP 200 Interactive Dashboard UI rendered

## Reviewer requested
- **Ghulam Qadir** (Co-Lead / Integration Lead)
- **Asif** (Security & Policy Lead)

## Known limitations
- Uses `InMemoryRunStore` for Day 2 milestone; database persistence (PostgreSQL / SQLite via Alembic) will be attached in subsequent phase.
- Step advancement currently uses mock pipeline progression for verification before real worker process and Nebius Token Factory inference adapter are connected.
