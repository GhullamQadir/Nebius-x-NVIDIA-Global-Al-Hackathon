import requests
import uuid
import sys

BASE_ENDPOINT = "http://localhost:8001/"

def test_createrun_success():
    headers = {"Content-Type": "application/json"}
    workspace_id = None
    run_id = None

    # Create a workspace to use for the run
    workspace_payload = {
        "name": f"test-workspace-{uuid.uuid4().hex[:8]}",
        "description": "Workspace for TC005 createrun_success"
    }

    try:
        try:
            resp_ws = requests.post(
                BASE_ENDPOINT + "api/v1/workspaces",
                json=workspace_payload,
                headers=headers,
                timeout=30
            )
        except requests.RequestException as e:
            raise AssertionError(f"Request to create workspace failed: {e}")

        assert resp_ws.status_code == 200, f"Expected 200 creating workspace, got {resp_ws.status_code}: {resp_ws.text}"
        try:
            ws_json = resp_ws.json()
        except ValueError:
            raise AssertionError(f"Workspace create response is not valid JSON: {resp_ws.text}")

        assert isinstance(ws_json, dict), "Workspace response JSON is not an object"
        workspace_id = ws_json.get("id") or ws_json.get("workspace_id")
        assert workspace_id, f"No workspace id returned in response: {ws_json}"

        # Prepare run payload with required fields
        run_payload = {
            "workspace_id": workspace_id,
            "revision": "main",
            "task": "Refactor parser to handle edge-case inputs",
            "task_text": "Refactor the parser module so it robustly handles edge-case inputs such as empty streams, unexpected tokens, and large payloads.",
            "acceptance_criteria": "All existing tests pass and edge-case tests added pass",
            "autonomy": True,
            "routing_mode": "auto",
            "budgets": {
                "token_budget": 1000,
                "time_budget_seconds": 300
            }
        }

        try:
            resp_run = requests.post(
                BASE_ENDPOINT + "api/v1/runs",
                json=run_payload,
                headers=headers,
                timeout=30
            )
        except requests.RequestException as e:
            raise AssertionError(f"Request to create run failed: {e}")

        assert resp_run.status_code == 200, f"Expected 200 creating run, got {resp_run.status_code}: {resp_run.text}"
        try:
            run_json = resp_run.json()
        except ValueError:
            raise AssertionError(f"Run create response is not valid JSON: {resp_run.text}")

        assert isinstance(run_json, dict), "Run response JSON is not an object"

        run_id = run_json.get("id") or run_json.get("run_id")
        assert run_id, f"No run id returned in response: {run_json}"

        # Validate returned run fields
        returned_ws = run_json.get("workspace_id") or run_json.get("workspace")
        # Accept both nested or direct workspace id representations
        if isinstance(returned_ws, dict):
            returned_ws_id = returned_ws.get("id") or returned_ws.get("workspace_id")
        else:
            returned_ws_id = returned_ws

        assert str(returned_ws_id) == str(workspace_id), f"Run workspace_id mismatch: expected {workspace_id}, got {returned_ws_id}"

        # Accept task returned under several possible keys and allow matching either payload 'task' or 'task_text'
        task_returned = run_json.get("task") or run_json.get("task_text") or run_json.get("description")
        expected_task_values = {run_payload["task"], run_payload["task_text"]}
        assert task_returned in expected_task_values, f"Run task mismatch: expected one of {expected_task_values}, got {task_returned}"

        # budgets and other fields should be present (best-effort)
        assert "budgets" in run_json or "budget" in run_json, "Run response missing budgets information (expected 'budgets' or 'budget')"

        print("TC005 createrun_success: PASSED")

    finally:
        # Cleanup: attempt to delete created run and workspace if API supports it
        if run_id:
            try:
                requests.delete(
                    BASE_ENDPOINT + f"api/v1/runs/{run_id}",
                    headers=headers,
                    timeout=30
                )
            except Exception:
                # best-effort cleanup; do not fail the test on cleanup error
                print(f"Warning: failed to delete run {run_id}", file=sys.stderr)

        if workspace_id:
            try:
                requests.delete(
                    BASE_ENDPOINT + f"api/v1/workspaces/{workspace_id}",
                    headers=headers,
                    timeout=30
                )
            except Exception:
                print(f"Warning: failed to delete workspace {workspace_id}", file=sys.stderr)


if __name__ == "__main__":
    test_createrun_success()
