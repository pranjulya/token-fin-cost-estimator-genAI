# Phase 14 + 15 — LLM Provider + End-to-End Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `LLMProvider` + OpenAI adapter and `POST /v1/generate` that runs estimate → reserve → mid-commit → LLM → `record_new` → `settle`, while making `POST /v1/cost/estimate` evaluate-only so it no longer leaks reservations.

**Architecture:** Protocol in `providers/llm/base.py`; official SDK only in `openai_provider.py`; `GenerationService` orchestrates existing `CostEstimator` / `BudgetService` / `UsageService` and never holds an `AsyncSession`. After a successful reserve, `session.commit()` releases `FOR UPDATE` before the HTTP call. `settle` always consumes this request’s `E` from reserved and adds `A` to committed (`apply_overage` when `A > E`).

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Pydantic v2, Postgres, Decimal money, structlog, official `openai` AsyncOpenAI, pytest/pytest-asyncio, httpx ASGI client.

**Spec:** `docs/superpowers/specs/2026-08-13-phase-14-15-generation-flow-design.md`

## Global Constraints

- Decimal-only money; JSON money is a string (`Money` / `SignedMoney`).
- Env prefix `APP_`; `get_settings` is `@lru_cache` (tests must `cache_clear()`).
- `generate_enabled` default **`False`**. Tests inject `True`. Production needs `APP_GENERATE_ENABLED=true` **and** `APP_OPENAI_API_KEY`.
- Never log or persist `input` / `output` text.
- Never hold `FOR UPDATE` or the request transaction across the provider HTTP call.
- Never call `commit_amount(A)` when `A > E`. Use `BudgetService.settle`.
- `POST /v1/usage` stays idempotent `record`. Generate uses `record_new`.
- Estimate must not `reserve`, write `budget_events`, or fire `BUDGET_THRESHOLD` alerts.
- No Alembic revision. No Redis. No auth. No streaming. No live OpenAI in CI.
- Mid-commit after every `reserve` (including BLOCK) and after `release(E)` on provider/409 failure, then re-raise.
- 403 message locked: `Budget exceeded for request_id='{rid}': status=BLOCK remaining_before={before} remaining_after={after}.`
- 409 message: list `GET /v1/usage` and filter by `request_id`; completion text is not stored.
- Core services must not `import openai`.
- Existing tokenizer quirk stays: `estimator_dep` uses `get_token_counter("openai")` (heuristic). Estimate and generate must share that estimator so `E` matches.

---

## File map (create / modify)

| Path | Action | Task |
|------|--------|------|
| `src/app/core/exceptions.py` | Modify | 1 (ProviderError); 3 (rest) |
| `src/app/core/config.py` | Modify | 1 |
| `src/app/providers/llm/base.py` | Create | 1 |
| `src/app/providers/llm/openai_provider.py` | Create | 1 |
| `src/app/providers/llm/__init__.py` | Replace empty | 1 |
| `tests/fakes/llm.py` | Create | 1 |
| `tests/unit/test_openai_provider.py` | Create | 1 |
| `pyproject.toml` | Modify | 1 (`openai>=1.40`) |
| `src/app/repositories/budget_repository.py` | Modify | 2 (`get_consumption`); 3 (`apply_overage`) |
| `src/app/services/budget_service.py` | Modify | 2 (`evaluate`, `find_applicable`); 3 (`settle`) |
| `src/app/api/v1/routes_cost.py` | Modify | 2 |
| `tests/integration/test_estimate_flow.py` | Modify | 2 |
| `tests/integration/test_budget.py` | Modify | 2 (evaluate); 3 (settle overlap) |
| `README.md` | Modify | 2 (estimate leak fix); 3 (generate) |
| `src/app/services/usage_service.py` | Modify | 3 (`record_new` only) |
| `src/app/repositories/usage_repository.py` | Modify | 3 (`add_new` savepoint) |
| `src/app/services/generation_service.py` | Create | 3 |
| `src/app/schemas/generate.py` | Create | 3 |
| `src/app/api/v1/routes_generate.py` | Create | 3 |
| `src/app/api/v1/router.py` | Modify | 3 |
| `src/app/api/dependencies.py` | Modify | 3 |
| `src/app/api/handlers.py` | Modify | 3 |
| `tests/unit/test_generation_service.py` | Create | 3 |
| `tests/integration/test_generate_flow.py` | Create | 3 |

---

### Task 1: LLMProvider protocol + OpenAI adapter

**Files:**
- Create: `src/app/providers/llm/base.py`
- Create: `src/app/providers/llm/openai_provider.py`
- Replace: `src/app/providers/llm/__init__.py`
- Create: `tests/fakes/llm.py`
- Create: `tests/unit/test_openai_provider.py`
- Modify: `src/app/core/exceptions.py`
- Modify: `src/app/core/config.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `AppError` / `ErrorCode` / `ModelNotSupportedError`; `get_settings`
- Produces: `LLMCompletion`; `LLMProvider.complete(...)`; `OpenAIProvider`; `get_llm_provider(name) -> LLMProvider`; `ProviderError` (502); Settings `openai_api_key`, `openai_base_url`, `openai_timeout_seconds`, `generate_enabled=False`

- [ ] **Step 1: Add `openai>=1.40` and write failing provider tests**

Add to `pyproject.toml` runtime `dependencies`:

```toml
"openai>=1.40",
```

Keep `httpx` in the **dev** group.

```bash
uv sync
```

Create `tests/fakes/llm.py`:

```python
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
```

Create `tests/unit/test_openai_provider.py`:

```python
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


def _resp(*, usage, text="hello", model="gpt-4o"):
    choice = SimpleNamespace(message=SimpleNamespace(content=text))
    return SimpleNamespace(choices=[choice], usage=usage, model=model)


@pytest.fixture
def provider():
    return OpenAIProvider(api_key="sk-test", base_url=None, timeout_seconds=5)


async def test_maps_usage_and_cached(provider):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=_resp(usage=_usage(prompt=12, completion=4, cached=3))
    )
    cm = AsyncMock()
    cm.__aenter__.return_value = client
    cm.__aexit__.return_value = False
    with patch("app.providers.llm.openai_provider.AsyncOpenAI", return_value=cm) as ctor:
        out = await provider.complete(
            model="gpt-4o", prompt="hi", max_output_tokens=20, request_id="req_1"
        )
    assert out.prompt_tokens == 12
    assert out.completion_tokens == 4
    assert out.cached_prompt_tokens == 3
    assert out.text == "hello"
    assert out.provider == "openai"
    ctor.assert_called_once()
    assert ctor.call_args.kwargs["max_retries"] == 0
    cm.__aenter__.assert_awaited()
    cm.__aexit__.assert_awaited()
    client.chat.completions.create.assert_awaited_once()
    kwargs = client.chat.completions.create.await_args.kwargs
    assert kwargs["max_tokens"] == 20
    assert kwargs["messages"] == [{"role": "user", "content": "hi"}]


async def test_missing_details_cached_zero(provider):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_resp(usage=_usage(cached=None)))
    cm = AsyncMock()
    cm.__aenter__.return_value = client
    cm.__aexit__.return_value = False
    with patch("app.providers.llm.openai_provider.AsyncOpenAI", return_value=cm):
        out = await provider.complete(
            model="gpt-4o", prompt="hi", max_output_tokens=1, request_id="req_1"
        )
    assert out.cached_prompt_tokens == 0


async def test_missing_usage_is_provider_error(provider):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_resp(usage=None))
    cm = AsyncMock()
    cm.__aenter__.return_value = client
    cm.__aexit__.return_value = False
    with patch("app.providers.llm.openai_provider.AsyncOpenAI", return_value=cm):
        with pytest.raises(ProviderError) as ei:
            await provider.complete(
                model="gpt-4o", prompt="hi", max_output_tokens=1, request_id="req_1"
            )
    assert ei.value.status_code == 502
    assert "usage" in ei.value.message


async def test_missing_api_key_does_not_construct_client():
    p = OpenAIProvider(api_key=None, base_url=None, timeout_seconds=5)
    with patch("app.providers.llm.openai_provider.AsyncOpenAI") as ctor:
        with pytest.raises(ProviderError) as ei:
            await p.complete(
                model="gpt-4o", prompt="hi", max_output_tokens=1, request_id="req_1"
            )
    ctor.assert_not_called()
    assert "APP_OPENAI_API_KEY" in ei.value.message


async def test_sdk_exception_is_provider_error(provider):
    cm = AsyncMock()
    cm.__aenter__.side_effect = RuntimeError("boom")
    with patch("app.providers.llm.openai_provider.AsyncOpenAI", return_value=cm):
        with pytest.raises(ProviderError) as ei:
            await provider.complete(
                model="gpt-4o", prompt="hi", max_output_tokens=1, request_id="req_1"
            )
    assert ei.value.status_code == 502
    assert "boom" in ei.value.message
    assert "hi" not in ei.value.message


def test_factory_unknown_provider():
    with pytest.raises(ModelNotSupportedError):
        get_llm_provider("anthropic")


def test_factory_openai_does_not_require_key():
    p = get_llm_provider("openai")
    assert isinstance(p, OpenAIProvider)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_openai_provider.py -v
```

Expected: FAIL (modules / `ProviderError` class missing).

- [ ] **Step 3: Implement exceptions, settings, Protocol, adapter, factory**

`src/app/core/exceptions.py` — add if missing:

```python
    PROVIDER_ERROR = "PROVIDER_ERROR"  # already present as string
    GENERATION_DISABLED = "GENERATION_DISABLED"  # used in Task 3; may add now
```

```python
class ProviderError(AppError):
    code = ErrorCode.PROVIDER_ERROR
    status_code = 502
```

`src/app/core/config.py` — add fields:

```python
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_timeout_seconds: float = 60
    generate_enabled: bool = False
```

`src/app/providers/llm/base.py` — exact Protocol from spec K6.

`src/app/providers/llm/openai_provider.py` — exact adapter from spec (key check **before** `AsyncOpenAI`; `async with AsyncOpenAI(...) as client:`; `max_retries=0`; missing usage → `ProviderError`; never put prompt text in the exception).

`src/app/providers/llm/__init__.py`:

```python
from app.core.config import get_settings
from app.core.exceptions import ModelNotSupportedError
from app.providers.llm.base import LLMCompletion, LLMProvider
from app.providers.llm.openai_provider import OpenAIProvider

def get_llm_provider(name: str) -> LLMProvider:
    if name != "openai":
        raise ModelNotSupportedError(name, model="*")
    s = get_settings()
    return OpenAIProvider(
        api_key=s.openai_api_key,
        base_url=s.openai_base_url,
        timeout_seconds=s.openai_timeout_seconds,
    )

__all__ = ["LLMCompletion", "LLMProvider", "OpenAIProvider", "get_llm_provider"]
```

- [ ] **Step 4: Run unit tests**

```bash
uv run pytest tests/unit/test_openai_provider.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/app/core/exceptions.py src/app/core/config.py \
  src/app/providers/llm tests/fakes/llm.py tests/unit/test_openai_provider.py
git commit -m "feat(llm): LLMProvider protocol and OpenAI adapter"
```

---

### Task 2: Evaluate-only estimate (stop reserved leak)

**Files:**
- Modify: `src/app/repositories/budget_repository.py`
- Modify: `src/app/services/budget_service.py`
- Modify: `src/app/api/v1/routes_cost.py`
- Modify: `tests/integration/test_budget.py`
- Modify: `tests/integration/test_estimate_flow.py`
- Modify: `README.md` (estimate behavior)

**Interfaces:**
- Consumes: existing `Budget`, `budget_policy.decide`, `period_key_for`
- Produces: `BudgetRepository.get_consumption(budget_id, period_key) -> BudgetConsumption | None`; `BudgetService.evaluate(budget, amount) -> BudgetDecision`; `BudgetService.find_applicable(*, team_id, application_id) -> Budget | None`
- Estimate route calls `evaluate`, never `reserve`

- [ ] **Step 1: Write failing tests**

Append to `tests/integration/test_budget.py`:

```python
class TestBudgetEvaluate:
    async def test_evaluate_does_not_mutate_or_event(self, db_session):
        bid = await make_budget(db_session)
        svc = BudgetService(BudgetRepository(db_session))
        budget = await svc.find_for("TEAM", "platform-team")
        await svc.reserve(budget, Decimal("10"), "req_seed")
        await db_session.commit()

        d = await svc.evaluate(budget, Decimal("20"))
        assert d.status == "ALLOW"
        await db_session.commit()

        row = await BudgetRepository(db_session).get_consumption(bid, "2026-08")
        # period_key is current month — use period_key_for in the test:
        from app.services.budget_service import period_key_for
        row = await BudgetRepository(db_session).get_consumption(
            bid, period_key_for(budget.period_type)
        )
        assert row.reserved_amount == Decimal("10")
        events = (
            await db_session.execute(select(BudgetEvent).where(BudgetEvent.budget_id == bid))
        ).scalars().all()
        assert all(e.event_type in {"RESERVE", "DECISION"} for e in events)
        assert sum(1 for e in events if e.event_type == "RESERVE") == 1

    async def test_find_applicable_prefers_team(self, db_session):
        await make_budget(db_session, scope_type="APPLICATION", scope_id="app-1")
        await make_budget(db_session, scope_type="TEAM", scope_id="team-1")
        svc = BudgetService(BudgetRepository(db_session))
        b = await svc.find_applicable(team_id="team-1", application_id="app-1")
        assert b is not None
        assert b.scope_type == "TEAM"
        assert b.scope_id == "team-1"
```

Append to `tests/integration/test_estimate_flow.py`:

```python
    async def test_estimate_does_not_reserve_or_alert(self, client, db_session):
        from sqlalchemy import func, select
        from app.db.models import Alert, BudgetConsumption, BudgetEvent

        await seed_price(db_session)
        bid = await seed_budget(db_session)
        resp = await client.post(
            "/v1/cost/estimate",
            json={
                "provider": "openai",
                "model": "gpt-4o",
                "input": "Hello world",
                "expected_output_tokens": 100,
                "team_id": "platform-team",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["budget"]["status"] == "ALLOW"
        n_events = await db_session.scalar(select(func.count()).select_from(BudgetEvent))
        assert n_events == 0
        n_alerts = await db_session.scalar(select(func.count()).select_from(Alert))
        assert n_alerts == 0
        n_cons = await db_session.scalar(select(func.count()).select_from(BudgetConsumption))
        assert n_cons == 0

    async def test_estimate_block_is_still_200(self, client, db_session):
        await seed_price(db_session)
        await seed_budget(db_session, limit_amount=Decimal("0.000001"))
        resp = await client.post(
            "/v1/cost/estimate",
            json={
                "provider": "openai",
                "model": "gpt-4o",
                "input": "Hello world",
                "expected_output_tokens": 100000,
                "team_id": "platform-team",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["budget"]["status"] == "BLOCK"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_budget.py::TestBudgetEvaluate tests/integration/test_estimate_flow.py -v
```

Expected: FAIL (`get_consumption` / `evaluate` missing; estimate still writes RESERVE).

- [ ] **Step 3: Implement evaluate-only path**

`BudgetRepository.get_consumption` — spec: no `FOR UPDATE`, no insert-if-absent.

`BudgetService.find_applicable` and `evaluate` — copy from spec Proposed Design.

`routes_cost.py` — replace the TEAM/APPLICATION loop + `reserve` with:

```python
envelope = BudgetEnvelope()
budget = await budget_service.find_applicable(
    team_id=body.team_id, application_id=body.application_id
)
if budget is not None:
    decision = await budget_service.evaluate(budget, b.total_cost)
    envelope = BudgetEnvelope(
        status=decision.status,
        remaining_before_request=decision.remaining_before,
        remaining_after_estimate=decision.remaining_after,
    )
```

README — replace the stale “Budget enforcement … next phases” / estimate-as-hold implication with:

```markdown
`POST /v1/cost/estimate` is evaluate-only: it returns a budget envelope
(`ALLOW`/`WARN`/`CRITICAL`/`BLOCK`) but does **not** reserve spend or write
budget events. `POST /v1/generate` (Phase 14–15) is the only path that
reserves and settles.
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/integration/test_budget.py tests/integration/test_estimate_flow.py tests/integration/test_alert_hooks.py -v
```

Expected: PASS. Alert hook tests still call `reserve` directly.

- [ ] **Step 5: Commit**

```bash
git add src/app/repositories/budget_repository.py src/app/services/budget_service.py \
  src/app/api/v1/routes_cost.py tests/integration/test_budget.py \
  tests/integration/test_estimate_flow.py README.md
git commit -m "fix(budget): estimate is evaluate-only and no longer reserves"
```

---

### Task 3: GenerationService + POST /v1/generate

**Files:**
- Create: `src/app/services/generation_service.py`
- Create: `src/app/schemas/generate.py`
- Create: `src/app/api/v1/routes_generate.py`
- Create: `tests/unit/test_generation_service.py`
- Create: `tests/integration/test_generate_flow.py`
- Modify: `src/app/services/usage_service.py` (`record_new` only)
- Modify: `src/app/repositories/usage_repository.py` (`add_new`)
- Modify: `src/app/services/budget_service.py` (`settle`)
- Modify: `src/app/repositories/budget_repository.py` (`apply_overage`)
- Modify: `src/app/core/exceptions.py`
- Modify: `src/app/api/handlers.py`
- Modify: `src/app/api/dependencies.py`
- Modify: `src/app/api/v1/router.py`
- Modify: `tests/integration/test_budget.py` (settle overlap)
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 1 factory + Task 2 `find_applicable`; existing `reserve` / `release` / `CostEstimator` / `UsageService.record` body
- Produces: `BudgetService.settle`; `UsageService.record_new`; `GenerationService.generate -> GenerationResult`; `POST /v1/generate`

- [ ] **Step 1: Write failing settle + record_new tests**

Append to `tests/integration/test_budget.py`:

```python
class TestBudgetSettle:
    async def test_settle_less_than_reserve(self, db_session):
        await make_budget(db_session)
        repo = BudgetRepository(db_session)
        svc = BudgetService(repo)
        budget = await svc.find_for("TEAM", "platform-team")
        await svc.reserve(budget, Decimal("10"), "req_1")
        await svc.settle(
            budget, reserved_amount=Decimal("10"), actual_amount=Decimal("4"), request_id="req_1"
        )
        await db_session.commit()
        row = await repo.get_consumption(budget.id, period_key_for(budget.period_type))
        assert row.reserved_amount == Decimal("0")
        assert row.committed_amount == Decimal("4")
        types = [
            e.event_type
            for e in (
                await db_session.execute(select(BudgetEvent).where(BudgetEvent.budget_id == budget.id))
            ).scalars()
        ]
        assert types.count("COMMIT") == 1
        assert types.count("RELEASE") == 1

    async def test_settle_overage_does_not_steal_other_reserve(self, db_session):
        await make_budget(db_session, limit_amount="100.00")
        repo = BudgetRepository(db_session)
        svc = BudgetService(repo)
        budget = await svc.find_for("TEAM", "platform-team")
        await svc.reserve(budget, Decimal("4"), "g1")
        await svc.reserve(budget, Decimal("4"), "g2")
        await svc.settle(
            budget, reserved_amount=Decimal("4"), actual_amount=Decimal("6"), request_id="g1"
        )
        await db_session.commit()
        row = await repo.get_consumption(budget.id, period_key_for(budget.period_type))
        # G2's E2=4 still reserved; G1 committed 6. used = 10.
        assert row.reserved_amount == Decimal("4")
        assert row.committed_amount == Decimal("6")
        events = (
            await db_session.execute(select(BudgetEvent).where(BudgetEvent.request_id == "g1"))
        ).scalars().all()
        assert [e.event_type for e in events if e.event_type != "RESERVE"] == ["COMMIT"]
        assert events[-1].amount == Decimal("6")
```

Import `period_key_for` at the top of `test_budget.py`.

Create `tests/unit/test_generation_service.py` with fakes. Minimum cases from spec K13:

```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import (
    BudgetExceededError,
    GenerationAlreadyRecordedError,
    GenerationDisabledError,
    ProviderError,
)
from app.domain.budget import ALLOW, BLOCK, BudgetDecision
from app.domain.cost import CostBreakdown
from app.providers.llm.base import LLMCompletion
from app.services.cost_estimator import Estimation
from app.services.generation_service import GenerationService
from tests.fakes.llm import FakeLLMProvider


def _estimation(total="4.00"):
    # CostBreakdown.total_cost is a property (input + cached + output).
    total_d = Decimal(total)
    bd = CostBreakdown(
        currency="USD",
        input_cost=Decimal("1.00"),
        cached_input_cost=Decimal("0"),
        output_cost=total_d - Decimal("1.00"),
    )
    pricing = SimpleNamespace(version=1)
    return Estimation(
        input_tokens=10,
        output_tokens=20,
        cached_input_tokens=0,
        breakdown=bd,
        pricing=pricing,
    )


def _decision(status=ALLOW, before="100", after="96"):
    return BudgetDecision(
        status=status,
        remaining_before=Decimal(before),
        remaining_after=Decimal(after),
    )


@dataclass
class _Usage:
    actual_cost: Decimal
    actual_input_tokens: int = 8
    cached_input_tokens: int = 0
    actual_output_tokens: int = 5
    variance_amount: Decimal = Decimal("0")
    variance_percent: Decimal = Decimal("0")
    pricing_version: int = 1
    status: str = "SUCCESS"


def _svc(*, enabled=True, existing=None, budget="yes", decision=None, fake=None, record_error=None):
    fake = fake or FakeLLMProvider(
        completion=LLMCompletion(
            text="out",
            prompt_tokens=10,
            completion_tokens=5,
            cached_prompt_tokens=0,
            model="gpt-4o",
            provider="openai",
        )
    )
    estimator = SimpleNamespace(estimate=AsyncMock(return_value=_estimation()))
    budget_svc = SimpleNamespace(
        find_applicable=AsyncMock(return_value=object() if budget else None),
        reserve=AsyncMock(return_value=decision or _decision()),
        release=AsyncMock(),
        settle=AsyncMock(),
    )
    usage_svc = SimpleNamespace(
        record_new=AsyncMock(side_effect=record_error or (lambda **k: _Usage(Decimal("1.00"))))
    )
    usage_repo = SimpleNamespace(get_by_request_id=AsyncMock(return_value=existing))
    commits: list[int] = []

    async def _commit():
        commits.append(1)

    svc = GenerationService(
        estimator=estimator,
        budget_service=budget_svc,
        usage_service=usage_svc,
        usage_repository=usage_repo,
        get_llm=lambda name: fake,
        session_commit=_commit,
        generate_enabled=enabled,
        environment="test",
    )
    return svc, fake, budget_svc, usage_svc, commits


async def test_disabled():
    svc, fake, *_ = _svc(enabled=False)
    with pytest.raises(GenerationDisabledError):
        await svc.generate(
            provider="openai", model="gpt-4o", input_text="hi",
            max_output_tokens=10, application_id=None, team_id=None,
            user_id=None, endpoint=None, request_id="r1", correlation_id=None,
        )
    assert fake.calls == []


async def test_existing_request_id_no_reserve():
    svc, fake, budget_svc, *_ = _svc(existing=object())
    with pytest.raises(GenerationAlreadyRecordedError):
        await svc.generate(
            provider="openai", model="gpt-4o", input_text="hi",
            max_output_tokens=10, application_id=None, team_id="t",
            user_id=None, endpoint=None, request_id="r1", correlation_id=None,
        )
    budget_svc.reserve.assert_not_awaited()
    assert fake.calls == []


async def test_block_no_provider():
    svc, fake, budget_svc, usage_svc, commits = _svc(decision=_decision(status=BLOCK))
    with pytest.raises(BudgetExceededError) as ei:
        await svc.generate(
            provider="openai", model="gpt-4o", input_text="hi",
            max_output_tokens=10, application_id=None, team_id="t",
            user_id=None, endpoint=None, request_id="r1", correlation_id=None,
        )
    assert fake.calls == []
    usage_svc.record_new.assert_not_awaited()
    assert ei.value.status_code == 403
    assert "request_id='r1'" in ei.value.message
    assert "status=BLOCK" in ei.value.message
    assert commits  # mid-commit before raise


async def test_provider_error_releases():
    fake = FakeLLMProvider(error=ProviderError("nope"))
    svc, _, budget_svc, usage_svc, _ = _svc(fake=fake)
    with pytest.raises(ProviderError):
        await svc.generate(
            provider="openai", model="gpt-4o", input_text="hi",
            max_output_tokens=10, application_id=None, team_id="t",
            user_id=None, endpoint=None, request_id="r1", correlation_id=None,
        )
    budget_svc.release.assert_awaited()
    budget_svc.settle.assert_not_awaited()
    usage_svc.record_new.assert_not_awaited()


async def test_success_settles():
    svc, fake, budget_svc, usage_svc, _ = _svc()
    result = await svc.generate(
        provider="openai", model="gpt-4o", input_text="hi",
        max_output_tokens=10, application_id=None, team_id="t",
        user_id=None, endpoint=None, request_id="r1", correlation_id=None,
    )
    assert result.output == "out"
    budget_svc.settle.assert_awaited()
    usage_svc.record_new.assert_awaited()


async def test_record_new_409_after_reserve_releases_no_settle():
    svc, fake, budget_svc, _, _ = _svc(record_error=GenerationAlreadyRecordedError("r1"))
    with pytest.raises(GenerationAlreadyRecordedError):
        await svc.generate(
            provider="openai", model="gpt-4o", input_text="hi",
            max_output_tokens=10, application_id=None, team_id="t",
            user_id=None, endpoint=None, request_id="r1", correlation_id=None,
        )
    budget_svc.release.assert_awaited()
    budget_svc.settle.assert_not_awaited()


async def test_no_budget_skips_reserve():
    svc, fake, budget_svc, usage_svc, _ = _svc(budget=False)
    await svc.generate(
        provider="openai", model="gpt-4o", input_text="hi",
        max_output_tokens=10, application_id=None, team_id=None,
        user_id=None, endpoint=None, request_id="r1", correlation_id=None,
    )
    budget_svc.reserve.assert_not_awaited()
    budget_svc.settle.assert_not_awaited()
    usage_svc.record_new.assert_awaited()
    assert fake.calls
```

Adjust `_estimation` to match the real `CostBreakdown` / `Estimation` / `ModelPrice` constructors in `src/app/domain/cost.py` and `src/app/domain/pricing.py` if fields differ — read those files and use the real types rather than inventing fields.

Also add `tests/unit` coverage for `record_new` against the real test DB in `tests/integration/test_usage.py` (or a small new module):

```python
async def test_record_new_raises_on_existing(db_session):
    # seed pricing, record once via record(), then record_new same request_id
    ...
    with pytest.raises(GenerationAlreadyRecordedError):
        await svc.record_new(...)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_generation_service.py tests/integration/test_budget.py::TestBudgetSettle -v
```

Expected: FAIL (missing symbols).

- [ ] **Step 3: Implement settle, apply_overage, record_new, exceptions, handler**

`apply_overage` — exact spec K16.

`BudgetService.settle` — one `lock_consumption`; branch `A < E` / `A == E` / `A > E` per spec; write COMMIT / optional RELEASE events; **no alerts**.

`UsageRepository.add_new`:

```python
async def add_new(self, record: UsageRecord) -> UsageRecord:
    try:
        async with self._session.begin_nested():
            self._session.add(record)
            await self._session.flush()
            return record
    except IntegrityError:
        raise
```

`UsageService.record_new`: same body as `record` after the idempotent return, but existing row → `GenerationAlreadyRecordedError`; wrap insert in `add_new`; map `IntegrityError` → `GenerationAlreadyRecordedError`. Still fire `maybe_cost_anomaly` on new SUCCESS.

Exceptions:

```python
class ErrorCode:
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    GENERATION_DISABLED = "GENERATION_DISABLED"
    GENERATION_ALREADY_RECORDED = "GENERATION_ALREADY_RECORDED"

class BudgetExceededError(AppError):
    code = ErrorCode.BUDGET_EXCEEDED
    status_code = 403

class GenerationDisabledError(AppError):
    code = ErrorCode.GENERATION_DISABLED
    status_code = 503

class GenerationAlreadyRecordedError(AppError):
    code = ErrorCode.GENERATION_ALREADY_RECORDED
    status_code = 409

    def __init__(self, request_id: str):
        super().__init__(
            f"Generation already recorded for request_id='{request_id}'. "
            "Completion text is not stored; list GET /v1/usage and filter by request_id.",
            request_id=request_id,
        )
```

`handlers.py` — prefer `exc.request_id`:

```python
def _request_id(request: Request, exc: AppError | None = None) -> str:
    if exc is not None and getattr(exc, "request_id", None):
        return exc.request_id
    return request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:16]}"
```

Update `_app_error` to pass `exc` into `_request_id`.

- [ ] **Step 4: Implement GenerationService + schemas + route + deps**

`generation_service.py` — copy the spec algorithm verbatim (including cached split, mid-commit, `settle`, 403 message). Logger: `get_logger("app.generate")`. Events: `generate_started`, `generate_duplicate`, `generate_blocked`, `generate_reserved`, `generate_provider_ok`, `generate_provider_failed`, `generate_settled`. **Never bind prompt/output.**

Reject `provider != "openai"` **after** BLOCK is ruled out (so blocked budgets still 403). Unknown provider after ALLOW is `ModelNotSupportedError` and must hit the `except AppError` release path.

`schemas/generate.py`:

```python
from pydantic import BaseModel, Field, model_validator
from app.core.config import get_settings
from app.schemas.common import APIModel, Money, SignedMoney
from app.schemas.cost import BudgetEnvelope

class GenerateRequest(BaseModel):
    provider: str = Field(..., min_length=1, max_length=64)
    model: str = Field(..., min_length=1, max_length=128)
    input: str
    max_output_tokens: int = Field(..., ge=1)
    application_id: str | None = Field(default=None, max_length=128)
    team_id: str | None = Field(default=None, max_length=128)
    user_id: str | None = Field(default=None, max_length=128)
    endpoint: str | None = Field(default=None, max_length=256)
    request_id: str | None = Field(default=None, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _limits(self):
        s = get_settings()
        if len(self.input) > s.max_prompt_chars:
            raise ValueError("input exceeds max_prompt_chars")
        if self.max_output_tokens > s.max_expected_output_tokens:
            raise ValueError("max_output_tokens exceeds max_expected_output_tokens")
        return self

class GenerateResponse(APIModel):
    request_id: str
    provider: str
    model: str
    output: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_input_cost: Money
    estimated_cached_input_cost: Money | None = None
    estimated_output_cost: Money
    estimated_total_cost: Money
    actual_input_tokens: int
    actual_cached_input_tokens: int
    actual_output_tokens: int
    actual_cost: Money
    variance_amount: SignedMoney | None = None
    variance_percent: SignedMoney | None = None
    currency: str
    pricing_version: int
    budget: BudgetEnvelope
    status: str

    @classmethod
    def from_result(cls, result) -> "GenerateResponse":
        est = result.estimation
        b = est.breakdown
        u = result.usage
        decision = result.budget_decision
        envelope = (
            BudgetEnvelope()
            if decision is None
            else BudgetEnvelope(
                status=decision.status,
                remaining_before_request=decision.remaining_before,
                remaining_after_estimate=decision.remaining_after,
            )
        )
        return cls(
            request_id=result.request_id,
            provider=result.provider,
            model=result.model,
            output=result.output,
            estimated_input_tokens=est.input_tokens,
            estimated_output_tokens=est.output_tokens,
            estimated_input_cost=b.input_cost,
            estimated_cached_input_cost=b.cached_input_cost,
            estimated_output_cost=b.output_cost,
            estimated_total_cost=b.total_cost,
            actual_input_tokens=u.actual_input_tokens,
            actual_cached_input_tokens=u.cached_input_tokens,
            actual_output_tokens=u.actual_output_tokens,
            actual_cost=u.actual_cost,
            variance_amount=u.variance_amount,
            variance_percent=u.variance_percent,
            currency=b.currency,
            pricing_version=u.pricing_version,
            budget=envelope,
            status=u.status,
        )
```

`routes_generate.py` — spec route (200, thin).

`router.py`: `api_router.include_router(routes_generate.router)`.

`dependencies.py`:

```python
from app.providers.llm import get_llm_provider
from app.services.generation_service import GenerationService

def llm_factory_dep():
    return get_llm_provider

async def generation_service_dep(
    session: AsyncSession = Depends(get_db_session),
    estimator: CostEstimator = Depends(estimator_dep),
    budget_service: BudgetService = Depends(budget_service_dep),
    usage_service: UsageService = Depends(usage_service_dep),
    get_llm=Depends(llm_factory_dep),
) -> GenerationService:
    settings = get_settings()
    return GenerationService(
        estimator=estimator,
        budget_service=budget_service,
        usage_service=usage_service,
        usage_repository=UsageRepository(session),
        get_llm=get_llm,
        session_commit=session.commit,
        generate_enabled=settings.generate_enabled,
        environment=settings.environment,
    )
```

No `_commit` wrapper.

- [ ] **Step 5: Write integration tests with FakeLLMProvider override**

Create `tests/integration/test_generate_flow.py`. Override **only in this module**:

```python
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.api.dependencies import llm_factory_dep
from app.core.config import get_settings
from app.db.models import BudgetConsumption, BudgetEvent, UsageRecord
from app.main import app
from app.providers.llm.base import LLMCompletion
from tests.fakes.llm import FakeLLMProvider
from tests.integration.test_estimate_flow import seed_budget, seed_price


@pytest.fixture
def fake_llm():
    return FakeLLMProvider(
        completion=LLMCompletion(
            text="generated",
            prompt_tokens=10,
            completion_tokens=4,
            cached_prompt_tokens=0,
            model="gpt-4o",
            provider="openai",
        )
    )


@pytest.fixture
def enable_generate(fake_llm):
    get_settings.cache_clear()
    app.dependency_overrides[llm_factory_dep] = lambda: (lambda name: fake_llm)
    # Force generate_enabled True for the process Settings used by the dep.
    from app.core.config import Settings
    get_settings.cache_clear()
    # The dep reads get_settings().generate_enabled. Patch Settings via env:
    import os
    os.environ["APP_GENERATE_ENABLED"] = "true"
    get_settings.cache_clear()
    yield fake_llm
    os.environ.pop("APP_GENERATE_ENABLED", None)
    get_settings.cache_clear()
    app.dependency_overrides.clear()
```

If `Settings` already cached `generate_enabled=False` before env is set, always `cache_clear()` **after** setting the env var.

Cases:

1. Happy path + budget: 200, usage SUCCESS, events include RESERVE + COMMIT, leftover RELEASE if `E > A`, `fake_llm.calls == 1`, envelope status ALLOW, `output == "generated"`.
2. STRICT over-limit (tiny `limit_amount`): 403, `error.code == BUDGET_EXCEEDED`, no usage row, `fake_llm.calls == []`, reserved unchanged (0).
3. ADVISORY over-limit: 200, provider called.
4. `fake_llm.error = ProviderError("x")`: 502, RESERVE + RELEASE(E), no SUCCESS usage.
5. Repeat same `request_id` after success: 409, `fake_llm.calls` still 1.
6. No budget: 200, no `budget_events`, usage row present, `budget.status == "ENABLED"`.
7. Without `APP_GENERATE_ENABLED`: 503 `GENERATION_DISABLED` (separate test that does not use `enable_generate`).

Use `period_key_for` + `get_consumption` to assert reserved/committed after happy path.

- [ ] **Step 6: Run the full suite**

```bash
uv run pytest
```

Expected: all existing tests still pass; new generate/settle/estimate tests pass. If `CostBreakdown` / `Estimation` constructors in unit tests do not match, fix the test fixtures — do not change money math.

- [ ] **Step 7: Update README**

API table: add `POST /v1/generate`.

Env:

```text
APP_GENERATE_ENABLED=true
APP_OPENAI_API_KEY=sk-...
APP_OPENAI_BASE_URL=          # optional
APP_OPENAI_TIMEOUT_SECONDS=60
```

Document:

- Estimate is evaluate-only (already in Task 2).
- Generate is the only reserve+settle path.
- Default generate is **off**.
- 409: list `GET /v1/usage` and filter by `request_id`; text is not stored.
- After 5xx, use a **new** `request_id`.
- Roadmap: mark Phase 14–15 done; next is observability / auth / Docker+CI.

- [ ] **Step 8: Commit**

```bash
git add src/app/services/generation_service.py src/app/schemas/generate.py \
  src/app/api/v1/routes_generate.py src/app/api/v1/router.py \
  src/app/api/dependencies.py src/app/api/handlers.py \
  src/app/core/exceptions.py src/app/services/usage_service.py \
  src/app/repositories/usage_repository.py src/app/services/budget_service.py \
  src/app/repositories/budget_repository.py \
  tests/unit/test_generation_service.py tests/integration/test_generate_flow.py \
  tests/integration/test_budget.py README.md
git commit -m "feat(generate): POST /v1/generate reserve-call-settle loop"
```

---

## Self-review (plan vs spec)

| Spec requirement | Task |
|------------------|------|
| K1 generate owns reserve+settle | 3 |
| K2 estimate evaluate-only | 2 |
| K3 mid-commit before LLM | 3 |
| K4 / K16 settle / apply_overage | 3 |
| K5 STRICT BLOCK 403 exact message | 3 |
| K6–K8 Protocol, adapter, factory, default-off | 1 |
| K9 contract + GenerationResult | 3 |
| K10 / K17 409 + record_new | 3 |
| K11 no migrations | all |
| K12 no prompt logs | 3 |
| K13 FakeLLMProvider, no live OpenAI | 1 + 3 |
| K14 session_commit=session.commit | 3 |
| K18 no remaining HTTP | 3 (do not add) |
| Handler prefers exc.request_id | 3 |
| Cached-token uncached split | 3 |
| `async with AsyncOpenAI` | 1 |
| PR2 README estimate note | 2 |

No TBD / “implement later” steps. Types (`LLMCompletion`, `GenerationResult`, `settle(reserved_amount, actual_amount)`, `record_new`) match the spec.
