"""Pure cost calculation engine (PRD # 21, Phase 3).

No I/O, no DB, no FastAPI — just Decimal math so it is trivially testable.
Inputs are token counts and a ModelPrice; output is a CostBreakdown.

Formula:
    input_cost  = input_tokens        × (input_price_per_million  / 1e6)
    cached_cost = cached_input_tokens × (cached_input_rate / 1e6)   [0 if no cached price]
    output_cost = output_tokens       × (output_price_per_million / 1e6)
    total       = input + cached + output
"""

from __future__ import annotations

from app.domain.cost import CostBreakdown
from app.domain.pricing import ModelPrice
from app.utils.money import Decimal, is_valid_amount
from app.utils.money import cost as _cost


class CostCalculator:
    @staticmethod
    def calculate(
        *,
        input_tokens: int,
        output_tokens: int,
        pricing: ModelPrice,
        cached_input_tokens: int = 0,
    ) -> CostBreakdown:
        if input_tokens < 0 or output_tokens < 0 or cached_input_tokens < 0:
            raise ValueError("token counts must be non-negative")

        input_cost = _cost(input_tokens, pricing.input_per_million)
        output_cost = _cost(output_tokens, pricing.output_per_million)

        cached_cost = Decimal("0")
        if cached_input_tokens and pricing.cached_input_per_million is not None:
            cached_cost = _cost(cached_input_tokens, pricing.cached_input_per_million)

        return CostBreakdown(
            currency=pricing.currency,
            input_cost=input_cost,
            cached_input_cost=cached_cost,
            output_cost=output_cost,
        )

    @staticmethod
    def validate_price(pricing: ModelPrice) -> None:
        """Reject nonsensical pricing early (guards against bad seed data)."""
        rates = [pricing.input_per_million, pricing.output_per_million]
        if pricing.cached_input_per_million is not None:
            rates.append(pricing.cached_input_per_million)
        if not all(is_valid_amount(r) for r in rates):
            raise ValueError("pricing rates must be non-negative Decimals")
