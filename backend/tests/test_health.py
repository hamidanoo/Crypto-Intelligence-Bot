from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "crypto-intelligence-backend"
    assert body["timestamp"]


def test_readiness_reports_components():
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in ("ready", "degraded")
    assert "database" in body["components"]
    assert "redis" in body["components"]
