import requests

BASE_ENDPOINT = "http://localhost:8001"

def test_createworkspace_validationerror_TC004():
    session = requests.Session()
    headers = {"Content-Type": "application/json"}
    list_url = BASE_ENDPOINT.rstrip("/") + "/api/v1/workspaces"

    def extract_count(data):
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            for key in ("workspaces", "items", "data", "results"):
                if key in data and isinstance(data[key], list):
                    return len(data[key])
            if "total" in data and isinstance(data["total"], int):
                return data["total"]
        return None

    # Get initial workspace count (if possible)
    try:
        resp = session.get(list_url, headers=headers, timeout=30)
    except requests.RequestException as e:
        raise AssertionError(f"Failed to GET workspaces: {e}")
    assert resp.status_code == 200, f"Expected 200 from GET /api/v1/workspaces, got {resp.status_code}. Body: {resp.text}"
    try:
        initial_data = resp.json()
    except ValueError:
        initial_data = None
    initial_count = extract_count(initial_data) if initial_data is not None else None

    # Send malformed payload expected to trigger 4xx validation error
    malformed_payload = {
        "invalid_field": ["unexpected", {"nested": "object"}],
        "name": 12345  # assuming name should be a string; this is intentionally malformed
    }

    try:
        post_resp = session.post(list_url, headers=headers, json=malformed_payload, timeout=30)
    except requests.RequestException as e:
        raise AssertionError(f"Failed to POST malformed workspace payload: {e}")

    assert 400 <= post_resp.status_code < 500, (
        f"Expected 4xx validation error for malformed payload, got {post_resp.status_code}. Response body: {post_resp.text}"
    )

    # Verify workspace was not created by comparing counts if possible
    try:
        resp_after = session.get(list_url, headers=headers, timeout=30)
    except requests.RequestException as e:
        raise AssertionError(f"Failed to GET workspaces after malformed POST: {e}")
    assert resp_after.status_code == 200, f"Expected 200 from GET after POST, got {resp_after.status_code}. Body: {resp_after.text}"
    try:
        after_data = resp_after.json()
    except ValueError:
        after_data = None
    after_count = extract_count(after_data) if after_data is not None else None

    if initial_count is not None and after_count is not None:
        assert after_count == initial_count, f"Workspace count changed after malformed POST: before={initial_count}, after={after_count}"

if __name__ == "__main__":
    test_createworkspace_validationerror_TC004()
    print("TC004 passed")