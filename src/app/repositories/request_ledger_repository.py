"""Data access for the request_ledger idempotency table (P2)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RequestLedger


class RequestLedgerRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self, request_id: str) -> RequestLedger | None:
        result = await self._session.scalar(
            select(RequestLedger).where(RequestLedger.request_id == request_id)
        )
        assert result is None or isinstance(result, RequestLedger)  # noqa: S101 - type guard
        return result

    async def create_in_flight(
        self, *, request_id: str, provider: str, model: str
    ) -> RequestLedger:
        """Insert an IN_FLIGHT ledger row. Raises IntegrityError on a duplicate
        request_id — callers map that to a 409."""
        row = RequestLedger(
            request_id=request_id,
            status="IN_FLIGHT",
            provider=provider,
            model=model,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError:
            # Roll back only this savepoint so the outer session stays usable.
            await self._session.rollback()
            raise
        return row

    async def mark_completed(self, request_id: str) -> None:
        row = await self.get(request_id)
        if row is not None:
            row.status = "COMPLETED"
            await self._session.flush()

    async def mark_failed(self, request_id: str) -> None:
        row = await self.get(request_id)
        if row is not None:
            row.status = "FAILED"
            await self._session.flush()
