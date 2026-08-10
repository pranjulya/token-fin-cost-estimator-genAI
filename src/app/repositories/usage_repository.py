"""Data access for usage_records."""

from __future__ import annotations

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
