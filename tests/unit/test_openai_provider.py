"""Unit tests for the httpx-based OpenAI provider (PRD Phase 14).

No live network: the OpenAI Chat Completions HTTP call is exercised through a
mocked ``httpx.AsyncClient`` (injected via the ``httpx_client_factory``
constructor hook) so tests never touch the wire.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ModelNotSupportedError, ProviderError
from app.providers.llm import get_llm_provider
from app.providers.llm.openai_provider import OpenAIProvider


def _usage(*, prompt=12, completion=4, cached=None):
    details = None
    if cached is not None:
        details = SimpleNamespace(cached_tokens=cached)
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        prompt_tokens_details=details,
    )


def _json_usage(*, prompt=12, completion=4, cached=None):
    usage = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
    }
    if cached is not None:
        usage["prompt_tokens_details"] = {"cached_tokens": cached}
    return usage


def _resp_json(*, usage=None, text="hello", model="gpt-4o"):
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
        "usage": usage,
    }


@pytest.fixture
def provider():
    return OpenAIProvider(api_key="sk-test", base_url=None, timeout_seconds=5)


@pytest.fixture
def mock_client():
    client = AsyncMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _resp_json(usage=_json_usage(prompt=12, completion=4, cached=3))
    client.post.return_value = resp
    cm = AsyncMock()
    cm.__aenter__.return_value = client
    cm.__aexit__.return_value = False
    with patch("app.providers.llm.openai_provider.httpx.AsyncClient", return_value=cm) as ctor:
        yield client, cm, ctor


def _set_json(client, payload):
    # httpx Response.json() is sync; use a plain callable instead of AsyncMock.
    client.post.return_value.json.return_value = payload


async def test_maps_usage_and_cached(provider, mock_client):
    client, cm, ctor = mock_client
    out = await provider.complete(
        model="gpt-4o", prompt="hi", max_output_tokens=20, request_id="req_1"
    )
    assert out.prompt_tokens == 12
    assert out.completion_tokens == 4
    assert out.cached_prompt_tokens == 3
    assert out.text == "hello"
    assert out.provider == "openai"
    ctor.assert_called_once()
    client.post.assert_awaited_once()
    url, kwargs = client.post.await_args.args[0], client.post.await_args.kwargs
    assert url.endswith("/chat/completions")
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
    assert kwargs["json"]["max_tokens"] == 20
    assert kwargs["json"]["messages"] == [{"role": "user", "content": "hi"}]
    cm.__aenter__.assert_awaited()
    cm.__aexit__.assert_awaited()


async def test_missing_details_cached_zero(provider, mock_client):
    client, _, _ = mock_client
    _set_json(client, _resp_json(usage=_json_usage(prompt=12, completion=4)))
    out = await provider.complete(
        model="gpt-4o", prompt="hi", max_output_tokens=1, request_id="req_1"
    )
    assert out.cached_prompt_tokens == 0


async def test_missing_usage_is_provider_error(provider, mock_client):
    client, _, _ = mock_client
    _set_json(client, _resp_json(usage=None))
    with pytest.raises(ProviderError) as ei:
        await provider.complete(
            model="gpt-4o", prompt="hi", max_output_tokens=1, request_id="req_1"
        )
    assert ei.value.status_code == 502
    assert "usage" in ei.value.message


async def test_non_2xx_is_provider_error(provider, mock_client):
    client, _, _ = mock_client
    resp = AsyncMock()
    resp.status_code = 401
    resp.text = "unauthorized"
    client.post.return_value = resp
    with pytest.raises(ProviderError) as ei:
        await provider.complete(
            model="gpt-4o", prompt="hi", max_output_tokens=1, request_id="req_1"
        )
    assert ei.value.status_code == 502
    assert "401" in ei.value.message
    assert "unauthorized" in ei.value.message


async def test_timeout_is_provider_error(provider, mock_client):
    client, _, _ = mock_client
    client.post.side_effect = TimeoutError("connect timed out")
    with pytest.raises(ProviderError) as ei:
        await provider.complete(
            model="gpt-4o", prompt="hi", max_output_tokens=1, request_id="req_1"
        )
    assert ei.value.status_code == 502


async def test_missing_api_key_does_not_construct_client():
    p = OpenAIProvider(api_key=None, base_url=None, timeout_seconds=5)
    with patch("app.providers.llm.openai_provider.httpx.AsyncClient") as ctor:
        with pytest.raises(ProviderError) as ei:
            await p.complete(model="gpt-4o", prompt="hi", max_output_tokens=1, request_id="req_1")
    ctor.assert_not_called()
    assert "APP_OPENAI_API_KEY" in ei.value.message


async def test_prompt_not_in_error_message(provider, mock_client):
    client, _, _ = mock_client
    client.post.side_effect = RuntimeError("boom")
    with pytest.raises(ProviderError) as ei:
        await provider.complete(
            model="gpt-4o",
            prompt="super-secret-prompt",
            max_output_tokens=1,
            request_id="req_1",
        )
    assert "super-secret-prompt" not in ei.value.message


def test_factory_unknown_provider():
    with pytest.raises(ModelNotSupportedError):
        get_llm_provider("anthropic")


def test_factory_openai_does_not_require_key():
    p = get_llm_provider("openai")
    assert isinstance(p, OpenAIProvider)
