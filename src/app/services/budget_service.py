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
from app.domain.budget import ALLOW, BudgetDecision
from app.repositories.budget_repository import BudgetRepository
from app.services.alert_service import AlertService


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
    def __init__(self, repository: BudgetRepository, alerts: AlertService | None = None):
        self._repository = repository
        self._alerts = alerts

    async def find_for(self, scope_type: str, scope_id: str) -> Budget | None:
        """Find the active budget for a scope, or None if none is configured."""
        return await self._repository.get_active(scope_type, scope_id)

    async def find_applicable(
        self, *, team_id: str | None, application_id: str | None
    ) -> Budget | None:
        """Encode the TEAM-then-APPLICATION lookup so estimate and generate agree.

        First match wins: a TEAM budget shadows an APPLICATION budget.
        """
        for scope_type, scope_id in (("TEAM", team_id), ("APPLICATION", application_id)):
            if scope_id:
                budget = await self.find_for(scope_type, scope_id)
                if budget is not None:
                    return budget
        return None

    async def evaluate(self, budget: Budget, amount: Decimal) -> BudgetDecision:
        """Pure snapshot decision for a preflight estimate (PRD Phase 15 / K2).

        Reads the current consumption without locking and runs the policy —
        no reserved mutation, no budget events, no alerts. A slightly stale
        snapshot is acceptable: evaluate is advisory; generate's ``reserve``
        is the race-safe enforcement point.
        """
        period_key = period_key_for(budget.period_type)
        row = await self._repository.get_consumption(budget.id, period_key)
        reserved = (row.reserved_amount if row is not None else Decimal("0")) or Decimal("0")
        committed = (row.committed_amount if row is not None else Decimal("0")) or Decimal("0")
        return budget_policy.decide(
            limit=budget.limit_amount,
            committed=committed,
            reserved=reserved,
            requested=amount,
            warning=budget.warning_threshold,
            critical=budget.critical_threshold,
            enforcement_mode=budget.enforcement_mode,
        )

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

        # Fire a budget threshold alert on non-ALLOW decisions (Phase 13).
        if self._alerts is not None and decision.status != ALLOW:
            await self._alerts.maybe_budget_threshold(
                budget=budget,
                decision=decision,
                period_key=period_key,
                requested_amount=amount,
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

    async def settle(
        self,
        budget: Budget,
        *,
        reserved_amount: Decimal,
        actual_amount: Decimal,
        request_id: str | None,
    ) -> None:
        """Settle a finished request: consume its E from reserved, add A to committed.

        Always consumes this request's reserved amount ``E`` — never the actual
        ``A`` when ``A > E`` (that would steal other in-flight reservations).
        Does not re-run ``decide()`` and fires no alerts (Phase 13 K3).
        """
        period_key = period_key_for(budget.period_type)
        row = await self._repository.lock_consumption(budget.id, period_key)
        if actual_amount < reserved_amount:
            await self._repository.commit_amount(row, actual_amount)
            await self._repository.add_event(
                budget_id=budget.id,
                event_type="COMMIT",
                period_key=period_key,
                amount=actual_amount,
                request_id=request_id,
            )
            leftover = reserved_amount - actual_amount
            await self._repository.release_amount(row, leftover)
            await self._repository.add_event(
                budget_id=budget.id,
                event_type="RELEASE",
                period_key=period_key,
                amount=leftover,
                request_id=request_id,
            )
        elif actual_amount == reserved_amount:
            await self._repository.commit_amount(row, reserved_amount)
            await self._repository.add_event(
                budget_id=budget.id,
                event_type="COMMIT",
                period_key=period_key,
                amount=reserved_amount,
                request_id=request_id,
            )
        else:  # A > E: actual exceeded estimate
            await self._repository.apply_overage(
                row, reserved_consume=reserved_amount, committed_add=actual_amount
            )
            await self._repository.add_event(
                budget_id=budget.id,
                event_type="COMMIT",
                period_key=period_key,
                amount=actual_amount,
                request_id=request_id,
            )
