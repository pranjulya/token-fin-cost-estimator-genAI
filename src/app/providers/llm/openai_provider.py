"""OpenAI Chat Completions provider over httpx (PRD Phase 14).

Deliberately does NOT use the ``openai`` SDK: v1 keeps the provider dependency
to a single HTTP client. If the deployed service later needs SDK features, swap
the body of ``complete()`` to the official SDK — the ``LLMProvider`` Protocol,
factory, and all callers stay unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from app.core.exceptions import ProviderError
from app.providers.llm.base import LLMCompletion

# Chat Completions endpoint relative to the base URL.
_CHAT_COMPLETIONS_PATH = "/chat/completions"

# Injectable client factory for tests (no wire in CI).
ClientFactory = Callable[[], httpx.AsyncClient]


def _default_client_factory(timeout_seconds: float) -> ClientFactory:
    def _build() -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout_seconds)

    return _build


class OpenAIProvider:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None,
        timeout_seconds: float,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client_factory = client_factory or _default_client_factory(timeout_seconds)

    async def complete(
        self,
        *,
        model: str,
        prompt: str,
        max_output_tokens: int,
        request_id: str,
    ) -> LLMCompletion:
        if not self._api_key:
            raise ProviderError(
                "OpenAI API key is not configured (APP_OPENAI_API_KEY).",
                request_id=request_id,
            )

        url = f"{self._base_url}{_CHAT_COMPLETIONS_PATH}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_output_tokens,
        }

        try:
            async with self._client_factory() as client:
                resp = await client.post(url, headers=headers, json=payload)
        except Exception as exc:
            # Never include prompt text in the error message (K12).
            raise ProviderError(f"OpenAI request failed: {exc}", request_id=request_id) from exc

        if resp.status_code != 200:
            body = (resp.text or "")[:500]
            raise ProviderError(
                f"OpenAI request failed: HTTP {resp.status_code} {body}".strip(),
                request_id=request_id,
            )

        try:
            data = resp.json()
            choice = (data.get("choices") or [None])[0]
            text = ((choice or {}).get("message") or {}).get("content") or ""
            usage = data.get("usage")
            if usage is None:
                raise ProviderError(
                    "OpenAI response omitted usage; cannot price actuals.",
                    request_id=request_id,
                )
            details = usage.get("prompt_tokens_details") or {}
            cached = int(details.get("cached_tokens") or 0) if details else 0
            return LLMCompletion(
                text=text,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                cached_prompt_tokens=cached,
                model=data.get("model") or model,
                provider="openai",
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                f"OpenAI response could not be parsed: {exc}", request_id=request_id
            ) from exc
