"""Unit tests for estimate-vs-actual reconciliation."""

from __future__ import annotations

from decimal import Decimal

from app.services.reconciliation_service import ReconciliationService


class TestReconciliation:
    def test_actual_less_than_estimate(self):
        r = ReconciliationService.reconcile(Decimal("0.031"), Decimal("0.026"))
        assert r.variance_amount == Decimal("-0.005")
        assert r.variance_percent == Decimal("-16.12903225806451612903225806")

    def test_exact_match(self):
        r = ReconciliationService.reconcile(Decimal("1"), Decimal("1"))
        assert r.variance_amount == Decimal("0")
        assert r.variance_percent == Decimal("0")

    def test_zero_estimate_percent_none(self):
        r = ReconciliationService.reconcile(Decimal("0"), Decimal("0.5"))
        assert r.variance_amount == Decimal("0.5")
        assert r.variance_percent is None

    def test_actual_greater(self):
        r = ReconciliationService.reconcile(Decimal("10"), Decimal("15"))
        assert r.variance_percent == Decimal("50")
