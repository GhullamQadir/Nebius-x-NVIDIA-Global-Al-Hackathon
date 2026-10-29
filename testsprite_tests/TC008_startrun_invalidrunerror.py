import requests
import uuid
import time
import sys

BASE_URL = "http://localhost:8001"
TIMEOUT = 30


def test_startrun_invalidrunerror():
    workspace_id = None
    run_id = None
    created_run_ids = []
    created_workspace_id = None

    headers = {"Content-Type": "application/json"}

    try:
        # 1) Create a workspace to use for run creation
        ws_payload = {"name": f"tc008-ws-{int(time.time())}"}
        resp = requests.post(f"{BASE_URL}/api/v1/workspaces", json=ws_payload, headers=headers, timeout=TIMEOUT)
        assert resp.status_code == 200, f"Expected 200 creating workspace, got {resp.status_code}, body={resp.text}"
        ws_obj = resp.json()
        workspace_id = ws_obj.get("id") or ws_obj.get("workspace_id") or ws_obj.get("id")
        assert workspace_id, f"Workspace creation response missing id: {ws_obj}"
        created_workspace_id = workspace_id

        # 2) Create a run to test unauthorized and terminal scenarios
        run_payload = {
            "workspace_id": workspace_id,
            "revision": "main",
            "task_text": "TC008 test task",
            "acceptance_criteria": "Create a run for negative start tests",
            "autonomy": 0,
            "routing_mode": "auto",
            "budgets": {"tokens": 1000}
        }
        resp = requests.post(f"{BASE_URL}/api/v1/runs", json=run_payload, headers=headers, timeout=TIMEOUT)
        assert resp.status_code == 200, f"Expected 200 creating run, got {resp.status_code}, body={resp.text}"
        run_obj = resp.json()
        run_id = run_obj.get("id") or run_obj.get("run_id") or run_obj.get("uuid")
        assert run_id, f"Run creation response missing id: {run_obj}"
        created_run_ids.append(run_id)

        # Capture original state
        def get_run_state(rid, hdrs=None):
            try:
                r = requests.get(f"{BASE_URL}/api/v1/runs/{rid}", headers=hdrs or headers, timeout=TIMEOUT)
            except requests.RequestException as e:
                raise AssertionError(f"GET /runs/{rid} request failed: {e}")
            # If the GET returns non-200, still return status for validation
            if r.status_code != 200:
                return None, r.status_code, r.text
            j = r.json()
            state = j.get("state") or j.get("status") or j.get("state_name")
            return state, r.status_code, r.text

        orig_state, _, _ = get_run_state(run_id)

        # Scenario A: Nonexistent run -> POST start should return 4xx (e.g., 404) and GET should not find it
        nonexistent_id = str(uuid.uuid4())
        try:
            resp = requests.post(f"{BASE_URL}/api/v1/runs/{nonexistent_id}/start", headers=headers, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise AssertionError(f"POST start for nonexistent run request failed: {e}")
        assert 400 <= resp.status_code < 500, f"Expected 4xx when starting nonexistent run, got {resp.status_code}, body={resp.text}"

        # Verify GET nonexistent returns 4xx as well (likely 404)
        try:
            resp_get = requests.get(f"{BASE_URL}/api/v1/runs/{nonexistent_id}", headers=headers, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise AssertionError(f"GET nonexistent run request failed: {e}")
        assert 400 <= resp_get.status_code < 500, f"Expected 4xx when getting nonexistent run, got {resp_get.status_code}, body={resp_get.text}"

        # Scenario B: Unauthorized attempt to start an existing run
        # Use an obviously invalid token to simulate unauthorized access
        bad_headers = {"Content-Type": "application/json", "Authorization": "Bearer invalid-token-for-tc008"}
        try:
            resp_unauth = requests.post(f"{BASE_URL}/api/v1/runs/{run_id}/start", headers=bad_headers, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise AssertionError(f"POST start (unauthorized) request failed: {e}")

        # Accept either 200 (no auth required) or 4xx (if server enforces auth)
        assert (resp_unauth.status_code == 200) or (400 <= resp_unauth.status_code < 500), (
            f"Expected 200 or 4xx for unauthorized start attempt, got {resp_unauth.status_code}, body={resp_unauth.text}"
        )

        # If unauthorized attempt returned 4xx, ensure run state remains unchanged
        # If it returned 200, treat it as a successful start and update the state accordingly
        started_by_unauth = False
        if resp_unauth.status_code == 200:
            state_after_unauth, status_get, _ = get_run_state(run_id)
            assert status_get == 200, f"Expected to be able to GET run after unauthorized (200) attempt, got {status_get}"
            # We consider this as the run having been started
            started_by_unauth = True
            state_after_first_start = state_after_unauth
        else:
            state_after_unauth, status_get, _ = get_run_state(run_id)
            if orig_state is not None:
                assert state_after_unauth == orig_state, (
                    f"Run state changed after unauthorized start attempt. before={orig_state} after={state_after_unauth}"
                )
            else:
                assert status_get == 200, f"Expected to be able to GET run after unauthorized attempt, got {status_get}"

        # Scenario C: Already terminal run -> attempt to simulate terminal by starting twice:
        # If unauthorized already started the run, treat that as the first start; otherwise perform first start now.
        if not started_by_unauth:
            try:
                resp_start1 = requests.post(f"{BASE_URL}/api/v1/runs/{run_id}/start", headers=headers, timeout=TIMEOUT)
            except requests.RequestException as e:
                raise AssertionError(f"First POST start request failed: {e}")
            assert resp_start1.status_code == 200, f"Expected first start to succeed with 200, got {resp_start1.status_code}, body={resp_start1.text}"

            # Capture state after first start
            state_after_first_start, status_get, _ = get_run_state(run_id)
            assert status_get == 200, f"Expected GET run to succeed after first start, got {status_get}"
        else:
            # already captured state_after_first_start above
            assert state_after_first_start is not None, "Expected state after unauthorized start to be present"

        # Second start attempt: per PRD, already terminal (or invalid) should return 4xx/403.
        try:
            resp_start2 = requests.post(f"{BASE_URL}/api/v1/runs/{run_id}/start", headers=headers, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise AssertionError(f"Second POST start request failed: {e}")

        assert 400 <= resp_start2.status_code < 500, (
            f"Expected 4xx when starting an already-started/terminal run, got {resp_start2.status_code}, body={resp_start2.text}"
        )

        # Ensure run state remains unchanged after the failed second start
        state_after_second_start, status_get2, _ = get_run_state(run_id)
        assert status_get2 == 200, f"Expected GET run to succeed after second start attempt, got {status_get2}"
        assert state_after_second_start == state_after_first_start, (
            f"Run state should remain unchanged after failed second start. before={state_after_first_start} after={state_after_second_start}"
        )

        print("TC008 passed: startrun_invalidrunerror")

    finally:
        # Cleanup created runs
        for rid in created_run_ids:
            try:
                requests.delete(f"{BASE_URL}/api/v1/runs/{rid}", headers=headers, timeout=TIMEOUT)
            except Exception:
                pass
        # Cleanup workspace
        if created_workspace_id:
            try:
                requests.delete(f"{BASE_URL}/api/v1/workspaces/{created_workspace_id}", headers=headers, timeout=TIMEOUT)
            except Exception:
                pass


if __name__ == "__main__":
    try:
        test_startrun_invalidrunerror()
    except AssertionError as e:
        print(f"Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error during test execution: {e}")
        sys.exit(2)
    sys.exit(0)
