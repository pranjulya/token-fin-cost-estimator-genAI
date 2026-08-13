"""POST /v1/generate — end-to-end generation flow (PRD Phase 15)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import generation_service_dep
from app.schemas.generate import GenerateRequest, GenerateResponse
from app.services.generation_service import GenerationService

router = APIRouter(tags=["generate"])


@router.post("/generate", response_model=GenerateResponse)
async def generate(
    body: GenerateRequest,
    service: GenerationService = Depends(generation_service_dep),
) -> GenerateResponse:
    result = await service.generate(
        provider=body.provider,
        model=body.model,
        input_text=body.input,
        max_output_tokens=body.max_output_tokens,
        application_id=body.application_id,
        team_id=body.team_id,
        user_id=body.user_id,
        endpoint=body.endpoint,
        request_id=body.request_id,
        correlation_id=body.correlation_id,
    )
    return GenerateResponse.from_result(result)
