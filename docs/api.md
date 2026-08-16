# API Reference

Live OpenAPI docs: `GET /docs` (Swagger UI) when the server is running.

## Error envelope

Every error response has one shape:

```json
{ "error": { "code": "...", "message": "...", "request_id": "..." } }
```

Common codes: `UNAUTHORIZED` (401), `FORBIDDEN` (403), `VALIDATION_ERROR` (422),
`BUDGET_EXCEEDED` (403), `GENERATION_ALREADY_RECORDED` (409), `RATE_LIMITED` (429),
`PROVIDER_ERROR` (502), `GENERATION_DISABLED` (503), `DATABASE_ERROR` (500),
`INTERNAL_ERROR` (500).

## Auth

- All `/v1/*` routes require a valid API key via `X-API-Key` or
  `Authorization: Bearer <key>`.
- Admin routes (budgets, alerts, pricing **writes**) require an admin key
  (`APP_ADMIN_API_KEYS`).
- `/health`, `/ready`, `/metrics` are open (ops probes).

## Routes

### Public (no auth)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness probe |
| GET | `/ready` | readiness probe (checks DB) |
| GET | `/metrics` | Prometheus metrics |

### User (any valid key)

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/cost/estimate` | tokenize + price + evaluate-only budget envelope |
| POST | `/v1/generate` | end-to-end: estimate → reserve → LLM → record → settle (rate-limited, `APP_GENERATE_ENABLED`) |
| POST | `/v1/usage` | record actual usage (idempotent on `request_id`, rate-limited) |
| GET | `/v1/usage` | list usage |
| GET | `/v1/usage/summary` | totals |
| GET | `/v1/cost/by-model` `/by-endpoint` `/by-team` | spend attribution |
| GET | `/v1/models/pricing` | list pricing |

### Admin (admin key)

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/models/pricing` | create/version pricing |
| POST | `/v1/budgets` | create budget |
| GET | `/v1/budgets/{id}` | read budget |
| PATCH | `/v1/budgets/{id}` | update budget |
| GET | `/v1/alerts` | list alerts (filters, pagination, `open_only`) |
| GET | `/v1/alerts/{id}` | get alert |
| POST | `/v1/alerts/{id}/acknowledge` | acknowledge alert |

## Notable behaviors

- **Estimate** is evaluate-only: `budget.status` may be `BLOCK` while the
  response is still 200. Generate is the enforcement point.
- **Generate** returns 409 on a repeated `request_id`; completion text is not
  stored — list `GET /v1/usage` and filter by `request_id` for money.
- **Usage** is idempotent: replaying the same `request_id` returns the existing
  record, never double-counting spend.
- Money is serialized as JSON **strings** (e.g. `"0.00002"`), never floats.
