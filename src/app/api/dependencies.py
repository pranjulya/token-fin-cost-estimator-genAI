"""FastAPI dependency factories — build services from a per-request DB session.

Routes stay thin: they parse/validate and hand off to services. Each service
gets a fresh repository bound to this request's session.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db_session
from app.providers.llm import get_llm_provider
from app.providers.llm.base import LLMProvider
from app.providers.pricing.database_pricing import DatabasePricingProvider
from app.repositories.alert_repository import AlertRepository
from app.repositories.budget_repository import BudgetRepository
from app.repositories.pricing_repository import PricingRepository
from app.repositories.usage_repository import UsageRepository
from app.services.aggregation_service import AggregationService
from app.services.alert_service import AlertService
from app.services.budget_service import BudgetService
from app.services.cost_estimator import CostEstimator
from app.services.generation_service import GenerationService
from app.services.usage_service import UsageService

LLMFactory = Callable[[str], LLMProvider]


def _alert_service(session: AsyncSession) -> AlertService:
    return AlertService(
        repository=AlertRepository(session),
        usage_repository=UsageRepository(session),
        settings=get_settings(),
    )


def _pricing_provider(session: AsyncSession) -> DatabasePricingProvider:
    return DatabasePricingProvider(PricingRepository(session))


async def estimator_dep(session: AsyncSession = Depends(get_db_session)) -> CostEstimator:
    from app.providers.tokenizers.openai_tokenizer import get_token_counter

    return CostEstimator(
        token_counter=get_token_counter("openai"),
        pricing=_pricing_provider(session),
    )


async def usage_service_dep(session: AsyncSession = Depends(get_db_session)) -> UsageService:
    return UsageService(
        pricing=_pricing_provider(session),
        repository=UsageRepository(session),
        alerts=_alert_service(session),
    )


async def aggregation_dep(session: AsyncSession = Depends(get_db_session)) -> AggregationService:
    return AggregationService(UsageRepository(session))


async def alert_service_dep(session: AsyncSession = Depends(get_db_session)) -> AlertService:
    return _alert_service(session)


async def budget_service_dep(
    session: AsyncSession = Depends(get_db_session),
) -> BudgetService:
    return BudgetService(BudgetRepository(session), alerts=_alert_service(session))


async def budget_repo_dep(session: AsyncSession = Depends(get_db_session)) -> BudgetRepository:
    return BudgetRepository(session)


async def pricing_repo_dep(session: AsyncSession = Depends(get_db_session)) -> PricingRepository:
    return PricingRepository(session)


async def usage_repo_dep(session: AsyncSession = Depends(get_db_session)) -> UsageRepository:
    return UsageRepository(session)


def llm_factory_dep() -> LLMFactory:
    return get_llm_provider


async def generation_service_dep(
    session: AsyncSession = Depends(get_db_session),
    estimator: CostEstimator = Depends(estimator_dep),
    budget_service: BudgetService = Depends(budget_service_dep),
    usage_service: UsageService = Depends(usage_service_dep),
    get_llm: LLMFactory = Depends(llm_factory_dep),
) -> GenerationService:
    settings = get_settings()
    return GenerationService(
        estimator=estimator,
        budget_service=budget_service,
        usage_service=usage_service,
        usage_repository=UsageRepository(session),
        get_llm=get_llm,
        session_commit=session.commit,
        generate_enabled=settings.generate_enabled,
        environment=settings.environment,
    )


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:24]}"
