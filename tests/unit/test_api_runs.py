from fastapi.testclient import TestClient
from apps.api.main import app
from packages.contracts.run import RunState

client = TestClient(app)

# ---------------------------------------------------------------------------
# Valid run creation
# ---------------------------------------------------------------------------

def test_create_run_valid_request():
    """POST /v1/runs with full valid payload returns 201 and correct shape."""
    payload = {
        "repository": {
            "source": "workspace://fixture-repo",
            "revision": "HEAD",
        },
        "task": "Fix the failing empty-input authentication test in auth.py",
        "acceptance": ["pytest tests/test_auth.py"],
        "autonomy": "sandboxed",
        "budgets": {
            "max_steps": 25,
            "max_tool_calls": 50,
            "timeout_seconds": 600,
            "max_input_tokens": 40000,
            "max_output_tokens": 8000,
        },
    }
    response = client.post("/v1/runs", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "run_id" in data
    assert data["run_id"].startswith("run_")
    assert data["state"] == RunState.QUEUED.value
    assert data["task"] == payload["task"]
    assert data["repository"]["source"] == "workspace://fixture-repo"
    assert data["budgets"]["max_steps"] == 25
    assert data["plan"] is not None
    assert "task_analysis" in data["plan"]


def test_create_run_gets_unique_run_id():
    """Each POST /v1/runs returns a distinct run_id."""
    payload = {
        "repository": {"source": "workspace://repo"},
        "task": "Add type hints to all public functions",
    }
    r1 = client.post("/v1/runs", json=payload).json()
    r2 = client.post("/v1/runs", json=payload).json()
    assert r1["run_id"] != r2["run_id"]


def test_create_run_initial_state_is_queued():
    """Initial run state must always be QUEUED."""
    payload = {
        "repository": {"source": "workspace://repo"},
        "task": "Refactor database connection pooling logic",
    }
    data = client.post("/v1/runs", json=payload).json()
    assert data["state"] == RunState.QUEUED.value


def test_create_run_valid_repository_fields():
    """Valid repository target with optional revision is accepted."""
    payload = {
        "repository": {
            "source": "workspace://my-service",
            "revision": "abc1234",
        },
        "task": "Add structured logging to the API layer",
    }
    response = client.post("/v1/runs", json=payload)
    assert response.status_code == 201
    assert response.json()["repository"]["revision"] == "abc1234"


def test_create_run_valid_autonomy_sandboxed():
    """autonomy=sandboxed is accepted."""
    payload = {
        "repository": {"source": "workspace://repo"},
        "task": "Fix null pointer in handler",
        "autonomy": "sandboxed",
    }
    assert client.post("/v1/runs", json=payload).status_code == 201


def test_create_run_valid_autonomy_monitored():
    """autonomy=monitored is accepted."""
    payload = {
        "repository": {"source": "workspace://repo"},
        "task": "Fix null pointer in handler",
        "autonomy": "monitored",
    }
    assert client.post("/v1/runs", json=payload).status_code == 201


# ---------------------------------------------------------------------------
# Invalid request validation
# ---------------------------------------------------------------------------

def test_create_run_invalid_empty_task():
    """Empty task string fails Pydantic min_length validation -> 422."""
    payload = {
        "repository": {"source": "workspace://fixture-repo"},
        "task": "",
    }
    assert client.post("/v1/runs", json=payload).status_code == 422


def test_create_run_missing_task():
    """Missing task field fails validation -> 422."""
    payload = {"repository": {"source": "workspace://fixture-repo"}}
    assert client.post("/v1/runs", json=payload).status_code == 422


def test_create_run_missing_repository():
    """Missing repository field fails validation -> 422."""
    payload = {"task": "Fix a generic bug without specifying repository"}
    assert client.post("/v1/runs", json=payload).status_code == 422


def test_create_run_malformed_repository():
    """repository without required source field fails -> 422."""
    payload = {
        "repository": {"revision": "HEAD"},  # source missing
        "task": "Fix something",
    }
    assert client.post("/v1/runs", json=payload).status_code == 422


def test_create_run_invalid_budget_boundaries():
    """max_steps exceeding max (100) fails -> 422."""
    payload = {
        "repository": {"source": "workspace://repo"},
        "task": "Valid task string",
        "budgets": {"max_steps": 500},
    }
    assert client.post("/v1/runs", json=payload).status_code == 422


def test_create_run_invalid_request_body():
    """Completely non-JSON body fails -> 422."""
    response = client.post(
        "/v1/runs",
        content=b"not-json-at-all",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET run
# ---------------------------------------------------------------------------

def test_get_run_existing():
    """GET /v1/runs/{run_id} returns 200 for existing run."""
    create_res = client.post(
        "/v1/runs",
        json={
            "repository": {"source": "workspace://test-repo"},
            "task": "Add input sanitization for password parameter",
        },
    )
    run_id = create_res.json()["run_id"]
    get_res = client.get(f"/v1/runs/{run_id}")
    assert get_res.status_code == 200
    assert get_res.json()["run_id"] == run_id


def test_get_run_not_found():
    """GET /v1/runs/{run_id} returns 404 for unknown run."""
    response = client.get("/v1/runs/run_nonexistent_000")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Cancel run
# ---------------------------------------------------------------------------

def test_cancel_run_success():
    """Valid cancellation transitions run to CANCELLED."""
    create_res = client.post(
        "/v1/runs",
        json={
            "repository": {"source": "workspace://cancel-test"},
            "task": "Task to be cancelled mid-flight",
        },
    )
    run_id = create_res.json()["run_id"]
    cancel_res = client.post(f"/v1/runs/{run_id}/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == RunState.CANCELLED.value

    get_res = client.get(f"/v1/runs/{run_id}")
    assert get_res.json()["state"] == RunState.CANCELLED.value


def test_cancel_run_unknown_returns_404():
    """Cancel of unknown run_id returns 404."""
    response = client.post("/v1/runs/run_unknown_xyz/cancel")
    assert response.status_code == 404


def test_cancel_run_already_completed_returns_409():
    """Cancellation of a terminal-state run is rejected with 409."""
    # Create and advance to COMPLETED via mock pipeline
    create_res = client.post(
        "/v1/runs",
        json={
            "repository": {"source": "workspace://completed-test"},
            "task": "Advance to completion then try to cancel",
        },
    )
    run_id = create_res.json()["run_id"]

    # Advance all the way to COMPLETED
    terminal_states = {RunState.COMPLETED, RunState.FAILED, RunState.BLOCKED, RunState.CANCELLED}
    for _ in range(15):
        r = client.post(f"/v1/runs/{run_id}/advance")
        if r.json().get("state") in {s.value for s in terminal_states}:
            break

    # Now try to cancel — must fail
    cancel_res = client.post(f"/v1/runs/{run_id}/cancel")
    assert cancel_res.status_code == 409


# ---------------------------------------------------------------------------
# List runs
# ---------------------------------------------------------------------------

def test_list_runs():
    """GET /v1/runs returns a list."""
    response = client.get("/v1/runs")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
