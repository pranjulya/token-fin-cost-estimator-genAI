"""AlertService — evaluate + persist alert candidates (Phase 13).

Orchestrates pure ``domain/alerts.py`` rules and repository I/O. Soft-fail by
contract (K9/K10): every ``maybe_*`` call returns None instead of raising, so an
alert-side failure can never poison the caller's money transaction. The service
holds NO session; all DB work runs in repositories, each isolating its own I/O
behind a savepoint.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.models import Alert, Budget, UsageRecord
from app.domain import alerts as alert_policy
from app.domain.budget import BudgetDecision
from app.repositories.alert_repository import AlertRepository
from app.repositories.usage_repository import UsageRepository

logger = get_logger("app.alerts")


class AlertService:
    def __init__(
        self,
        repository: AlertRepository,
        usage_repository: UsageRepository | None = None,
        settings: Settings | None = None,
    ):
        self._repository = repository
        self._usage_repository = usage_repository
        self._settings = settings or get_settings()

    # --- budget threshold alerts ---------------------------------------------

    async def maybe_budget_threshold(
        self,
        *,
        budget: Budget,
        decision: BudgetDecision,
        period_key: str,
        requested_amount: Decimal,
        request_id: str | None,
    ) -> Alert | None:
        """Emit a budget threshold alert if the decision is non-ALLOW. Never raises."""
        if not self._settings.alerts_enabled:
            return None
        try:
            return await self._emit_budget_threshold(
                budget=budget,
                decision=decision,
                period_key=period_key,
                requested_amount=requested_amount,
                request_id=request_id,
            )
        except Exception:
            logger.error(
                "alert_emit_failed",
                alert_type=alert_policy.BUDGET_THRESHOLD,
                budget_id=budget.id,
                exc_info=True,
            )
            return None

    async def _emit_budget_threshold(
        self,
        *,
        budget: Budget,
        decision: BudgetDecision,
        period_key: str,
        requested_amount: Decimal,
        request_id: str | None,
    ) -> Alert | None:
        candidate = alert_policy.budget_threshold_candidate(
            decision_status=decision.status,
            budget_id=budget.id,
            scope_type=budget.scope_type,
            scope_id=budget.scope_id,
            period_key=period_key,
            period_type=budget.period_type,
            request_id=request_id,
            limit_amount=budget.limit_amount,
            remaining_before=decision.remaining_before,
            remaining_after=decision.remaining_after,
            requested_amount=requested_amount,
            warning_threshold=budget.warning_threshold,
            critical_threshold=budget.critical_threshold,
            enforcement_mode=budget.enforcement_mode,
            currency=budget.currency,
        )
        if candidate is None:
            return None
        return await self._insert_and_log(candidate)

    # --- cost anomaly alerts --------------------------------------------------

    async def maybe_cost_anomaly(self, record: UsageRecord) -> Alert | None:
        """Evaluate + persist a cost anomaly for a newly-created usage row. Never raises."""
        if not self._settings.alerts_enabled:
            return None
        try:
            return await self._emit_cost_anomaly(record)
        except Exception:
            logger.error(
                "alert_emit_failed",
                alert_type=alert_policy.COST_ANOMALY,
                request_id=record.request_id,
                exc_info=True,
            )
            return None

    async def _emit_cost_anomaly(self, record: UsageRecord) -> Alert | None:
        # 1) Baseline (repo-isolated SELECT, excludes this request_id).
        avg, n = await self._usage_repository.historical_avg_cost(
            provider=record.provider,
            model=record.model,
            exclude_request_id=record.request_id,
            limit=self._settings.alert_anomaly_lookback,
        )
        # 2) Pure rules.
        candidate = alert_policy.cost_anomaly_candidate(
            request_id=record.request_id,
            provider=record.provider,
            model=record.model,
            actual_cost=record.actual_cost,
            estimated_cost=record.estimated_cost,
            variance_percent=record.variance_percent,
            historical_avg=avg,
            sample_count=n,
            team_id=record.team_id,
            application_id=record.application_id,
            min_samples=self._settings.alert_anomaly_min_samples,
            multiplier=self._settings.alert_anomaly_multiplier,
            absolute_min=self._settings.alert_anomaly_absolute_min_usd,
            critical_abs=self._settings.alert_anomaly_critical_usd,
            variance_percent_threshold=self._settings.alert_anomaly_variance_percent,
        )
        if candidate is None:
            return None
        # 3) Persist (repo-isolated INSERT, unique-deduped).
        return await self._insert_and_log(candidate)

    # --- shared ----------------------------------------------------------------

    async def _insert_and_log(self, candidate: alert_policy.AlertCandidate) -> Alert | None:
        row = await self._repository.create_if_absent(
            alert_type=candidate.alert_type,
            severity=candidate.severity,
            scope_type=candidate.scope_type,
            scope_id=candidate.scope_id,
            request_id=candidate.request_id,
            message=candidate.message,
            metadata=candidate.metadata,
            dedupe_key=candidate.dedupe_key,
        )
        if row is not None:
            logger.warning(
                "alert_created",
                alert_id=row.id,
                alert_type=row.alert_type,
                severity=row.severity,
                scope_type=row.scope_type,
                scope_id=row.scope_id,
                request_id=row.request_id,
                dedupe_key=row.dedupe_key,
                message=row.message,
            )
        return row

    # --- read/ack (API) --------------------------------------------------------

    async def list_alerts(
        self,
        *,
        alert_type: str | None = None,
        severity: str | None = None,
        scope_type: str | None = None,
        scope_id: str | None = None,
        open_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Alert]:
        return await self._repository.list(
            alert_type=alert_type,
            severity=severity,
            scope_type=scope_type,
            scope_id=scope_id,
            open_only=open_only,
            limit=limit,
            offset=offset,
        )

    async def get(self, alert_id: int) -> Alert | None:
        return await self._repository.get(alert_id)

    async def acknowledge(self, alert: Alert) -> Alert:
        logged = await self._repository.acknowledge(alert)
        logger.info(
            "alert_acknowledged",
            alert_id=logged.id,
            request_id=logged.request_id,
        )
        return logged
