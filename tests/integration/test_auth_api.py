"""Integration tests for Phase 17 API-key auth + admin scoping."""

from __future__ import annotations

from tests.integration.test_usage import seed_price


class TestAuthRequired:
    async def test_user_routes_require_key(self, client):
        # client sends a valid user key by default; build a no-key client here.
        import httpx

        from app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as anon:
            resp = await anon.post("/v1/usage", json={})
            assert resp.status_code == 401
            assert resp.json()["error"]["code"] == "UNAUTHORIZED"

    async def test_invalid_key_rejected(self, client):
        import httpx

        from app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver", headers={"X-API-Key": "bad"}
        ) as anon:
            resp = await anon.get("/v1/usage")
            assert resp.status_code == 401

    async def test_bearer_token_accepted(self, client, db_session):
        import httpx

        from app.main import app

        await seed_price(db_session)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"Authorization": "Bearer test-user-key"},
        ) as c:
            resp = await c.get("/v1/usage")
            assert resp.status_code == 200

    async def test_health_and_metrics_open(self, client):
        import httpx

        from app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as anon:
            assert (await anon.get("/health")).status_code == 200
            assert (await anon.get("/metrics")).status_code == 200


class TestAdminScope:
    async def test_user_key_forbidden_on_admin_route(self, client):
        # client uses user key -> budget create should 403.
        resp = await client.post(
            "/v1/budgets",
            json={
                "scope_type": "TEAM",
                "scope_id": "platform-team",
                "period_type": "MONTHLY",
                "limit_amount": "100.00",
            },
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    async def test_admin_key_allowed_on_admin_route(self, admin_client, db_session):
        resp = await admin_client.post(
            "/v1/budgets",
            json={
                "scope_type": "TEAM",
                "scope_id": "platform-team",
                "period_type": "MONTHLY",
                "limit_amount": "100.00",
            },
        )
        assert resp.status_code == 201

    async def test_user_key_can_read_pricing(self, client, db_session):
        await seed_price(db_session)
        resp = await client.get("/v1/models/pricing")
        assert resp.status_code == 200
