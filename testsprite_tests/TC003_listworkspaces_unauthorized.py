import requests
import sys

BASE_ENDPOINT = "http://localhost:8001"


def test_listworkspaces_unauthorized():
    url = BASE_ENDPOINT.rstrip("/") + "/api/v1/workspaces"
    # Keep an invalid Authorization header to simulate an unauthenticated client, but per PRD the endpoint is public
    headers = {
        "Authorization": "Bearer invalid_or_expired_token",
        "Accept": "application/json",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=30)
    except requests.RequestException as e:
        raise AssertionError(f"HTTP request failed: {e}")

    # Per PRD, this endpoint does not require auth and should return 200 with a WorkspaceList
    if resp.status_code != 200:
        raise AssertionError(
            f"Expected status 200 for public workspace listing, got {resp.status_code}. Response body: {resp.text}"
        )

    try:
        body = resp.json()
    except ValueError:
        raise AssertionError(f"Response is not valid JSON. Status: {resp.status_code}. Body: {resp.text}")

    if not isinstance(body, dict):
        raise AssertionError(f"Expected JSON object in response, got {type(body)}")

    # Expect a list of workspaces under 'workspaces' key and an optional 'total' field
    if "workspaces" not in body:
        raise AssertionError(f"'workspaces' key missing in response: {list(body.keys())}")
    if not isinstance(body["workspaces"], list):
        raise AssertionError(f"'workspaces' should be a list, got {type(body['workspaces'])}")

    if "total" in body and not isinstance(body["total"], int):
        raise AssertionError(f"'total' should be int, got {type(body['total'])}")

    # If there are items, check structure of first item
    if len(body["workspaces"]) > 0:
        first = body["workspaces"][0]
        if not isinstance(first, dict):
            raise AssertionError(f"workspace item should be dict, got {type(first)}")
        for key in ("id", "name", "is_active"):
            if key not in first:
                raise AssertionError(f"workspace item missing expected key '{key}': {list(first.keys())}")


if __name__ == "__main__":
    try:
        test_listworkspaces_unauthorized()
        print("TC003 listworkspaces_unauthorized: PASSED")
        sys.exit(0)
    except AssertionError as e:
        print(f"TC003 listworkspaces_unauthorized: FAILED - {e}")
        sys.exit(1)