# Token Cost Estimator

A FinOps gateway for LLM calls. It estimates the cost of a request before it is sent, enforces team and
application budgets atomically in PostgreSQL, reconciles each estimate against actual provider usage,
and raises alerts on threshold breaches and cost anomalies.

[![CI](https://github.com/pranjulya/token-fin-cost-estimator-genAI/actions/workflows/ci.yml/badge.svg)](https://github.com/pranjulya/token-fin-cost-estimator-genAI/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![PostgreSQL 14+](https://img.shields.io/badge/PostgreSQL-14%2B-336791)
![mypy strict](https://img.shields.io/badge/mypy-strict-blue)
[![Coverage 89%](https://img.shields.io/badge/coverage-89%25-brightgreen)](docs/testing.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

> A budget check that runs *after* the provider call is an invoice, not a control. This service
> blocks an over-budget request before any money is spent.

## The problem

LLM spend is easy to start and hard to stop:

- **Overruns are found on the monthly bill.** Nothing stops a runaway job mid-month.
- **Concurrent requests race past the limit.** Two requests both see $1 left, and both spend it.
- **Estimates drift from reality.** Nobody compares predicted tokens with what the provider actually billed.
- **History gets rewritten.** A price change silently re-values last month's report.

## How it works

`POST /v1/cost/estimate` is **evaluate-only**. It tokenizes the input, prices it, and returns a
budget envelope (`ALLOW` / `WARN` / `CRITICAL` / `BLOCK`) without reserving anything.
`POST /v1/generate` is the guarded execution path: **reserve → call the provider → settle**.

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant Gateway as Token Cost Estimator
    participant DB as PostgreSQL (System of Record)
    participant LLM as LLM Provider (e.g. OpenAI)

    rect rgb(240, 248, 255)
    Note over Client,DB: Evaluate-Only Preflight (POST /v1/cost/estimate)
    Client->>Gateway: POST /v1/cost/estimate (prompt + expected tokens)
    Gateway->>Gateway: Tokenize input (tiktoken) + Calculate Cost
    Gateway->>DB: Read Budget State (Evaluate-only, no lock)
    Gateway-->>Client: 200 OK (Estimated Cost + Envelope: ALLOW / WARN / BLOCK)
    end

    rect rgb(255, 245, 238)
    Note over Client,LLM: Protected Generation (POST /v1/generate)
    Client->>Gateway: POST /v1/generate (Idempotency-Key + Prompt)
    Gateway->>DB: Lock Budget Row (SELECT ... FOR UPDATE)
    alt Budget Exceeded (STRICT)
        Gateway-->>Client: 403 Forbidden (BUDGET_EXCEEDED) - Provider never called
    else Budget Approved
        Gateway->>DB: Reserve Estimated Cost (state = RESERVED)
        Gateway->>LLM: Dispatch completion call
        LLM-->>Gateway: Return response + actual token counts
        Gateway->>DB: Settle Budget with actual cost (state = SETTLED)
        Gateway->>DB: Insert immutable usage_records row
        Gateway-->>Client: 200 OK (Completion response + reconciled spend)
    end
    end
```

| Capability | Implementation | Why it matters |
|---|---|---|
| Exact money math | `Decimal` fixed-point arithmetic (`src/app/utils/money.py`), serialized as strings | No binary floating-point drift across many small charges |
| Atomic budget reservation | PostgreSQL `SELECT ... FOR UPDATE` on the budget period row | Concurrent requests cannot both spend the last dollar |
| Leaked-reservation recovery | `scripts/expire_reservations.py` (dry-run by default, `--apply` to release); run it on a schedule | A crash between reserve and settle does not shrink the budget until the period ends |
| Immutable pricing history | Every usage record stores its `pricing_version` | Past reports stay correct after a price change |
| No prompt persistence | Prompt and completion text are processed in memory and never written to the database | Spend data can be shared without exposing content |
| Ports and adapters | `TokenCounter`, `PricingProvider` and `LLMProvider` sit behind `Protocol` interfaces | You can add a provider without touching the budget logic |

## See it work (no API key, no cost)

```bash
make setup     # install, create databases, migrate, seed pricing
make demo      # three scenarios against an in-process mock LLM
```

```text
== Beat 1: Normal request ==
  [estimate] status=200 budget=ALLOW cost=0.0010175
  [usage] status=201 actual_cost=0.0003375 variance=0.0003375

== Beat 2: Large request (blocked before provider) ==
  [estimate] status=200 budget=BLOCK
  [generate] status=403 code=BUDGET_EXCEEDED

== Beat 3: Multiple requests -> threshold + alert ==
  [summary] requests=7 cost=0.0023625000
  [by-model] model=gpt-4o cost=0.0023625000
  [alerts] count=1
  [ack] alert_id=1 -> 200
```

In beat 2 the request is rejected with `403` **before** the provider is called. The demo asserts that
the mock LLM receives zero calls. The demo resets its schema on every run, so it uses a throwaway
`<your_db_name>_demo` database and never touches your main one. Run `make setup` first, or point
`APP_DATABASE_URL` at your Postgres.

## Quickstart

### Docker Compose

Starts the API and PostgreSQL 14 with health checks and idempotent pricing seeding:

```bash
git clone https://github.com/pranjulya/token-fin-cost-estimator-genAI.git
cd token-fin-cost-estimator-genAI
docker compose up --build
```

- OpenAPI docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health> and `/ready`
- Prometheus metrics: <http://localhost:8000/metrics>
- Dev keys: `dev-user-key` (standard) and `dev-admin-key` (admin endpoints)

### Local development (macOS / Linux)

Requires Python 3.12, PostgreSQL 14+ and [uv](https://docs.astral.sh/uv/). On Windows, use Docker Compose or WSL2.

```bash
make setup     # install dependencies, create databases, migrate, seed pricing
make run       # dev server on :8000 with auto-reload
```

`make setup` runs `psql` as your OS user with no password. If your Postgres needs a password, or runs
somewhere else, export `PGHOST`/`PGUSER`/`PGPASSWORD` for `psql` and set both URLs first:

```bash
export APP_DATABASE_URL=postgresql+psycopg://USER:PASS@localhost:5432/token_cost_estimator
export TEST_DATABASE_URL=postgresql+psycopg://USER:PASS@localhost:5432/token_cost_estimator_test
export APP_API_KEYS=dev-user-key APP_ADMIN_API_KEYS=dev-admin-key
```

`make run` needs `APP_API_KEYS` and `APP_ADMIN_API_KEYS` (or a `.env` copied from `.env.example`).
Without keys, every `/v1` call returns `401`.

> **Token counting needs a one-time download.** `tiktoken` fetches its encoding files on first use, and
> the Docker image bakes them in. For a local install, run `make run` once with internet access. If the
> download fails, the service falls back to an estimate of about 4 characters per token and logs a
> `tiktoken_unavailable_using_heuristic` warning. It never fails the request.

## API examples

<!-- Every curl block below is executed in CI by scripts/readme_smoke.py. Keep them runnable. -->

All `/v1/*` routes require an `X-API-Key` or `Authorization: Bearer <key>` header.

### 0. Create a Budget (admin key, one time)

Without a budget, the estimate returns `"budget": {"status": "ENABLED", ...}` with no limits. Create a $10 monthly STRICT budget for the `analytics` team first:

```bash
curl -X POST http://localhost:8000/v1/budgets \
  -H "X-API-Key: dev-admin-key" \
  -H "Content-Type: application/json" \
  -d '{"scope_type": "TEAM", "scope_id": "analytics", "period_type": "MONTHLY",
       "limit_amount": "10.00", "enforcement_mode": "STRICT"}'
```

### 1. Pre-flight Cost Estimation
Tokenize prompt and calculate cost against current active model rates. The budget is evaluated but nothing is reserved:

<!-- smoke-shape -->
```bash
curl -X POST http://localhost:8000/v1/cost/estimate \
  -H "X-API-Key: dev-user-key" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "openai",
    "model": "gpt-4o",
    "input": "Analyze quarterly cloud spend and generate executive summary.",
    "expected_output_tokens": 500,
    "team_id": "analytics"
  }'
```

```json
{
  "request_id": "req_...",
  "provider": "openai",
  "model": "gpt-4o",
  "estimated_input_tokens": 10,
  "estimated_output_tokens": 500,
  "estimated_input_cost": "0.000025",
  "estimated_cached_input_cost": "0",
  "estimated_output_cost": "0.005",
  "estimated_total_cost": "0.005025",
  "currency": "USD",
  "pricing_version": 1,
  "budget": {
    "status": "ALLOW",
    "remaining_before_request": "10",
    "remaining_after_estimate": "9.994975"
  }
}
```

`estimated_input_tokens` is exact (tiktoken) when the encoding files are available. In the heuristic fallback it is about 4 characters per token, so you may see 16 instead of 10 for this prompt. The numbers above are illustrative; request IDs and token counts vary.

### 2. End-to-End Generation (Atomic Budget Lock)
Executes budget reservation, makes the LLM call, records actual usage, and settles spend.

This endpoint spends real money, so it is **off by default** (`GENERATION_DISABLED` error). To enable it, set `APP_GENERATE_ENABLED=true` and `APP_OPENAI_API_KEY=sk-...` (for Docker Compose, edit the `app` service environment in `docker-compose.yml`), then restart. Use `make demo` to see the full flow with a mock LLM and no key.

<!-- smoke-expect: 503 GENERATION_DISABLED -->
```bash
curl -X POST http://localhost:8000/v1/generate \
  -H "X-API-Key: dev-user-key" \
  -H "Idempotency-Key: req_gen_01" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "openai",
    "model": "gpt-4o",
    "input": "Explain raft consensus in two sentences.",
    "max_output_tokens": 100,
    "team_id": "analytics"
  }'
```

### 3. Spend Attribution Analytics
Retrieve multi-dimensional spend aggregations:

```bash
# Spend by Model
curl http://localhost:8000/v1/cost/by-model -H "X-API-Key: dev-user-key"

# Spend by Team
curl http://localhost:8000/v1/cost/by-team -H "X-API-Key: dev-user-key"

# Global Usage Summary
curl http://localhost:8000/v1/usage/summary -H "X-API-Key: dev-user-key"
```

The full reference is in [`docs/api.md`](docs/api.md).

## Observability

Prometheus metrics are exposed at `/metrics`:

| Metric | Type | Labels |
|---|---|---|
| `llm_requests_total` | Counter | `provider`, `model`, `endpoint`, `status` |
| `llm_request_duration_seconds` | Histogram | `provider`, `model`, `endpoint`, `status` |
| `llm_input_tokens_total`, `llm_output_tokens_total` | Counter | provider and model |
| `llm_cost_total`, `llm_estimated_cost_total` | Counter | provider and model |
| `llm_budget_rejections_total` | Counter | `provider`, `model`, `reason` |
| `llm_cost_anomaly_total` | Counter | provider and model |

Structured logs (JSON in production, readable console output in development) carry a `request_id` and `correlation_id` on every line. See [`docs/observability.md`](docs/observability.md).

## Security

- **Two key scopes.** `user` keys call the API; `admin` keys also manage pricing, budgets and alerts.
  Empty keys do **not** disable auth.
- **Hashed keys (optional).** With `APP_AUTH_HASH_KEYS=true`, configuration stores only SHA-256 digests.
- **Rate limits.** A per-key token bucket (`APP_RATE_LIMIT_PER_MINUTE`, `APP_RATE_LIMIT_GENERATE_PER_MINUTE`).
- **Log redaction.** A structlog processor replaces secret-shaped values with `[REDACTED]`.
- **Generation is off by default.** `/v1/generate` spends real money, so it needs `APP_GENERATE_ENABLED=true` and a provider key.

Details are in [`docs/security.md`](docs/security.md).

## Key engineering decisions

| Decision | Record |
|---|---|
| Money is `Decimal`; IEEE-754 floats are banned from financial math | [ADR-001](docs/adr/ADR-001-decimal-money.md) |
| PostgreSQL is the system of record for the ledger and budgets | [ADR-002](docs/adr/ADR-002-postgres-system-of-record.md) |
| `FOR UPDATE` row locks instead of Redis counters, to avoid dual-write inconsistency | [ADR-003](docs/adr/ADR-003-postgres-for-update-not-redis.md) |
| Pricing providers are decoupled from estimation | [ADR-004](docs/adr/ADR-004-pricing-provider-separated.md) |
| Each usage record snapshots its pricing version | [ADR-005](docs/adr/ADR-005-pricing-version-on-usage.md) |
| Budgets fail closed when state is uncertain | [ADR-006](docs/adr/ADR-006-fail-closed-budget.md) |
| Raw prompts are never persisted | [ADR-007](docs/adr/ADR-007-no-raw-prompt-persistence.md) |

## Quality

```bash
make lint            # ruff check + ruff format --check
make typecheck       # mypy strict
make test            # unit, integration and contract tests against real Postgres
make coverage        # gate: 80% (currently about 89%)
make security-check  # dependency audit and committed-secret scan
```

CI also boots the Docker image and runs every `curl` example in this README against it
(`scripts/readme_smoke.py`), so the documentation cannot silently drift from the API.

## Project layout

```
token-fin-cost-estimator-genAI/
├── src/app/
│   ├── api/v1/          # FastAPI route handlers & dependency injection
│   ├── core/            # App configuration, structured logging, exceptions
│   ├── db/              # SQLAlchemy 2.0 async engine, models, & base schemas
│   ├── domain/          # Pure business logic (Cost, Pricing, Usage models)
│   ├── providers/       # Tokenizers (tiktoken), Pricing providers, LLM clients
│   ├── repositories/    # Database access layers (Usage, Budget, Pricing)
│   ├── schemas/         # Pydantic v2 request/response contracts
│   ├── services/        # Orchestration (CostEstimator, BudgetService, Reconciler)
│   └── utils/           # Financial Decimal math helpers
├── docs/                # Architecture docs, PRD, production scenarios, & ADRs
├── migrations/          # Version-controlled Alembic schema migrations
├── scripts/             # Seed data, benchmark helpers, and interactive demo
├── tests/
│   ├── unit/            # Fast, isolated domain logic tests
│   ├── integration/     # Database-backed repository and service tests
│   └── contract/        # HTTP API envelope and status code tests
├── .github/             # GitHub Actions CI workflows, issue & PR templates
├── Dockerfile           # Multi-stage production container image
├── docker-compose.yml   # Dev orchestration with PostgreSQL 14
└── pyproject.toml       # Modern Python packaging with uv and hatchling
```

## Limitations

- **One provider.** Only OpenAI tokenization and generation are implemented. Other models fall back to
  the heuristic token estimate.
- **The reservation sweeper is not scheduled for you.** Run `scripts/expire_reservations.py --apply`
  from cron or a job runner.
- **Rate limits are per process.** The in-memory token bucket does not coordinate across replicas.

## Documentation

[PRD](docs/prd.md) · [Architecture](docs/architecture.md) · [Database](docs/database.md) ·
[API](docs/api.md) · [Production scenarios](docs/production-scenarios.md) ·
[Reservation sweeper](docs/reservation-sweeper.md) · [Testing](docs/testing.md) ·
[Roadmap](docs/roadmap.md) · [ADRs](docs/adr/README.md) · [Learning guide](Learning/README.md) ·
[Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md)

## License

[MIT](LICENSE)
