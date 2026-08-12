"""Budget schemas (PRD # 28)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import APIModel, Money
from app.utils.money import _CURRENCY_PLACES

SCOPE_TYPES = {"TEAM", "APPLICATION"}
PERIOD_TYPES = {"MONTHLY", "DAILY"}
ENFORCEMENT_MODES = {"STRICT", "ADVISORY"}


class BudgetCreate(BaseModel):
    scope_type: str = Field(..., min_length=1)
    scope_id: str = Field(..., min_length=1, max_length=128)
    period_type: str = Field(...)
    limit_amount: Money
    currency: str = "USD"
    warning_threshold: Decimal = Field(default=Decimal("0.70"), ge=0, le=1)
    critical_threshold: Decimal = Field(default=Decimal("0.90"), ge=0, le=1)
    enforcement_mode: str = "STRICT"
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @field_validator("scope_type")
    @classmethod
    def _scope(cls, v: str) -> str:
        v = v.upper()
        if v not in SCOPE_TYPES:
            raise ValueError(f"scope_type must be one of {sorted(SCOPE_TYPES)}")
        return v

    @field_validator("period_type")
    @classmethod
    def _period(cls, v: str) -> str:
        v = v.upper()
        if v not in PERIOD_TYPES:
            raise ValueError(f"period_type must be one of {sorted(PERIOD_TYPES)}")
        return v

    @field_validator("enforcement_mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        v = v.upper()
        if v not in ENFORCEMENT_MODES:
            raise ValueError(f"enforcement_mode must be one of {sorted(ENFORCEMENT_MODES)}")
        return v

    @field_validator("currency")
    @classmethod
    def _currency(cls, v: str) -> str:
        v = v.upper()
        if v not in _CURRENCY_PLACES:
            raise ValueError(f"unsupported currency: {v}")
        return v

    @field_validator("critical_threshold")
    @classmethod
    def _critical_sane(cls, v: Decimal) -> Decimal:
        if not (Decimal("0") < v <= Decimal("1")):
            raise ValueError("critical_threshold must be in (0, 1]")
        return v

    @model_validator(mode="after")
    def _thresholds_ordered(self):
        if self.warning_threshold > self.critical_threshold:
            raise ValueError("warning_threshold must be <= critical_threshold")
        return self


class BudgetUpdate(BaseModel):
    limit_amount: Money | None = None
    warning_threshold: Decimal | None = Field(default=None, ge=0, le=1)
    critical_threshold: Decimal | None = Field(default=None, ge=0, le=1)
    enforcement_mode: str | None = None
    ends_at: datetime | None = None

    @field_validator("enforcement_mode")
    @classmethod
    def _mode(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.upper()
        if v not in ENFORCEMENT_MODES:
            raise ValueError(f"enforcement_mode must be one of {sorted(ENFORCEMENT_MODES)}")
        return v


class BudgetOut(APIModel):
    id: int
    scope_type: str
    scope_id: str
    period_type: str
    limit_amount: Money
    currency: str
    warning_threshold: Decimal
    critical_threshold: Decimal
    enforcement_mode: str
    starts_at: datetime | None
    ends_at: datetime | None
    created_at: datetime
    updated_at: datetime
