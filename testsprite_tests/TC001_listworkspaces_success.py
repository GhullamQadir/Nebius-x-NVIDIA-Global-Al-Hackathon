import requests

BASE_URL = "http://localhost:8001"
TIMEOUT = 30

def test_listworkspaces_success():
    url = BASE_URL.rstrip("/") + "/api/v1/workspaces"
    headers = {"Accept": "application/json"}
    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise AssertionError(f"HTTP request to {url} failed: {e}")

    assert resp.status_code == 200, f"Expected status 200, got {resp.status_code}: {resp.text}"

    try:
        data = resp.json()
    except ValueError:
        raise AssertionError("Response is not valid JSON")

    # Accept either a list of workspaces or an object with a 'workspaces' list
    if isinstance(data, list):
        workspaces = data
    elif isinstance(data, dict) and isinstance(data.get("workspaces"), list):
        workspaces = data["workspaces"]
    else:
        raise AssertionError(f"Unexpected response shape: {type(data)} -- {data}")

    # Validate each workspace entry is an object and optionally has an id if present
    for idx, ws in enumerate(workspaces):
        assert isinstance(ws, dict), f"Workspace at index {idx} is not an object: {ws}"
        if "id" in ws:
            assert isinstance(ws["id"], (str, int)), f"Workspace id at index {idx} has unexpected type: {type(ws['id'])}"

    print(f"test_listworkspaces_success: PASSED ({len(workspaces)} workspace(s) returned)")

if __name__ == "__main__":
    test_listworkspaces_success()