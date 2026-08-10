"""Pricing domain model (pure, no DB/FastAPI knowledge).

Prices are held per-million-token in ``Decimal``. Conversion to per-token and
cost math live in the cost calculator / money helpers so the domain stays dumb
data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ModelPrice:
    provider: str
    model: str
    currency: str
    input_per_million: Decimal
    output_per_million: Decimal
    version: int = 1
    cached_input_per_million: Decimal | None = None
    effective_from: date | None = None
    effective_to: date | None = None
