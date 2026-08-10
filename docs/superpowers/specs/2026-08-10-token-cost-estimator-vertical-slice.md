# Vertical Slice — GenAI Token Cost Estimator

**Date:** 2026-08-10
**Status:** Approved
**Parent spec:** `# Project 02 — GenAI Token Cost Estimato.md` (the full 22-phase PRD)
**Scope decision:** Build the core money path first as one runnable vertical slice. Defer Redis budget counters, budget reservations, alerts, anomaly ML, provider dialing, Docker, and CI to later phases.

---

## 1. Goal

A production-quality, runnable FastAPI service that answers the first four questions of the PRD:

1. Estimate the cost of an LLM request before execution.
2. Track actual usage after execution.
3. Attribute spend (model / endpoint / team / application).
4. Reconcile estimate vs actual.

Budget enforcement, alerting, and anomaly detection are deliberately out of scope for this slice (they arrive with the budget phase).

## 2. In scope / out of scope

**In scope:**
- Repo foundation (pyproject, uv env, config, logging, health/ready).
- Pricing registry: `model_pricing` table, admin pricing APIs, seed script with realistic OpenAI rates.
- Token counting via `tiktoken` (OpenAI BPE), with a deterministic fallback tokenizer.
- Pure Decimal `CostCalculator` (input / cached-input / output / total).
- `POST /v1/cost/estimate` (tokenize → price → calculate → return envelope with stubbed budget fields).
- Usage ledger: `usage_records` table, `POST /v1/usage` (idempotent on `request_id`), `GET /v1/usage`.
- Aggregation APIs: `GET /v1/usage/summary`, `GET /v1/cost/by-model|by-endpoint|by-team`.
- Reconciliation: estimate-vs-actual variance computed at usage-record time.
- Pricing versioning: a `pricing_version` is stamped on every usage record so historical cost never changes when pricing updates.
- Unit + integration tests against a real Postgres test DB.
- Alembic migrations.
- README + Makefile.

**Out of scope (later phases):**
- Redis (budget counters/reservations), budgets, enforcement, alerts, anomaly detection.
- Actual provider dialing (this service receives real token counts from the caller).
- Docker, CI/CD, authN/authZ, rate limiting, tracing.
- Multiple providers (OpenAI only for now; the interface supports more later).

## 3. Environment decision (differs from PRD)

- Native **PostgreSQL 14** (Homebrew, already running) — a dedicated `token_cost_estimator` database.
- **uv**-managed **Python 3.12**.
- **No Docker** for this slice; Docker + Redis arrive with the budget phase.
- Unrelated existing DB (`mistreal-stream-gateway`) is never touched.

## 4. Architecture & components

Business logic depends on abstractions (PRD §11, §13). Core domain has no FastAPI/DB knowledge.

```
client → API layer → CostEstimator → TokenCounter (provider impl)
                              └──→ PricingProvider (DB impl) → repository → Postgres
client → API layer → UsageService → ReconciliationService → PricingProvider → repository
                              └──→ AggregationService → repository
```

### Components

- **API layer** — HTTP parsing, Pydantic validation, error translation. No cost logic.
- **TokenCounter** — `count(model: str, text: str) -> int`. OpenAI impl uses `tiktoken`; fallback estimates chars/4.
- **PricingProvider** — `get_pricing(provider: str, model: str) -> ModelPricing`. DB-backed.
- **CostCalculator** — pure function, `Decimal` only, no deps.
- **CostEstimator** — orchestrates tokenizer → pricing → calculator.
- **ReconciliationService** — computes absolute/percentage variance between estimate and actual.
- **AggregationService** — SQL group-by queries.
- **PricingRepository / UsageRepository** — data access.

## 5. Contracts

```python
class TokenCounter:
    def count(self, model: str, text: str) -> int: ...

class PricingProvider:
    def get_pricing(self, provider: str, model: str) -> ModelPricing: ...

# CostCalculator — pure, returns a CostBreakdown:
#   input_cost, cached_input_cost, output_cost, total_cost  (Decimal, currency-quantized)
```

## 6. Data model (Postgres)

### `model_pricing`
`id`, `provider`, `model`, `input_price_per_million`, `cached_input_price_per_million`, `output_price_per_million`, `currency`, `effective_from`, `effective_to` (nullable), `version`, `created_at`, `updated_at`. Unique on `(provider, model, version)` / effective range.

### `usage_records`
`id`, `request_id` (unique, idempotency key), `correlation_id`, `provider`, `model`, `application_id`, `team_id`, `user_id`, `endpoint`, `environment`, `estimated_input_tokens`, `estimated_output_tokens`, `estimated_cost`, `actual_input_tokens`, `cached_input_tokens`, `actual_output_tokens`, `actual_cost`, `pricing_version`, `status`, `started_at`, `completed_at`, `created_at`.

**Pricing versioning:** `actual_cost` is computed with the pricing version effective at write time, and `pricing_version` is stored. Historical records therefore never re-price.

## 7. API surface

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/cost/estimate` | tokenize + price + calculate; budget envelope stub |
| POST | `/v1/usage` | record actual usage (idempotent on `request_id`) |
| GET | `/v1/usage` | list usage records |
| GET | `/v1/usage/summary` | aggregated totals |
| GET | `/v1/cost/by-model` | spend by model |
| GET | `/v1/cost/by-endpoint` | spend by endpoint |
| GET | `/v1/cost/by-team` | spend by team |
| POST | `/v1/models/pricing` | admin: upsert pricing |
| GET | `/v1/models/pricing` | list pricing |
| GET | `/health` | liveness |
| GET | `/ready` | readiness (checks DB) |

Error envelope (PRD §30): `{"error": {"code": "...", "message": "...", "request_id": "..."}}`.

## 8. Money safety

`utils/money.py` provides Decimal helpers: per-million → per-token conversion, currency quantization. **All money paths use `Decimal`; binary `float` is forbidden for money.** Prices are stored per-million-token; domain converts to per-token in `Decimal`.

## 9. Idempotency (design addition)

`POST /v1/usage` dedupes on `request_id`: a second POST with the same `request_id` returns the existing record rather than double-counting. This handles the PRD's "LLM succeeded but persistence retried" failure mode (PRD §37 Scenario 8) without double-charging.

## 10. Error handling

Standard error codes: `VALIDATION_ERROR`, `MODEL_PRICING_NOT_FOUND`, `MODEL_NOT_SUPPORTED`, `TOKENIZATION_FAILED`, `USAGE_RECONCILIATION_FAILED`, `DATABASE_ERROR`, `INTERNAL_ERROR`. Exceptions map to the envelope via an exception handler.

## 11. Testing

- **Unit:** cost calculator (zero tokens, huge counts, unknown model, missing pricing, cached tokens, zero output, negative rejected, boundary decimals), money helpers, tokenizer (empty/unicode/long/fallback).
- **Integration (real Postgres test DB):** pricing repo CRUD + versioning, estimate flow end-to-end, usage persistence + idempotency, aggregation queries.

## 12. Definition of done (slice)

- `POST /v1/cost/estimate` returns accurate Decimal cost with budget envelope stub.
- `POST /v1/usage` persists actual usage, dedupes on retry, computes reconciliation variance, freezes pricing version.
- Aggregation endpoints return correct group-bys.
- Pricing admin + seed produce realistic OpenAI rates.
- Unit + integration tests green against real Postgres.
- `make test`, `make run`, `make seed` all work; README documents it.
