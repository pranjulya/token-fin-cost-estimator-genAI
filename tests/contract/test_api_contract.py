"""API contract tests (PRD Phase 18).

Assert the OpenAPI surface + error-envelope contract. No product logic — these
guard against accidental route/schema drift.
"""

from __future__ import annotations

import httpx

from app.main import app


def test_openapi_exposes_required_routes():
    paths = app.openapi()["paths"]
    assert "/v1/cost/estimate" in paths
    assert "/v1/generate" in paths
    assert "/v1/usage" in paths
    assert "/v1/budgets" in paths
    assert "/v1/models/pricing" in paths
    assert "/v1/alerts" in paths
    assert "/health" in paths
    assert "/ready" in paths
    assert "/metrics" in paths

    methods = {m for p in paths.values() for m in p}
    assert {"get", "post", "patch"} <= methods


async def test_error_envelope_shape_on_401():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        resp = await c.post("/v1/usage", json={})
    assert resp.status_code == 401
    body = resp.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "request_id"}
    assert body["error"]["code"] == "UNAUTHORIZED"


async def test_error_envelope_shape_on_404():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", headers={"X-API-Key": "test-admin-key"}
    ) as c:
        resp = await c.get("/v1/budgets/999999")
    assert resp.status_code == 404
    body = resp.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "request_id"}


async def test_health_metrics_open_without_auth():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        assert (await c.get("/health")).status_code == 200
        assert (await c.get("/metrics")).status_code == 200


async def test_metrics_scrape_token_required_when_set():
    import os

    from app.core.config import get_settings

    os.environ["APP_METRICS_SCRAPE_TOKEN"] = "scrape-secret"
    get_settings.cache_clear()
    try:
        test_app = __import__("app.main", fromlist=["create_app"]).create_app()
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            assert (await c.get("/metrics")).status_code == 401
            assert (
                await c.get("/metrics", headers={"Authorization": "Bearer nope"})
            ).status_code == 401
            ok = await c.get("/metrics", headers={"Authorization": "Bearer scrape-secret"})
            assert ok.status_code == 200
            assert "llm_requests_total" in ok.text
    finally:
        os.environ.pop("APP_METRICS_SCRAPE_TOKEN", None)
        get_settings.cache_clear()


async def test_v1_requires_auth():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        for path, method in (
            ("/v1/usage", "post"),
            ("/v1/cost/estimate", "post"),
            ("/v1/generate", "post"),
            ("/v1/budgets", "post"),
        ):
            resp = await c.request(method, path, json={})
            assert resp.status_code == 401, f"{method.upper()} {path} should require auth"
