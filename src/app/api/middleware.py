"""Request-scoped observability middleware (PRD Phase 16).

- Resolves a request_id from ``X-Request-ID`` (or generates ``req_xxx``).
- Binds request_id / correlation_id / endpoint / method to structlog
  contextvars so every log in the request carries them (merge_contextvars).
- Echoes the request_id back as an ``X-Request-ID`` response header.
- Times the request, records the Prometheus request metrics, and emits one
  ``request_completed`` access-log event.
- Never logs request bodies (prompt privacy, PRD §35).
"""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.metrics import metrics

logger = structlog.get_logger("app.access")


def _new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:24]}"


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        request_id = request.headers.get("X-Request-ID") or _new_request_id()
        correlation_id = request.headers.get("X-Correlation-ID") or request_id

        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            correlation_id=correlation_id,
            endpoint=request.url.path,
            method=request.method,
        )

        response = Response(status_code=500)
        try:
            response = await call_next(request)
            return response
        finally:
            response.headers.setdefault("X-Request-ID", request_id)
            duration = time.perf_counter() - start
            status = response.status_code
            metrics.record_request(
                duration_seconds=duration,
                endpoint=request.url.path,
                status=status,
                provider=structlog.contextvars.get_contextvars().get("provider", ""),
                model=structlog.contextvars.get_contextvars().get("model", ""),
            )
            logger.info(
                "request_completed",
                request_id=request_id,
                correlation_id=correlation_id,
                endpoint=request.url.path,
                method=request.method,
                status=status,
                latency_ms=round(duration * 1000, 2),
                duration_seconds=round(duration, 6),
            )
            structlog.contextvars.clear_contextvars()
