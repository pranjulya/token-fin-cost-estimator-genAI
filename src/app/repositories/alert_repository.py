"""Data access for alerts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Alert


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AlertRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_if_absent(
        self,
        *,
        alert_type: str,
        severity: str,
        scope_type: str | None,
        scope_id: str | None,
        request_id: str | None,
        message: str,
        metadata: dict[str, Any] | None,
        dedupe_key: str,
    ) -> Alert | None:
        """Insert an alert if its dedupe_key is free.

        Runs inside a savepoint (begin_nested) so a unique violation or any
        failure rolls back only this insert — it never poisons the outer money
        transaction. Returns None on dedupe (unique conflict), the row on success.
        """
        try:
            async with self._session.begin_nested():
                row = Alert(
                    alert_type=alert_type,
                    severity=severity,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    request_id=request_id,
                    message=message,
                    metadata_json=metadata,
                    dedupe_key=dedupe_key,
                )
                self._session.add(row)
                await self._session.flush()
                return row
        except IntegrityError:
            # Duplicate dedupe_key — dedupe no-op.
            return None

    async def get(self, alert_id: int) -> Alert | None:
        return await self._session.get(Alert, alert_id)

    async def list(
        self,
        *,
        alert_type: str | None = None,
        severity: str | None = None,
        scope_type: str | None = None,
        scope_id: str | None = None,
        open_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Alert]:
        stmt = select(Alert).order_by(Alert.created_at.desc()).limit(limit).offset(offset)
        if alert_type is not None:
            stmt = stmt.where(Alert.alert_type == alert_type)
        if severity is not None:
            stmt = stmt.where(Alert.severity == severity)
        if scope_type is not None:
            stmt = stmt.where(Alert.scope_type == scope_type)
        if scope_id is not None:
            stmt = stmt.where(Alert.scope_id == scope_id)
        if open_only:
            stmt = stmt.where(Alert.acknowledged_at.is_(None))
        return list((await self._session.scalars(stmt)).all())

    async def acknowledge(self, alert: Alert) -> Alert:
        if alert.acknowledged_at is None:
            alert.acknowledged_at = _utcnow()
            await self._session.flush()
        return alert
