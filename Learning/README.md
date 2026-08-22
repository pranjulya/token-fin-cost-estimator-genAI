# Study Guide — learn this codebase end-to-end

This folder is a guided path through the codebase: **WHAT → WHY → HOW → WHAT
CAN FAIL → HOW TO TEST → HOW IT SCALES → ALTERNATIVES**. Work through the
concepts in order and read the linked source as you go — the code is the real
teacher.

## How to use this

1. **Read** each concept below and open the linked files.
2. **Run** the service (`make demo` or the [quick start](../README.md)) and
   watch the money loop: estimate → reserve → LLM → record → settle.
3. **Break it** deliberately: BLOCK a budget, replay an `Idempotency-Key`,
   kill the process mid-reserve and run `scripts/expire_reservations.py`.
4. **Self-test** with [`interview-questions.md`](interview-questions.md) — the
   answers are in the code and docs.

## Concepts, in build order

1. **Tokenization** — BPE token counting (`tiktoken`), heuristic fallback.
   `providers/tokenizers/`.
2. **LLM pricing** — per-million-token `Decimal` rates, effective-date
   versioning. `providers/pricing/`, `migrations/`.
3. **Decimal-safe money math** — no binary floats; per-token conversion,
   quantized totals. `utils/money.py`, `services/cost_calculator.py`.
4. **Pricing registry** — versioned `model_pricing`; history never re-prices.
5. **Cost estimation** — tokenize → price → calculate, before execution.
6. **Usage tracking** — idempotent `usage_records` ledger, `request_id` unique.
7. **Reconciliation** — estimate-vs-actual variance stored per row.
8. **Postgres data modeling** — `Numeric` money, indexes, append-only audit.
9. **Budget management** — STRICT/ADVISORY policy, thresholds, windows.
10. **Atomic reservations** — `SELECT ... FOR UPDATE` + savepoint insert; the
    Redis alternative that was deliberately skipped (ADR-003).
11. **Reservation lifecycle** — reserve → mid-commit → settle/release.
12. **Idempotency across the money lifecycle** — `request_ledger` +
    `Idempotency-Key` header (the P2 hardening).
13. **Cost aggregation** — group-by dimensions (model/team/endpoint).
14. **Anomaly detection** — rule-based baselines + variance thresholds.
15. **Observability** — structured logs, correlation IDs, Prometheus, spans.
16. **Security** — API-key auth, admin scope, hashed keys, rate limits,
    redaction, audit.

## Interview Q&A

[`interview-questions.md`](interview-questions.md) is the check-your-
understanding companion. It is deliberately public — use it to self-test. For
a guided walkthrough that explains the *why* behind each answer, join the
[course/workshop]. *(Link optional — this is the paid funnel.)*
