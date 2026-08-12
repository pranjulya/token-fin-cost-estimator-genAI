"""Integration tests for POST /v1/cost/estimate end-to-end."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.repositories.budget_repository import BudgetRepository
from app.repositories.pricing_repository import PricingRepository


async def seed_budget(db, **overrides):
    data = {
        "scope_type": "TEAM",
        "scope_id": "platform-team",
        "period_type": "MONTHLY",
        "limit_amount": Decimal("100.00"),
        "currency": "USD",
        "warning_threshold": Decimal("0.7"),
        "critical_threshold": Decimal("0.9"),
        "enforcement_mode": "STRICT",
    }
    data.update(overrides)
    row = await BudgetRepository(db).create(
        scope_type=data["scope_type"],
        scope_id=data["scope_id"],
        period_type=data["period_type"],
        limit_amount=data["limit_amount"],
        currency=data["currency"],
        warning_threshold=data["warning_threshold"],
        critical_threshold=data["critical_threshold"],
        enforcement_mode=data["enforcement_mode"],
        starts_at=None,
        ends_at=None,
    )
    await db.commit()
    return row.id


async def seed_price(db, model="gpt-4o"):
    await PricingRepository(db).create(
        provider="openai",
        model=model,
        input_per_million=Decimal("2.50"),
        output_per_million=Decimal("10.00"),
        cached_input_per_million=Decimal("1.25"),
        effective_from=date.today(),
    )
    await db.commit()


class TestEstimateFlow:
    async def test_estimate_known_model(self, client, db_session):
        await seed_price(db_session)
        resp = await client.post(
            "/v1/cost/estimate",
            json={
                "provider": "openai",
                "model": "gpt-4o",
                "input": "Hello world",
                "expected_output_tokens": 100,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "openai"
        assert data["estimated_input_tokens"] >= 1
        assert data["estimated_output_tokens"] == 100
        # 100 output @ $10/M = 0.001 ; total > 0
        assert Decimal(data["estimated_output_cost"]) == Decimal("0.001")
        assert Decimal(data["estimated_total_cost"]) == Decimal(
            data["estimated_input_cost"]
        ) + Decimal("0.001")
        assert data["currency"] == "USD"
        assert data["pricing_version"] == 1
        assert data["budget"]["status"] == "ENABLED"

    async def test_estimate_missing_pricing(self, client):
        resp = await client.post(
            "/v1/cost/estimate",
            json={
                "provider": "openai",
                "model": "unknown-model",
                "input": "hi",
                "expected_output_tokens": 10,
            },
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == "MODEL_PRICING_NOT_FOUND"

    async def test_estimate_validation_error(self, client, db_session):
        await seed_price(db_session)
        resp = await client.post(
            "/v1/cost/estimate",
            json={"provider": "openai", "model": "gpt-4o", "input": "hi"},
        )  # missing expected_output_tokens
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_estimate_negative_output_rejected(self, client, db_session):
        await seed_price(db_session)
        resp = await client.post(
            "/v1/cost/estimate",
            json={
                "provider": "openai",
                "model": "gpt-4o",
                "input": "hi",
                "expected_output_tokens": -5,
            },
        )
        assert resp.status_code == 422

    async def test_estimate_with_budget_envelope(self, client, db_session):
        await seed_price(db_session)
        await seed_budget(db_session)
        resp = await client.post(
            "/v1/cost/estimate",
            json={
                "provider": "openai",
                "model": "gpt-4o",
                "input": "Hello world",
                "expected_output_tokens": 100,
                "team_id": "platform-team",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        env = data["budget"]
        assert env["status"] == "ALLOW"
        assert Decimal(env["remaining_before_request"]) == Decimal("100.00")
        # remaining_after = 100 - total_cost
        assert Decimal(env["remaining_after_estimate"]) == Decimal("100.00") - Decimal(
            data["estimated_total_cost"]
        )
