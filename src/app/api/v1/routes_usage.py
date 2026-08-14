"""Usage ledger + aggregation routes (PRD Phases 5-7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import aggregation_dep, usage_repo_dep, usage_service_dep
from app.api.ratelimit import rate_limit_dep
from app.repositories.usage_repository import UsageRepository
from app.schemas.usage import CostByDimension, UsageCreate, UsageOut, UsageSummary
from app.services.aggregation_service import AggregationService
from app.services.usage_service import UsageService

router = APIRouter(tags=["usage"])


@router.post(
    "/usage",
    response_model=UsageOut,
    status_code=201,
    dependencies=[Depends(rate_limit_dep("default"))],
)
async def create_usage(
    body: UsageCreate, service: UsageService = Depends(usage_service_dep)
) -> UsageOut:
    return await service.record(
        request_id=body.request_id,
        correlation_id=body.correlation_id,
        provider=body.provider,
        model=body.model,
        application_id=body.application_id,
        team_id=body.team_id,
        user_id=body.user_id,
        endpoint=body.endpoint,
        environment=body.environment,
        estimated_input_tokens=body.estimated_input_tokens,
        estimated_output_tokens=body.estimated_output_tokens,
        estimated_cost=body.estimated_cost,
        actual_input_tokens=body.actual_input_tokens,
        cached_input_tokens=body.cached_input_tokens,
        actual_output_tokens=body.actual_output_tokens,
        status=body.status,
    )


@router.get("/usage", response_model=list[UsageOut])
async def list_usage(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    repo: UsageRepository = Depends(usage_repo_dep),
) -> list[UsageOut]:
    return await repo.list_records(limit=limit, offset=offset)


@router.get("/usage/summary", response_model=UsageSummary)
async def usage_summary(agg: AggregationService = Depends(aggregation_dep)) -> UsageSummary:
    return UsageSummary(**await agg.summary())


@router.get("/cost/by-model", response_model=list[CostByDimension])
async def cost_by_model(
    agg: AggregationService = Depends(aggregation_dep),
) -> list[CostByDimension]:
    return [CostByDimension(**row) for row in await agg.by_model()]


@router.get("/cost/by-endpoint", response_model=list[CostByDimension])
async def cost_by_endpoint(
    agg: AggregationService = Depends(aggregation_dep),
) -> list[CostByDimension]:
    return [CostByDimension(**row) for row in await agg.by_endpoint()]


@router.get("/cost/by-team", response_model=list[CostByDimension])
async def cost_by_team(agg: AggregationService = Depends(aggregation_dep)) -> list[CostByDimension]:
    return [CostByDimension(**row) for row in await agg.by_team()]
