"""Unit tests for pure alert domain rules (Phase 13)."""

from __future__ import annotations

from decimal import Decimal

from app.domain.alerts import (
    REASON_ABSOLUTE,
    REASON_HISTORICAL,
    REASON_VARIANCE,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    budget_threshold_candidate,
    cost_anomaly_candidate,
)
from app.services.reconciliation_service import ReconciliationService


def _d(s):
    return Decimal(s)


def _budget(**kw):
    base = dict(
        decision_status="WARN",
        budget_id=42,
        scope_type="TEAM",
        scope_id="platform-team",
        period_key="2026-08",
        period_type="MONTHLY",
        request_id="req_1",
        limit_amount=_d("100.00"),
        remaining_before=_d("60.00"),
        remaining_after=_d("50.00"),
        requested_amount=_d("10.00"),
        warning_threshold=_d("0.70"),
        critical_threshold=_d("0.90"),
        enforcement_mode="STRICT",
        currency="USD",
    )
    base.update(kw)
    return budget_threshold_candidate(**base)


def _anomaly(**kw):
    base = dict(
        request_id="req_x",
        provider="openai",
        model="gpt-4o",
        actual_cost=_d("15.00"),
        estimated_cost=_d("0.03"),
        variance_percent=_d("49900"),
        historical_avg=_d("0.03"),
        sample_count=20,
        team_id="platform-team",
        application_id=None,
        min_samples=10,
        multiplier=_d("50"),
        absolute_min=_d("5.00"),
        critical_abs=_d("10.00"),
        variance_percent_threshold=_d("400"),
        currency="USD",
    )
    base.update(kw)
    return cost_anomaly_candidate(**base)


class TestBudgetCandidate:
    def test_allow_no_candidate(self):
        assert _budget(decision_status="ALLOW") is None

    def test_warn_severity_and_key(self):
        c = _budget(decision_status="WARN")
        assert c is not None
        assert c.severity == SEVERITY_WARNING
        assert c.dedupe_key == "BUDGET_THRESHOLD:42:2026-08:WARN"
        assert c.dedupe_key.endswith(":WARN")

    def test_critical_severity_and_key(self):
        c = _budget(decision_status="CRITICAL")
        assert c is not None
        assert c.severity == SEVERITY_CRITICAL
        assert c.dedupe_key.endswith(":CRITICAL")

    def test_block_severity_critical_key_block(self):
        # BLOCK severity is CRITICAL but the dedupe key must carry :BLOCK,
        # never :CRITICAL — so WARN and BLOCK each fire once per period.
        c = _budget(decision_status="BLOCK")
        assert c is not None
        assert c.severity == SEVERITY_CRITICAL
        assert c.dedupe_key.endswith(":BLOCK")
        assert ":CRITICAL" not in c.dedupe_key

    def test_advisory_over_limit_warn(self):
        # ADVISORY over-limit maps to decision status WARN -> WARNING severity.
        c = _budget(decision_status="WARN", enforcement_mode="ADVISORY")
        assert c is not None
        assert c.severity == SEVERITY_WARNING
        assert c.dedupe_key.endswith(":WARN")


class TestAnomalyCandidate:
    def test_historical_multiplier_fires(self):
        c = _anomaly()
        assert c is not None
        assert REASON_HISTORICAL in c.metadata["reasons"]
        assert c.dedupe_key == "COST_ANOMALY:req_x"

    def test_sparse_history_uses_absolute_floor(self):
        # samples 3 < min 10 -> historical skipped; 15 >= 5 -> absolute fires.
        c = _anomaly(sample_count=3, historical_avg=_d("0.03"))
        assert c is not None
        reasons = c.metadata["reasons"]
        assert REASON_HISTORICAL not in reasons
        assert REASON_ABSOLUTE in reasons

    def test_low_actual_below_floor_no_fire(self):
        # variance_percent default must not leak: pass one below threshold.
        assert (
            _anomaly(
                actual_cost=_d("0.04"),
                estimated_cost=_d("0.03"),
                variance_percent=_d("33"),
                historical_avg=_d("0.03"),
                sample_count=20,
            )
            is None
        )

    def test_variance_threshold_5x_fires(self):
        # reconcile(est=1, actual=5) -> variance_percent=400 -> fires at threshold 400.
        rec = ReconciliationService.reconcile(_d("1"), _d("5"))
        c = _anomaly(
            actual_cost=_d("5.00"),
            estimated_cost=_d("1.00"),
            variance_percent=rec.variance_percent,
            historical_avg=None,
            sample_count=0,
            absolute_min=_d("100"),
        )
        assert c is not None
        assert REASON_VARIANCE in c.metadata["reasons"]

    def test_variance_just_below_fires_not(self):
        rec = ReconciliationService.reconcile(_d("1"), _d("4.99"))
        c = _anomaly(
            actual_cost=_d("4.99"),
            estimated_cost=_d("1.00"),
            variance_percent=rec.variance_percent,
            historical_avg=None,
            sample_count=0,
            absolute_min=_d("100"),
        )
        assert c is None

    def test_no_estimate_skips_variance(self):
        # estimated_cost=0 / variance None -> variance rule skipped.
        c = _anomaly(
            actual_cost=_d("0.04"),
            estimated_cost=_d("0"),
            variance_percent=None,
            historical_avg=_d("0.03"),
            sample_count=20,
        )
        assert c is None

    def test_scope_attribution_prefers_team(self):
        c = _anomaly()
        assert c.scope_type == "TEAM"
        assert c.scope_id == "platform-team"

    def test_scope_application_when_no_team(self):
        c = _anomaly(team_id=None, application_id="app-1")
        assert c.scope_type == "APPLICATION"
        assert c.scope_id == "app-1"

    def test_critical_when_above_critical_abs(self):
        c = _anomaly(actual_cost=_d("15.00"))
        assert c.severity == SEVERITY_CRITICAL

    def test_warning_when_below_critical_abs(self):
        # Isolate the variance rule so only it fires, below the critical threshold.
        c = _anomaly(
            actual_cost=_d("6.00"),
            estimated_cost=_d("1.00"),
            variance_percent=_d("500"),
            historical_avg=_d("100.00"),
            sample_count=20,
            absolute_min=_d("100.00"),
            critical_abs=_d("100.00"),
            multiplier=_d("10"),
        )
        assert c is not None
        assert c.severity == SEVERITY_WARNING
