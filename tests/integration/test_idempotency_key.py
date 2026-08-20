"""Integration tests for the P2 Idempotency-Key (request ledger covers
reserve->settle, not only the usage row).

Real Postgres + FakeLLMProvider (overridden in THIS module only).
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select

from app.api.dependencies import llm_factory_dep
from app.core.config import get_settings
from app.db.models import RequestLedger, UsageRecord
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


async def _post(client, *, key=None, request_id=None):
    payload = {
        "provider": "openai",
        "model": "gpt-4o",
        "input": "Hello world",
        "max_output_tokens": 20,
        "team_id": "platform-team",
    }
    if request_id:
        payload["request_id"] = request_id
    headers = {"Idempotency-Key": key} if key else None
    return await client.post("/v1/generate", json=payload, headers=headers)


class TestIdempotencyKey:
    async def test_header_key_creates_ledger_and_usage(
        self, client, db_session, enable_generate, fake_llm
    ):
        await seed_price(db_session)
        await seed_budget(db_session)

        resp = await _post(client, key="idem_1")
        assert resp.status_code == 200
        assert resp.json()["request_id"] == "idem_1"

        ledger = await db_session.scalar(
            select(RequestLedger).where(RequestLedger.request_id == "idem_1")
        )
        assert ledger is not None
        assert ledger.status == "COMPLETED"

        rec = await db_session.scalar(select(UsageRecord).where(UsageRecord.request_id == "idem_1"))
        assert rec is not None

    async def test_retry_same_header_key_is_409_no_double_reserve(
        self, client, db_session, enable_generate, fake_llm
    ):
        await seed_price(db_session)
        bid = await seed_budget(db_session)

        first = await _post(client, key="idem_2")
        assert first.status_code == 200
        calls_after_first = len(fake_llm.calls)

        second = await _post(client, key="idem_2")
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "GENERATION_ALREADY_RECORDED"

        # No second provider call, no double reserve.
        assert len(fake_llm.calls) == calls_after_first

        from app.db.models import BudgetEvent

        events = (
            (await db_session.execute(select(BudgetEvent).where(BudgetEvent.budget_id == bid)))
            .scalars()
            .all()
        )
        # Exactly one RESERVE + one COMMIT (the settle); no extra reserve.
        assert sum(1 for e in events if e.event_type == "RESERVE") == 1
        assert sum(1 for e in events if e.event_type == "COMMIT") == 1

    async def test_header_takes_precedence_over_body(
        self, client, db_session, enable_generate, fake_llm
    ):
        await seed_price(db_session)
        await seed_budget(db_session)

        resp = await _post(client, key="idem_header", request_id="idem_body")
        assert resp.status_code == 200
        assert resp.json()["request_id"] == "idem_header"

        # Only the header key has a usage row; the body id was ignored.
        rec_header = await db_session.scalar(
            select(UsageRecord).where(UsageRecord.request_id == "idem_header")
        )
        rec_body = await db_session.scalar(
            select(UsageRecord).where(UsageRecord.request_id == "idem_body")
        )
        assert rec_header is not None
        assert rec_body is None

    async def test_in_flight_row_is_409_without_second_provider_call(
        self, client, db_session, enable_generate, fake_llm
    ):
        """Simulate a crashed request: an IN_FLIGHT ledger row exists with no
        usage row. A retry must 409 (not re-reserve/re-call)."""
        await seed_price(db_session)
        await seed_budget(db_session)

        # Pre-seed an IN_FLIGHT row (as if UoW1 committed then the process died).
        db_session.add(
            RequestLedger(
                request_id="idem_crash",
                status="IN_FLIGHT",
                provider="openai",
                model="gpt-4o",
            )
        )
        await db_session.commit()

        resp = await _post(client, key="idem_crash")
        assert resp.status_code == 409
        assert fake_llm.calls == []  # provider never called
