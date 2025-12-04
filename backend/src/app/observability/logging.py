"""Structured logging configuration and middleware."""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import structlog
from fastapi import Request
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

_logging_configured = False


def configure_logging_once() -> None:
    """Configure structlog-backed logging in an idempotent way."""

    global _logging_configured
    if _logging_configured:
        return

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    structlog.reset_defaults()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, log_level, logging.INFO)),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging through structlog
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(message)s",
    )

    _logging_configured = True


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that emits a structured log entry for every request."""

    def __init__(self, app, logger_name: str = "api.request"):
        super().__init__(app)
        self.logger = structlog.get_logger(logger_name)

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        initial_correlation = getattr(request.state, "correlation_id", None)
        correlation_id = initial_correlation
        status: Optional[int] = None

        with structlog.contextvars.bound_contextvars(method=request.method, path=request.url.path):
            try:
                response = await call_next(request)
                status = response.status_code
                correlation_id = getattr(request.state, "correlation_id", initial_correlation)
                return response
            finally:
                duration = time.perf_counter() - start
                trace_id = _current_trace_id()
                span_id = _current_span_id()
                structlog.contextvars.bind_contextvars(
                    trace_id=trace_id,
                    span_id=span_id,
                    correlation_id=correlation_id,
                )
                self.logger.info(
                    "request.completed",
                    status=status or 500,
                    duration_ms=round(duration * 1000, 3),
                )
                structlog.contextvars.reset_contextvars()


def _current_trace_id() -> Optional[str]:
    span = trace.get_current_span()
    span_context = span.get_span_context()
    if span_context and span_context.trace_id:
        return format(span_context.trace_id, "032x")
    return None


def _current_span_id() -> Optional[str]:
    span = trace.get_current_span()
    span_context = span.get_span_context()
    if span_context and span_context.span_id:
        return format(span_context.span_id, "016x")
    return None

