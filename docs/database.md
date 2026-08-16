# Database Design

PostgreSQL 14, managed via SQLAlchemy 2.0 async + Alembic (`migrations/`).
Six tables.

## Tables

### `model_pricing`

Versioned pricing registry. Re-creating a price for the same (provider, model)
bumps `version`; historical rows are never mutated, so past usage never
re-prices.

| Column | Notes |
|---|---|
| `provider`, `model` | e.g. `openai` / `gpt-4o` |
| `input_price_per_million`, `cached_input_price_per_million`, `output_price_per_million` | `Numeric`, per 1M tokens, USD |
| `effective_from`, `effective_to` | date window for "effective" lookup |
| `version` | frozen on usage rows as `pricing_version` |

### `usage_records`

Append-only ledger of LLM interactions. The unique `request_id` is the
idempotency gate.

| Column | Notes |
|---|---|
| `request_id` | unique — retries never double-count |
| `provider`, `model` | attribution + pricing lookup |
| `application_id`, `team_id`, `user_id`, `endpoint`, `environment` | cost attribution (FR-06) |
| `estimated_input_tokens`, `estimated_output_tokens`, `estimated_cost` | pre-execution |
| `actual_input_tokens`, `cached_input_tokens`, `actual_output_tokens`, `actual_cost` | post-execution |
| `variance_amount`, `variance_percent` | estimate vs actual reconciliation |
| `pricing_version` | frozen pricing context (historical cost is stable) |
| `status` | `SUCCESS` etc. |

### `budgets`

Budget policy per scope. `enforcement_mode` is `STRICT` (BLOCK at 100%) or
`ADVISORY` (WARN instead).

| Column | Notes |
|---|---|
| `scope_type`, `scope_id` | `TEAM` or `APPLICATION` |
| `period_type` | `MONTHLY` (YYYY-MM) or `DAILY` (YYYY-MM-DD) |
| `limit_amount`, `currency` | budget cap |
| `warning_threshold`, `critical_threshold` | 0–1 fractions |
| `starts_at`, `ends_at` | active window (null = open-ended) |

### `budget_consumption`

The atomic spend counter — one row per (budget, period_key). All reserve /
commit / release / settle operations take `SELECT ... FOR UPDATE` on this row.

| Column | Notes |
|---|---|
| `budget_id`, `period_key` | unique pair |
| `reserved_amount` | in-flight reservations (estimates) |
| `committed_amount` | settled actual spend |

### `budget_events`

Immutable audit trail of every reserve / commit / release / decision. Fields:
`event_type` (`RESERVE`, `COMMIT`, `RELEASE`, `DECISION`), `amount`, `decision`,
`period_key`, `request_id`, `details`.

### `alerts`

Phase 13 alert records. `dedupe_key` is unique so retries/repeated same-band
decisions never flood the table. Fields: `alert_type` (`BUDGET_THRESHOLD`,
`COST_ANOMALY`), `severity`, `scope_type`/`scope_id`, `request_id`, `metadata`
(JSON), `acknowledged_at`.

## Key design rules

- **Decimal-only money** — `Numeric(20,10)`, never binary float.
- **Idempotency** — `usage_records.request_id` unique; `record_new` maps a
  unique-violation to a 409 inside a savepoint so the outer session survives.
- **Frozen pricing** — usage rows store `pricing_version`; history never
  re-prices (PRD #20).
- **No prompt text stored** — `usage_records` has no prompt column.
- **No schema changes in Phases 14–18** — everything reused existing tables.
