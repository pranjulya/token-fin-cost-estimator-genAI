"""Integration tests for Phase 17 rate limiting + input limits."""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.main import app
from app.providers.llm.base import LLMCompletion
from tests.fakes.llm import FakeLLMProvider
from tests.integration.test_estimate_flow import seed_budget, seed_price


@pytest.fixture
def enable_generate():
    from app.api.dependencies import llm_factory_dep as dep

    fake = FakeLLMProvider(
        completion=LLMCompletion(
            text="generated",
            prompt_tokens=10,
            completion_tokens=4,
            cached_prompt_tokens=0,
            model="gpt-4o",
            provider="openai",
        )
    )
    app.dependency_overrides[dep] = lambda: lambda name: fake
    import os

    os.environ["APP_GENERATE_ENABLED"] = "true"
    get_settings.cache_clear()
    yield fake
    os.environ.pop("APP_GENERATE_ENABLED", None)
    get_settings.cache_clear()
    app.dependency_overrides.clear()


class TestInputLimits:
    async def test_estimate_oversized_input_rejected(self, client, db_session):
        await seed_price(db_session)
        resp = await client.post(
            "/v1/cost/estimate",
            json={
                "provider": "openai",
                "model": "gpt-4o",
                "input": "x" * 300_000,  # > default 200k
                "expected_output_tokens": 10,
            },
        )
        assert resp.status_code == 422

    async def test_estimate_output_tokens_over_cap_rejected(self, client, db_session):
        await seed_price(db_session)
        resp = await client.post(
            "/v1/cost/estimate",
            json={
                "provider": "openai",
                "model": "gpt-4o",
                "input": "hi",
                "expected_output_tokens": 2_000_000,  # > default 1M
            },
        )
        assert resp.status_code == 422

    async def test_usage_absurd_tokens_rejected(self, client, db_session):
        await seed_price(db_session)
        resp = await client.post(
            "/v1/usage",
            json={
                "request_id": "req_big",
                "provider": "openai",
                "model": "gpt-4o",
                "actual_input_tokens": 10**18,
                "actual_output_tokens": 10,
            },
        )
        assert resp.status_code == 422


class TestRateLimitAPI:
    async def test_generate_rate_limited(self, client, db_session, enable_generate):
        await seed_price(db_session)
        await seed_budget(db_session)
        # conftest sets generate limit 1000; force a low limit for this test.
        import os

        os.environ["APP_RATE_LIMIT_GENERATE_PER_MINUTE"] = "2"
        get_settings.cache_clear()
        try:
            from app.api.ratelimit import _limiter

            _limiter.cache_clear()
            first = await client.post(
                "/v1/generate",
                json={
                    "provider": "openai",
                    "model": "gpt-4o",
                    "input": "hi",
                    "max_output_tokens": 10,
                    "request_id": "req_rl_1",
                },
            )
            second = await client.post(
                "/v1/generate",
                json={
                    "provider": "openai",
                    "model": "gpt-4o",
                    "input": "hi",
                    "max_output_tokens": 10,
                    "request_id": "req_rl_2",
                },
            )
            third = await client.post(
                "/v1/generate",
                json={
                    "provider": "openai",
                    "model": "gpt-4o",
                    "input": "hi",
                    "max_output_tokens": 10,
                    "request_id": "req_rl_3",
                },
            )
            assert first.status_code == 200
            assert second.status_code == 200
            assert third.status_code == 429
            assert third.json()["error"]["code"] == "RATE_LIMITED"
            assert third.headers.get("Retry-After") is not None
        finally:
            os.environ.pop("APP_RATE_LIMIT_GENERATE_PER_MINUTE", None)
            get_settings.cache_clear()
            _limiter.cache_clear()

    async def test_rate_limit_does_not_block_other_routes(self, client, db_session):
        # After exhausting default route for a key, a different route still works.
        import os

        from app.api.ratelimit import _limiter

        os.environ["APP_RATE_LIMIT_PER_MINUTE"] = "1"
        get_settings.cache_clear()
        _limiter.cache_clear()
        try:
            await seed_price(db_session)
            first = await client.post(
                "/v1/usage",
                json={
                    "request_id": "req_rr_1",
                    "provider": "openai",
                    "model": "gpt-4o",
                    "actual_input_tokens": 10,
                    "actual_output_tokens": 10,
                },
            )
            second = await client.post(
                "/v1/usage",
                json={
                    "request_id": "req_rr_2",
                    "provider": "openai",
                    "model": "gpt-4o",
                    "actual_input_tokens": 10,
                    "actual_output_tokens": 10,
                },
            )
            assert first.status_code == 201
            assert second.status_code == 429
        finally:
            os.environ.pop("APP_RATE_LIMIT_PER_MINUTE", None)
            get_settings.cache_clear()
            _limiter.cache_clear()
