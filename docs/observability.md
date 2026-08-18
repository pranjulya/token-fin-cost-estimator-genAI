# Observability (Phase 16)

## Structured logs

structlog — JSON renderer in production, console in development. The
`ObservabilityMiddleware` binds per-request context vars so every log event in
a request carries: `request_id`, `correlation_id`, `endpoint`, `method`.

Key events:

| Event | When | Bindings |
|---|---|---|
| `request_completed` | every request | `request_id`, `correlation_id`, `endpoint`, `method`, `status`, `latency_ms`, `duration_seconds` |
| `span_completed` | each traced span | `span` name, `span_duration_seconds` |
| `generate_*` | generate lifecycle | request_id, costs, token counts (never prompt text) |
| `alert_created` / `alert_emit_failed` | alert lifecycle | alert metadata, request_id |
| `audit_*` | admin mutations | actor (key prefix), request_id |

## Correlation IDs

- Client sends `X-Request-ID` (or `X-Correlation-ID`) → echoed on the response
  and propagated through logs/errors.
- Absent → a `req_...` id is generated per request.
- Business errors surface the exception's `request_id` in the envelope.

## Metrics

`GET /metrics` (Prometheus text format, open — no auth). Names:

| Metric | Type | Labels |
|---|---|---|
| `llm_requests_total` | Counter | provider, model, endpoint, status |
| `llm_request_duration_seconds` | Histogram | provider, model, endpoint, status |
| `llm_input_tokens_total` | Counter | provider, model |
| `llm_output_tokens_total` | Counter | provider, model |
| `llm_cost_total` | Counter | provider, model |
| `llm_estimated_cost_total` | Counter | provider, model |
| `llm_budget_rejections_total` | Counter | provider, model, reason |
| `llm_cost_anomaly_total` | Counter | provider, model |

No high-cardinality labels (raw `user_id` is deliberately excluded). Disable
with `APP_METRICS_ENABLED=false`.

**Scrape access:** `/metrics` is open by default — fine behind a private scrape
network (Prometheus/grafana agent). To require a token on a shared network, set
`APP_METRICS_SCRAPE_TOKEN` and configure the scraper with
`Authorization: Bearer <token>` (rejected without it → `401`).

## Tracing (span events)

The PRD trace chain is approximated with lightweight span events (no OTel):

```
HTTP Request → tokenization → pricing_lookup → cost_estimation
            → budget reserve/evaluate → llm_provider → usage_reconciliation
```

Each emits a `span_completed` log event with `span_duration_seconds`.
