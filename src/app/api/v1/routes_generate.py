"""POST /v1/generate — end-to-end generation flow (PRD Phase 15)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header

from app.api.dependencies import generation_service_dep
from app.api.ratelimit import rate_limit_dep
from app.schemas.generate import GenerateRequest, GenerateResponse
from app.services.generation_service import GenerationService

router = APIRouter(tags=["generate"])


@router.post(
    "/generate",
    response_model=GenerateResponse,
    dependencies=[Depends(rate_limit_dep("generate"))],
)
async def generate(
    body: GenerateRequest,
    service: GenerationService = Depends(generation_service_dep),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> GenerateResponse:
    # Idempotency-Key header (P2) takes precedence over the body request_id so
    # clients can retry reserve->settle atomically. Same key while in-flight or
    # completed -> 409, never a double reserve or double provider call.
    request_id = idempotency_key or body.request_id
    result = await service.generate(
        provider=body.provider,
        model=body.model,
        input_text=body.input,
        max_output_tokens=body.max_output_tokens,
        application_id=body.application_id,
        team_id=body.team_id,
        user_id=body.user_id,
        endpoint=body.endpoint,
        request_id=request_id,
        correlation_id=body.correlation_id,
    )
    return GenerateResponse.from_result(result)
