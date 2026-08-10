"""Seed realistic OpenAI pricing into the pricing registry.

Usage:
    uv run python scripts/seed_pricing.py            (dev DB)
    APP_DATABASE_URL=... uv run python scripts/seed_pricing.py
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from app.db import models  # noqa: F401
from app.db.base import Base  # noqa: F401 (register metadata)
from app.db.models import ModelPricing
from app.db.session import SyncSessionLocal

# provider -> model -> (input, cached_input, output) per 1M tokens USD.
PRICING: dict[str, dict[str, tuple[str, str | None, str]]] = {
    "openai": {
        # gpt-4o: input $2.50, cached $1.25, output $10.00 per 1M tokens
        "gpt-4o": ("2.50", "1.25", "10.00"),
        # gpt-4o-mini
        "gpt-4o-mini": ("0.15", "0.075", "0.60"),
        # gpt-4-turbo
        "gpt-4-turbo": ("10.00", "5.00", "30.00"),
        # o1-mini (no cached pricing exposed)
        "o1-mini": ("3.00", None, "12.00"),
    }
}


def main() -> None:
    with SyncSessionLocal() as session:
        for provider, models in PRICING.items():
            for model, (inp, cached, out) in models.items():
                # bump version if a row already exists for this model
                latest_version = (
                    session.execute(
                        select(func.max(ModelPricing.version)).where(
                            ModelPricing.provider == provider, ModelPricing.model == model
                        )
                    ).scalar()
                    or 0
                )
                session.add(
                    ModelPricing(
                        provider=provider,
                        model=model,
                        currency="USD",
                        input_price_per_million=inp,
                        cached_input_price_per_million=cached,
                        output_price_per_million=out,
                        effective_from=date.today(),
                        effective_to=None,
                        version=latest_version + 1,
                    )
                )
        session.commit()
    print(f"Seeded {sum(len(m) for m in PRICING.values())} pricing rows.")


if __name__ == "__main__":
    main()
