"""Failure-mode tests (PRD Phase 18).

Prove the soft-fail contracts: an alert-side failure never poisons the money
transaction, and the generate unique-race maps to a usable 409.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.exceptions import GenerationAlreadyRecordedError
from app.db.models import BudgetEvent, UsageRecord
from app.providers.pricing.database_pricing import DatabasePricingProvider
from app.repositories.alert_repository import AlertRepository
from app.repositories.budget_repository import BudgetRepository
from app.repositories.pricing_repository import PricingRepository
from app.repositories.usage_repository import UsageRepository
from app.services.alert_service import AlertService
from app.services.budget_service import BudgetService
from app.services.usage_service import UsageService
from tests.integration.test_estimate_flow import seed_budget, seed_price


async def _usage_service(db, alerts):
    return UsageService(
        pricing=DatabasePricingProvider(PricingRepository(db)),
        repository=UsageRepository(db),
        alerts=alerts,
    )


class TestAlertSoftFail:
    async def test_alert_soft_fail_still_commits_usage(self, db_session, monkeypatch):
        await seed_price(db_session)

        # Alert repo blows up on insert — must NOT break the usage commit.
        async def boom(*a, **k):
            raise RuntimeError("alert db down")

        monkeypatch.setattr(AlertRepository, "create_if_absent", boom)
        svc = await _usage_service(db_session, AlertService(AlertRepository(db_session)))
        rec = await svc.record(
            request_id="req_soft",
            provider="openai",
            model="gpt-4o",
            actual_input_tokens=10,
            actual_output_tokens=10,
        )
        await db_session.commit()
        assert rec.status == "SUCCESS"
        n = await db_session.scalar(select(func.count()).select_from(UsageRecord))
        assert n == 1

    async def test_alert_soft_fail_still_commits_reserve(self, db_session, monkeypatch):
        await seed_budget(db_session)

        async def boom(*a, **k):
            raise RuntimeError("alert db down")

        monkeypatch.setattr(AlertRepository, "create_if_absent", boom)
        svc = BudgetService(BudgetRepository(db_session))
        budget = await svc.find_for("TEAM", "platform-team")
        decision = await svc.reserve(budget, Decimal("10"), "req_soft_reserve")
        await db_session.commit()
        assert decision.status != "BLOCK"
        n_events = await db_session.scalar(select(func.count()).select_from(BudgetEvent))
        assert n_events == 1


class TestRecordNewRace:
    async def test_record_new_unique_race_maps_to_409_and_session_usable(self, db_session):
        await seed_price(db_session)
        svc = await _usage_service(db_session, None)
        # Pre-insert via record().
        await svc.record(
            request_id="req_dup",
            provider="openai",
            model="gpt-4o",
            actual_input_tokens=5,
            actual_output_tokens=5,
        )
        await db_session.commit()

        with pytest.raises(GenerationAlreadyRecordedError):
            await svc.record_new(
                request_id="req_dup",
                provider="openai",
                model="gpt-4o",
                actual_input_tokens=5,
                actual_output_tokens=5,
            )
        # The outer session is still usable: a subsequent insert + commit works.
        rec = await svc.record(
            request_id="req_after_dup",
            provider="openai",
            model="gpt-4o",
            actual_input_tokens=5,
            actual_output_tokens=5,
        )
        await db_session.commit()
        assert rec is not None
        n = await db_session.scalar(select(func.count()).select_from(UsageRecord))
        assert n == 2
