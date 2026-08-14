"""GET /metrics — Prometheus exposition (PRD Phase 16)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from app.core.config import get_settings
from app.core.metrics import metrics

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics_endpoint() -> Response:
    if not get_settings().metrics_enabled:
        return Response(status_code=503, content="metrics disabled")
    return Response(
        content=metrics.render(),
        media_type="text/plain; version=0.0.4",
    )
