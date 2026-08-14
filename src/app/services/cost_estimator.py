"""CostEstimator — orchestrates tokenize → price → calculate (PRD §22).

Dependencies are injected as the TokenCounter and PricingProvider abstractions,
so the estimator never knows about tiktoken or Postgres specifics.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.metrics import span
from app.domain.cost import CostBreakdown
from app.domain.pricing import ModelPrice
from app.providers.pricing.base import PricingProvider
from app.providers.tokenizers.base import TokenCounter
from app.services.cost_calculator import CostCalculator


@dataclass(frozen=True)
class Estimation:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    breakdown: CostBreakdown
    pricing: ModelPrice

    @property
    def total_cost(self) -> Decimal:
        return self.breakdown.total_cost


class CostEstimator:
    def __init__(self, token_counter: TokenCounter, pricing: PricingProvider):
        self._token_counter = token_counter
        self._pricing = pricing

    async def estimate(
        self,
        *,
        provider: str,
        model: str,
        input_text: str,
        expected_output_tokens: int,
    ) -> Estimation:
        with span("tokenization"):
            input_tokens = self._token_counter.count(model, input_text)
        with span("pricing_lookup"):
            model_price = await self._pricing.get_pricing(provider, model)
        CostCalculator.validate_price(model_price)
        with span("cost_estimation"):
            breakdown = CostCalculator.calculate(
                input_tokens=input_tokens,
                output_tokens=expected_output_tokens,
                pricing=model_price,
            )
        return Estimation(
            input_tokens=input_tokens,
            output_tokens=expected_output_tokens,
            cached_input_tokens=0,
            breakdown=breakdown,
            pricing=model_price,
        )
