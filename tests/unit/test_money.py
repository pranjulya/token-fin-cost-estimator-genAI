"""Unit tests for the money helpers."""

from __future__ import annotations

from decimal import Decimal

from app.utils.money import as_decimal, cost, is_valid_amount, per_unit, quantize


class TestAsDecimal:
    def test_int_and_string(self):
        assert as_decimal("3.14") == Decimal("3.14")
        assert as_decimal(5) == Decimal("5")

    def test_float_clean(self):
        # 0.1 as float must not leak binary artifacts.
        assert as_decimal(0.1) == Decimal("0.1")

    def test_decimal_passthrough(self):
        d = Decimal("2.00")
        assert as_decimal(d) is d or as_decimal(d) == d


class TestCost:
    def test_million_tokens(self):
        assert cost(1_000_000, "3") == Decimal("3")

    def test_output_small(self):
        assert cost(500, "6") == Decimal("0.003")

    def test_cached(self):
        assert cost(2_000, "1.25") == Decimal("0.0025")

    def test_zero_tokens(self):
        assert cost(0, "10") == Decimal("0")


class TestPerUnit:
    def test_conversion(self):
        assert per_unit("3000") == Decimal("0.003")


class TestQuantize:
    def test_usd_two_places(self):
        assert quantize("0.00425") == Decimal("0.00")
        assert quantize("0.005") == Decimal("0.01")  # half-up

    def test_exact(self):
        assert quantize("3.005", "USD") == Decimal("3.01")


class TestIsValidAmount:
    def test_positive_and_zero(self):
        assert is_valid_amount("0")
        assert is_valid_amount("12.50")

    def test_rejects_negative(self):
        assert not is_valid_amount("-1")

    def test_rejects_non_numeric(self):
        assert not is_valid_amount("abc")

    def test_rejects_huge(self):
        assert not is_valid_amount("1e20")

    def test_rejects_float_artifacts(self):
        assert not is_valid_amount(float("nan"))


def test_money_json_is_fixed_point_never_scientific():
    from decimal import Decimal

    from pydantic import TypeAdapter

    from app.schemas.common import Money

    ta = TypeAdapter(Money)
    assert ta.dump_python(Decimal("1E+1")) == "10"
    assert ta.dump_python(Decimal("0.00004")) == "0.00004"
    assert ta.dump_python(Decimal("1E-7")) == "0.0000001"
