"""FastAPI dependency factories — build services from a per-request DB session.

Routes stay thin: they parse/validate and hand off to services. Each service
gets a fresh repository bound to this request's session.
"""

from __future__ import annotations

import uuid

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.providers.pricing.database_pricing import DatabasePricingProvider
from app.repositories.pricing_repository import PricingRepository
from app.repositories.usage_repository import UsageRepository
from app.services.aggregation_service import AggregationService
from app.services.cost_estimator import CostEstimator
from app.services.usage_service import UsageService


def _pricing_provider(session: AsyncSession) -> DatabasePricingProvider:
    return DatabasePricingProvider(PricingRepository(session))


async def estimator_dep(session: AsyncSession = Depends(get_db_session)) -> CostEstimator:
    from app.providers.tokenizers.openai_tokenizer import get_token_counter

    return CostEstimator(
        token_counter=get_token_counter("openai"),
        pricing=_pricing_provider(session),
    )


async def usage_service_dep(session: AsyncSession = Depends(get_db_session)) -> UsageService:
    return UsageService(pricing=_pricing_provider(session), repository=UsageRepository(session))


async def aggregation_dep(session: AsyncSession = Depends(get_db_session)) -> AggregationService:
    return AggregationService(UsageRepository(session))


async def pricing_repo_dep(session: AsyncSession = Depends(get_db_session)) -> PricingRepository:
    return PricingRepository(session)


async def usage_repo_dep(session: AsyncSession = Depends(get_db_session)) -> UsageRepository:
    return UsageRepository(session)


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:24]}"
