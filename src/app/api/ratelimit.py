"""In-memory per-key rate limiting (PRD Phase 17).

Token-bucket, process-local (resets on restart — acceptable without Redis).
Used to protect the money paths: /v1/generate (tight), /v1/usage + estimate.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends

from app.api.auth import get_api_key
from app.core.config import get_settings
from app.core.exceptions import RateLimitError

# Lazy-eviction guard: drop buckets untouched for this long.
_STALE_AFTER_SECONDS = 300.0


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class RateLimiter:
    """Per-key token buckets keyed by route name."""

    def __init__(self, per_minute: int, generate_per_minute: int) -> None:
        self._limits: dict[str, float] = {
            "default": float(per_minute),
            "generate": float(generate_per_minute),
        }
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._now = time.monotonic

    def _capacity(self, route: str) -> float:
        return self._limits.get(route, self._limits["default"])

    def _refill(self, b: _Bucket, capacity: float) -> None:
        now = self._now()
        elapsed = now - b.updated_at
        if elapsed > 0:
            b.tokens = min(capacity, b.tokens + elapsed * (capacity / 60.0))
            b.updated_at = now

    def allow(self, *, key: str, route: str = "default") -> bool:
        """Consume one token for (key, route); True if within limit."""
        capacity = self._capacity(route)
        now = self._now()
        k = (key, route)
        b = self._buckets.get(k)
        if b is None:
            b = _Bucket(tokens=capacity, updated_at=now)
            self._buckets[k] = b
        self._refill(b, capacity)
        if b.tokens >= 1.0:
            b.tokens -= 1.0
            return True
        return False

    def _evict_stale(self) -> None:
        now = self._now()
        stale = [k for k, b in self._buckets.items() if now - b.updated_at > _STALE_AFTER_SECONDS]
        for k in stale:
            del self._buckets[k]


@lru_cache
def _limiter() -> RateLimiter:
    s = get_settings()
    return RateLimiter(
        per_minute=s.rate_limit_per_minute,
        generate_per_minute=s.rate_limit_generate_per_minute,
    )


def rate_limit_dep(route: str = "default"):
    """Build a FastAPI dependency that rate-limits the resolved API key.

    Usage: ``Depends(rate_limit_dep("generate"))`` — the returned dependency
    also depends on ``get_api_key`` so it runs after auth and has the key.
    """

    def _dependency(key: str = Depends(get_api_key)) -> None:
        if not _limiter().allow(key=key, route=route):
            raise RateLimitError("Rate limit exceeded.")

    return _dependency
