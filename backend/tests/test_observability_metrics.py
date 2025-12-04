from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.observability import setup_observability


def test_prometheus_metrics_endpoint_reports_request_counts():
    app = FastAPI()

    @app.get("/hello")
    def hello():
        return {"message": "hi"}

    setup_observability(app)

    client = TestClient(app)

    client.get("/hello")
    client.get("/hello")

    metrics_response = client.get("/metrics/prometheus")
    assert metrics_response.status_code == 200
    body = metrics_response.text
    assert "app_http_requests_total" in body
    assert 'route="/hello"' in body

