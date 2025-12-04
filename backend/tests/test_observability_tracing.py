from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.observability import setup_observability


def test_tracing_records_spans_for_requests():
    exporter = InMemorySpanExporter()
    app = FastAPI()

    @app.get("/hello")
    def hello():
        return {"ok": True}

    setup_observability(app, tracing_exporter=exporter)

    client = TestClient(app)
    exporter.clear()
    response = client.get("/hello")
    assert response.status_code == 200

    spans = exporter.get_finished_spans()
    assert spans, "expected at least one span to be exported"
    assert any("/hello" in span.name for span in spans)

