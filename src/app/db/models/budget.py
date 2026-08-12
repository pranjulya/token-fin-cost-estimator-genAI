"""budgets entity (PRD # 18). A spend-limit policy scoped to a team or app."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TimestampMixin


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Budget(Base, PKMixin, TimestampMixin):
    __tablename__ = "budgets"

    # Who the budget applies to (PRD FR-07): TEAM or APPLICATION.
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False)

    period_type: Mapped[str] = mapped_column(String(16), nullable=False)  # MONTHLY | DAILY

    # Exact currency amount available per period (NOT per-million pricing).
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")

    # 0..1 thresholds; usage fraction below warning -> ALLOW, above -> WARN/CRITICAL.
    warning_threshold: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    critical_threshold: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)

    # STRICT blocks over-limit reservations; ADVISORY only reports.
    enforcement_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="STRICT")

    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_budgets_scope", "scope_type", "scope_id"),)
