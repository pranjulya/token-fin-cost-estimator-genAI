"""Concurrency tests (PRD Phase 18).

Prove the core atomicity claim under REAL parallelism: separate AsyncSessions,
asyncio.gather, Postgres FOR UPDATE row locks. The existing
``test_double_reserve_is_race_safe`` only ran sequential awaits in one session.
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models import BudgetConsumption, BudgetEvent, UsageRecord
from app.repositories.budget_repository import BudgetRepository
from app.services.budget_service import BudgetService, period_key_for
from tests.conftest import session_factory
from tests.integration.test_estimate_flow import seed_budget, seed_price


async def _reserve_once(scope_id: str, amount: Decimal, request_id: str):
    """Reserve in its own session (true concurrency: separate transactions)."""
    async with session_factory() as session:
        svc = BudgetService(BudgetRepository(session))
        budget = await svc.find_for("TEAM", scope_id)
        assert budget is not None
        decision = await svc.reserve(budget, amount, request_id)
        await session.commit()
        return decision.status


class TestConcurrentReserve:
    async def test_concurrent_reserves_cannot_overspend(self):
        """10 x reserve(20) vs a 100 limit: exactly 4 fit (80), 6 BLOCK.

        decide() BLOCKs at fraction >= 1.0, so the 5th request (which would
        reach exactly 100) is rejected — the max reservable is 80, never 100+.
        """
        async with session_factory() as session:
            bid = await seed_budget(session)
            await session.commit()

        results = await asyncio.gather(
            *[_reserve_once("platform-team", Decimal("20"), f"req_c_{i}") for i in range(10)]
        )
        allowed = [s for s in results if s != "BLOCK"]
        blocked = [s for s in results if s == "BLOCK"]
        assert len(allowed) == 4
        assert len(blocked) == 6

        # The shared counter never exceeded the limit (80 reserved, no overspend).
        async with session_factory() as session:
            row = await BudgetRepository(session).get_consumption(bid, period_key_for("MONTHLY"))
            assert row is not None
            assert row.reserved_amount == Decimal("80")
            assert row.committed_amount == Decimal("0")
            n_events = await session.scalar(select(func.count()).select_from(BudgetEvent))
            assert n_events == 10


class TestConcurrentGenerate:
    async def test_concurrent_generate_same_request_id_single_winner(self):
        """Two concurrent generates with the same request_id: one 200, one 409."""
        import httpx

        from app.api.dependencies import llm_factory_dep
        from app.main import app
        from app.providers.llm.base import LLMCompletion
        from tests.fakes.llm import FakeLLMProvider

        fake = FakeLLMProvider(
            completion=LLMCompletion(
                text="ok",
                prompt_tokens=10,
                completion_tokens=4,
                cached_prompt_tokens=0,
                model="gpt-4o",
                provider="openai",
            )
        )
        app.dependency_overrides[llm_factory_dep] = lambda: lambda name: fake
        os.environ["APP_GENERATE_ENABLED"] = "true"
        get_settings.cache_clear()

        async with session_factory() as session:
            await seed_price(session)
            await seed_budget(session)
            await session.commit()

        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
                headers={"X-API-Key": "test-user-key"},
            ) as client:
                body = {
                    "provider": "openai",
                    "model": "gpt-4o",
                    "input": "hi",
                    "max_output_tokens": 10,
                    "request_id": "req_same",
                    "team_id": "platform-team",
                }
                r1, r2 = await asyncio.gather(
                    client.post("/v1/generate", json=body),
                    client.post("/v1/generate", json=body),
                )
        finally:
            os.environ.pop("APP_GENERATE_ENABLED", None)
            get_settings.cache_clear()
            app.dependency_overrides.clear()

        statuses = sorted([r1.status_code, r2.status_code])
        assert statuses == [200, 409]
        loser = r2 if r2.status_code == 409 else r1
        assert loser.json()["error"]["code"] == "GENERATION_ALREADY_RECORDED"

        async with session_factory() as session:
            n = await session.scalar(select(func.count()).select_from(UsageRecord))
            assert n == 1


class TestConcurrentEstimate:
    async def test_concurrent_estimates_no_contention(self):
        """N concurrent estimates (evaluate-only) all succeed without mutation."""
        async with session_factory() as session:
            await seed_price(session)
            await seed_budget(session)
            await session.commit()

        import httpx

        from app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"X-API-Key": "test-user-key"},
        ) as client:
            body = {
                "provider": "openai",
                "model": "gpt-4o",
                "input": "Hello world",
                "expected_output_tokens": 100,
                "team_id": "platform-team",
            }
            responses = await asyncio.gather(
                *[client.post("/v1/cost/estimate", json=body) for _ in range(10)]
            )
        assert all(r.status_code == 200 for r in responses)

        async with session_factory() as session:
            n_events = await session.scalar(select(func.count()).select_from(BudgetEvent))
            assert n_events == 0
            n_cons = await session.scalar(select(func.count()).select_from(BudgetConsumption))
            assert n_cons == 0
