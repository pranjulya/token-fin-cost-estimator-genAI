"""POST /v1/cost/estimate — tokenize, price, and estimate cost (PRD §22 / §29)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import estimator_dep, new_request_id
from app.schemas.cost import BudgetEnvelope, EstimateRequest, EstimateResponse
from app.services.cost_estimator import CostEstimator

router = APIRouter(prefix="/cost", tags=["cost"])


@router.post("/estimate", response_model=EstimateResponse)
async def estimate_cost(
    body: EstimateRequest, estimator: CostEstimator = Depends(estimator_dep)
) -> EstimateResponse:
    estimation = await estimator.estimate(
        provider=body.provider,
        model=body.model,
        input_text=body.input,
        expected_output_tokens=body.expected_output_tokens,
    )
    b = estimation.breakdown
    return EstimateResponse(
        request_id=new_request_id(),
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
        budget=BudgetEnvelope(),
    )
