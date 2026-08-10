"""PricingProvider backed by the model_pricing repository."""

from __future__ import annotations

from app.domain.pricing import ModelPrice
from app.repositories.pricing_repository import PricingRepository


class DatabasePricingProvider:
    """Implements the PricingProvider protocol against Postgres."""

    def __init__(self, repository: PricingRepository):
        self._repository = repository

    async def get_pricing(self, provider: str, model: str) -> ModelPrice:
        return await self._repository.get_effective(provider, model)
