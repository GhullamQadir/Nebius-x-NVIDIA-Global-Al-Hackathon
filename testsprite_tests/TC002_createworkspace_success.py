import requests
import uuid

BASE_URL = "http://localhost:8001"

def test_createworkspace_success():
    url = BASE_URL.rstrip("/") + "/api/v1/workspaces"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    payload = {
        "name": f"test-workspace-{uuid.uuid4()}",
        "description": "Workspace created by automated test"
    }

    created_id = None

    try:
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
        except requests.RequestException as e:
            raise AssertionError(f"POST request to create workspace failed: {e}")

        assert resp.status_code == 200, f"Expected status 200, got {resp.status_code}, body: {resp.text}"
        content_type = resp.headers.get("Content-Type", "")
        assert "application/json" in content_type.lower(), f"Expected JSON response, got Content-Type: {content_type}"

        try:
            data = resp.json()
        except ValueError:
            raise AssertionError(f"Response body is not valid JSON: {resp.text}")

        assert isinstance(data, dict), f"Expected workspace object (dict), got {type(data)}"
        created_id = data.get("id") or data.get("_id") or data.get("workspace_id")
        assert created_id, f"Created workspace id not found in response: {data}"
        assert data.get("name") == payload["name"], f"Workspace name mismatch: expected {payload['name']}, got {data.get('name')}"

    finally:
        if created_id:
            del_url = BASE_URL.rstrip("/") + f"/api/v1/workspaces/{created_id}"
            try:
                del_resp = requests.delete(del_url, headers=headers, timeout=30)
                # Accept common successful deletion status codes
                assert del_resp.status_code in (200, 202, 204), f"Failed to delete workspace {created_id}, status {del_resp.status_code}, body: {del_resp.text}"
            except requests.RequestException as e:
                raise AssertionError(f"Cleanup DELETE request failed for workspace {created_id}: {e}")

if __name__ == "__main__":
    test_createworkspace_success()
    print("TC002 createworkspace_success passed")