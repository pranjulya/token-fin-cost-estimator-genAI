"""Assemble the v1 API router."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.auth import get_api_key, require_admin
from app.api.v1 import (
    routes_alerts,
    routes_budget,
    routes_cost,
    routes_generate,
    routes_health,
    routes_metrics,
    routes_pricing,
    routes_usage,
)

# All /v1 routes require a valid API key (Phase 17). Health/metrics stay open.
api_router = APIRouter(prefix="/v1", dependencies=[Depends(get_api_key)])

# Admin-only: budget management + alerts (ops). Pricing writes enforce
# require_admin at the handler; GET /v1/models/pricing stays user-readable.
admin_router = APIRouter(dependencies=[Depends(require_admin)])
admin_router.include_router(routes_budget.router)
admin_router.include_router(routes_alerts.router)

api_router.include_router(routes_cost.router)
api_router.include_router(routes_usage.router)
api_router.include_router(routes_generate.router)
api_router.include_router(routes_pricing.router)
api_router.include_router(admin_router)

# Health + metrics are version-agnostic; mount at root too.
health_router = APIRouter()
health_router.include_router(routes_health.router)
health_router.include_router(routes_metrics.router)
