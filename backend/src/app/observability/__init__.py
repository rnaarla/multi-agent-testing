"""Observability utilities for tracing, logging, metrics, and alerting."""

from __future__ import annotations

from fastapi import FastAPI
from typing import Optional

from .logging import configure_logging_once
from .metrics import configure_metrics_once
from .tracing import configure_tracing

_configured_apps: set[int] = set()


def setup_observability(
    app: FastAPI,
    *,
    tracing_exporter=None,
) -> None:
    """
    Configure logging, tracing, and metrics for the given FastAPI app.

    The configuration is idempotent; subsequent calls with the same app are ignored.
    Tests can pass a custom ``tracing_exporter`` such as ``InMemorySpanExporter``
    for assertions.
    """

    app_id = id(app)
    if app_id in _configured_apps:
        return

    configure_logging_once()
    configure_metrics_once(app)
    configure_tracing(app, exporter=tracing_exporter)

    _configured_apps.add(app_id)

