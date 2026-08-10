"""Integration tests for the pricing repository + versioning (PRD # 20)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import ModelPricingNotFoundError
from app.repositories.pricing_repository import PricingRepository


async def _seed(db, provider="openai", model="gpt-4o", inp="2.50", out="10.00", cached=None):
    repo = PricingRepository(db)
    row = await repo.create(
        provider=provider,
        model=model,
        input_per_million=Decimal(inp),
        output_per_million=Decimal(out),
        cached_input_per_million=Decimal(cached) if cached else None,
        effective_from=date.today(),
    )
    await db.commit()
    return row


class TestPricingRepository:
    async def test_create_and_get_effective(self, db_session):
        await _seed(db_session)
        price = await PricingRepository(db_session).get_effective("openai", "gpt-4o")
        assert price.input_per_million == Decimal("2.50")
        assert price.output_per_million == Decimal("10.00")
        assert price.version == 1
        assert price.currency == "USD"

    async def test_version_bumps_on_update(self, db_session):
        await _seed(db_session)
        repo = PricingRepository(db_session)
        await repo.create(
            provider="openai",
            model="gpt-4o",
            input_per_million=Decimal("3.00"),
            output_per_million=Decimal("12.00"),
        )
        await db_session.commit()
        second = await repo.get_effective("openai", "gpt-4o")
        assert second.version == 2
        assert second.input_per_million == Decimal("3.00")
        # History preserved: both versions exist.
        assert len(await repo.list_all()) == 2

    async def test_missing_pricing_raises(self, db_session):
        with pytest.raises(ModelPricingNotFoundError):
            await PricingRepository(db_session).get_effective("openai", "nope-model")

    async def test_cached_price_absent(self, db_session):
        await _seed(db_session, cached=None)
        price = await PricingRepository(db_session).get_effective("openai", "gpt-4o")
        assert price.cached_input_per_million is None
