"""BudgetService — orchestrate budget lookup and Postgres-atomic reservations.

PRD Phases 8–12. Postgres-first: reservations are race-free via a row lock on
the budget_consumption counter, avoiding the naive read-check-reserve race
(PRD # 25/26). Redis can slot in later as a fast-path counter without changing
this contract. ``reserve`` returns a :class:`BudgetDecision` from the pure
domain policy; it does NOT hard-fail — callers enforce per enforcement_mode.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.db.models import Budget
from app.domain import budget as budget_policy
from app.domain.budget import BudgetDecision
from app.repositories.budget_repository import BudgetRepository


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def period_key_for(period_type: str, when: datetime | None = None) -> str:
    """Bucket a timestamp into a period key (PRD FR-07).

    MONTHLY -> '2026-08', DAILY -> '2026-08-12'.
    """
    when = when or _utcnow()
    if period_type == "DAILY":
        return when.strftime("%Y-%m-%d")
    return when.strftime("%Y-%m")


class BudgetService:
    def __init__(self, repository: BudgetRepository):
        self._repository = repository

    async def find_for(self, scope_type: str, scope_id: str) -> Budget | None:
        """Find the active budget for a scope, or None if none is configured."""
        return await self._repository.get_active(scope_type, scope_id)

    async def reserve(
        self, budget: Budget, amount: Decimal, request_id: str | None
    ) -> BudgetDecision:
        """Atomically reserve ``amount`` against the budget's current period.

        Row-locks the consumption counter, evaluates the pure domain policy
        against the projected usage, and — only if allowed — increments the
        reserved amount. Returns the decision; the caller decides how strictly
        to act on a BLOCK.
        """
        period_key = period_key_for(budget.period_type)
        row = await self._repository.lock_consumption(budget.id, period_key)
        row.reserved_amount = row.reserved_amount or Decimal("0")
        row.committed_amount = row.committed_amount or Decimal("0")

        decision = budget_policy.decide(
            limit=budget.limit_amount,
            committed=row.committed_amount,
            reserved=row.reserved_amount,
            requested=amount,
            warning=budget.warning_threshold,
            critical=budget.critical_threshold,
            enforcement_mode=budget.enforcement_mode,
        )

        if decision.allowed:
            await self._repository.set_reserved(row, row.reserved_amount + amount)

        await self._repository.add_event(
            budget_id=budget.id,
            event_type="RESERVE" if decision.allowed else "DECISION",
            period_key=period_key,
            amount=amount,
            decision=decision.status,
            request_id=request_id,
        )
        return decision

    async def commit(self, budget: Budget, amount: Decimal, request_id: str | None = None) -> None:
        """Move reserved -> committed once actual spend is known (PRD # 26)."""
        period_key = period_key_for(budget.period_type)
        row = await self._repository.lock_consumption(budget.id, period_key)
        await self._repository.commit_amount(row, amount)
        await self._repository.add_event(
            budget_id=budget.id,
            event_type="COMMIT",
            period_key=period_key,
            amount=amount,
            request_id=request_id,
        )

    async def release(self, budget: Budget, amount: Decimal, request_id: str | None = None) -> None:
        """Drop a reservation when the request never ran / actual < estimate."""
        period_key = period_key_for(budget.period_type)
        row = await self._repository.lock_consumption(budget.id, period_key)
        await self._repository.release_amount(row, amount)
        await self._repository.add_event(
            budget_id=budget.id,
            event_type="RELEASE",
            period_key=period_key,
            amount=amount,
            request_id=request_id,
        )
