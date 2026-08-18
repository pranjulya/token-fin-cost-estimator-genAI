"""budget_events entity (PRD # 20 / budget_events). Durable audit of budget ops.

Alerts (PRD Phase 13) read this later; this branch only records the events.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class BudgetEvent(Base, PKMixin):
    __tablename__ = "budget_events"

    budget_id: Mapped[int] = mapped_column(ForeignKey("budgets.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # RESERVE|COMMIT|RELEASE|DECISION
    period_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)  # e.g. ALLOW|BLOCK
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
