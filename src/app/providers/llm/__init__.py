"""LLM provider factory (PRD Phase 14).

v1 ships a single provider: ``openai`` (httpx). Unknown provider names raise
``ModelNotSupportedError`` so callers get a 422 rather than a provider 502.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.exceptions import ModelNotSupportedError
from app.providers.llm.base import LLMCompletion, LLMProvider
from app.providers.llm.openai_provider import OpenAIProvider

__all__ = ["LLMCompletion", "LLMProvider", "OpenAIProvider", "get_llm_provider"]


def get_llm_provider(name: str) -> LLMProvider:
    if name != "openai":
        raise ModelNotSupportedError(name, model="*")
    s = get_settings()
    return OpenAIProvider(
        api_key=s.openai_api_key,
        base_url=s.openai_base_url,
        timeout_seconds=s.openai_timeout_seconds,
    )
