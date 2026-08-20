"""request_ledger — idempotency ledger covering reserve->settle (P2).

The usage_records.request_id unique constraint only protects the final record;
a crash after reserve (UoW1) but before record_new leaves the reservation
unbounded for retries. This row is written IN UoW1 (same transaction as the
RESERVE event), so a retry with the same key while IN_FLIGHT is rejected with
409 BEFORE any second reserve or provider call.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TimestampMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RequestLedger(Base, PKMixin, TimestampMixin):
    __tablename__ = "request_ledger"

    request_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    # IN_FLIGHT -> COMPLETED on success; the sweeper marks stale IN_FLIGHT -> FAILED.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="IN_FLIGHT")
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
