# ADR-003 — Atomic budget reservations via Postgres `FOR UPDATE` (not Redis)

- **Status:** Accepted (implemented) — **deviation from the PRD**
- **Date:** 2026-08-15
- **Related:** ADR-002, ADR-006

## Context

Budget enforcement must never overspend under concurrency. The PRD originally
called for Redis atomic counters. A naive read-check-reserve sequence races:
two concurrent requests can both read `used=99`, both see room, and both
reserve.

## Decision

The budget's spend counter lives in one Postgres row per
(`budget_id`, `period_key`) in `budget_consumption`. Every reserve/commit/
release/settle runs `SELECT ... FOR UPDATE` on that row, evaluates the pure
domain policy, mutates under the lock, and commits. `Redis is intentionally
NOT used` — not in docker-compose, not in code.

## Consequences

- **Good:** the same race-free guarantee as a Redis counter with **zero extra
  infrastructure** and transactional durability (a reservation can't be lost
  in a crash).
- **Good:** reserve → mid-commit releases the lock before the LLM call, so a
  slow provider doesn't serialize other reserves.
- **Cost:** one write-hot row per budget period; fine at this scale, and a
  Redis fast-path counter remains a documented future option.
- **Proven by:** `tests/integration/test_concurrency.py`
  (`test_concurrent_reserves_cannot_overspend`).
