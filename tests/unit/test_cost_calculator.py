"""Unit tests for the pure cost calculator (PRD # 36 example cases)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.pricing import ModelPrice
from app.services.cost_calculator import CostCalculator


def price(**overrides) -> ModelPrice:
    base = dict(
        provider="openai",
        model="gpt-4o",
        currency="USD",
        input_per_million=Decimal("2.50"),
        output_per_million=Decimal("10.00"),
        cached_input_per_million=Decimal("1.25"),
    )
    base.update(overrides)
    return ModelPrice(**base)


class TestCostCalculator:
    def test_zero_tokens(self):
        b = CostCalculator.calculate(input_tokens=0, output_tokens=0, pricing=price())
        assert b.total_cost == Decimal("0")

    def test_basic(self):
        b = CostCalculator.calculate(input_tokens=1_000, output_tokens=1_000, pricing=price())
        assert b.input_cost == Decimal("0.0025")
        assert b.output_cost == Decimal("0.01")
        assert b.total_cost == Decimal("0.0125")

    def test_cached_tokens(self):
        b = CostCalculator.calculate(
            input_tokens=1000, cached_input_tokens=2000, output_tokens=500, pricing=price()
        )
        assert b.cached_input_cost == Decimal("0.0025")

    def test_no_cached_price(self):
        p = price(cached_input_per_million=None)
        b = CostCalculator.calculate(
            input_tokens=100, cached_input_tokens=1000, output_tokens=100, pricing=p
        )
        assert b.input_cost == Decimal("0.00025")
        assert b.cached_input_cost == Decimal("0")

    def test_zero_output_tokens(self):
        b = CostCalculator.calculate(input_tokens=100, output_tokens=0, pricing=price())
        assert b.total_cost == b.input_cost

    def test_large_token_count(self):
        b = CostCalculator.calculate(
            input_tokens=1_000_000, output_tokens=1_000_000, pricing=price()
        )
        assert b.total_cost == Decimal("12.50")

    def test_negative_rejected(self):
        with pytest.raises(ValueError):
            CostCalculator.calculate(input_tokens=-1, output_tokens=0, pricing=price())
        with pytest.raises(ValueError):
            CostCalculator.calculate(
                input_tokens=0, output_tokens=0, cached_input_tokens=-5, pricing=price()
            )

    def test_decimal_not_float(self):
        b = CostCalculator.calculate(input_tokens=3, output_tokens=1, pricing=price())
        assert isinstance(b.total_cost, Decimal)
        # No binary float artifacts: 3 * 2.5e-6 + 1e-5 == 1.75e-5 exactly
        assert b.total_cost == Decimal("0.0000175")


class TestValidatePrice:
    def test_negative_rate_rejected(self):
        with pytest.raises(ValueError):
            CostCalculator.validate_price(price(input_per_million=Decimal("-3")))

    def test_valid_rate_ok(self):
        CostCalculator.validate_price(price())
