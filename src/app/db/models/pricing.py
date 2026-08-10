"""model_pricing entity (PRD # 16)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TimestampMixin


class ModelPricing(Base, PKMixin, TimestampMixin):
    __tablename__ = "model_pricing"

    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")

    # USD per 1,000,000 tokens (normalized storage; domain converts per-token).
    input_price_per_million: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    cached_input_price_per_million: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 10), nullable=True
    )
    output_price_per_million: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)

    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    version: Mapped[int] = mapped_column(nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint(
            "provider", "model", "version", name="uq_model_pricing_provider_model_version"
        ),
        Index("ix_model_pricing_provider_model", "provider", "model"),
    )
