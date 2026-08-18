"""GET /metrics — Prometheus exposition (PRD Phase 16)."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Header
from fastapi.responses import Response

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError
from app.core.metrics import metrics

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics_endpoint(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Response:
    settings = get_settings()
    if not settings.metrics_enabled:
        return Response(status_code=503, content="metrics disabled")

    # Optional scrape token (e.g. Prometheus bearer_auth). Open by default so
    # a private scrape network works without config; set APP_METRICS_SCRAPE_TOKEN
    # to require it.
    if settings.metrics_scrape_token:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            token.strip(), settings.metrics_scrape_token
        ):
            raise AuthenticationError("Metrics scrape token required.")

    return Response(
        content=metrics.render(),
        media_type="text/plain; version=0.0.4",
    )
