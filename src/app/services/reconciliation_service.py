"""Estimate-vs-actual reconciliation (PRD # 24, Phase 6).

Pure logic: given estimated and actual costs, compute the variance and the
percentage variance. Percentage is None when the estimate is zero (undefined).
"""

from __future__ import annotations

from decimal import Decimal

from app.domain.usage import ReconciliationResult

HUNDRED = Decimal("100")


class ReconciliationService:
    @staticmethod
    def reconcile(estimated_cost: Decimal, actual_cost: Decimal) -> ReconciliationResult:
        variance = actual_cost - estimated_cost
        if estimated_cost == 0:
            variance_percent = None
        else:
            variance_percent = (variance / estimated_cost) * HUNDRED
        return ReconciliationResult(
            estimated_cost=estimated_cost,
            actual_cost=actual_cost,
            variance_amount=variance,
            variance_percent=variance_percent,
        )
