"""usage_records entity (PRD # 17). Append-only ledger of LLM interactions."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TimestampMixin, utcnow


class UsageRecord(Base, PKMixin, TimestampMixin):
    __tablename__ = "usage_records"

    request_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)

    # Cost attribution (PRD FR-06).
    application_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    team_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    endpoint: Mapped[str | None] = mapped_column(String(256), nullable=True)
    environment: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Estimates (pre-execution).
    estimated_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)

    # Actuals (post-execution, reported by the caller).
    actual_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actual_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actual_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)

    # Reconciliation variance (PRD # 24).
    variance_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    variance_percent: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)

    # Freeze pricing context so historical cost never re-prices (PRD # 20).
    pricing_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="SUCCESS")

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_usage_provider_model", "provider", "model"),
        Index("ix_usage_team_app", "team_id", "application_id"),
        Index("ix_usage_endpoint", "endpoint"),
        Index("ix_usage_created_at", "created_at"),
    )
