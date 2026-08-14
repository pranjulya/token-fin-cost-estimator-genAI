"""Unit tests for the Phase 17 in-memory rate limiter."""

from __future__ import annotations

from app.api.ratelimit import RateLimiter


def test_bucket_allows_initial_burst():
    rl = RateLimiter(per_minute=3, generate_per_minute=1)
    assert rl.allow(key="k", route="default")
    assert rl.allow(key="k", route="default")
    assert rl.allow(key="k", route="default")
    assert not rl.allow(key="k", route="default")


def test_generate_route_has_own_limit():
    rl = RateLimiter(per_minute=60, generate_per_minute=1)
    assert rl.allow(key="k", route="generate")
    assert not rl.allow(key="k", route="generate")
    # default route unaffected.
    assert rl.allow(key="k", route="default")


def test_keys_are_isolated():
    rl = RateLimiter(per_minute=1, generate_per_minute=1)
    assert rl.allow(key="a", route="default")
    assert not rl.allow(key="a", route="default")
    assert rl.allow(key="b", route="default")


def test_refill_over_time():
    rl = RateLimiter(per_minute=2, generate_per_minute=1)  # 2/min = 1/30s
    assert rl.allow(key="k", route="default")
    assert rl.allow(key="k", route="default")
    assert not rl.allow(key="k", route="default")  # exhausted
    # Simulate 31s passing -> ~1 token refilled (2/min => 1 per 30s).
    rl._buckets[("k", "default")].updated_at -= 31.0
    assert rl.allow(key="k", route="default")
