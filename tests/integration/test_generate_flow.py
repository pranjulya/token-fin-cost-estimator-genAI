"""Integration tests for POST /v1/generate (real Postgres + FakeLLMProvider).

The LLM factory is overridden in THIS module only (never conftest) so no test
ever dials a real provider.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.api.dependencies import llm_factory_dep
from app.core.config import get_settings
from app.db.models import Alert, BudgetConsumption, BudgetEvent, UsageRecord
from app.main import app
from app.providers.llm.base import LLMCompletion
from tests.fakes.llm import FakeLLMProvider
from tests.integration.test_estimate_flow import seed_budget, seed_price

FAKE_COMPLETION = LLMCompletion(
    text="generated",
    prompt_tokens=10,
    completion_tokens=4,
    cached_prompt_tokens=0,
    model="gpt-4o",
    provider="openai",
)


@pytest.fixture
def fake_llm():
    return FakeLLMProvider(completion=FAKE_COMPLETION)


@pytest.fixture
def enable_generate(fake_llm):
    app.dependency_overrides[llm_factory_dep] = lambda: lambda name: fake_llm
    os.environ["APP_GENERATE_ENABLED"] = "true"
    get_settings.cache_clear()
    yield fake_llm
    os.environ.pop("APP_GENERATE_ENABLED", None)
    get_settings.cache_clear()
    app.dependency_overrides.clear()


async def _post(client, **over):
    payload = {
        "provider": "openai",
        "model": "gpt-4o",
        "input": "Hello world",
        "max_output_tokens": 20,
        "team_id": "platform-team",
    }
    payload.update(over)
    return await client.post("/v1/generate", json=payload)


class TestGenerateFlow:
    async def test_happy_path_budget(self, client, db_session, enable_generate, fake_llm):
        await seed_price(db_session)
        bid = await seed_budget(db_session)

        resp = await _post(client, request_id="req_gen_1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["request_id"] == "req_gen_1"
        assert data["output"] == "generated"
        assert data["budget"]["status"] == "ALLOW"
        assert fake_llm.calls  # provider called once

        # Usage row written.
        rec = await db_session.scalar(
            select(UsageRecord).where(UsageRecord.request_id == "req_gen_1")
        )
        assert rec is not None
        assert rec.status == "SUCCESS"
        assert rec.actual_input_tokens == 10
        assert rec.actual_output_tokens == 4

        # Budget events: RESERVE + settle (COMMIT A and/or RELEASE leftover).
        events = (
            (await db_session.execute(select(BudgetEvent).where(BudgetEvent.budget_id == bid)))
            .scalars()
            .all()
        )
        types = [e.event_type for e in events]
        assert "RESERVE" in types
        assert "COMMIT" in types

        row = await db_session.scalar(
            select(BudgetConsumption).where(BudgetConsumption.budget_id == bid)
        )
        assert row.reserved_amount == Decimal("0")
        assert row.committed_amount == rec.actual_cost

    async def test_strict_block_403_no_provider(
        self, client, db_session, enable_generate, fake_llm
    ):
        await seed_price(db_session)
        await seed_budget(db_session, limit_amount=Decimal("0.000001"))

        resp = await _post(client, request_id="req_block")
        assert resp.status_code == 403
        body = resp.json()
        assert body["error"]["code"] == "BUDGET_EXCEEDED"
        assert "status=BLOCK" in body["error"]["message"]
        assert body["error"]["request_id"] == "req_block"
        assert fake_llm.calls == []  # provider never called
        # No usage row.
        n = await db_session.scalar(select(func.count()).select_from(UsageRecord))
        assert n == 0
        # DECISION event written (reserved unchanged / absent).
        events = (await db_session.execute(select(BudgetEvent))).scalars().all()
        assert any(e.event_type == "DECISION" for e in events)

    async def test_advisory_over_limit_calls(self, client, db_session, enable_generate, fake_llm):
        await seed_price(db_session)
        await seed_budget(db_session, limit_amount=Decimal("0.000001"), enforcement_mode="ADVISORY")
        resp = await _post(client, request_id="req_advisory")
        assert resp.status_code == 200
        assert fake_llm.calls
        assert resp.json()["budget"]["status"] in {"WARN", "CRITICAL"}

    async def test_provider_error_releases(self, client, db_session, enable_generate, fake_llm):
        from app.core.exceptions import ProviderError

        await seed_price(db_session)
        bid = await seed_budget(db_session)
        fake_llm.error = ProviderError("boom")

        resp = await _post(client, request_id="req_fail")
        assert resp.status_code == 502
        assert resp.json()["error"]["code"] == "PROVIDER_ERROR"
        # No SUCCESS usage row.
        n = await db_session.scalar(select(func.count()).select_from(UsageRecord))
        assert n == 0
        # RESERVE then RELEASE events.
        events = (
            (await db_session.execute(select(BudgetEvent).where(BudgetEvent.budget_id == bid)))
            .scalars()
            .all()
        )
        types = [e.event_type for e in events]
        assert "RESERVE" in types
        assert "RELEASE" in types
        row = await db_session.scalar(
            select(BudgetConsumption).where(BudgetConsumption.budget_id == bid)
        )
        assert row.reserved_amount == Decimal("0")

    async def test_repeat_request_id_409(self, client, db_session, enable_generate, fake_llm):
        await seed_price(db_session)
        await seed_budget(db_session)

        first = await _post(client, request_id="req_dup")
        assert first.status_code == 200
        second = await _post(client, request_id="req_dup")
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "GENERATION_ALREADY_RECORDED"
        assert fake_llm.calls  # only the first call made the provider
        n = await db_session.scalar(select(func.count()).select_from(UsageRecord))
        assert n == 1

    async def test_no_budget(self, client, db_session, enable_generate, fake_llm):
        await seed_price(db_session)
        resp = await _post(client, request_id="req_nobudget", team_id=None)
        assert resp.status_code == 200
        assert resp.json()["budget"]["status"] == "ENABLED"
        n_events = await db_session.scalar(select(func.count()).select_from(BudgetEvent))
        assert n_events == 0
        rec = await db_session.scalar(
            select(UsageRecord).where(UsageRecord.request_id == "req_nobudget")
        )
        assert rec is not None

    async def test_disabled_returns_503(self, client, db_session, fake_llm):
        await seed_price(db_session)
        # No enable_generate fixture -> generate_enabled defaults False.
        get_settings.cache_clear()
        try:
            resp = await _post(client, request_id="req_off")
        finally:
            get_settings.cache_clear()
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "GENERATION_DISABLED"
        assert fake_llm.calls == []

    async def test_estimate_block_does_not_alert(
        self, client, db_session, enable_generate, fake_llm
    ):
        # Sanity: generate's reserve fires a threshold alert on BLOCK,
        # but estimate (evaluate-only) must not. Verify no alert from estimate.
        from tests.integration.test_estimate_flow import seed_budget as sb

        await seed_price(db_session)
        await sb(db_session, limit_amount=Decimal("0.000001"))
        resp = await client.post(
            "/v1/cost/estimate",
            json={
                "provider": "openai",
                "model": "gpt-4o",
                "input": "Hello world",
                "expected_output_tokens": 100000,
                "team_id": "platform-team",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["budget"]["status"] == "BLOCK"
        n_alerts = await db_session.scalar(select(func.count()).select_from(Alert))
        assert n_alerts == 0
