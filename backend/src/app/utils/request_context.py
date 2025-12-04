"""HTTP middleware to attach per-request context like correlation IDs."""

import time
import uuid
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Adds correlation IDs and timing metadata to each request."""

    def __init__(self, app, header_name: str = "X-Request-ID"):
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next) -> Response:
        correlation_id = request.headers.get(self.header_name) or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        request.state.started_at = time.time()

        response = await call_next(request)
        response.headers[self.header_name] = correlation_id
        duration_ms = int((time.time() - request.state.started_at) * 1000)
        response.headers["X-Response-Time-ms"] = str(duration_ms)
        return response


def get_correlation_id(request: Optional[Request]) -> Optional[str]:
    """Helper to fetch the correlation ID from a request if available."""
    if request is None:
        return None
    return getattr(request.state, "correlation_id", None)
