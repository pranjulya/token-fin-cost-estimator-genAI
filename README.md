# Token Cost Estimator — FinOps service (vertical slice)

Estimate LLM cost before generation, track actual usage after, attribute spend,
and reconcile estimate vs actual — with Decimal-safe money math and frozen
pricing history.

**This is the vertical slice.** Budget enforcement, Redis counters, alerts, and
anomaly detection are the next phases (see `# Project 02` spec).

> **Budget preflight:** `POST /v1/cost/estimate` is **evaluate-only** — it returns
> a budget envelope (`ALLOW`/`WARN`/`CRITICAL`/`BLOCK`) but does **not** reserve
> spend or write budget events. `POST /v1/generate` (Phase 14–15) is the only
> path that reserves and settles.

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
| POST | `/v1/cost/estimate` | tokenize + price + estimate cost (evaluate-only budget envelope) |
| POST | `/v1/generate` | end-to-end: estimate → budget reserve → LLM call → record → settle (disabled unless `APP_GENERATE_ENABLED=true`) |
| POST | `/v1/usage` | record actual usage (idempotent on `request_id`) |
| GET | `/v1/usage` | list usage |
| GET | `/v1/usage/summary` | totals |
| GET | `/v1/cost/by-model` `/by-endpoint` `/by-team` | spend attribution |
| POST/GET | `/v1/models/pricing` | pricing admin (versioned) |
| POST/GET | `/v1/budgets` `/v1/budgets/{id}` | budget CRUD (TEAM/APPLICATION, MONTHLY/DAILY) |
| GET/POST | `/v1/alerts` `/v1/alerts/{id}/acknowledge` | budget-threshold + cost-anomaly alerts |
| GET | `/health` `/ready` | probes |

Errors follow one envelope: `{"error":{"code","message","request_id"}}`.

## Generating completions

`POST /v1/generate` is the only path that calls an LLM **and** the only path
that reserves **and** settles a budget. It is **off by default** — set these to
enable it:

```text
APP_GENERATE_ENABLED=true
APP_OPENAI_API_KEY=sk-...
APP_OPENAI_BASE_URL=          # optional, defaults to api.openai.com/v1
APP_OPENAI_TIMEOUT_SECONDS=60 # optional
```

- STRICT budget BLOCK → `403 BUDGET_EXCEEDED`, the LLM is never called.
- Provider failure → reservation is released and no SUCCESS usage row is written.
- Repeating a `request_id` → `409 GENERATION_ALREADY_RECORDED`; completion text
  is **not** stored — list `GET /v1/usage` and filter by `request_id` for money.
- After a 5xx, retry with a **new** `request_id`.
- Prompts and completions are never logged or persisted.

`POST /v1/usage` remains for clients that call an LLM themselves (ledger only —
it does not reserve or settle budgets).

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
uv run pytest                 # unit + integration (real test DB)
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

Implemented: Phases 0–13 (vertical slice, budgets with Postgres-atomic
reservations, alert system) and Phases 14–15 (`LLMProvider` Protocol + OpenAI
over httpx, and `POST /v1/generate` end-to-end reserve → call → settle).

Next:

1. Observability (metrics/tracing, Phase 16).
2. Security hardening: authN/authZ, rate limits, input size limits (Phase 17).
3. Docker + CI (Phases 19–20).