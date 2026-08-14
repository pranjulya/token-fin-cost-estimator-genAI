"""Integration tests for budgets, Postgres-atomic consumption, and events."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.db.models import BudgetEvent
from app.domain.budget import BLOCK
from app.repositories.budget_repository import BudgetRepository
from app.services.budget_service import BudgetService, period_key_for

SCOPE = {"scope_type": "TEAM", "scope_id": "platform-team"}


async def make_budget(db, **overrides) -> int:
    data = {
        "scope_type": "TEAM",
        "scope_id": "platform-team",
        "period_type": "MONTHLY",
        "limit_amount": "100.00",
        "currency": "USD",
        "warning_threshold": "0.7",
        "critical_threshold": "0.9",
        "enforcement_mode": "STRICT",
    }
    data.update(overrides)
    row = await BudgetRepository(db).create(
        scope_type=data["scope_type"],
        scope_id=data["scope_id"],
        period_type=data["period_type"],
        limit_amount=Decimal(data["limit_amount"]),
        currency=data["currency"],
        warning_threshold=Decimal(data["warning_threshold"]),
        critical_threshold=Decimal(data["critical_threshold"]),
        enforcement_mode=data["enforcement_mode"],
        starts_at=None,
        ends_at=None,
    )
    await db.commit()
    return row.id


class TestBudgetAPI:
    async def test_create_and_read(self, admin_client, db_session):
        resp = await admin_client.post(
            "/v1/budgets",
            json=SCOPE
            | {
                "period_type": "MONTHLY",
                "limit_amount": "100.00",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["scope_id"] == "platform-team"
        assert Decimal(data["limit_amount"]) == Decimal("100.00")
        assert data["enforcement_mode"] == "STRICT"

        got = await admin_client.get(f"/v1/budgets/{data['id']}")
        assert got.status_code == 200
        assert got.json()["period_type"] == "MONTHLY"

    async def test_invalid_scope_type_rejected(self, admin_client, db_session):
        resp = await admin_client.post(
            "/v1/budgets",
            json=SCOPE
            | {
                "period_type": "MONTHLY",
                "limit_amount": "100.00",
                "scope_type": "USER",
            },
        )
        assert resp.status_code == 422

    async def test_warning_exceeds_critical_rejected(self, admin_client, db_session):
        resp = await admin_client.post(
            "/v1/budgets",
            json=SCOPE
            | {
                "period_type": "MONTHLY",
                "limit_amount": "100.00",
                "warning_threshold": "0.9",
                "critical_threshold": "0.7",
            },
        )
        assert resp.status_code == 422

    async def test_unknown_id_404(self, admin_client, db_session):
        assert (await admin_client.get("/v1/budgets/99999")).status_code == 404


class TestBudgetService:
    async def test_reserve_creates_consumption_and_decision(self, db_session):
        await make_budget(db_session)
        svc = BudgetService(BudgetRepository(db_session))
        budget = await svc.find_for("TEAM", "platform-team")
        assert budget is not None
        decision = await svc.reserve(budget, Decimal("50"), "req_1")
        assert decision.status == "ALLOW"
        assert decision.remaining_before == Decimal("100")
        assert decision.remaining_after == Decimal("50")

    async def test_double_reserve_is_race_safe(self, db_session):
        await make_budget(db_session)
        svc = BudgetService(BudgetRepository(db_session))
        budget = await svc.find_for("TEAM", "platform-team")
        d1 = await svc.reserve(budget, Decimal("60"), "req_1")
        d2 = await svc.reserve(budget, Decimal("60"), "req_2")
        # First OK, second sees updated counter -> BLOCK (60+60 > 100).
        assert d1.status == "ALLOW"
        assert d2.status == BLOCK

    async def test_commit_then_release_roundtrip(self, db_session):
        await make_budget(db_session)
        svc = BudgetService(BudgetRepository(db_session))
        budget = await svc.find_for("TEAM", "platform-team")
        await svc.reserve(budget, Decimal("80"), "req_1")
        await svc.commit(budget, Decimal("80"), "req_1")
        await db_session.commit()

        # After commit the 80 is permanently consumed; reserving 30 more is BLOCK.
        d = await svc.reserve(budget, Decimal("30"), "req_2")
        assert d.status == BLOCK

    async def test_release_frees_reservation(self, db_session):
        await make_budget(db_session)
        svc = BudgetService(BudgetRepository(db_session))
        budget = await svc.find_for("TEAM", "platform-team")
        d1 = await svc.reserve(budget, Decimal("60"), "req_1")
        assert d1.allowed
        await svc.release(budget, Decimal("60"), "req_1")
        await db_session.commit()

        d2 = await svc.reserve(budget, Decimal("60"), "req_2")
        # After release, full capacity is back: 60 alone OK.
        assert d2.status != BLOCK

    async def test_events_written(self, db_session):
        bid = await make_budget(db_session)
        svc = BudgetService(BudgetRepository(db_session))
        budget = await svc.find_for("TEAM", "platform-team")
        await svc.reserve(budget, Decimal("10"), "req_1")
        await db_session.commit()

        rows = await db_session.execute(select(BudgetEvent).where(BudgetEvent.budget_id == bid))
        events = rows.scalars().all()
        assert len(events) == 1
        assert events[0].event_type == "RESERVE"


class TestBudgetEvaluate:
    async def test_evaluate_does_not_mutate_or_event(self, db_session):
        bid = await make_budget(db_session)
        svc = BudgetService(BudgetRepository(db_session))
        budget = await svc.find_for("TEAM", "platform-team")
        await svc.reserve(budget, Decimal("10"), "req_seed")
        await db_session.commit()

        d = await svc.evaluate(budget, Decimal("20"))
        assert d.status == "ALLOW"
        await db_session.commit()

        row = await BudgetRepository(db_session).get_consumption(
            bid, period_key_for(budget.period_type)
        )
        assert row is not None
        assert row.reserved_amount == Decimal("10")
        events = (
            (await db_session.execute(select(BudgetEvent).where(BudgetEvent.budget_id == bid)))
            .scalars()
            .all()
        )
        assert all(e.event_type in {"RESERVE", "DECISION"} for e in events)
        assert sum(1 for e in events if e.event_type == "RESERVE") == 1

    async def test_find_applicable_prefers_team(self, db_session):
        await make_budget(db_session, scope_type="APPLICATION", scope_id="app-1")
        await make_budget(db_session, scope_type="TEAM", scope_id="team-1")
        svc = BudgetService(BudgetRepository(db_session))
        b = await svc.find_applicable(team_id="team-1", application_id="app-1")
        assert b is not None
        assert b.scope_type == "TEAM"
        assert b.scope_id == "team-1"


class TestBudgetSettle:
    async def test_settle_less_than_reserve(self, db_session):
        await make_budget(db_session)
        repo = BudgetRepository(db_session)
        svc = BudgetService(repo)
        budget = await svc.find_for("TEAM", "platform-team")
        await svc.reserve(budget, Decimal("10"), "req_1")
        await svc.settle(
            budget, reserved_amount=Decimal("10"), actual_amount=Decimal("4"), request_id="req_1"
        )
        await db_session.commit()
        row = await repo.get_consumption(budget.id, period_key_for(budget.period_type))
        assert row.reserved_amount == Decimal("0")
        assert row.committed_amount == Decimal("4")
        types = [
            e.event_type
            for e in (
                await db_session.execute(
                    select(BudgetEvent).where(BudgetEvent.budget_id == budget.id)
                )
            )
            .scalars()
            .all()
        ]
        assert types.count("COMMIT") == 1
        assert types.count("RELEASE") == 1

    async def test_settle_overage_does_not_steal_other_reserve(self, db_session):
        await make_budget(db_session, limit_amount="100.00")
        repo = BudgetRepository(db_session)
        svc = BudgetService(repo)
        budget = await svc.find_for("TEAM", "platform-team")
        await svc.reserve(budget, Decimal("4"), "g1")
        await svc.reserve(budget, Decimal("4"), "g2")
        await svc.settle(
            budget, reserved_amount=Decimal("4"), actual_amount=Decimal("6"), request_id="g1"
        )
        await db_session.commit()
        row = await repo.get_consumption(budget.id, period_key_for(budget.period_type))
        # G2's E2=4 still reserved; G1 committed 6. used = 10.
        assert row.reserved_amount == Decimal("4")
        assert row.committed_amount == Decimal("6")
        events = (
            (await db_session.execute(select(BudgetEvent).where(BudgetEvent.request_id == "g1")))
            .scalars()
            .all()
        )
        assert [e.event_type for e in events if e.event_type != "RESERVE"] == ["COMMIT"]
        assert events[-1].amount == Decimal("6")
