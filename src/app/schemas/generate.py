"""Schemas for POST /v1/generate (PRD Phase 15)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, model_validator

from app.core.config import get_settings
from app.schemas.common import APIModel, Money, SignedMoney
from app.schemas.cost import BudgetEnvelope

if TYPE_CHECKING:
    from app.services.generation_service import GenerationResult


class GenerateRequest(BaseModel):
    provider: str = Field(..., min_length=1, max_length=64)
    model: str = Field(..., min_length=1, max_length=128)
    input: str
    max_output_tokens: int = Field(..., ge=1)
    application_id: str | None = Field(default=None, max_length=128)
    team_id: str | None = Field(default=None, max_length=128)
    user_id: str | None = Field(default=None, max_length=128)
    endpoint: str | None = Field(default=None, max_length=256)
    request_id: str | None = Field(default=None, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _limits(self) -> GenerateRequest:
        s = get_settings()
        if len(self.input) > s.max_prompt_chars:
            raise ValueError("input exceeds max_prompt_chars")
        if self.max_output_tokens > s.max_expected_output_tokens:
            raise ValueError("max_output_tokens exceeds max_expected_output_tokens")
        return self


class GenerateResponse(APIModel):
    request_id: str
    provider: str
    model: str
    output: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_input_cost: Money
    estimated_cached_input_cost: Money | None = None
    estimated_output_cost: Money
    estimated_total_cost: Money
    actual_input_tokens: int
    actual_cached_input_tokens: int
    actual_output_tokens: int
    actual_cost: Money
    variance_amount: SignedMoney | None = None
    variance_percent: SignedMoney | None = None
    currency: str
    pricing_version: int
    budget: BudgetEnvelope
    status: str

    @classmethod
    def from_result(cls, result: GenerationResult) -> GenerateResponse:
        est = result.estimation
        b = est.breakdown
        u = result.usage
        decision = result.budget_decision
        envelope = (
            BudgetEnvelope()
            if decision is None
            else BudgetEnvelope(
                status=decision.status,
                # Clamp negative remainings (over-limit) to 0: Money is non-negative.
                remaining_before_request=max(decision.remaining_before, Decimal("0")),
                remaining_after_estimate=max(decision.remaining_after, Decimal("0")),
            )
        )
        # On the generate path actual_cost and pricing_version are always set
        # (record_new computes them); narrow the nullable ORM types.
        assert u.actual_cost is not None  # noqa: S101 - type guard
        assert u.pricing_version is not None  # noqa: S101 - type guard
        return cls(
            request_id=result.request_id,
            provider=result.provider,
            model=result.model,
            output=result.output,
            estimated_input_tokens=est.input_tokens,
            estimated_output_tokens=est.output_tokens,
            estimated_input_cost=b.input_cost,
            estimated_cached_input_cost=b.cached_input_cost,
            estimated_output_cost=b.output_cost,
            estimated_total_cost=b.total_cost,
            actual_input_tokens=u.actual_input_tokens,
            actual_cached_input_tokens=u.cached_input_tokens,
            actual_output_tokens=u.actual_output_tokens,
            actual_cost=u.actual_cost,
            variance_amount=u.variance_amount,
            variance_percent=u.variance_percent,
            currency=b.currency,
            pricing_version=u.pricing_version,
            budget=envelope,
            status=u.status,
        )
