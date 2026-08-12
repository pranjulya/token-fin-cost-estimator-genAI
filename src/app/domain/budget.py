"""Budget domain — pure policy evaluation (PRD # 27).

No FastAPI/DB knowledge. Evaluates a spend decision from a budget's policy and
the current consumption counters. All money in ``Decimal`` (utils/money.py);
never binary float.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.utils.money import ZERO

ALLOW = "ALLOW"
WARN = "WARN"
CRITICAL = "CRITICAL"
BLOCK = "BLOCK"

STRICT = "STRICT"
ADVISORY = "ADVISORY"


@dataclass(frozen=True)
class BudgetDecision:
    status: str
    remaining_before: Decimal
    remaining_after: Decimal

    @property
    def allowed(self) -> bool:
        return self.status != BLOCK


def _fraction(used: Decimal, limit: Decimal) -> Decimal:
    if limit <= ZERO:
        return Decimal("1")  # zero/no limit degenerates to fully consumed
    return (used / limit).normalize()


def decide(
    *,
    limit: Decimal,
    committed: Decimal,
    reserved: Decimal,
    requested: Decimal,
    warning: Decimal,
    critical: Decimal,
    enforcement_mode: str,
) -> BudgetDecision:
    """Evaluate a request of ``requested`` against current consumption.

    Read the projected usage AFTER this request, then classify by fraction of
    the limit (PRD # 27 default policy, thresholds are caller-supplied):

        < warning      -> ALLOW
        < critical     -> WARN
        < 1.0 (100%)   -> CRITICAL
        >= 1.0         -> BLOCK (STRICT) or WARN (ADVISORY)
    """
    if requested < ZERO:
        raise ValueError("requested amount must be non-negative")
    if not (ZERO < warning <= critical <= Decimal("1")):
        raise ValueError("thresholds must satisfy 0 < warning <= critical <= 1")

    used_before = (committed + reserved).normalize()
    used_after = (used_before + requested).normalize()
    remaining_before = (limit - used_before).normalize()
    remaining_after = (limit - used_after).normalize()

    fraction = _fraction(used_after, limit)
    if fraction >= Decimal("1"):
        status = WARN if enforcement_mode == ADVISORY else BLOCK
    elif fraction >= critical:
        status = CRITICAL
    elif fraction >= warning:
        status = WARN
    else:
        status = ALLOW

    return BudgetDecision(
        status=status,
        remaining_before=remaining_before,
        remaining_after=remaining_after,
    )
