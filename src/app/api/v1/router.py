"""Assemble the v1 API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    routes_alerts,
    routes_budget,
    routes_cost,
    routes_generate,
    routes_health,
    routes_pricing,
    routes_usage,
)

api_router = APIRouter(prefix="/v1")
api_router.include_router(routes_cost.router)
api_router.include_router(routes_usage.router)
api_router.include_router(routes_pricing.router)
api_router.include_router(routes_budget.router)
api_router.include_router(routes_alerts.router)
api_router.include_router(routes_generate.router)

# Health endpoints are version-agnostic; mount at root too.
health_router = APIRouter()
health_router.include_router(routes_health.router)
