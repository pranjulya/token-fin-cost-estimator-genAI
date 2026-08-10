"""Data access for model_pricing."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ModelPricingNotFoundError
from app.db.models import ModelPricing
from app.domain.pricing import ModelPrice


class PricingRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_effective(self, provider: str, model: str) -> ModelPrice:
        """Return the currently-effective price for a model.

        Resolution: latest version among rows whose effective interval contains
        today. Falls back to the highest version if no interval matches (e.g.
        open-ended rows with only effective_from set).
        """
        today = date.today()
        stmt = (
            select(ModelPricing)
            .where(ModelPricing.provider == provider, ModelPricing.model == model)
            .order_by(ModelPricing.version.desc())
        )
        rows = (await self._session.scalars(stmt)).all()
        if not rows:
            raise ModelPricingNotFoundError(provider, model)

        for row in rows:
            if row.effective_from is not None and row.effective_from > today:
                continue
            if row.effective_to is not None and row.effective_to < today:
                continue
            return self._to_domain(row)

        # No interval matches today; prefer the most recent version.
        return self._to_domain(rows[0])

    async def list_all(self) -> list[ModelPricing]:
        stmt = select(ModelPricing).order_by(
            ModelPricing.provider, ModelPricing.model, ModelPricing.version
        )
        return list((await self._session.scalars(stmt)).all())

    async def create(
        self,
        *,
        provider: str,
        model: str,
        input_per_million: Decimal,
        output_per_million: Decimal,
        currency: str = "USD",
        cached_input_per_million: Decimal | None = None,
        effective_from: date | None = None,
        effective_to: date | None = None,
    ) -> ModelPricing:
        """Insert a new pricing row. If one exists for (provider, model), bump
        the version — preserving history (PRD # 20)."""
        latest = await self._latest_version(provider, model)
        version = latest.version + 1 if latest else 1
        row = ModelPricing(
            provider=provider,
            model=model,
            currency=currency,
            input_price_per_million=input_per_million,
            cached_input_price_per_million=cached_input_per_million,
            output_price_per_million=output_per_million,
            effective_from=effective_from or date.today(),
            effective_to=effective_to,
            version=version,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def _latest_version(self, provider: str, model: str) -> ModelPricing | None:
        stmt = (
            select(ModelPricing)
            .where(ModelPricing.provider == provider, ModelPricing.model == model)
            .order_by(ModelPricing.version.desc())
            .limit(1)
        )
        return await self._session.scalar(stmt)

    @staticmethod
    def _to_domain(row: ModelPricing) -> ModelPrice:
        return ModelPrice(
            provider=row.provider,
            model=row.model,
            currency=row.currency,
            input_per_million=row.input_price_per_million,
            output_per_million=row.output_price_per_million,
            version=row.version,
            cached_input_per_million=row.cached_input_price_per_million,
            effective_from=row.effective_from,
            effective_to=row.effective_to,
        )
