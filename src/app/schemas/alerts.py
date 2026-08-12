"""Alert schemas (PRD §19, Phase 13)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import APIModel

ALERT_TYPES = {"BUDGET_THRESHOLD", "COST_ANOMALY"}
SEVERITIES = {"WARNING", "CRITICAL"}


class AlertOut(APIModel):
    id: int
    alert_type: str
    severity: str
    scope_type: str | None
    scope_id: str | None
    request_id: str | None
    message: str
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias="metadata_json",  # ORM attribute
        serialization_alias="metadata",  # JSON key matches PRD §19
    )
    dedupe_key: str
    created_at: datetime
    acknowledged_at: datetime | None
