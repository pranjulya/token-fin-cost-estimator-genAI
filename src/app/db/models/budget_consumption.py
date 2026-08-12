"""budget_consumption entity — the Postgres-atomic spend counter per period.

One row per (budget, period_key). ``remaining = limit - committed - reserved``.
Updates to this table are the atomic operation that prevents overspend races
(PRD # 26): a guarded ``UPDATE … RETURNING`` either reserves or reports no row.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TimestampMixin


class BudgetConsumption(Base, PKMixin, TimestampMixin):
    __tablename__ = "budget_consumption"

    budget_id: Mapped[int] = mapped_column(
        ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_key: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. 2026-08, 2026-08-12

    reserved_amount: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False, default=0)
    committed_amount: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("budget_id", "period_key", name="uq_budget_consumption_period"),
    )
