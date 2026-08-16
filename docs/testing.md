# Testing (Phase 18)

## Layers

| Layer | Where | Covers |
|---|---|---|
| Unit | `tests/unit/` | money math, cost calculator, tokenizer, budget domain, alerts domain, reconciliation, provider (mocked httpx), generation service (fakes), auth, rate limiter, redaction, middleware, metrics |
| Integration | `tests/integration/` | real Postgres: pricing versioning, estimate flow, usage ledger + idempotency, budget reserve/commit/release/settle, alert hooks + repo, generate flow, auth API, rate-limit API |
| Contract | `tests/contract/` | OpenAPI route/method surface, error-envelope shape, auth-required vs open routes |
| Concurrency | `tests/integration/test_concurrency.py` | real parallel sessions: reserves can't overspend, same-`request_id` generate single-winner, estimates don't contend |
| Failure-mode | `tests/integration/test_failure_modes.py` | alert soft-fail still commits money, `record_new` unique-race → 409 with usable session |
| Load smoke | `tests/integration/test_load_smoke.py` | 20 concurrent generates all 200 + 20 usage rows |

## The concurrency proof

`test_concurrent_reserves_cannot_overspend` fires 10 concurrent
`reserve(20)` against a 100 budget in separate sessions via `asyncio.gather`.
Because `decide()` BLOCKs at fraction >= 1.0, exactly 4 fit (reserved=80),
6 are BLOCKed, and the shared counter never exceeds the limit. This is the
product's core atomicity claim, proven under real parallelism (not sequential
awaits).

## Run

```bash
make test             # full suite (creates test DB if missing)
make test-unit        # tests/unit only
make test-integration # tests/integration + tests/contract (real Postgres)
make lint             # ruff check + format --check
make typecheck        # mypy src
make security-check   # pip-audit + secrets grep
```

Tests use a dedicated `token_cost_estimator_test` DB (see `tests/conftest.py`),
truncated between tests. CI runs the same commands in
`.github/workflows/ci.yml` with a Postgres service container.

## CI pipeline (Phase 20)

```
checkout → uv sync → ruff lint → mypy → unit tests → integration+contract
tests → pip-audit → secrets scan → docker build
```
