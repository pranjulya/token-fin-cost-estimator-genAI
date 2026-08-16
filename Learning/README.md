# Learning Path (PRD §38 / §39)

The PRD's learning-first rule: every major concept is understood as
**WHAT → WHY → HOW → WHAT CAN FAIL → HOW TO TEST → HOW IT SCALES → ALTERNATIVES → INTERVIEW**.

## Concepts, in build order

1. **Tokenization** — BPE token counting (`tiktoken`), heuristic fallback for
   unknown models. See `providers/tokenizers/`.
2. **LLM pricing** — per-million-token rates stored as `Decimal`, effective-date
   versioning. See `providers/pricing/`, `migrations/`.
3. **Decimal-safe cost math** — no binary floats; per-token conversion and
   quantized totals. See `utils/money.py`, `services/cost_calculator.py`.
4. **Pricing registry** — versioned `model_pricing`, history never re-prices.
5. **Cost estimation** — tokenize → price → calculate, before execution.
6. **Usage tracking** — idempotent `usage_records` ledger, `request_id` unique.
7. **Reconciliation** — estimate-vs-actual variance stored per row.
8. **Postgres data modeling** — Numeric money, indexes, append-only audit.
9. **Budget management** — STRICT/ADVISORY policy, thresholds, windows.
10. **Atomic reservations** — `SELECT ... FOR UPDATE` + savepoint insert;
    the Redis alternative that was deliberately skipped.
11. **Reservation lifecycle** — reserve → mid-commit → settle/release.
12. **Cost aggregation** — group-by dimensions (model/team/endpoint).
13. **Anomaly detection** — rule-based baselines + variance thresholds.
14. **Observability** — structured logs, correlation IDs, Prometheus, spans.
15. **Security** — API-key auth, admin scope, rate limits, redaction, audit.

See `interview-questions.md` for the Q&A drill-down.
