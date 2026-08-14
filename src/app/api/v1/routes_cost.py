"""POST /v1/cost/estimate — tokenize, price, estimate cost + budget preflight (PRD §22 / §29)."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends

from app.api.dependencies import budget_service_dep, estimator_dep, new_request_id
from app.api.ratelimit import rate_limit_dep
from app.schemas.cost import BudgetEnvelope, EstimateRequest, EstimateResponse
from app.services.budget_service import BudgetService
from app.services.cost_estimator import CostEstimator

router = APIRouter(prefix="/cost", tags=["cost"])


@router.post(
    "/estimate",
    response_model=EstimateResponse,
    dependencies=[Depends(rate_limit_dep("default"))],
)
async def estimate_cost(
    body: EstimateRequest,
    estimator: CostEstimator = Depends(estimator_dep),
    budget_service: BudgetService = Depends(budget_service_dep),
) -> EstimateResponse:
    estimation = await estimator.estimate(
        provider=body.provider,
        model=body.model,
        input_text=body.input,
        expected_output_tokens=body.expected_output_tokens,
    )
    b = estimation.breakdown
    requested = new_request_id()

    # Budget preflight (PRD # 27): evaluate the applicable budget without
    # reserving (Phase 14/15: estimate is evaluate-only; generate reserves).
    # No budget configured -> ENABLED stub.
    envelope = BudgetEnvelope()
    budget = await budget_service.find_applicable(
        team_id=body.team_id, application_id=body.application_id
    )
    if budget is not None:
        decision = await budget_service.evaluate(budget, b.total_cost)
        # Clamp negative remainings (over-limit) to 0: Money must be non-negative.
        envelope = BudgetEnvelope(
            status=decision.status,
            remaining_before_request=max(decision.remaining_before, Decimal("0")),
            remaining_after_estimate=max(decision.remaining_after, Decimal("0")),
        )

    return EstimateResponse(
        request_id=requested,
        provider=body.provider,
        model=body.model,
        estimated_input_tokens=estimation.input_tokens,
        estimated_output_tokens=estimation.output_tokens,
        estimated_input_cost=b.input_cost,
        estimated_cached_input_cost=b.cached_input_cost,
        estimated_output_cost=b.output_cost,
        estimated_total_cost=b.total_cost,
        currency=b.currency,
        pricing_version=estimation.pricing.version,
        budget=envelope,
    )
