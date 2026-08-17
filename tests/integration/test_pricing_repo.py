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

    async def test_all_expired_fails_closed(self, db_session):
        """Every row's window has ended -> no price applies today -> 404."""
        repo = PricingRepository(db_session)
        await repo.create(
            provider="openai",
            model="gpt-3.5",
            input_per_million=Decimal("1.00"),
            output_per_million=Decimal("2.00"),
            effective_from=date(2020, 1, 1),
            effective_to=date(2020, 12, 31),
        )
        await repo.create(
            provider="openai",
            model="gpt-3.5",
            input_per_million=Decimal("1.50"),
            output_per_million=Decimal("3.00"),
            effective_from=date(2021, 1, 1),
            effective_to=date(2021, 12, 31),
        )
        await db_session.commit()
        with pytest.raises(ModelPricingNotFoundError):
            await repo.get_effective("openai", "gpt-3.5")

    async def test_all_future_dated_fails_closed(self, db_session):
        """Only future-dated rows exist -> no price applies today -> 404."""
        repo = PricingRepository(db_session)
        await repo.create(
            provider="openai",
            model="gpt-5",
            input_per_million=Decimal("5.00"),
            output_per_million=Decimal("20.00"),
            effective_from=date(2030, 1, 1),
        )
        await db_session.commit()
        with pytest.raises(ModelPricingNotFoundError):
            await repo.get_effective("openai", "gpt-5")

    async def test_expired_latest_version_does_not_shadow_active(self, db_session):
        """A newer-but-expired version must not win over an older active one."""
        repo = PricingRepository(db_session)
        await repo.create(
            provider="openai",
            model="gpt-4o-mini",
            input_per_million=Decimal("0.15"),
            output_per_million=Decimal("0.60"),
            effective_from=date(2024, 1, 1),
            effective_to=date(2024, 12, 31),  # v1: expired
        )
        await repo.create(
            provider="openai",
            model="gpt-4o-mini",
            input_per_million=Decimal("0.20"),
            output_per_million=Decimal("0.80"),
            effective_from=date(2025, 1, 1),  # v2: open-ended, active
        )
        await db_session.commit()
        price = await repo.get_effective("openai", "gpt-4o-mini")
        assert price.version == 2
        assert price.input_per_million == Decimal("0.20")
