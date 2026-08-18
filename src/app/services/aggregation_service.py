"""Aggregation service (PRD Phase 7). Thin wrapper over usage repository."""

from __future__ import annotations

from typing import Any

from app.repositories.usage_repository import UsageRepository


class AggregationService:
    def __init__(self, repository: UsageRepository):
        self._repository = repository

    async def summary(self) -> dict[str, Any]:
        return await self._repository.summary()

    async def by_model(self) -> list[dict[str, Any]]:
        return await self._repository.cost_by("model")

    async def by_endpoint(self) -> list[dict[str, Any]]:
        return await self._repository.cost_by("endpoint")

    async def by_team(self) -> list[dict[str, Any]]:
        return await self._repository.cost_by("team_id")
