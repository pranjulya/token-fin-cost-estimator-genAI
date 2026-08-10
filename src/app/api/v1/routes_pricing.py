"""Pricing admin routes (PRD Phase 1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import pricing_repo_dep
from app.repositories.pricing_repository import PricingRepository
from app.schemas.pricing import PricingCreate, PricingOut

router = APIRouter(prefix="/models/pricing", tags=["pricing"])


@router.post("", response_model=PricingOut, status_code=201)
async def create_pricing(
    body: PricingCreate, repo: PricingRepository = Depends(pricing_repo_dep)
) -> PricingOut:
    row = await repo.create(
        provider=body.provider,
        model=body.model,
        input_per_million=body.input_price_per_million,
        output_per_million=body.output_price_per_million,
        currency=body.currency,
        cached_input_per_million=body.cached_input_price_per_million,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
    )
    return PricingOut.model_validate(row)


@router.get("", response_model=list[PricingOut])
async def list_pricing(repo: PricingRepository = Depends(pricing_repo_dep)) -> list[PricingOut]:
    rows = await repo.list_all()
    return [PricingOut.model_validate(r) for r in rows]
