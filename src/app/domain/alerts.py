"""Alert domain — pure rule evaluation (PRD FR-09, UC-07, Phase 13).

No I/O, no FastAPI. Two evaluators return an :class:`AlertCandidate` (or None):
budget threshold crossings and rule-based cost anomalies. All money Decimal.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.domain.budget import BLOCK, CRITICAL, WARN

BUDGET_THRESHOLD = "BUDGET_THRESHOLD"
COST_ANOMALY = "COST_ANOMALY"

SEVERITY_WARNING = "WARNING"
SEVERITY_CRITICAL = "CRITICAL"

REASON_HISTORICAL = "HISTORICAL_MULTIPLIER"
REASON_ABSOLUTE = "ABSOLUTE_FLOOR"
REASON_VARIANCE = "ESTIMATE_VARIANCE"

# Non-ALLOW decision statuses that produce a budget alert.
_ALERT_STATUSES = {WARN, CRITICAL, BLOCK}

# decision status -> severity (BLOCK and CRITICAL share CRITICAL severity).
_SEVERITY_BY_STATUS = {
    WARN: SEVERITY_WARNING,
    CRITICAL: SEVERITY_CRITICAL,
    BLOCK: SEVERITY_CRITICAL,
}


@dataclass(frozen=True)
class AlertCandidate:
    alert_type: str
    severity: str
    scope_type: str | None
    scope_id: str | None
    request_id: str | None
    message: str
    metadata: dict[str, Any]
    dedupe_key: str


def budget_threshold_candidate(
    *,
    decision_status: str,
    budget_id: int,
    scope_type: str,
    scope_id: str,
    period_key: str,
    period_type: str,
    request_id: str | None,
    limit_amount: Decimal,
    remaining_before: Decimal,
    remaining_after: Decimal,
    requested_amount: Decimal,
    warning_threshold: Decimal,
    critical_threshold: Decimal,
    enforcement_mode: str,
    currency: str = "USD",
) -> AlertCandidate | None:
    """Return a candidate when decision_status is WARN|CRITICAL|BLOCK, else None.

    severity: WARNING for WARN; CRITICAL for CRITICAL and BLOCK.
    dedupe_key: ``BUDGET_THRESHOLD:{budget_id}:{period_key}:{decision_status}`` —
    the token is the decision status (WARN|CRITICAL|BLOCK), NOT the severity.
    """
    if decision_status not in _ALERT_STATUSES:
        return None

    dedupe_key = f"{BUDGET_THRESHOLD}:{budget_id}:{period_key}:{decision_status}"
    message = (
        f"Budget {scope_type}/{scope_id} period {period_key} reached "
        f"{decision_status} (limit={limit_amount}, remaining_after={remaining_after})"
    )
    return AlertCandidate(
        alert_type=BUDGET_THRESHOLD,
        severity=_SEVERITY_BY_STATUS[decision_status],
        scope_type=scope_type,
        scope_id=scope_id,
        request_id=request_id,
        message=message,
        metadata={
            "budget_id": budget_id,
            "period_key": period_key,
            "period_type": period_type,
            "decision": decision_status,
            "enforcement_mode": enforcement_mode,
            "limit_amount": str(limit_amount),
            "remaining_before": str(remaining_before),
            "remaining_after": str(remaining_after),
            "requested_amount": str(requested_amount),
            "warning_threshold": str(warning_threshold),
            "critical_threshold": str(critical_threshold),
            "currency": currency,
        },
        dedupe_key=dedupe_key,
    )


def _scope_for(team_id: str | None, application_id: str | None) -> tuple[str | None, str | None]:
    if team_id:
        return "TEAM", team_id
    if application_id:
        return "APPLICATION", application_id
    return None, None


def cost_anomaly_candidate(
    *,
    request_id: str,
    provider: str,
    model: str,
    actual_cost: Decimal,
    estimated_cost: Decimal | None,
    variance_percent: Decimal | None,
    historical_avg: Decimal | None,
    sample_count: int,
    team_id: str | None,
    application_id: str | None,
    min_samples: int,
    multiplier: Decimal,
    absolute_min: Decimal,
    critical_abs: Decimal,
    variance_percent_threshold: Decimal,
    currency: str = "USD",
) -> AlertCandidate | None:
    """Rule-based cost anomaly evaluation (UC-07). Returns None if no rule fires.

    Rules (OR):
      1. absolute floor: actual_cost >= absolute_min
      2. historical multiplier: sample_count >= min_samples and historical_avg > 0
         and actual_cost >= historical_avg * multiplier
      3. estimate variance: estimated_cost > 0 and variance_percent is not None
         and variance_percent >= variance_percent_threshold
    """
    reasons: list[str] = []
    if actual_cost >= absolute_min:
        reasons.append(REASON_ABSOLUTE)
    if (
        sample_count >= min_samples
        and historical_avg is not None
        and historical_avg > Decimal("0")
        and actual_cost >= historical_avg * multiplier
    ):
        reasons.append(REASON_HISTORICAL)
    if (
        estimated_cost is not None
        and estimated_cost > Decimal("0")
        and variance_percent is not None
        and variance_percent >= variance_percent_threshold
    ):
        reasons.append(REASON_VARIANCE)

    if not reasons:
        return None

    scope_type, scope_id = _scope_for(team_id, application_id)

    # Critical when actual >= critical_abs OR >= 10x historical average.
    critical = False
    if actual_cost >= critical_abs:
        critical = True
    elif (
        historical_avg is not None
        and historical_avg > Decimal("0")
        and actual_cost >= historical_avg * Decimal("10")
    ):
        critical = True

    message = (
        f"Cost anomaly for {provider}/{model} request_id={request_id}: "
        f"actual={actual_cost} vs historical_avg={historical_avg or '-'}"
    )
    return AlertCandidate(
        alert_type=COST_ANOMALY,
        severity=SEVERITY_CRITICAL if critical else SEVERITY_WARNING,
        scope_type=scope_type,
        scope_id=scope_id,
        request_id=request_id,
        message=message,
        metadata={
            "provider": provider,
            "model": model,
            "actual_cost": str(actual_cost),
            "estimated_cost": str(estimated_cost) if estimated_cost is not None else None,
            "variance_percent": str(variance_percent) if variance_percent is not None else None,
            "historical_avg": str(historical_avg) if historical_avg is not None else None,
            "sample_count": sample_count,
            "multiplier": str(multiplier),
            "reasons": reasons,
            "currency": currency,
        },
        dedupe_key=f"{COST_ANOMALY}:{request_id}",
    )
