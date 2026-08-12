"""alerts entity (PRD §19, Phase 13). Operator-facing tickets, not audit rows.

Alongside immutable ``budget_events``, alerts are the queryable/acknowledgeable
signal for budget threshold crossings and cost anomalies.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Alert(Base, PKMixin):
    __tablename__ = "alerts"

    alert_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # BUDGET_THRESHOLD | COST_ANOMALY
    severity: Mapped[str] = mapped_column(String(16), nullable=False)  # WARNING | CRITICAL

    # Attribution (may be null for model-only anomalies).
    scope_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scope_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    message: Mapped[str] = mapped_column(String(512), nullable=False)

    # DB column matches PRD §19 (`metadata`); ORM attr avoids the reserved
    # SQLAlchemy `metadata` name.
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)

    dedupe_key: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_alerts_created_at", "created_at"),
        Index("ix_alerts_type_severity", "alert_type", "severity"),
        Index("ix_alerts_scope", "scope_type", "scope_id"),
        Index("ix_alerts_acknowledged_at", "acknowledged_at"),
    )
