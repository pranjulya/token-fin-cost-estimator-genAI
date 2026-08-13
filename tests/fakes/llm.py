"""Fake LLM provider for tests (no network, no SDK)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.providers.llm.base import LLMCompletion


@dataclass
class FakeLLMProvider:
    completion: LLMCompletion | None = None
    error: Exception | None = None
    calls: list[dict] = field(default_factory=list)

    async def complete(self, **kwargs) -> LLMCompletion:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.completion or LLMCompletion(
            text="ok",
            prompt_tokens=10,
            completion_tokens=5,
            cached_prompt_tokens=0,
            model=kwargs["model"],
            provider="openai",
        )
