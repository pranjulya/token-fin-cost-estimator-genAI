"""Usage domain snapshot produced by reconciliation (pure)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ReconciliationResult:
    """Estimate-vs-actual comparison (PRD # 24)."""

    estimated_cost: Decimal
    actual_cost: Decimal
    variance_amount: Decimal
    variance_percent: Decimal | None  # None when estimated cost is zero
