"""PricingProvider abstraction (PRD FR-03 / §13).

Business logic depends on this interface, never on concrete storage.
The stack is async, so the contract is an async ``get_pricing``.
"""

from __future__ import annotations

from typing import Protocol

from app.domain.pricing import ModelPrice


class PricingProvider(Protocol):
    async def get_pricing(self, provider: str, model: str) -> ModelPrice:
        """Return the currently-effective price for a provider/model.

        Raises ModelPricingNotFoundError when no matching configuration exists.
        """
        ...
