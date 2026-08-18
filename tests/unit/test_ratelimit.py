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


def test_evict_stale_removes_old_buckets():
    rl = RateLimiter(per_minute=60, generate_per_minute=1)
    rl.allow(key="old", route="default")
    rl.allow(key="new", route="default")
    # Age only the "old" bucket beyond the stale window.
    rl._buckets[("old", "default")].updated_at -= 400.0
    rl._evict_stale()
    assert ("old", "default") not in rl._buckets
    assert ("new", "default") in rl._buckets


def test_retry_after_reports_seconds():
    rl = RateLimiter(per_minute=60, generate_per_minute=1)
    rl.allow(key="k", route="default")
    rl.allow(key="k", route="default")
    rl.allow(key="k", route="default")
    # Exhausted: retry_after should be >= 1s (60/60 = 1s per token).
    assert rl.retry_after(key="k", route="default") >= 1


def test_rate_limit_error_carries_retry_after():
    from app.core.exceptions import RateLimitError

    err = RateLimitError("Rate limit exceeded.", retry_after_seconds=6)
    assert err.status_code == 429
    assert err.code == "RATE_LIMITED"
    assert err.retry_after_seconds == 6
