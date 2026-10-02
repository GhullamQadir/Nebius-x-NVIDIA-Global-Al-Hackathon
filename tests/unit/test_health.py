from fastapi.testclient import TestClient
from apps.api.main import app

client = TestClient(app)


def test_get_health():
    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "nexora-backend"
    assert data["version"] == "0.1.0"
    assert "timestamp" in data
