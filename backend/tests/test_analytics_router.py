from fastapi.testclient import TestClient

from app.main import app


def test_latency_anomalies_endpoint():
    client = TestClient(app)
    payload = {
        "baseline": [100, 110, 120],
        "candidate": [115, 130, 400],
        "threshold": 2.0,
    }
    response = client.post("/analytics/anomalies/latency", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert 2 in data["anomalies"]


def test_series_anomaly_endpoint_detects_outlier():
    client = TestClient(app)
    payload = {"series": [1, 1, 1, 10], "z_threshold": 1.5}
    response = client.post("/analytics/anomalies/series", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["anomaly_indices"] == [3]
    assert "processed_series" in data
