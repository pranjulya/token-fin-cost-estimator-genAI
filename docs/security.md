# Security (Phase 17)

## Controls implemented

### API-key authentication

- Every `/v1/*` route requires a valid API key via `X-API-Key` or
  `Authorization: Bearer <key>`.
- Missing/invalid key → `401 UNAUTHORIZED`.
- Keys configured via environment: `APP_API_KEYS` (comma-separated user keys),
  `APP_ADMIN_API_KEYS` (comma-separated admin keys).

### Authorization (admin scope)

Admin keys are a superset of user keys (an admin key can call any route).
Admin-only: budget CRUD, alerts read/ack, pricing **writes**.
User key on an admin route → `403 FORBIDDEN`.
`GET /v1/models/pricing` stays user-readable (reads are low-risk).

### Rate limiting

In-memory per-key token buckets (process-local; resets on restart — acceptable
without Redis):

| Setting | Applied to |
|---|---|
| `APP_RATE_LIMIT_PER_MINUTE` (default 60) | `POST /v1/usage`, `POST /v1/cost/estimate` |
| `APP_RATE_LIMIT_GENERATE_PER_MINUTE` (default 10) | `POST /v1/generate` (spends money) |

Exceeded → `429 RATE_LIMITED`.

### Input limits

- `APP_MAX_PROMPT_CHARS` (default 200k) enforced on estimate + generate input.
- `APP_MAX_EXPECTED_OUTPUT_TOKENS` (default 1M) enforced on estimate output,
  generate `max_output_tokens`, and all usage token counts.
- Oversized → `422 VALIDATION_ERROR` (blocks large-payload DoS).

### Log redaction

A structlog processor redacts any event key matching
`api_key | token | secret | password | authorization` → `[REDACTED]`, across
all log events. Prompts/completions are never logged or persisted.

### Audit events

Structured `audit_*` logs on admin mutations: `audit_pricing_created`,
`audit_budget_created`, `audit_budget_updated`, `audit_alert_acknowledged`.
The actor is a key prefix (`key:abcd...wxyz`), never the raw key.

## Deployment notes (documented, not implemented here)

- **TLS** — terminate at a reverse proxy / load balancer in production.
- **Secrets** — API keys and `APP_OPENAI_API_KEY` come from env/secrets
  manager, never committed (`.env` is gitignored; `.dockerignore` excludes it).
- **Least-privilege DB credentials** — use a role with only the needed grants.
- **`APP_GENERATE_ENABLED`** is `false` by default; enabling it without a real
  `APP_OPENAI_API_KEY` still yields `502` (key missing) — a fresh deploy never
  silently spends money.

## CI security checks

`make security-check` / the CI pipeline run:

1. `uvx pip-audit` — dependency vulnerability scan.
2. A committed-secret grep (`scripts/security_scan.sh`) that fails on tracked
   `.env`/`.pem`/key files or obvious `sk-...`/`Bearer ...` literals.
