"""Integration tests for alert hooks on reserve + usage paths (Phase 13).

Uses the real session + repositories, not HTTP, to inspect DB rows directly.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.models import Alert
from app.domain.budget import BLOCK
from app.repositories.alert_repository import AlertRepository
from app.repositories.budget_repository import BudgetRepository
from app.repositories.usage_repository import UsageRepository
from app.services.alert_service import AlertService
from app.services.budget_service import BudgetService
from app.services.usage_service import UsageService
from tests.integration.test_budget import make_budget
from tests.integration.test_usage import seed_price


def _alert_service(session) -> AlertService:
    return AlertService(
        repository=AlertRepository(session),
        usage_repository=UsageRepository(session),
    )


async def _alerts(session, budget_id=None) -> list[Alert]:
    stmt = select(Alert).order_by(Alert.created_at.desc())
    if budget_id is not None:
        stmt = stmt.where(Alert.metadata_json["budget_id"].as_integer() == budget_id)
    return list((await session.scalars(stmt)).all())


class TestBudgetThresholdAlerts:
    async def test_allow_reserve_no_alert(self, db_session):
        await make_budget(db_session)
        svc = BudgetService(BudgetRepository(db_session), alerts=_alert_service(db_session))
        budget = await svc.find_for("TEAM", "platform-team")
        await svc.reserve(budget, Decimal("50"), "req_1")
        await db_session.commit()
        assert (await _alerts(db_session)) == []

    async def test_warn_band_deduped(self, db_session):
        await make_budget(db_session)
        svc = BudgetService(BudgetRepository(db_session), alerts=_alert_service(db_session))
        budget = await svc.find_for("TEAM", "platform-team")
        # 70/100 = 70% = at warning -> WARN alert.
        await svc.reserve(budget, Decimal("70"), "req_1")
        await db_session.commit()
        got = await _alerts(db_session)
        assert len(got) == 1
        assert got[0].alert_type == "BUDGET_THRESHOLD"
        assert got[0].severity == "WARNING"
        assert got[0].dedupe_key.endswith(":WARN")

        # Same band again -> still one alert (released + re-reserve to re-evaluate).
        await svc.release(budget, Decimal("70"), "req_1")
        await svc.reserve(budget, Decimal("70"), "req_2")
        await db_session.commit()
        assert len(await _alerts(db_session)) == 1

    async def test_escalation_to_critical_distinct_key(self, db_session):
        await make_budget(db_session)
        svc = BudgetService(BudgetRepository(db_session), alerts=_alert_service(db_session))
        budget = await svc.find_for("TEAM", "platform-team")
        await svc.reserve(budget, Decimal("70"), "req_1")  # WARN
        await db_session.commit()
        # Escalate: another 20 -> 90/100 = 90% -> CRITICAL.
        await svc.reserve(budget, Decimal("20"), "req_2")
        await db_session.commit()
        got = await _alerts(db_session)
        keys = {a.dedupe_key for a in got}
        assert any(k.endswith(":WARN") for k in keys)
        assert any(k.endswith(":CRITICAL") for k in keys)

    async def test_block_alert_severity_critical_key_block(self, db_session):
        await make_budget(db_session)
        svc = BudgetService(BudgetRepository(db_session), alerts=_alert_service(db_session))
        budget = await svc.find_for("TEAM", "platform-team")
        decision = await svc.reserve(budget, Decimal("105"), "req_1")  # over limit -> BLOCK
        assert decision.status == BLOCK
        await db_session.commit()
        got = await _alerts(db_session)
        assert len(got) == 1
        assert got[0].severity == "CRITICAL"
        assert got[0].dedupe_key.endswith(":BLOCK")

    async def test_constructor_without_alerts_compatible(self, db_session):
        await make_budget(db_session)
        svc = BudgetService(BudgetRepository(db_session))  # no alerts
        budget = await svc.find_for("TEAM", "platform-team")
        assert (await svc.reserve(budget, Decimal("105"), "req_1")).status == BLOCK
        await db_session.commit()
        assert (await _alerts(db_session)) == []


class TestCostAnomalyAlerts:
    async def _seed_history(self, db_session, n=12):
        await seed_price(db_session)
        # 12 small SUCCESS usage rows on the same provider/model.
        for i in range(n):
            await db_session.execute(
                __import__("app.db.models", fromlist=["UsageRecord"])
                .UsageRecord.__table__.insert()
                .values(
                    request_id=f"hist_{i}",
                    provider="openai",
                    model="gpt-4o",
                    actual_input_tokens=100,
                    actual_output_tokens=100,
                    actual_cost=Decimal("0.003"),
                    status="SUCCESS",
                )
            )
        await db_session.commit()

    async def test_anomaly_fires_once_and_dedupes_on_retry(self, db_session):
        await self._seed_history(db_session)
        # record() requires a pricing provider; use a stub to compute actual cost.
        from app.domain.pricing import ModelPrice

        class _P:
            async def get_pricing(self, provider, model):
                p = ModelPrice(
                    provider=provider,
                    model=model,
                    currency="USD",
                    input_per_million=Decimal("2.50"),
                    output_per_million=Decimal("10.00"),
                    cached_input_per_million=None,
                    version=1,
                    effective_from=date.today(),
                    effective_to=None,
                )
                return p

        svc2 = UsageService(
            pricing=_P(),
            repository=UsageRepository(db_session),
            alerts=_alert_service(db_session),
        )
        # A single big usage -> anomaly alert (15 >= $5 absolute floor).
        await svc2.record(
            request_id="req_big",
            provider="openai",
            model="gpt-4o",
            actual_input_tokens=500000,
            actual_output_tokens=1000000,
        )
        await db_session.commit()
        got = [a for a in await _alerts(db_session) if a.alert_type == "COST_ANOMALY"]
        assert len(got) == 1
        assert got[0].dedupe_key == "COST_ANOMALY:req_big"
        assert got[0].severity == "CRITICAL"

        # Retry same request_id -> idempotent, no second alert.
        await svc2.record(
            request_id="req_big",
            provider="openai",
            model="gpt-4o",
            actual_input_tokens=500000,
            actual_output_tokens=1000000,
        )
        await db_session.commit()
        got = [a for a in await _alerts(db_session) if a.alert_type == "COST_ANOMALY"]
        assert len(got) == 1
