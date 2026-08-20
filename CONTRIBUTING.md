# Contributing

Thanks for considering a contribution! This is a FastAPI + PostgreSQL FinOps
service — estimate LLM cost before execution, track actual usage, enforce
budgets atomically, and alert on anomalies.

## Setup

```bash
make setup        # uv sync + create DBs + migrate + seed pricing
make run          # dev server on :8000
make demo         # the $10 team-budget portfolio walkthrough
```

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), PostgreSQL 14.

## Checks before you open a PR

The CI pipeline runs these — run them locally first:

```bash
make lint          # ruff check + format
make typecheck     # mypy --strict on src
make test          # full suite (unit + integration + contract, real Postgres)
make coverage      # same tests with the 80% coverage gate on src/app
make security-check # pip-audit + committed-secret grep
```

Pre-commit hooks run the fast checks automatically:

```bash
pre-commit install
```

## Branch + PR flow

1. Branch off `main`: `git checkout -b fix/your-change` (or `feat/`).
2. Make small, focused changes; one concern per PR.
3. Run the checks above.
4. Open a PR against `main` with a summary of what + why.

## Conventions

- **Money is `Decimal`**, serialized as strings — never float (ADR-001).
- **Layers:** routes are thin → services orchestrate (no sessions) →
  repositories own SQLAlchemy I/O. New logic follows the same split.
- **Providers** (LLM, pricing, tokenizer) sit behind `Protocol`s — a new
  vendor is a new implementation, not a change to business logic.
- **Tests:** unit tests in `tests/unit`, real-Postgres integration in
  `tests/integration`, API-shape in `tests/contract`. New behavior ships with
  tests.
- **Idempotency:** `POST /v1/generate` is guarded by the `request_ledger`
  (reserve→settle) + the `usage_records.request_id` unique constraint. Retries
  must reuse the `Idempotency-Key` header.
- **Secrets** never go in the repo: `.env` is gitignored; keys come from env
  (optionally `sha256`-hashed via `APP_AUTH_HASH_KEYS`).
