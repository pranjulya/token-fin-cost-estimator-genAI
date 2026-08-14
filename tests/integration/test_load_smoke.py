"""Load smoke tests (PRD Phase 18).

Not a benchmark — a quick check that N concurrent generate requests complete
correctly and write N usage rows, so CI stays fast.
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models import UsageRecord
from tests.conftest import session_factory
from tests.integration.test_estimate_flow import seed_budget, seed_price


class TestLoadSmoke:
    async def test_concurrent_generate_requests(self):
        import httpx

        from app.api.dependencies import llm_factory_dep
        from app.main import app
        from app.providers.llm.base import LLMCompletion
        from tests.fakes.llm import FakeLLMProvider

        fake = FakeLLMProvider(
            completion=LLMCompletion(
                text="ok",
                prompt_tokens=10,
                completion_tokens=4,
                cached_prompt_tokens=0,
                model="gpt-4o",
                provider="openai",
            )
        )
        app.dependency_overrides[llm_factory_dep] = lambda: lambda name: fake
        os.environ["APP_GENERATE_ENABLED"] = "true"
        get_settings.cache_clear()

        async with session_factory() as session:
            await seed_price(session)
            await seed_budget(session)
            await session.commit()

        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
                headers={"X-API-Key": "test-user-key"},
            ) as client:
                requests = [
                    client.post(
                        "/v1/generate",
                        json={
                            "provider": "openai",
                            "model": "gpt-4o",
                            "input": f"prompt {i}",
                            "max_output_tokens": 10,
                            "request_id": f"req_load_{i}",
                            "team_id": "platform-team",
                        },
                    )
                    for i in range(20)
                ]
                responses = await asyncio.gather(*requests)
        finally:
            os.environ.pop("APP_GENERATE_ENABLED", None)
            get_settings.cache_clear()
            app.dependency_overrides.clear()

        assert all(r.status_code == 200 for r in responses)

        async with session_factory() as session:
            n = await session.scalar(select(func.count()).select_from(UsageRecord))
            assert n == 20
