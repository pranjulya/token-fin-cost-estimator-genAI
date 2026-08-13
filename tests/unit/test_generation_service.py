"""Unit tests for GenerationService with fakes (no network, no DB)."""

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
    ModelNotSupportedError,
    ProviderError,
)
from app.domain.budget import ALLOW, BLOCK, BudgetDecision
from app.domain.cost import CostBreakdown
from app.providers.llm.base import LLMCompletion
from app.services.cost_estimator import Estimation
from app.services.generation_service import GenerationService
from tests.fakes.llm import FakeLLMProvider


def _estimation(total="4.00"):
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


def _generate(svc, **over):
    defaults = dict(
        provider="openai",
        model="gpt-4o",
        input_text="hi",
        max_output_tokens=10,
        application_id=None,
        team_id=None,
        user_id=None,
        endpoint=None,
        request_id="r1",
        correlation_id=None,
    )
    defaults.update(over)
    return svc.generate(**defaults)


async def test_disabled():
    svc, fake, *_ = _svc(enabled=False)
    with pytest.raises(GenerationDisabledError):
        await _generate(svc)
    assert fake.calls == []


async def test_existing_request_id_no_reserve():
    svc, fake, budget_svc, *_ = _svc(existing=object())
    with pytest.raises(GenerationAlreadyRecordedError):
        await _generate(svc, team_id="t")
    budget_svc.reserve.assert_not_awaited()
    assert fake.calls == []


async def test_block_no_provider():
    svc, fake, budget_svc, usage_svc, commits = _svc(decision=_decision(status=BLOCK))
    with pytest.raises(BudgetExceededError) as ei:
        await _generate(svc, team_id="t")
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
        await _generate(svc, team_id="t")
    budget_svc.release.assert_awaited()
    budget_svc.settle.assert_not_awaited()
    usage_svc.record_new.assert_not_awaited()


async def test_unknown_provider_releases():
    fake = FakeLLMProvider()
    svc, _, budget_svc, usage_svc, _ = _svc(fake=fake)
    with pytest.raises(ModelNotSupportedError):
        await _generate(svc, provider="anthropic", team_id="t")
    budget_svc.release.assert_awaited()
    budget_svc.settle.assert_not_awaited()
    usage_svc.record_new.assert_not_awaited()


async def test_success_settles():
    svc, fake, budget_svc, usage_svc, _ = _svc()
    result = await _generate(svc, team_id="t")
    assert result.output == "out"
    budget_svc.settle.assert_awaited()
    usage_svc.record_new.assert_awaited()
    assert fake.calls


async def test_record_new_409_after_reserve_releases_no_settle():
    svc, fake, budget_svc, _, _ = _svc(record_error=GenerationAlreadyRecordedError("r1"))
    with pytest.raises(GenerationAlreadyRecordedError):
        await _generate(svc, team_id="t")
    budget_svc.release.assert_awaited()
    budget_svc.settle.assert_not_awaited()


async def test_no_budget_skips_reserve():
    svc, fake, budget_svc, usage_svc, _ = _svc(budget=False)
    await _generate(svc)
    budget_svc.reserve.assert_not_awaited()
    budget_svc.settle.assert_not_awaited()
    usage_svc.record_new.assert_awaited()
    assert fake.calls
