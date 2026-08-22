# Interview Questions — self-test companion

Use these to check your understanding of the codebase before an interview or
as a study drill. Every answer is grounded in the code and docs — read the
linked source in [`README.md`](../README.md) and
[`docs/`](../docs/architecture.md) first, then try to answer from memory.

> The *why* behind each answer (and the trade-offs the code makes) is covered
> in the guided walkthrough. This file is the question bank; the walkthrough
> is the explanation.

## Money & correctness

1. **Why Decimal instead of float for costs?**
   Binary floats can't represent 0.1 exactly; accumulating float error in money
   is unacceptable. The service stores per-million rates as `Decimal`, converts
   via integer-safe division, and serializes money as JSON strings.

2. **How do you prevent budget overspend under concurrency?**
   A single `budget_consumption` row per (budget, period) is locked with
   `SELECT ... FOR UPDATE`; reserve reads the counter under the lock, so two
   concurrent reserves serialize. Proven by a real parallel test
   (`test_concurrent_reserves_cannot_overspend`).

3. **Why was Redis skipped for budget counters?**
   The Postgres `FOR UPDATE` approach gives the same race-free guarantee with
   zero extra infrastructure. Redis would add a fast-path counter with the
   same lock semantics for correctness; not worth it here.

4. **What happens when actual cost exceeds the estimate (`A > E`)?**
   `settle` uses `apply_overage`: it consumes exactly this request's reserved
   `E` and adds the full actual `A` to committed. Decrementing reserved by `A`
   would steal other in-flight reservations.

5. **Why is `POST /v1/cost/estimate` evaluate-only?**
   Reserving on every estimate leaked `reserved_amount` forever (nothing
   settled it) and estimate-then-generate would double-reserve. Estimate is a
   calculator; generate is the gate.

## Idempotency & reliability

6. **How is usage recording idempotent?**
   `usage_records.request_id` is unique. `record` returns the existing row on
   replay; `record_new` raises 409 instead, and maps the unique-violation to
   409 inside a savepoint so the outer transaction stays usable.

7. **A client retries generate after a 5xx — what happens?**
   If no usage row exists, it re-reserves and re-calls the LLM (accepted).
   Clients should send a new `request_id` after a 5xx. A 409 only fires when a
   usage row already exists.

8. **How do you keep `FOR UPDATE` from being held across the provider HTTP call?**
   Mid-commit: after reserve, `session.commit()` makes UoW1 durable and
   releases the lock before the LLM call. A second UoW persists usage + settle.

## Architecture

9. **How are providers decoupled?**
   Protocols (`TokenCounter`, `PricingProvider`, `LLMProvider`). Core services
   depend on the interfaces; the OpenAI SDK/httpx lives only in
   `providers/llm/openai_provider.py`. Swapping vendors never touches business
   logic.

10. **What's the layering?**
    Routes (thin) → services (orchestration, no sessions) → repositories
    (SQLAlchemy I/O) → Postgres, with a pure `domain/` layer that imports no
    framework.

11. **Why does generate need a mid-commit at all?**
    Without it, a BLOCK/provider-failure after reserve would roll back the
    `DECISION`/`RESERVE`/`RELEASE` audit and Phase 13 alerts (the request-scoped
    session rolls back on any exception). Mid-commit makes UoW1 durable.

12. **How does the error envelope stay uniform?**
    A single `AppError` hierarchy + global handlers render
    `{"error": {code, message, request_id}}`; even route-level 404s are wrapped
    by an `HTTPException` handler.

## Observability & security

13. **What's in a request log?**
    `request_completed` with request_id, correlation_id, endpoint, method,
    status, latency. Prompts/completions are never logged.

14. **What metrics does the service expose?**
    `llm_requests_total`, `llm_request_duration_seconds`,
    `llm_input/output_tokens_total`, `llm_cost_total`,
    `llm_estimated_cost_total`, `llm_budget_rejections_total`,
    `llm_cost_anomaly_total` — dims: provider/model/endpoint/status, no
    high-cardinality user ids.

15. **How is auth structured?**
    User keys for estimate/generate/usage/reads; admin keys (a superset) for
    budgets/alerts/pricing writes. Health/metrics stay open. Missing key → 401,
    wrong scope → 403.

16. **How are secrets protected in logs?**
    A structlog processor redacts keys matching
    `api_key/token/secret/password/authorization`; audit actors are key
    prefixes; `.env` is gitignored and dockerignored; CI greps for committed
    secrets.

17. **How does rate limiting protect spend?**
    In-memory per-key token buckets: `/v1/generate` is capped tighter
    (`APP_RATE_LIMIT_GENERATE_PER_MINUTE`, default 10) than usage/estimate.

## Alerts & reconciliation

18. **How does cost-anomaly detection work?**
    Rule-based: a new SUCCESS row's actual cost is compared to the historical
    average for (provider, model) — absolute floor, multiplier (≥50×), or
    estimate-variance (≥400%) — gated by `min_samples`.

19. **What happens if the alert subsystem fails?**
    Soft-fail: alert I/O runs in savepoints; failures are logged
    (`alert_emit_failed`) and the money transaction still commits. Tested.

20. **What are the alert types?**
    `BUDGET_THRESHOLD` (WARN/CRITICAL/BLOCK at reserve) and `COST_ANOMALY`,
    deduped by `dedupe_key`.

## Operations

21. **How do you run it in Docker?**
    `docker compose up --build` — app auto-migrates + seeds idempotent pricing,
    then serves; Postgres has a health check; `/health`/`/ready` gate startup.

22. **What does CI run?**
    checkout → uv sync → ruff → mypy → unit → integration+contract (Postgres
    service) → pip-audit → secrets scan → docker build.

23. **What's the Redis deviation and why?**
    PRD Phase 19 lists Redis; the service uses Postgres `FOR UPDATE` for budget
    atomicity, so Redis was intentionally omitted from compose.
