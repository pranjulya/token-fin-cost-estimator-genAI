"""Unit tests for the pure BudgetPolicy decision logic (PRD # 27)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.budget import ALLOW, BLOCK, CRITICAL, STRICT, WARN, decide


def _d(s):  # helper: Decimal from string
    return Decimal(s)


class TestDecisionThresholds:
    limit = Decimal("100")

    def _decide(
        self, *, committed="0", reserved="0", requested, warning="0.7", critical="0.9", mode=STRICT
    ):
        return decide(
            limit=self.limit,
            committed=Decimal(committed),
            reserved=Decimal(reserved),
            requested=Decimal(requested),
            warning=Decimal(warning),
            critical=Decimal(critical),
            enforcement_mode=mode,
        )

    def test_below_warning_allow(self):
        assert self._decide(requested="50").status == ALLOW

    def test_at_warning_is_warn(self):
        # usage fraction == warning (70) -> WARN (>= warning)
        assert self._decide(requested="70").status == WARN

    def test_between_warning_and_critical_warn(self):
        assert self._decide(requested="80").status == WARN

    def test_at_critical_is_critical(self):
        assert self._decide(requested="90").status == CRITICAL

    def test_below_100_critical(self):
        assert self._decide(requested="95").status == CRITICAL

    def test_at_limit_strict_blocks(self):
        assert self._decide(requested="100").status == BLOCK

    def test_over_limit_strict_blocks(self):
        assert self._decide(requested="105").status == BLOCK

    def test_advisory_over_limit_not_blocked(self):
        assert self._decide(requested="105", mode="ADVISORY") != BLOCK

    def test_remaining_fields(self):
        d = self._decide(requested="30")
        assert d.remaining_before == Decimal("100")
        assert d.remaining_after == Decimal("70")

    def test_reserved_counts_toward_usage(self):
        # 60 committed + 30 reserved = 90 <= 100 -> CRITICAL, not ALLOW
        assert self._decide(committed="60", reserved="30", requested="1").status == CRITICAL


class TestDecisionValidation:
    def test_negative_requested_rejected(self):
        with pytest.raises(ValueError):
            decide(
                limit=Decimal("100"),
                committed=Decimal("0"),
                reserved=Decimal("0"),
                requested=Decimal("-1"),
                warning=Decimal("0.7"),
                critical=Decimal("0.9"),
                enforcement_mode=STRICT,
            )

    def test_bad_threshold_order_rejected(self):
        with pytest.raises(ValueError):
            decide(
                limit=Decimal("100"),
                committed=Decimal("0"),
                reserved=Decimal("0"),
                requested=Decimal("1"),
                warning=Decimal("0.9"),
                critical=Decimal("0.7"),
                enforcement_mode=STRICT,
            )

    def test_allow_means_not_blocked(self):
        d = decide(
            limit=Decimal("100"),
            committed=Decimal("0"),
            reserved=Decimal("0"),
            requested=Decimal("10"),
            warning=Decimal("0.7"),
            critical=Decimal("0.9"),
            enforcement_mode=STRICT,
        )
        assert d.allowed is True
