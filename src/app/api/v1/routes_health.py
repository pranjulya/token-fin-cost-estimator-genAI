"""Liveness and readiness probes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.version import get_build_sha, get_version
from app.db.session import async_engine

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": get_version(),
        "build": get_build_sha(),
    }


@router.get("/ready")
async def ready() -> JSONResponse:
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return JSONResponse({"status": "ready", "database": "ok"})
    except Exception:
        return JSONResponse({"status": "not_ready", "database": "unavailable"}, status_code=503)
