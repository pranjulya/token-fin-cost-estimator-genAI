# Token Cost Estimator — FinOps service (vertical slice)

Estimate LLM cost before generation, track actual usage after, attribute spend,
and reconcile estimate vs actual — with Decimal-safe money math and frozen
pricing history.

**This is the vertical slice.** Budget enforcement, Redis counters, alerts, and
anomaly detection are the next phases (see `# Project 02` spec).

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · Alembic · PostgreSQL 14 ·
structlog · tiktoken · pytest

## Quick start (macOS, Homebrew Postgres already running)

```bash
# 1. Create the database (once)
psql -d postgres -c "CREATE DATABASE token_cost_estimator;"

# 2. Install deps + apply migrations + seed realistic OpenAI pricing
uv sync                       # or: uv pip install -e ".[dev]"
uv run alembic upgrade head
uv run python scripts/seed_pricing.py

# 3. Run
uv run uvicorn app.main:app --reload
# → http://127.0.0.1:8000/docs   (OpenAPI)
# → http://127.0.0.1:8000/health
```

Or use the Makefile: `make setup`, `make run`, `make test`, `make seed`.

## Try it

```bash
# Estimate cost (OpenAI-tiktoken real token count)
curl -X POST localhost:8000/v1/cost/estimate -H 'Content-Type: application/json' \
  -d '{"provider":"openai","model":"gpt-4o","input":"Explain microservices",
       "expected_output_tokens":200}'

# Record actual usage after the LLM call (supply real token counts from provider response)
curl -X POST localhost:8000/v1/usage -H 'Content-Type: application/json' \
  -d '{"request_id":"req_a1","provider":"openai","model":"gpt-4o",
       "actual_input_tokens":100,"actual_output_tokens":80,"team_id":"ml"}'

# Aggregations
curl localhost:8000/v1/usage/summary
curl localhost:8000/v1/cost/by-model
curl localhost:8000/v1/cost/by-endpoint
curl localhost:8000/v1/cost/by-team
```

## API surface

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/cost/estimate` | tokenize + price + estimate cost |
| POST | `/v1/usage` | record actual usage (idempotent on `request_id`) |
| GET | `/v1/usage` | list usage |
| GET | `/v1/usage/summary` | totals |
| GET | `/v1/cost/by-model` `/by-endpoint` `/by-team` | spend attribution |
| POST/GET | `/v1/models/pricing` | pricing admin (versioned) |
| GET | `/health` `/ready` | probes |

Errors follow one envelope: `{"error":{"code","message","request_id"}}`.

## Design highlights

- **Decimal-only money** — `src/app/utils/money.py`; per-million storage →
  per-token conversion; no binary floats (PRD # 21, ADR-001).
- **Pricing versioning** — every `usage_records` row stores `pricing_version`;
  history never re-prices (PRD # 20, ADR-005).
- **Abstractions** — `TokenCounter`, `PricingProvider`, pure `CostCalculator`:
  business logic never imports FastAPI or the DB driver (§13).
- **Idempotent usage ledger** — replaying `POST /v1/usage` with the same
  `request_id` returns the existing record (no double-count on retries).
- **Single provider for now** — OpenAI pricing seeded (`gpt-4o`, `gpt-4o-mini`,
  `gpt-4-turbo`, `o1-mini`).

## Tests

```bash
uv run pytest                 # 49 tests: unit + integration (real test DB)
```

`tests/conftest.py` points at the `token_cost_estimator_test` database
(created by `make test-db`) and truncates between tests.

## Layout

```
src/app/
  api/v1/        routes (cost, usage, pricing, health)
  core/          config, exceptions, logging
  db/            session, models
  domain/        pure domain (pricing, cost, usage)
  providers/     tokenizers (tiktoken), pricing (DB-backed)
  repositories/  pricing, usage
  schemas/       Pydantic request/response
  services/      cost_calculator, cost_estimator, usage, reconciliation, aggregation
  utils/money.py Decimal money
migrations/      Alembic
scripts/         seed_pricing.py
tests/           unit + integration
```

## Roadmap (next phases from the PRD)

1. Budget domain + Redis atomic counters/reservations → enforcement
   (`ALLOW/WARN/CRITICAL/BLOCK`).
2. Alerts + rule-based anomaly detection.
3. LLM provider adapter (service calls the LLM itself).
4. Observability (metrics/tracing), authN/authZ, rate limits.
5. Docker + CI.