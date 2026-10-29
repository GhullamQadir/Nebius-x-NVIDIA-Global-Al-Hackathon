import requests
import time
import sys

BASE_URL = "http://localhost:8001"
TIMEOUT = 30
HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}


def test_startrun_success():
    ws_id = None
    run_id = None

    # Create a workspace to use for the run
    try:
        ws_payload = {
            "name": f"test-ws-{int(time.time())}",
            "description": "Workspace for TC006 startrun_success"
        }
        resp = requests.post(f"{BASE_URL}/api/v1/workspaces", json=ws_payload, headers=HEADERS, timeout=TIMEOUT)
        assert resp.status_code == 200, f"Expected 200 creating workspace, got {resp.status_code}, body={resp.text}"
        ws_json = resp.json()
        # Expecting an id field in returned Workspace object
        assert isinstance(ws_json, dict), f"Workspace create response not a JSON object: {ws_json}"
        assert "id" in ws_json, f"Workspace object missing 'id': {ws_json}"
        ws_id = ws_json["id"]

        # Create a run in queued/planning state
        run_payload = {
            "workspace_id": ws_id,
            "revision": "main",
            # API expects 'task_text' field
            "task_text": "Add a small feature for testing start run",
            "acceptance_criteria": "Code builds and tests pass",
            "autonomy": "low",
            # routing_mode must be 'auto' or 'fixed'
            "routing_mode": "auto",
            "budgets": {"tokens": 1000}
        }
        resp = requests.post(f"{BASE_URL}/api/v1/runs", json=run_payload, headers=HEADERS, timeout=TIMEOUT)
        assert resp.status_code == 200, f"Expected 200 creating run, got {resp.status_code}, body={resp.text}"
        run_json = resp.json()
        assert isinstance(run_json, dict), f"Run create response not a JSON object: {run_json}"
        assert "id" in run_json, f"Run object missing 'id': {run_json}"
        assert "status" in run_json, f"Run object missing 'status': {run_json}"
        run_id = run_json["id"]

        initial_status = run_json.get("status")
        assert initial_status in ("queued", "planning", "queued/planning", None) or isinstance(initial_status, str), \
            f"Unexpected initial run status: {initial_status}"

        # Start the run
        start_resp = requests.post(f"{BASE_URL}/api/v1/runs/{run_id}/start", headers=HEADERS, timeout=TIMEOUT)
        assert start_resp.status_code == 200, f"Expected 200 starting run, got {start_resp.status_code}, body={start_resp.text}"
        start_json = start_resp.json()
        assert isinstance(start_json, dict), f"Start run response not a JSON object: {start_json}"
        assert "status" in start_json, f"Start run response missing 'status': {start_json}"
        updated_status = start_json["status"]

        # Validate the run status moved to execution
        assert updated_status == "execution", f"Expected run status 'execution' after start, got '{updated_status}'"

        print("TC006 passed: Run started and status updated to 'execution'.")

    except AssertionError:
        raise
    except Exception as e:
        # Re-raise as assertion to mark test failure
        raise AssertionError(f"Unexpected error during test_startrun_success: {e}") from e
    finally:
        # Cleanup: attempt to delete run and workspace if created. Ignore errors during cleanup.
        if run_id is not None:
            try:
                requests.delete(f"{BASE_URL}/api/v1/runs/{run_id}", headers=HEADERS, timeout=TIMEOUT)
            except Exception:
                pass
        if ws_id is not None:
            try:
                requests.delete(f"{BASE_URL}/api/v1/workspaces/{ws_id}", headers=HEADERS, timeout=TIMEOUT)
            except Exception:
                pass


if __name__ == "__main__":
    try:
        test_startrun_success()
    except AssertionError as e:
        print(f"Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(2)
    sys.exit(0)
