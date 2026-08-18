"""LLM provider factory (PRD Phase 14).

v1 ships a single provider: ``openai`` (httpx). Unknown provider names raise
``ModelNotSupportedError`` so callers get a 422 rather than a provider 502.

The provider (and its pooled httpx client) is created ONCE per process and
cached; tests override ``llm_factory_dep`` so they never touch the cache.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.core.exceptions import ModelNotSupportedError
from app.providers.llm.base import LLMCompletion, LLMProvider
from app.providers.llm.openai_provider import OpenAIProvider

__all__ = ["LLMCompletion", "LLMProvider", "OpenAIProvider", "get_llm_provider"]


@lru_cache(maxsize=1)
def _cached_provider(name: str) -> LLMProvider:
    """Build (and cache) the provider so its httpx client is pooled.

    Settings are read once at first call; a process restart picks up changes.
    """
    if name != "openai":
        raise ModelNotSupportedError(name, model="*")
    s = get_settings()
    return OpenAIProvider(
        api_key=s.openai_api_key,
        base_url=s.openai_base_url,
        timeout_seconds=s.openai_timeout_seconds,
    )


def get_llm_provider(name: str) -> LLMProvider:
    if name != "openai":
        raise ModelNotSupportedError(name, model="*")
    return _cached_provider(name)
