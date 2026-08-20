"""Decimal-safe money helpers.

Rule (PRD # 21): never use binary float for financial math; always ``Decimal``.
Pricing is stored per-million-token; these helpers convert and quantize safely.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from math import isfinite

__all__ = [
    "ZERO",
    "Decimal",
    "isfinite",
    "as_decimal",
    "per_unit",
    "cost",
    "quantize",
    "is_valid_amount",
    "_CURRENCY_PLACES",
]

ZERO = Decimal("0")

# Currency -> number of decimal places used for money display/quantization.
_CURRENCY_PLACES: dict[str, int] = {"USD": 2, "EUR": 2, "GBP": 2, "INR": 2}

_MILLION = Decimal("1000000")


def as_decimal(value: int | float | str | Decimal) -> Decimal:
    """Coerce a value to Decimal safely.

    Converts floats via string representation so binary float noise (e.g.
    0.1 -> 0.1000000000000000055) does not leak in, then normalizes.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not a valid money value")
    if isinstance(value, int):
        result = Decimal(value)
    else:
        # str(value) on float avoids float->binary artifacts.
        result = Decimal(str(value))
    return result.normalize()


def per_unit(price_per_million: int | float | str | Decimal) -> Decimal:
    """Convert a per-million-token rate to a per-token Decimal."""
    return (as_decimal(price_per_million) / _MILLION).normalize()


def cost(tokens: int, price_per_million: int | float | str | Decimal) -> Decimal:
    """cost = tokens * (per-million price / 1,000,000), all in Decimal."""
    tokens_dec = Decimal(tokens)
    return (tokens_dec * as_decimal(price_per_million) / _MILLION).normalize()


def quantize(amount: int | float | str | Decimal, currency: str = "USD") -> Decimal:
    """Round money to the currency's standard precision (half-up)."""
    places = _CURRENCY_PLACES.get(currency.upper(), 2)
    quantum = Decimal("1").scaleb(-places)
    return as_decimal(amount).quantize(quantum, rounding=ROUND_HALF_UP)


def is_valid_amount(value: int | float | str | Decimal) -> bool:
    """True if the value is a non-negative finite Decimal within a sane range."""
    try:
        d = as_decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return False
    if not isfinite(float(d)):  # guards NaN / Infinity, which compare with exceptions
        return False
    return d >= ZERO and d < Decimal("1e15")
