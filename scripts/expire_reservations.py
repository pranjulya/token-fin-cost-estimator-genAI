"""Reservation sweeper — release stale budget reservations.

A request reserves budget before the LLM call; if the process crashes after
reserve but before settle/release, the reservation leaks. This script finds
reservations older than RESERVATION_TTL (15 min) and releases them.

Dry-run by default: prints candidates without mutating. Pass --apply to
actually release (writes RELEASE budget events).

Usage:
    uv run python scripts/expire_reservations.py            # dry-run
    uv run python scripts/expire_reservations.py --apply    # release stale
    APP_DATABASE_URL=... uv run python scripts/expire_reservations.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.db.models import Budget, BudgetConsumption, BudgetEvent
from app.db.session import AsyncSessionLocal

RESERVATION_TTL_MINUTES = 15


def _stale_cutoff() -> datetime:
    return datetime.now(UTC) - timedelta(minutes=RESERVATION_TTL_MINUTES)


async def find_stale(session) -> list[tuple[BudgetConsumption, Budget]]:
    """Return (consumption, budget) rows with a stale reservation."""
    cutoff = _stale_cutoff()
    stmt = (
        select(BudgetConsumption, Budget)
        .join(Budget, Budget.id == BudgetConsumption.budget_id)
        .where(
            BudgetConsumption.reserved_amount > 0,
            BudgetConsumption.updated_at < cutoff,
        )
        .order_by(BudgetConsumption.updated_at)
    )
    result = await session.execute(stmt)
    return [(bc, b) for bc, b in result.all()]


async def release_stale(session, pairs) -> int:
    """Release the stale reservations (mutates). Returns number released."""
    released = 0
    for bc, budget in pairs:
        amount = bc.reserved_amount
        await session.execute(
            update(BudgetConsumption).where(BudgetConsumption.id == bc.id).values(reserved_amount=0)
        )
        session.add(
            BudgetEvent(
                budget_id=budget.id,
                event_type="RELEASE",
                period_key=bc.period_key,
                amount=amount,
                request_id=None,
                details={"sweeper": True, "reason": "stale"},
            )
        )
        released += 1
    await session.commit()
    return released


async def _run(apply: bool) -> int:
    async with AsyncSessionLocal() as session:
        stale = await find_stale(session)
        if not stale:
            print("No stale reservations found.")
            return 0
        for bc, budget in stale:
            print(
                f"stale: budget={budget.id} period={bc.period_key} "
                f"reserved={bc.reserved_amount} updated={bc.updated_at.isoformat()}"
            )
        if apply:
            n = await release_stale(session, stale)
            print(f"Released {n} stale reservation(s).")
        else:
            print(f"Dry-run: {len(stale)} candidate(s). Re-run with --apply to release.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Release stale budget reservations")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually release (default is a dry-run that only reports)",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.apply))


if __name__ == "__main__":
    sys.exit(main())
