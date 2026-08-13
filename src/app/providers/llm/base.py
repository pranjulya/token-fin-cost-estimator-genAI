"""LLMProvider abstraction (PRD Phase 14).

Business logic depends on this interface, never on a concrete vendor SDK.
Mirrors the duck-typed Protocol style of ``providers/tokenizers/base.py`` and
``providers/pricing/base.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMCompletion:
    text: str
    prompt_tokens: int
    completion_tokens: int
    cached_prompt_tokens: int  # 0 if provider omitted
    model: str
    provider: str


class LLMProvider(Protocol):
    """Call an LLM and return token usage. Raises ProviderError on failure."""

    async def complete(
        self,
        *,
        model: str,
        prompt: str,
        max_output_tokens: int,
        request_id: str,
    ) -> LLMCompletion: ...
