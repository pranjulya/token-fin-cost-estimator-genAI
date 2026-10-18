"""Shared schema building blocks."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, PlainValidator

from app.utils.money import Decimal, is_valid_amount, isfinite


def _validate_money(value: Any) -> Decimal:
    d = Decimal(str(value))
    if not is_valid_amount(d):
        raise ValueError("amount must be a non-negative decimal")
    return d


def _validate_signed(value: Any) -> Decimal:
    d = Decimal(str(value))
    if not isfinite(float(d)):
        raise ValueError("amount must be a finite decimal")
    if abs(d) >= Decimal("1e15"):
        raise ValueError("amount out of range")
    return d


def _plain(v: Decimal) -> str:
    """Fixed-point string: ``str(Decimal('1E+1'))`` would leak scientific notation."""
    return format(v, "f")


# Money serialized as a string in JSON so decimal precision is never lost
# (binary float conversion would break financial accuracy, PRD NFR).
Money = Annotated[
    Decimal,
    PlainValidator(_validate_money),
    PlainSerializer(_plain, return_type=str),
]

# Signed money: variances and deltas may be negative (PRD # 24).
SignedMoney = Annotated[
    Decimal,
    PlainValidator(_validate_signed),
    PlainSerializer(_plain, return_type=str),
]


def decimals_field(**kwargs: Any) -> Any:
    return Field(default=Decimal("0"), **kwargs)


class APIModel(BaseModel):
    """Base response model enabling ORM attribute mapping."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class GenericError(BaseModel):
    error: ErrorDetail
