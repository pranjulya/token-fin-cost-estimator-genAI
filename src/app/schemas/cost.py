"""Estimate API schemas (PRD UC-01 / §29)."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.core.config import get_settings
from app.schemas.common import Money


class EstimateRequest(BaseModel):
    provider: str = Field(..., min_length=1, max_length=64)
    model: str = Field(..., min_length=1, max_length=128)
    input: str = Field(..., description="Prompt text to estimate")
    expected_output_tokens: int = Field(..., ge=0)
    application_id: str | None = Field(default=None, max_length=128)
    team_id: str | None = Field(default=None, max_length=128)
    endpoint: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def _limits(self) -> EstimateRequest:
        s = get_settings()
        if len(self.input) > s.max_prompt_chars:
            raise ValueError("input exceeds max_prompt_chars")
        if self.expected_output_tokens > s.max_expected_output_tokens:
            raise ValueError("expected_output_tokens exceeds max_expected_output_tokens")
        return self


class BudgetEnvelope(BaseModel):
    """Placeholder for the budget phase — always empty in this vertical slice."""

    status: str = "ENABLED"
    remaining_before_request: Money | None = None
    remaining_after_estimate: Money | None = None


class EstimateResponse(BaseModel):
    request_id: str
    provider: str
    model: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_input_cost: Money
    estimated_cached_input_cost: Money | None = None
    estimated_output_cost: Money
    estimated_total_cost: Money
    currency: str
    pricing_version: int
    budget: BudgetEnvelope
