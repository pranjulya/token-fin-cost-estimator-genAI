# Token Cost Estimator — a production-shaped GenAI FinOps service

Estimate LLM cost before you call a model, enforce budgets atomically, track
actual spend, reconcile estimate vs actual, and alert on anomalies — with
Decimal-safe money math, frozen pricing history, and a strict security +
observability posture.

This is a **complete, production-shaped backend** — not a toy. It is built to be
read, run, and studied end-to-end.

---

## Who is this for?

- **Students & GenAI aspirants** — a real, deployable service you can clone,
  run, and study: layered architecture, provider protocols, Postgres `FOR
  UPDATE` concurrency, idempotency, observability, security hardening, CI.
- **Engineers evaluating a FinOps pattern** — the estimate → reserve → execute →
  settle loop with atomic budget enforcement is the core idea; the code is the
  reference.
- **Interview prep** — see [`Learning/`](Learning/) for a guided study path and
  a check-your-understanding Q&A.

> **Budget preflight:** `POST /v1/cost/estimate` is **evaluate-only** — it
> returns a budget envelope (`ALLOW`/`WARN`/`CRITICAL`/`BLOCK`) but does **not**
> reserve spend. `POST /v1/generate` is the only path that reserves **and**
> settles.

---

## What you'll learn from this repo

- **Decimal-safe money math** — never a float for money (`utils/money.py`,
  ADR-001).
- **Race-free budget enforcement** — one Postgres row locked with `FOR UPDATE`
  per budget period; concurrent reserves cannot overspend (proven by a real
  parallel test).
- **Idempotency across a money lifecycle** — a `request_ledger` covering
  reserve → settle, plus an `Idempotency-Key` header on generate.
- **Provider abstraction** — LLM / pricing / tokenizer sit behind `Protocol`s;
  swapping a vendor never touches business logic.
- **Versioned pricing** — history never re-prices (ADR-005).
- **Observability** — structured logs, correlation IDs, Prometheus metrics,
  lightweight span events.
- **Security hardening** — API-key auth with admin scope, hashed keys,
  rate limiting, input limits, log redaction, audit events, prod boot guard.
- **CI that means it** — mypy strict, ruff (B/UP/S), 80% coverage gate, tests
  against real Postgres, and a container smoke test.

---

## Quick start

### Docker (easiest)

```bash
docker compose up --build
# → http://localhost:8000/health
# → http://localhost:8000/docs   (OpenAPI, dev only)
```

Compose defaults: user key `dev-user-key`, admin key `dev-admin-key`
(header `X-API-Key`).

### Local (macOS/Linux, Postgres running)

```bash
make setup        # uv sync + create DBs + migrate + seed pricing
make run          # uvicorn on :8000
make demo         # the $10 team-budget walkthrough
```

Or step by step: `uv sync` → `uv run alembic upgrade head` →
`uv run python scripts/seed_pricing.py` → `uv run uvicorn app.main:app --reload`.

> `APP_SEED_PRICING=true` is the dev default in compose; production seeds
> explicitly. See [`docs/security.md`](docs/security.md) for the production
> compose overlay.

---

## Try it

```bash
# Estimate cost (real tiktoken token count, evaluate-only budget envelope)
curl -X POST localhost:8000/v1/cost/estimate -H 'Content-Type: application/json' \
  -d '{"provider":"openai","model":"gpt-4o","input":"Explain microservices",
       "expected_output_tokens":200}'

# Record actual usage after an LLM call (supply real token counts)
curl -X POST localhost:8000/v1/usage -H 'Content-Type: application/json' \
  -d '{"request_id":"req_a1","provider":"openai","model":"gpt-4o",
       "actual_input_tokens":100,"actual_output_tokens":80,"team_id":"ml"}'

# Aggregations
curl localhost:8000/v1/usage/summary
curl localhost:8000/v1/cost/by-model
curl localhost:8000/v1/cost/by-endpoint
curl localhost:8000/v1/cost/by-team
```

To actually **generate** completions (the full reserve → call → settle loop),
set `APP_GENERATE_ENABLED=true` and `APP_OPENAI_API_KEY=sk-...`.

---

## Architecture in 30 seconds

```
api/v1 routes ──> services ──> repositories ──> PostgreSQL
      │              │
      │              └──> domain (pure policy, no framework imports)
      └──> providers (TokenCounter, PricingProvider, LLMProvider)
```

- **Estimate** is a cheap calculator (tokenize → price → evaluate, no writes).
- **Generate** is the money loop: reserve `E` (`FOR UPDATE`) → mid-commit →
  LLM call (no DB lock held) → record actuals (idempotent) → settle.
- **Why Postgres, not Redis?** The PRD called for Redis counters, but a single
  locked Postgres row gives the same race-free guarantee with zero extra
  infrastructure. Documented in ADR-003.

Full detail: [`docs/architecture.md`](docs/architecture.md).

---

## API surface

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/cost/estimate` | tokenize + price + estimate (evaluate-only budget envelope) |
| POST | `/v1/generate` | end-to-end: estimate → reserve → LLM call → record → settle |
| POST | `/v1/usage` | record actual usage (idempotent on `request_id`) |
| GET | `/v1/usage` `/v1/usage/summary` | list + totals |
| GET | `/v1/cost/by-model` `/by-endpoint` `/by-team` | spend attribution |
| POST/GET | `/v1/models/pricing` | versioned pricing |
| POST/GET/PATCH | `/v1/budgets` `/v1/budgets/{id}` | budget CRUD (TEAM/APPLICATION) |
| GET/POST | `/v1/alerts` `/v1/alerts/{id}/acknowledge` | threshold + anomaly alerts |
| GET | `/metrics` `/health` `/ready` | ops probes |

Errors use one envelope: `{"error": {"code", "message", "request_id"}}`.

Full reference: [`docs/api.md`](docs/api.md).

---

## Tests & CI

```bash
make test        # unit + integration + contract (real Postgres)
make coverage    # + 80% coverage gate on src/app
make typecheck   # mypy --strict
make lint        # ruff (E, F, I, W, B, UP, S)
```

- **216 tests**, **90% coverage**, mypy strict, ruff B/UP/S.
- The concurrency proof: 10 parallel reserves against a $100 budget — exactly
  4 fit, 6 BLOCK, the counter never overspends.
- CI (`.github/workflows/ci.yml`) runs everything **and** boots the built
  container, curling `/health` + `/ready` + a 401 check.

---

## Docs

| Doc | Contents |
|---|---|
| [architecture](docs/architecture.md) | layers, provider abstractions, the estimate/generate flows |
| [adr](docs/adr/) | architecture decision records (Decimal money, fail-closed budget, …) |
| [api](docs/api.md) | full route reference, auth scopes, error envelope |
| [database](docs/database.md) | table-by-table design + money/idempotency rules |
| [security](docs/security.md) | keys, hashing, rate limits, redaction, audit, prod deploy |
| [observability](docs/observability.md) | logs, correlation IDs, metrics, spans |
| [testing](docs/testing.md) | test layers, the concurrency proof, CI pipeline |
| [production-scenarios](docs/production-scenarios.md) | failure/distributed cases |
| [demo](docs/demo.md) | the $10 team-budget walkthrough (`make demo`) |
| [roadmap](docs/roadmap.md) | next-quarter items (Redis rate limit, OTel, IdP, …) |
| [prd](docs/prd.md) | the original 22-phase PRD (source spec) |
| [Learning](Learning/) | study guide + interview Q&A |

---

## Project layout

```
src/app/
  api/v1/        routes (cost, usage, pricing, health, alerts, budgets, generate)
  core/          config, exceptions, logging, metrics, audit, version
  db/            session + models (usage, pricing, budgets, alerts, request_ledger)
  domain/        pure policy — no framework imports
  providers/     tokenizers (tiktoken), pricing (DB-backed), llm (httpx)
  repositories/  all SQLAlchemy I/O
  schemas/       Pydantic request/response
  services/      cost, budget, usage, generation, alert, aggregation
  utils/         Decimal money helpers
migrations/      Alembic
scripts/         seed_pricing.py, expire_reservations.py (sweeper), demo.py
tests/           unit + integration + contract + concurrency
docs/            architecture, api, security, observability, …
```

---

## Contributing

Open to contributions and questions. See
[`CONTRIBUTING.md`](CONTRIBUTING.md) — including a "for students" note.

## License

MIT — see [`LICENSE`](LICENSE).
