"""Pricing admin schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import APIModel, Money


class PricingCreate(BaseModel):
    provider: str = Field(..., min_length=1, max_length=64)
    model: str = Field(..., min_length=1, max_length=128)
    input_price_per_million: Money
    output_price_per_million: Money
    cached_input_price_per_million: Money | None = None
    currency: str = Field(default="USD", min_length=3, max_length=8)
    effective_from: date | None = None
    effective_to: date | None = None

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.upper()


class PricingOut(APIModel):
    id: int
    provider: str
    model: str
    currency: str
    input_price_per_million: Money
    cached_input_price_per_million: Money | None
    output_price_per_million: Money
    effective_from: date | None
    effective_to: date | None
    version: int
    created_at: datetime
    updated_at: datetime
