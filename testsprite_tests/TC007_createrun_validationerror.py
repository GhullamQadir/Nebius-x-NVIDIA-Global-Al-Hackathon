import requests
import sys

BASE_URL = "http://localhost:8001"
RUNS_PATH = "/api/v1/runs"
TIMEOUT = 30
HEADERS = {"Content-Type": "application/json"}


def test_createrun_validationerror():
    url = BASE_URL.rstrip("/") + RUNS_PATH

    invalid_payloads = [
        # Completely missing required fields
        {},
        # Invalid budget values (negative tokens)
        {
            "workspace_id": "example-workspace",
            "revision": "main",
            "task": "Implement feature X",
            "acceptance_criteria": "Feature X should pass all tests",
            "autonomy": 0.7,
            "routing": "default",
            "budgets": {"tokens": -100}
        }
    ]

    for payload in invalid_payloads:
        created_run_id = None
        try:
            try:
                resp = requests.post(url, json=payload, headers=HEADERS, timeout=TIMEOUT)
            except requests.exceptions.RequestException as e:
                raise AssertionError(f"Request to create run failed with exception: {e}")

            # Expect a 4xx client validation error
            if 400 <= resp.status_code < 500:
                # Good: validation error returned
                # Additional checks: ensure response body does not include a created run id
                try:
                    body = resp.json()
                except ValueError:
                    body = None

                if isinstance(body, dict):
                    # There must not be an 'id' or full Run object returned on validation errors
                    assert "id" not in body, f"Validation error response unexpectedly contains 'id': {body}"
                    # Some APIs may nest errors; ensure no 'run' object present
                    assert "run" not in body, f"Validation error response unexpectedly contains 'run': {body}"
                continue  # proceed to next payload

            # If we reach here, server did not return a 4xx. If it returned 200, try to clean up created run.
            if resp.status_code == 200:
                try:
                    body = resp.json()
                except ValueError:
                    body = {}

                # Try to locate created run id in common locations
                created_run_id = None
                if isinstance(body, dict):
                    created_run_id = body.get("id") or (body.get("run") and body["run"].get("id"))

                # Fail the test because a validation case unexpectedly succeeded
                raise AssertionError(
                    f"Expected 4xx validation error but got 200 OK. Payload: {payload}. Response body: {body}"
                )
            else:
                # Unexpected non-4xx, non-200 status code
                raise AssertionError(
                    f"Expected 4xx validation error but got status {resp.status_code}. Response text: {resp.text}"
                )
        finally:
            # If a run was unexpectedly created, attempt best-effort deletion to avoid side effects.
            if created_run_id:
                delete_url = BASE_URL.rstrip("/") + f"/api/v1/runs/{created_run_id}"
                try:
                    requests.delete(delete_url, timeout=TIMEOUT, headers=HEADERS)
                except requests.exceptions.RequestException:
                    # Ignore cleanup failures but surface them via printed message
                    print(f"Warning: failed to clean up created run {created_run_id}", file=sys.stderr)


if __name__ == "__main__":
    test_createrun_validationerror()
    print("TC007 createrun_validationerror: PASSED")