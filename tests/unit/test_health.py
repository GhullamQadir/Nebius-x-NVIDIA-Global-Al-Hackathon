from fastapi.testclient import TestClient
from apps.api.main import app

client = TestClient(app)


def test_get_health_status_ok():
    """GET /v1/health returns 200 with status ok."""
    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_get_health_response_structure():
    """GET /v1/health response contains required fields."""
    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "service" in data
    assert "version" in data
    assert data["service"] == "nexora-backend"
    assert data["version"] == "0.1.0"
