"""Data access for usage_records."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UsageRecord


class UsageRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_request_id(self, request_id: str) -> UsageRecord | None:
        return await self._session.scalar(
            select(UsageRecord).where(UsageRecord.request_id == request_id)
        )

    async def add(self, record: UsageRecord) -> UsageRecord:
        self._session.add(record)
        await self._session.flush()
        return record

    async def add_new(self, record: UsageRecord) -> UsageRecord:
        """Insert a usage row inside a savepoint; re-raise IntegrityError.

        The generate path maps a unique ``request_id`` violation to a 409. The
        nested transaction rolls back only the failed INSERT so the outer
        session stays usable (e.g. for release(E) + commit after the 409).
        """
        async with self._session.begin_nested():
            self._session.add(record)
            await self._session.flush()
            return record

    async def historical_avg_cost(
        self,
        *,
        provider: str,
        model: str,
        exclude_request_id: str | None = None,
        limit: int = 100,
        isolate: bool = True,
    ) -> tuple[Decimal | None, int]:
        """AVG(actual_cost) over the most recent SUCCESS rows for (provider, model).

        Model-level baseline (not scoped by team/app). Excludes the just-inserted
        request_id so a new row never appears in its own baseline. Returns
        (avg, sample_count); avg is None when there are no samples.

        isolate=True runs the SELECT inside a savepoint so a query failure cannot
        poison the outer money transaction (alert soft-fail path).
        """

        async def _run() -> tuple[Decimal | None, int]:
            inner = select(UsageRecord.actual_cost).where(
                UsageRecord.status == "SUCCESS",
                UsageRecord.provider == provider,
                UsageRecord.model == model,
                UsageRecord.actual_cost.is_not(None),
            )
            if exclude_request_id is not None:
                inner = inner.where(UsageRecord.request_id != exclude_request_id)
            inner = inner.order_by(UsageRecord.created_at.desc()).limit(limit)

            sub = inner.subquery()
            row = (
                await self._session.execute(
                    select(func.avg(sub.c.actual_cost), func.count()).select_from(sub)
                )
            ).one()
            avg = row[0] if row[0] is not None else None
            count = int(row[1] or 0)
            return avg, count

        if isolate:
            async with self._session.begin_nested():
                return await _run()
        return await _run()

    async def count(self) -> int:
        return await self._session.scalar(select(func.count()).select_from(UsageRecord)) or 0

    async def list_records(self, *, limit: int = 100, offset: int = 0) -> list[UsageRecord]:
        stmt = (
            select(UsageRecord).order_by(UsageRecord.created_at.desc()).limit(limit).offset(offset)
        )
        return list((await self._session.scalars(stmt)).all())

    async def summary(self) -> dict:
        """Totals over all recorded usage."""
        filters = [UsageRecord.actual_cost.is_not(None)]  # type: ignore[attr-defined]
        rows = (
            await self._session.execute(
                select(
                    func.count().label("total_requests"),
                    func.sum(UsageRecord.actual_input_tokens).label("total_input_tokens"),
                    func.sum(UsageRecord.cached_input_tokens).label("total_cached_tokens"),
                    func.sum(UsageRecord.actual_output_tokens).label("total_output_tokens"),
                    func.sum(UsageRecord.actual_cost).label("total_cost"),
                ).where(*filters)
            )
        ).one()
        return {
            "total_requests": rows.total_requests or 0,
            "total_input_tokens": rows.total_input_tokens or 0,
            "total_cached_tokens": rows.total_cached_tokens or 0,
            "total_output_tokens": rows.total_output_tokens or 0,
            "total_cost": rows.total_cost,
        }

    async def cost_by(self, dimension: str) -> list[dict]:
        """Group total actual cost by one attribution dimension."""
        col = getattr(UsageRecord, dimension, None)
        if col is None:
            raise ValueError(f"unsupported aggregation dimension: {dimension}")
        stmt = (
            select(col, func.sum(UsageRecord.actual_cost).label("cost"), func.count().label("n"))
            .where(UsageRecord.actual_cost.is_not(None))  # type: ignore[attr-defined]
            .group_by(col)
            .order_by(func.sum(UsageRecord.actual_cost).desc())
        )
        results = []
        for row in await self._session.execute(stmt):
            results.append({"key": row[0], "cost": row.cost, "requests": row.n})
        return results
