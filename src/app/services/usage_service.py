"""Usage ledger service (PRD Phase 5-6).

Records actual LLM usage reported by the caller, computes the true cost at the
currently-effective pricing, freezes the pricing version, and reconciles the
estimate vs actual. Idempotent on ``request_id`` so retries never double-count
spend (design addition for PRD # 37 Scenario 8).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.db.models import UsageRecord
from app.providers.pricing.base import PricingProvider
from app.repositories.usage_repository import UsageRepository
from app.services.alert_service import AlertService
from app.services.cost_calculator import CostCalculator
from app.services.reconciliation_service import ReconciliationService


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UsageService:
    def __init__(
        self,
        pricing: PricingProvider,
        repository: UsageRepository,
        alerts: AlertService | None = None,
    ):
        self._pricing = pricing
        self._repository = repository
        self._alerts = alerts

    async def record(
        self,
        *,
        request_id: str,
        provider: str,
        model: str,
        actual_input_tokens: int,
        actual_output_tokens: int,
        cached_input_tokens: int = 0,
        correlation_id: str | None = None,
        application_id: str | None = None,
        team_id: str | None = None,
        user_id: str | None = None,
        endpoint: str | None = None,
        environment: str | None = None,
        estimated_input_tokens: int = 0,
        estimated_output_tokens: int = 0,
        estimated_cost: Decimal | None = None,
        status: str = "SUCCESS",
    ) -> UsageRecord:
        # Idempotency: same request_id already recorded → return the existing
        # record unchanged rather than double-counting spend.
        existing = await self._repository.get_by_request_id(request_id)
        if existing is not None:
            return existing

        model_price = await self._pricing.get_pricing(provider, model)
        CostCalculator.validate_price(model_price)

        breakdown = CostCalculator.calculate(
            input_tokens=actual_input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=actual_output_tokens,
            pricing=model_price,
        )
        actual_cost = breakdown.total_cost

        rec = ReconciliationService.reconcile(estimated_cost or Decimal("0"), actual_cost)

        record = UsageRecord(
            request_id=request_id,
            correlation_id=correlation_id,
            provider=provider,
            model=model,
            application_id=application_id,
            team_id=team_id,
            user_id=user_id,
            endpoint=endpoint,
            environment=environment,
            estimated_input_tokens=estimated_input_tokens,
            estimated_output_tokens=estimated_output_tokens,
            estimated_cost=estimated_cost,
            actual_input_tokens=actual_input_tokens,
            cached_input_tokens=cached_input_tokens,
            actual_output_tokens=actual_output_tokens,
            actual_cost=actual_cost,
            variance_amount=rec.variance_amount,
            variance_percent=rec.variance_percent,
            pricing_version=model_price.version,
            status=status,
            completed_at=_utcnow(),
        )
        record = await self._repository.add(record)

        # Fire a cost anomaly alert on newly-created SUCCESS rows (Phase 13).
        # Idempotent retries return early above, so alerts never double-fire.
        if self._alerts is not None and record.status == "SUCCESS":
            await self._alerts.maybe_cost_anomaly(record)
        return record
