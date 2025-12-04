"""OpenTelemetry tracing helpers."""

from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

try:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore
        OTLPSpanExporter,
    )
except Exception:  # pragma: no cover - optional dependency
    OTLPSpanExporter = None  # type: ignore

_fastapi_instrumentor = FastAPIInstrumentor()
_requests_instrumented = False
_provider: Optional[TracerProvider] = None
_default_processor_configured = False


def configure_tracing(app: FastAPI, *, exporter: Optional[SpanExporter] = None) -> None:
    """Configure tracing for the application."""

    global _provider, _default_processor_configured

    if _provider is None:
        provider = TracerProvider(
            sampler=TraceIdRatioBased(float(os.getenv("OTEL_SAMPLING_RATIO", "1.0"))),
            resource=Resource.create(
                {
                    "service.name": os.getenv("OTEL_SERVICE_NAME", "multi-agent-testing"),
                    "service.namespace": os.getenv("OTEL_SERVICE_NAMESPACE", "platform"),
                    "deployment.environment": os.getenv("ENVIRONMENT", "local"),
                }
            ),
        )
        trace.set_tracer_provider(provider)
        _provider = provider
    else:
        provider = _provider

    if exporter is None and not _default_processor_configured:
        exporter = _default_exporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        _default_processor_configured = True
    elif exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))

    # Re-instrument if necessary
    if _fastapi_instrumentor.is_instrumented_by_opentelemetry:
        _fastapi_instrumentor.uninstrument_app(app)

    _fastapi_instrumentor.instrument_app(app, tracer_provider=provider)

    global _requests_instrumented
    if not _requests_instrumented:
        RequestsInstrumentor().instrument()
        _requests_instrumented = True


def get_tracer(name: str = "app") -> trace.Tracer:
    """Return a tracer from the globally configured provider."""

    return trace.get_tracer(name)


def _default_exporter() -> SpanExporter:
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint and OTLPSpanExporter:
        return OTLPSpanExporter(endpoint=otlp_endpoint)
    if os.getenv("OTEL_TRACING_CONSOLE", "false").lower() == "true":
        return ConsoleSpanExporter()
    return _NullSpanExporter()


class _NullSpanExporter(SpanExporter):
    """A no-op exporter used when no backend is configured."""

    def export(self, spans):
        return SpanExportResult.SUCCESS

    def shutdown(self):
        return

