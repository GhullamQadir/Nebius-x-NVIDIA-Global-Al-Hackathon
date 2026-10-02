from fastapi.testclient import TestClient
from apps.api.main import app
from packages.contracts.run import RunState

client = TestClient(app)


def test_create_run_valid_request():
    payload = {
        "repository": {
            "source": "workspace://fixture-repo",
            "revision": "HEAD"
        },
        "task": "Fix the failing empty-input authentication test in auth.py",
        "acceptance": ["pytest tests/test_auth.py"],
        "autonomy": "sandboxed",
        "budgets": {
            "max_steps": 25,
            "max_tool_calls": 50,
            "timeout_seconds": 600,
            "max_input_tokens": 40000,
            "max_output_tokens": 8000
        }
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


def test_create_run_invalid_empty_task():
    payload = {
        "repository": {
            "source": "workspace://fixture-repo"
        },
        "task": ""  # empty task must fail min_length validation
    }
    response = client.post("/v1/runs", json=payload)
    assert response.status_code == 422


def test_create_run_missing_repository():
    payload = {
        "task": "Fix a generic bug without specifying repository"
    }
    response = client.post("/v1/runs", json=payload)
    assert response.status_code == 422


def test_create_run_invalid_budget_boundaries():
    payload = {
        "repository": {
            "source": "workspace://repo"
        },
        "task": "Valid task string",
        "budgets": {
            "max_steps": 500  # Exceeds max 100 limit
        }
    }
    response = client.post("/v1/runs", json=payload)
    assert response.status_code == 422


def test_get_run_existing():
    create_res = client.post("/v1/runs", json={
        "repository": {"source": "workspace://test-repo"},
        "task": "Add input sanitization for password parameter"
    })
    run_id = create_res.json()["run_id"]

    get_res = client.get(f"/v1/runs/{run_id}")
    assert get_res.status_code == 200
    assert get_res.json()["run_id"] == run_id


def test_get_run_not_found():
    response = client.get("/v1/runs/run_non_existent_999")
    assert response.status_code == 404


def test_cancel_run_success():
    create_res = client.post("/v1/runs", json={
        "repository": {"source": "workspace://cancel-test"},
        "task": "Task to be cancelled mid-flight"
    })
    run_id = create_res.json()["run_id"]

    cancel_res = client.post(f"/v1/runs/{run_id}/cancel")
    assert cancel_res.status_code == 200
    data = cancel_res.json()
    assert data["status"] == RunState.CANCELLED.value

    # Verify run state is CANCELLED
    get_res = client.get(f"/v1/runs/{run_id}")
    assert get_res.json()["state"] == RunState.CANCELLED.value


def test_list_runs():
    response = client.get("/v1/runs")
    assert response.status_code == 200
    runs = response.json()
    assert isinstance(runs, list)
    assert len(runs) >= 1
