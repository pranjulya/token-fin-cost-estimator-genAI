"""Unit tests for ObservabilityMiddleware (Phase 16)."""

from __future__ import annotations

import structlog
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.middleware import ObservabilityMiddleware


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    app.add_middleware(ObservabilityMiddleware)
    return app


async def test_echoes_supplied_request_id():
    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get("/ping", headers={"X-Request-ID": "req_manual"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID") == "req_manual"


async def test_generates_request_id_when_absent():
    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get("/ping")
    rid = resp.headers.get("X-Request-ID")
    assert rid and rid.startswith("req_")


async def test_binds_contextvars_and_clears():
    app = _make_app()
    structlog.contextvars.clear_contextvars()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        await client.get("/ping", headers={"X-Request-ID": "req_ctx"})
    # After the request, contextvars are cleared (no leak to next request).
    assert structlog.contextvars.get_contextvars() == {}
