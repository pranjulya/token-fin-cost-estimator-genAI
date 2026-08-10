"""Cost breakdown domain model (pure)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.utils.money import ZERO


@dataclass(frozen=True)
class CostBreakdown:
    currency: str
    input_cost: Decimal = ZERO
    cached_input_cost: Decimal = ZERO
    output_cost: Decimal = ZERO

    @property
    def total_cost(self) -> Decimal:
        return self.input_cost + self.cached_input_cost + self.output_cost
