"""Data access for budgets, budget_consumption, and budget_events."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Budget, BudgetConsumption, BudgetEvent


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BudgetRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    # --- budgets CRUD -------------------------------------------------------

    async def create(
        self,
        *,
        scope_type: str,
        scope_id: str,
        period_type: str,
        limit_amount: Decimal,
        currency: str,
        warning_threshold: Decimal,
        critical_threshold: Decimal,
        enforcement_mode: str,
        starts_at: datetime | None,
        ends_at: datetime | None,
    ) -> Budget:
        row = Budget(
            scope_type=scope_type,
            scope_id=scope_id,
            period_type=period_type,
            limit_amount=limit_amount,
            currency=currency,
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
            enforcement_mode=enforcement_mode,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, budget_id: int) -> Budget | None:
        return await self._session.get(Budget, budget_id)

    async def get_active(self, scope_type: str, scope_id: str) -> Budget | None:
        """Return the active budget for a scope, or None.

        A budget is active when its [starts_at, ends_at) window contains now
        (null bounds are open-ended). If several match, prefer the most recent.
        """
        now = _utcnow()
        stmt = (
            select(Budget)
            .where(Budget.scope_type == scope_type, Budget.scope_id == scope_id)
            .order_by(Budget.created_at.desc())
        )
        row = await self._session.scalar(stmt)
        if row is None:
            return None
        if row.starts_at is not None and row.starts_at > now:
            return None
        if row.ends_at is not None and row.ends_at <= now:
            return None
        return row

    async def update(self, budget: Budget, **fields: Any) -> Budget:
        for key, value in fields.items():
            if value is not None or key == "ends_at":
                setattr(budget, key, value)
        await self._session.flush()
        return budget

    # --- consumption (Postgres-atomic) --------------------------------------

    async def lock_consumption(self, budget_id: int, period_key: str) -> BudgetConsumption:
        """Return the consumption row for (budget, period), row-locked FOR UPDATE.

        Insert-if-absent using a savepoint so a concurrent first insert (which
        hits the unique constraint) is rolled back cleanly, then the winner's
        row is re-selected — the caller blocks on the lock until the other
        transaction commits. This is the race-safe primitive (PRD # 26).
        """
        stmt = select(BudgetConsumption).where(
            BudgetConsumption.budget_id == budget_id,
            BudgetConsumption.period_key == period_key,
        )
        row = await self._session.scalar(stmt.with_for_update())
        if row is not None:
            return row

        try:
            async with self._session.begin_nested():
                self._session.add(
                    BudgetConsumption(
                        budget_id=budget_id,
                        period_key=period_key,
                        reserved_amount=0,
                        committed_amount=0,
                    )
                )
                await self._session.flush()
                row = await self._session.scalar(
                    stmt.with_for_update()
                )  # re-select (locked) inside savepoint
                return row  # type: ignore[return-value]
        except IntegrityError:
            # Lost the concurrent first-insert race; reload the winner's row.
            return await self._session.scalar(stmt.with_for_update())  # type: ignore[return-value]

    async def set_reserved(self, row: BudgetConsumption, amount: Decimal) -> None:
        row.reserved_amount = amount
        await self._session.flush()

    async def commit_amount(self, row: BudgetConsumption, amount: Decimal) -> None:
        """Move reserved -> committed (actual spend)."""
        row.reserved_amount = max(row.reserved_amount - amount, Decimal("0"))
        row.committed_amount += amount
        await self._session.flush()

    async def release_amount(self, row: BudgetConsumption, amount: Decimal) -> None:
        """Drop a reservation (estimate over actual / request never ran)."""
        row.reserved_amount = max(row.reserved_amount - amount, Decimal("0"))
        await self._session.flush()

    # --- events --------------------------------------------------------------

    async def add_event(
        self,
        *,
        budget_id: int,
        event_type: str,
        period_key: str | None = None,
        amount: Decimal | None = None,
        decision: str | None = None,
        request_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> BudgetEvent:
        event = BudgetEvent(
            budget_id=budget_id,
            event_type=event_type,
            period_key=period_key,
            amount=amount,
            decision=decision,
            request_id=request_id,
            details=details,
        )
        self._session.add(event)
        await self._session.flush()
        return event
