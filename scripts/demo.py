"""Phase 22 portfolio demo — Team budget = $10 walkthrough.

Runs the three PRD demo beats against the live app via an in-process ASGI
client (no network, no OpenAI key):

  1. Normal request  -> estimate ALLOW -> usage tracked.
  2. Large request   -> budget insufficient -> 403 BEFORE the provider call.
  3. Multiple reqs   -> usage aggregated -> threshold crossed -> alert created.

Usage:
    uv run python scripts/demo.py
"""

from __future__ import annotations

import asyncio
import os
from datetime import date
from decimal import Decimal

from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings


def _isolate_database() -> str:
    """Point the demo at a throwaway ``*_demo`` database and return its name.

    The demo drops every table before it runs. To make sure that can never
    touch real data, it never uses the configured database directly: it
    switches to ``<name>_demo`` (created on demand). A database that already
    ends in ``_demo`` or ``_test`` is used as is.
    """
    url = make_url(get_settings().database_url)
    name = url.database or "token_cost_estimator"
    if not name.endswith(("_demo", "_test")):
        name = f"{name}_demo"
    demo_url = url.set(database=name)
    admin = create_engine(
        demo_url.set(database="postgres"), isolation_level="AUTOCOMMIT", future=True
    )
    with admin.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name})
        if exists.scalar() is None:
            conn.execute(text(f'CREATE DATABASE "{name}"'))  # noqa: S608 (identifier, not input)
    admin.dispose()
    os.environ["APP_DATABASE_URL"] = demo_url.render_as_string(hide_password=False)
    get_settings.cache_clear()
    return name


_DEMO_DB = _isolate_database()

from app.api.dependencies import llm_factory_dep  # noqa: E402
from app.db import models  # noqa: E402, F401  (register tables)
from app.db.base import Base  # noqa: E402
from app.db.session import AsyncSessionLocal, async_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.providers.llm.base import LLMCompletion  # noqa: E402
from app.repositories.budget_repository import BudgetRepository  # noqa: E402
from app.repositories.pricing_repository import PricingRepository  # noqa: E402

USER_KEY = "demo-user-key"
ADMIN_KEY = "demo-admin-key"


class _FakeLLM:
    """Deterministic stand-in for the LLM (no network, no cost)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def complete(self, **kwargs) -> LLMCompletion:
        self.calls.append(kwargs)
        return LLMCompletion(
            text="demo completion",
            prompt_tokens=15,
            completion_tokens=30,
            cached_prompt_tokens=0,
            model=kwargs["model"],
            provider="openai",
        )


def _env(key: str) -> str:
    return os.environ.get(key, "")


async def _seed() -> None:
    """Create pricing + a $10 STRICT TEAM budget if missing (idempotent)."""
    async with AsyncSessionLocal() as session:
        if await session.scalar(models.ModelPricing.__table__.select().limit(1)) is None:
            await PricingRepository(session).create(
                provider="openai",
                model="gpt-4o",
                input_per_million=Decimal("2.50"),
                output_per_million=Decimal("10.00"),
                cached_input_per_million=Decimal("1.25"),
                effective_from=date.today(),
            )
        existing = await session.scalar(
            models.Budget.__table__.select().where(
                models.Budget.scope_type == "TEAM",
                models.Budget.scope_id == "platform-team",
            )
        )
        if existing is None:
            await BudgetRepository(session).create(
                scope_type="TEAM",
                scope_id="platform-team",
                period_type="MONTHLY",
                limit_amount=Decimal("10.00"),
                currency="USD",
                warning_threshold=Decimal("0.7"),
                critical_threshold=Decimal("0.9"),
                enforcement_mode="STRICT",
                starts_at=None,
                ends_at=None,
            )
        await session.commit()


async def _reset_tables() -> None:
    """Drop + recreate schema so the demo is deterministic on re-runs."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


def _print(step: str, detail: str) -> None:
    print(f"  [{step}] {detail}")


async def _demo() -> None:
    transport = ASGITransport(app=app)
    headers_user = {"X-API-Key": USER_KEY}
    headers_admin = {"X-API-Key": ADMIN_KEY}

    fake_llm = _FakeLLM()
    app.dependency_overrides[llm_factory_dep] = lambda: lambda name: fake_llm
    os.environ["APP_GENERATE_ENABLED"] = "true"
    get_settings.cache_clear()

    async with (
        AsyncClient(
            transport=transport, base_url="http://testserver", headers=headers_admin
        ) as admin,
        AsyncClient(
            transport=transport, base_url="http://testserver", headers=headers_user
        ) as user,
    ):
        # ---- Beat 1: normal request -----------------------------------------
        print("\n== Beat 1: Normal request ==")
        r = await user.post(
            "/v1/cost/estimate",
            json={
                "provider": "openai",
                "model": "gpt-4o",
                "input": "Explain Decimal money math",
                "expected_output_tokens": 100,
                "team_id": "platform-team",
            },
        )
        est = r.json()
        _print(
            "estimate",
            f"status={r.status_code} budget={est['budget']['status']} "
            f"cost={est['estimated_total_cost']}",
        )
        assert r.status_code == 200
        assert est["budget"]["status"] == "ALLOW"

        r = await user.post(
            "/v1/usage",
            json={
                "request_id": "demo_req_1",
                "provider": "openai",
                "model": "gpt-4o",
                "actual_input_tokens": 15,
                "actual_output_tokens": 30,
                "team_id": "platform-team",
            },
        )
        usage = r.json()
        _print(
            "usage",
            f"status={r.status_code} actual_cost={usage['actual_cost']} "
            f"variance={usage['variance_amount']}",
        )
        assert r.status_code == 201

        # ---- Beat 2: large request -> blocked before provider ---------------
        print("\n== Beat 2: Large request (blocked before provider) ==")
        r = await user.post(
            "/v1/cost/estimate",
            json={
                "provider": "openai",
                "model": "gpt-4o",
                "input": "Write a 100 page report",
                "expected_output_tokens": 1_000_000,  # $10 output; over the $10 budget
                "team_id": "platform-team",
            },
        )
        est = r.json()
        _print("estimate", f"status={r.status_code} budget={est['budget']['status']}")
        assert r.status_code == 200
        assert est["budget"]["status"] == "BLOCK"

        before_calls = len(fake_llm.calls)
        r = await user.post(
            "/v1/generate",
            json={
                "provider": "openai",
                "model": "gpt-4o",
                "input": "Write a 100 page report",
                "max_output_tokens": 1_000_000,
                "team_id": "platform-team",
            },
        )
        body = r.json()
        _print("generate", f"status={r.status_code} code={body['error']['code']}")
        assert r.status_code == 403
        assert body["error"]["code"] == "BUDGET_EXCEEDED"
        assert len(fake_llm.calls) == before_calls, "provider must NOT be called on BLOCK"

        # ---- Beat 3: multiple requests -> aggregate + alert -----------------
        print("\n== Beat 3: Multiple requests -> threshold + alert ==")
        for i in range(6):
            r = await user.post(
                "/v1/generate",
                json={
                    "provider": "openai",
                    "model": "gpt-4o",
                    "input": f"small request {i}",
                    "max_output_tokens": 200,
                    "request_id": f"demo_gen_{i}",
                    "team_id": "platform-team",
                },
            )
            assert r.status_code == 200, r.text

        r = await user.get("/v1/usage/summary")
        summary = r.json()
        _print("summary", f"requests={summary['total_requests']} cost={summary['total_cost']}")
        assert summary["total_requests"] >= 7

        r = await user.get("/v1/cost/by-model")
        by_model = r.json()
        _print("by-model", f"model={by_model[0]['key']} cost={by_model[0]['cost']}")

        r = await admin.get("/v1/alerts")
        alerts = r.json()
        _print("alerts", f"count={len(alerts)}")
        assert len(alerts) >= 1
        assert any(a["alert_type"] == "BUDGET_THRESHOLD" for a in alerts)

        # acknowledge the first open alert
        open_alert = next(a for a in alerts if a["acknowledged_at"] is None)
        r = await admin.post(f"/v1/alerts/{open_alert['id']}/acknowledge")
        _print("ack", f"alert_id={open_alert['id']} -> {r.status_code}")
        assert r.status_code == 200

    os.environ.pop("APP_GENERATE_ENABLED", None)
    get_settings.cache_clear()
    app.dependency_overrides.clear()
    print("\nDemo complete: all three beats passed.")


def main() -> None:
    print(f"Using throwaway database '{_DEMO_DB}' (reset on every run; your data is untouched).")
    if not (_env("APP_API_KEYS") or _env("APP_ADMIN_API_KEYS")):
        os.environ["APP_API_KEYS"] = f"{USER_KEY},{ADMIN_KEY}"
        os.environ["APP_ADMIN_API_KEYS"] = ADMIN_KEY
        get_settings.cache_clear()

    async def _run() -> None:
        await _reset_tables()
        await _seed()
        await _demo()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
