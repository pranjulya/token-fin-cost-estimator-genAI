# ADR-006 — Fail closed when strict budget enforcement is unavailable

- **Status:** Accepted (implemented)
- **Date:** 2026-08-15
- **Related:** ADR-003

## Context

The product's core promise is "reject before LLM execution" to prevent
overspend. If budget state is missing/locked/errored, the system must decide
whether to let a request through (fail open) or reject it (fail closed).

## Decision

`POST /v1/generate` fails closed:

- `STRICT` budget + projected usage ≥ 100% → `403 BUDGET_EXCEEDED` **before the
  provider is called** (verified by the demo: mock LLM records zero calls on
  BLOCK).
- Budget row cannot be locked / budget lookup errors → the request surfaces a
  `5xx` and does **not** call the LLM.
- `ADVISORY` mode softens the policy (BLOCK becomes WARN) — that is an explicit
  admin choice, not an availability fallback.
- The reverse path (no budget configured) is an explicit admin decision too:
  `find_applicable` returning None means "unbounded", and the request proceeds.

## Consequences

- **Good:** a degraded budget system cannot silently overspend money.
- **Good:** `DECISION`/`RESERVE` events and threshold alerts are durable
  (mid-commit UoW1) even when the request is blocked.
- **Cost:** a budget-DB outage blocks spend-generation entirely (5xx) — the
  safe trade for a FinOps gate. Proven by
  `tests/integration/test_failure_modes.py`.
