"""Integration tests for the reservation sweeper (scripts/expire_reservations.py).

Proves the rule: a reservation older than the TTL with no settled usage is a
release candidate; a fresh one is not; --apply releases only stale ones and
writes RELEASE events.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.models import Budget, BudgetConsumption, BudgetEvent
from app.domain.budget import BLOCK
from app.repositories.budget_repository import BudgetRepository
from app.services.budget_service import BudgetService, period_key_for
from scripts.expire_reservations import find_stale, release_stale


async def _make_budget_and_reserve(
    db, *, scope_id: str, amount: str, days_old: int | None
) -> tuple[Budget, BudgetConsumption]:
    """Create a budget for ``scope_id`` and reserve ``amount`` on it.

    ``days_old`` ages the consumption row so the sweeper treats it as stale.
    """
    repo = BudgetRepository(db)
    budget = await repo.create(
        scope_type="TEAM",
        scope_id=scope_id,
        period_type="MONTHLY",
        limit_amount=Decimal("100.00"),
        currency="USD",
        warning_threshold=Decimal("0.7"),
        critical_threshold=Decimal("0.9"),
        enforcement_mode="STRICT",
        starts_at=None,
        ends_at=None,
    )
    svc = BudgetService(repo)
    decision = await svc.reserve(budget, Decimal(amount), "sweep_req")
    assert decision.allowed or decision.status == BLOCK  # reserved or blocked
    await db.commit()

    row = await repo.get_consumption(budget.id, period_key_for(budget.period_type))
    assert row is not None
    if days_old is not None:
        # Age the row so the sweeper sees it as stale.
        row.updated_at = row.updated_at - timedelta(days=days_old)
        await db.commit()
    return budget, row


async def test_fresh_reservation_not_stale(db_session):
    _, row = await _make_budget_and_reserve(
        db_session, scope_id="sweep-fresh", amount="10", days_old=None
    )
    stale = await find_stale(db_session)
    assert row.id not in [bc.id for bc, _ in stale]


async def test_stale_reservation_is_candidate(db_session):
    _, row = await _make_budget_and_reserve(
        db_session, scope_id="sweep-stale", amount="10", days_old=1
    )
    stale = await find_stale(db_session)
    ids = [bc.id for bc, _ in stale]
    assert row.id in ids


async def test_apply_releases_only_stale_and_writes_event(db_session):
    # One stale + one fresh reservation on DIFFERENT budgets.
    budget, stale_row = await _make_budget_and_reserve(
        db_session, scope_id="sweep-apply-stale", amount="10", days_old=1
    )
    _, fresh_row = await _make_budget_and_reserve(
        db_session, scope_id="sweep-apply-fresh", amount="5", days_old=None
    )

    pairs = await find_stale(db_session)
    assert stale_row.id in [bc.id for bc, _ in pairs]
    assert fresh_row.id not in [bc.id for bc, _ in pairs]

    n = await release_stale(db_session, pairs)
    assert n == 1

    # Stale released to 0, fresh untouched.
    await db_session.refresh(stale_row)
    await db_session.refresh(fresh_row)
    assert stale_row.reserved_amount == Decimal("0")
    assert fresh_row.reserved_amount == Decimal("5")

    # A RELEASE event was written for the stale one.
    events = (
        (await db_session.execute(select(BudgetEvent).where(BudgetEvent.budget_id == budget.id)))
        .scalars()
        .all()
    )
    releases = [e for e in events if e.event_type == "RELEASE" and e.details.get("sweeper")]
    assert len(releases) == 1
    assert releases[0].amount == Decimal("10")
