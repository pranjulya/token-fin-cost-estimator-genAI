# Architecture

## System overview

A GenAI FinOps service (FastAPI + PostgreSQL) that estimates LLM cost before
execution, records actual usage, attributes spend, enforces budgets atomically,
and raises alerts. It never dials an LLM itself except through the
`POST /v1/generate` endpoint, which is the only path that reserves **and**
settles a budget.

## Layers

```
api/v1 routes ──> services ──> repositories ──> PostgreSQL
      │              │
      │              └──> domain (pure policy, no framework imports)
      └──> providers (TokenCounter, PricingProvider, LLMProvider)
```

| Layer | Files | Responsibility |
|---|---|---|
| `api/` | `routes_*.py`, `auth.py`, `ratelimit.py`, `middleware.py`, `handlers.py` | Thin HTTP layer: parse/validate, DI, auth, rate limits, error envelope |
| `core/` | `config.py`, `exceptions.py`, `logging.py`, `metrics.py`, `audit.py` | Settings, error model, structlog, Prometheus, audit events |
| `domain/` | `cost.py`, `pricing.py`, `usage.py`, `budget.py`, `alerts.py` | Pure dataclasses + policy. No FastAPI/SQLAlchemy imports |
| `services/` | `cost_estimator.py`, `budget_service.py`, `usage_service.py`, `generation_service.py`, `alert_service.py` | Orchestration. Services never hold a session |
| `repositories/` | `*_repository.py` | All SQLAlchemy I/O, including `FOR UPDATE` + savepoint primitives |
| `providers/` | `tokenizers/`, `pricing/`, `llm/` | Protocols + implementations (tiktoken, DB pricing, OpenAI via httpx) |
| `schemas/` | per-feature Pydantic models | Validation + Decimal-as-string JSON serialization |

### Provider abstractions

- `TokenCounter` — `count(model, text) -> int` (tiktoken, heuristic fallback).
- `PricingProvider` — `get_pricing(provider, model) -> ModelPrice` (DB-backed,
  versioned).
- `LLMProvider` — `complete(...) -> LLMCompletion` (OpenAI via httpx in v1).
  Business logic depends on these interfaces, never on vendor SDKs.

## Key flows

### Estimate (evaluate-only)

`POST /v1/cost/estimate` → tokenize → price → calculate → **evaluate** budget
(a non-locking snapshot decision) → return envelope. It never reserves, never
writes events, never fires alerts. BLOCK on estimate is still HTTP 200 —
estimate is a calculator, not a gate.

### Generate (the money loop)

```
request
  → tokenize + estimate cost (E)
  → find applicable budget (TEAM then APPLICATION)
  → reserve(E)                 # FOR UPDATE; writes RESERVE/DECISION event
  → session_commit()           # UoW1 durable; releases the row lock
  → LLM call (no DB lock held)
  → record_new(actuals)        # idempotent on request_id; writes usage row
  → settle(reserved=E, actual=A)  # consume E from reserved, add A to committed
  → response
```

- STRICT BLOCK → 403 before the provider is ever called.
- Provider failure → `release(E)`, mid-commit, re-raise 502.
- Concurrent duplicate `request_id` → loser gets 409 from `record_new`, then
  `release(E)` (no settle).

The mid-commit is deliberate (K3): holding `FOR UPDATE` across the OpenAI HTTP
call would serialize every other reserve on that period for up to the timeout.

## Why Postgres `FOR UPDATE` instead of Redis

The PRD originally called for Redis atomic counters, but this service uses a
Postgres `budget_consumption` row locked with `SELECT ... FOR UPDATE` plus a
savepoint insert-if-absent. It gives the same race-free guarantee with no
extra infrastructure; Redis was intentionally omitted from docker-compose.
This and the other key decisions are recorded as [Architecture Decision
Records](adr/).

## Concurrency guarantees

- Reserves serialize on the row lock; concurrent reserves can never overspend
  (proven by `tests/integration/test_concurrency.py`).
- `settle` always consumes **this request's** reserved amount `E` — never the
  larger actual `A` — so an over-budget actual cannot steal another in-flight
  reservation (`apply_overage`).
