import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.observability import setup_observability
from app.observability.logging import RequestLoggingMiddleware
from app.utils.request_context import RequestContextMiddleware


def test_structured_logging_includes_context(caplog):
    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"status": "ok"}

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    setup_observability(app)

    client = TestClient(app)
    caplog.clear()
    caplog.set_level("INFO")

    response = client.get("/ping", headers={"X-Request-ID": "req-123"})
    assert response.status_code == 200

    structured_records = []
    for record in caplog.records:
        try:
            data = json.loads(record.message)
        except json.JSONDecodeError:
            continue
        if data.get("event") == "request.completed":
            structured_records.append(data)

    assert structured_records, "expected structured log records"
    record = structured_records[-1]
    assert record["correlation_id"] == "req-123"
    assert record["path"] == "/ping"
    assert record.get("trace_id"), "trace_id should be present for correlation"

