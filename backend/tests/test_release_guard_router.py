from fastapi.testclient import TestClient

from app.main import app


def test_release_guard_endpoint_accepts_payload(monkeypatch):
    client = TestClient(app)

    payload = {
        "latency_p95_ms": 700,
        "latency_p99_ms": 1000,
        "success_rate": 0.995,
        "active_incidents": 0,
        "regression_tests_passed": True,
    }

    response = client.post("/release/guard", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "approved" in data
    assert data["approved"] is True


def test_release_guard_endpoint_blocks_on_failure(monkeypatch):
    client = TestClient(app)

    payload = {
        "latency_p95_ms": 5000,
        "latency_p99_ms": 6000,
        "success_rate": 0.2,
        "active_incidents": 2,
        "regression_tests_passed": False,
    }
    response = client.post("/release/guard", json=payload)
    assert response.status_code == 200
    assert response.json()["approved"] is False

