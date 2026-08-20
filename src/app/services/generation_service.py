"""GenerationService — orchestrate the end-to-end FinOps loop (PRD Phase 15).

``POST /v1/generate`` owns the full money lifecycle:

    estimate -> budget reserve -> mid-commit -> LLM call -> record_new -> settle

The service never holds an ``AsyncSession`` (K14); repositories stay on the
child services and an explicit ``session_commit`` callback is injected so the
reservation (or BLOCK decision / release) becomes durable and ``FOR UPDATE`` is
released before the provider HTTP call (K3).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from app.core.exceptions import (
    AppError,
    BudgetExceededError,
    GenerationAlreadyRecordedError,
    GenerationDisabledError,
    ModelNotSupportedError,
    ProviderError,
)
from app.core.logging import get_logger
from app.core.metrics import metrics, span
from app.domain.budget import BudgetDecision
from app.providers.llm.base import LLMProvider
from app.services.cost_estimator import CostEstimator, Estimation
from app.services.usage_service import UsageService

if TYPE_CHECKING:
    from app.db.models import UsageRecord
    from app.repositories.usage_repository import UsageRepository
    from app.services.budget_service import BudgetService

logger = get_logger("app.generate")


@dataclass(frozen=True)
class GenerationResult:
    request_id: str
    provider: str
    model: str
    output: str
    estimation: Estimation
    usage: UsageRecord
    budget_decision: BudgetDecision | None  # None -> ENABLED stub envelope


class GenerationService:
    def __init__(
        self,
        *,
        estimator: CostEstimator,
        budget_service: BudgetService,
        usage_service: UsageService,
        usage_repository: UsageRepository,
        get_llm: Callable[[str], LLMProvider],
        session_commit: Callable[[], Awaitable[None]],
        generate_enabled: bool,
        environment: str,
    ) -> None:
        self._estimator = estimator
        self._budget_service = budget_service
        self._usage_service = usage_service
        self._usage_repository = usage_repository
        self._get_llm = get_llm
        self._session_commit = session_commit
        self._generate_enabled = generate_enabled
        self._environment = environment

    async def generate(
        self,
        *,
        provider: str,
        model: str,
        input_text: str,
        max_output_tokens: int,
        application_id: str | None,
        team_id: str | None,
        user_id: str | None,
        endpoint: str | None,
        request_id: str | None,
        correlation_id: str | None,
    ) -> GenerationResult:
        if not self._generate_enabled:
            raise GenerationDisabledError("Generation is disabled (APP_GENERATE_ENABLED=false).")

        rid = request_id or f"req_{uuid.uuid4().hex[:24]}"
        ep = endpoint or "/v1/generate"

        existing = await self._usage_repository.get_by_request_id(rid)
        if existing is not None:
            logger.info("generate_duplicate", request_id=rid)
            raise GenerationAlreadyRecordedError(rid)

        estimation = await self._estimator.estimate(
            provider=provider,
            model=model,
            input_text=input_text,
            expected_output_tokens=max_output_tokens,
        )
        E = estimation.total_cost

        budget = await self._budget_service.find_applicable(
            team_id=team_id, application_id=application_id
        )
        decision = None
        reserved = False
        if budget is not None:
            decision = await self._budget_service.reserve(budget, E, request_id=rid)
            await self._session_commit()  # UoW1: RESERVE or DECISION (+ alerts) durable
            if not decision.allowed:
                logger.info(
                    "generate_blocked",
                    request_id=rid,
                    status=decision.status,
                    estimated_cost=str(E),
                )
                metrics.record_budget_rejection(
                    provider=provider, model=model, reason=decision.status
                )
                raise BudgetExceededError(
                    f"Budget exceeded for request_id='{rid}': status=BLOCK "
                    f"remaining_before={decision.remaining_before} "
                    f"remaining_after={decision.remaining_after}.",
                    request_id=rid,
                )
            reserved = True
            logger.info(
                "generate_reserved",
                request_id=rid,
                status=decision.status,
                estimated_cost=str(E),
            )

        # Budget is the product gate: rule out BLOCK before touching the provider.
        if provider != "openai":
            if reserved and budget is not None:
                await self._budget_service.release(budget, E, request_id=rid)
                await self._session_commit()
            raise ModelNotSupportedError(provider, model, request_id=rid)

        try:
            llm = self._get_llm(provider)
            with span("llm_provider"):
                completion = await llm.complete(
                    model=model,
                    prompt=input_text,
                    max_output_tokens=max_output_tokens,
                    request_id=rid,
                )
        except AppError:
            if reserved and budget is not None:
                await self._budget_service.release(budget, E, request_id=rid)
                await self._session_commit()
            raise
        except Exception as exc:
            if reserved and budget is not None:
                await self._budget_service.release(budget, E, request_id=rid)
                await self._session_commit()
            raise ProviderError(f"Provider call failed: {exc}", request_id=rid) from exc

        logger.info(
            "generate_provider_ok",
            request_id=rid,
            prompt_tokens=completion.prompt_tokens,
            cached_prompt_tokens=completion.cached_prompt_tokens,
            completion_tokens=completion.completion_tokens,
        )

        # Billing split: OpenAI reports prompt_tokens INCLUDING cached tokens.
        cached = completion.cached_prompt_tokens
        uncached = max(completion.prompt_tokens - cached, 0)

        try:
            record = await self._usage_service.record_new(
                request_id=rid,
                correlation_id=correlation_id,
                provider=completion.provider,
                model=completion.model,
                application_id=application_id,
                team_id=team_id,
                user_id=user_id,
                endpoint=ep,
                environment=self._environment,
                estimated_input_tokens=estimation.input_tokens,
                estimated_output_tokens=estimation.output_tokens,
                estimated_cost=E,
                actual_input_tokens=uncached,
                cached_input_tokens=cached,
                actual_output_tokens=completion.completion_tokens,
                status="SUCCESS",
            )
        except GenerationAlreadyRecordedError:
            if reserved and budget is not None:
                await self._budget_service.release(budget, E, request_id=rid)
                await self._session_commit()
            raise

        A = record.actual_cost or Decimal("0")

        if reserved and budget is not None:
            await self._budget_service.settle(
                budget, reserved_amount=E, actual_amount=A, request_id=rid
            )
            logger.info(
                "generate_settled",
                request_id=rid,
                estimated_cost=str(E),
                actual_cost=str(A),
                leftover=str(max(E - A, Decimal("0"))),
            )

        return GenerationResult(
            request_id=rid,
            provider=completion.provider,
            model=completion.model,
            output=completion.text,
            estimation=estimation,
            usage=record,
            budget_decision=decision,
        )
