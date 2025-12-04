"""Prometheus metrics helpers and middleware."""

from __future__ import annotations

import time
from typing import Optional

from fastapi import FastAPI, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

REQUEST_COUNTER = Counter(
    "app_http_requests_total",
    "Total HTTP requests processed",
    ["method", "route", "status"],
)

REQUEST_LATENCY = Histogram(
    "app_http_request_latency_seconds",
    "HTTP request latency in seconds",
    ["method", "route"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)

RUN_OUTCOME_COUNTER = Counter(
    "app_run_outcomes_total",
    "Total number of run outcomes recorded by status",
    ["status"],
)

RUN_COST_USD = Counter(
    "app_run_cost_usd_total",
    "Total cost in USD for completed runs partitioned by status",
    ["status"],
)

WORKER_ACTIVE_GAUGE = Gauge(
    "app_worker_active_jobs",
    "Number of active background jobs currently executing",
)

_configured_apps: set[int] = set()


def configure_metrics_once(app: FastAPI) -> None:
    """Register metrics middleware and endpoint exactly once per app."""

    app_id = id(app)
    if app_id in _configured_apps:
        return

    app.add_middleware(RequestMetricsMiddleware)
    app.add_route("/metrics/prometheus", prometheus_endpoint, methods=["GET"])
    _configured_apps.add(app_id)


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    """Collect metrics for each HTTP request."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        route = _safe_route(request)
        if not route.startswith("/metrics"):
            REQUEST_COUNTER.labels(request.method, route, str(response.status_code)).inc()
            REQUEST_LATENCY.labels(request.method, route).observe(duration)

        return response


async def prometheus_endpoint(request=None) -> Response:
    """Return the Prometheus exposition format metrics payload."""

    payload = generate_latest()
    return Response(payload, media_type=CONTENT_TYPE_LATEST)


def record_run_outcome(*, status: str, cost_usd: Optional[float] = None) -> None:
    """Update run outcome counters from worker and orchestration flows."""

    RUN_OUTCOME_COUNTER.labels(status=status).inc()
    if cost_usd:
        RUN_COST_USD.labels(status=status).inc(cost_usd)


class worker_job_active:
    """Context manager that updates the worker activity gauge."""

    def __enter__(self):
        WORKER_ACTIVE_GAUGE.inc()

    def __exit__(self, exc_type, exc_val, exc_tb):
        WORKER_ACTIVE_GAUGE.dec()
        # Do not suppress exceptions
        return False


def _safe_route(request: Request) -> str:
    route = request.scope.get("route")
    if route and getattr(route, "path", None):
        return route.path
    return request.url.path

