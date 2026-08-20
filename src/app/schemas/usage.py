"""Usage ledger schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.core.config import get_settings
from app.schemas.common import APIModel, Money, SignedMoney


class UsageCreate(BaseModel):
    request_id: str = Field(..., min_length=1, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=128)
    provider: str = Field(..., min_length=1, max_length=64)
    model: str = Field(..., min_length=1, max_length=128)
    application_id: str | None = Field(default=None, max_length=128)
    team_id: str | None = Field(default=None, max_length=128)
    user_id: str | None = Field(default=None, max_length=128)
    endpoint: str | None = Field(default=None, max_length=256)
    environment: str | None = Field(default=None, max_length=32)

    estimated_input_tokens: int = Field(default=0, ge=0)
    estimated_output_tokens: int = Field(default=0, ge=0)
    estimated_cost: Money | None = None

    actual_input_tokens: int = Field(..., ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    actual_output_tokens: int = Field(..., ge=0)

    status: str = Field(default="SUCCESS", max_length=32)

    @model_validator(mode="after")
    def _token_limits(self) -> UsageCreate:
        """Block absurd token counts (Phase 17 input limits)."""
        cap = get_settings().max_expected_output_tokens
        for field in (
            "estimated_input_tokens",
            "estimated_output_tokens",
            "actual_input_tokens",
            "cached_input_tokens",
            "actual_output_tokens",
        ):
            if getattr(self, field) > cap:
                raise ValueError(f"{field} exceeds max_expected_output_tokens")
        return self


class UsageOut(APIModel):
    id: int
    request_id: str
    correlation_id: str | None
    provider: str
    model: str
    application_id: str | None
    team_id: str | None
    user_id: str | None
    endpoint: str | None
    environment: str | None
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost: Money | None
    actual_input_tokens: int
    cached_input_tokens: int
    actual_output_tokens: int
    actual_cost: Money | None
    variance_amount: SignedMoney | None
    variance_percent: SignedMoney | None
    pricing_version: int | None
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class UsageSummary(BaseModel):
    total_requests: int
    total_input_tokens: int
    total_cached_tokens: int
    total_output_tokens: int
    total_cost: Money | None


class CostByDimension(BaseModel):
    key: str | None
    cost: Money | None
    requests: int
