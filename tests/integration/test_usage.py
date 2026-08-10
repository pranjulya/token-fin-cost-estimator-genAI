"""Integration tests for the usage ledger + idempotency + aggregation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.repositories.pricing_repository import PricingRepository

PAYLOAD = {
    "request_id": "req_abc123",
    "correlation_id": "corr-1",
    "provider": "openai",
    "model": "gpt-4o",
    "application_id": "arch-assistant",
    "team_id": "platform-team",
    "endpoint": "/generate",
    "environment": "prod",
    "estimated_input_tokens": 1000,
    "estimated_output_tokens": 500,
    "estimated_cost": "0.0075",
    "actual_input_tokens": 900,
    "cached_input_tokens": 100,
    "actual_output_tokens": 400,
}


async def seed_price(db):
    await PricingRepository(db).create(
        provider="openai",
        model="gpt-4o",
        input_per_million=Decimal("2.50"),
        output_per_million=Decimal("10.00"),
        cached_input_per_million=Decimal("1.25"),
        effective_from=date.today(),
    )
    await db.commit()


class TestUsageLedger:
    async def test_create_usage(self, client, db_session):
        await seed_price(db_session)
        resp = await client.post("/v1/usage", json=PAYLOAD)
        assert resp.status_code == 201
        data = resp.json()
        assert data["request_id"] == "req_abc123"
        assert data["actual_input_tokens"] == 900
        # 900 @ $2.5/M + 100 @ $1.25/M + 400 @ $10/M
        assert Decimal(data["actual_cost"]) == Decimal("0.006375")
        assert data["pricing_version"] == 1
        # Reconciliation: est 0.0075, actual 0.006375 → variance < 0
        assert Decimal(data["variance_amount"]) < Decimal("0")

    async def test_idempotent_same_request_id(self, client, db_session):
        await seed_price(db_session)
        first = await client.post("/v1/usage", json=PAYLOAD)
        second = await client.post("/v1/usage", json=PAYLOAD)
        assert first.status_code == 201 and second.status_code == 201
        assert first.json()["id"] == second.json()["id"]
        # Only one usage record exists.
        listing = await client.get("/v1/usage")
        assert len(listing.json()) == 1

    async def test_usage_unknown_model_404(self, client):
        payload = {**PAYLOAD, "request_id": "req_zzz", "model": "nope"}
        resp = await client.post("/v1/usage", json=payload)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "MODEL_PRICING_NOT_FOUND"

    async def test_summary_and_aggregation(self, client, db_session):
        await seed_price(db_session)
        await client.post(
            "/v1/usage",
            json={**PAYLOAD, "request_id": "req_1", "team_id": "team-a", "endpoint": "/gen-a"},
        )
        await client.post(
            "/v1/usage",
            json={**PAYLOAD, "request_id": "req_2", "team_id": "team-b", "endpoint": "/gen-b"},
        )

        summary = (await client.get("/v1/usage/summary")).json()
        assert summary["total_requests"] == 2
        assert Decimal(summary["total_cost"]) == Decimal("0.01275")

        by_team = (await client.get("/v1/cost/by-team")).json()
        assert {row["key"] for row in by_team} == {"team-a", "team-b"}
        assert sum(Decimal(row["cost"]) for row in by_team) == Decimal("0.01275")

        by_endpoint = (await client.get("/v1/cost/by-endpoint")).json()
        assert len(by_endpoint) == 2

        by_model = (await client.get("/v1/cost/by-model")).json()
        assert len(by_model) == 1
        assert by_model[0]["key"] == "gpt-4o"
