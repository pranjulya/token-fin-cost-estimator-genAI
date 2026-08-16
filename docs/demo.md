# Portfolio Demo (Phase 22) — Team Budget = $10

Run it with:

```bash
make demo        # or: uv run python scripts/demo.py
```

The demo uses the app's own ASGI server in-process with a **mock LLM** — no
network, no OpenAI key, no cost. It resets the schema, seeds `gpt-4o` pricing
and a **$10 STRICT TEAM budget**, then walks the PRD's three beats:

## Beat 1 — Normal request

`POST /v1/cost/estimate` (small prompt) → `budget.status = ALLOW`.
`POST /v1/usage` (small actuals) → `201` with `actual_cost` + variance.

> Proves: estimate is a cheap preflight; usage is recorded and reconciled.

## Beat 2 — Large request, blocked before the provider

`POST /v1/cost/estimate` with `expected_output_tokens=1_000_000` (≈ $10
output, over budget) → `budget.status = BLOCK` (still HTTP 200 — estimate is
evaluate-only).

`POST /v1/generate` with the same large payload → **`403 BUDGET_EXCEEDED`**
and the mock LLM records **zero calls** (`calls == []`).

> Proves: STRICT budgets are enforced BEFORE any provider spend — the product's
> core value ("reject before LLM execution").

## Beat 3 — Multiple requests → aggregate + alert

Six small `POST /v1/generate` calls accumulate spend; then:

- `GET /v1/usage/summary` → `total_requests` + `total_cost`.
- `GET /v1/cost/by-model` → spend grouped by model.
- `GET /v1/alerts` → contains a `BUDGET_THRESHOLD` alert (crossed WARN/CRITICAL).
- `POST /v1/alerts/{id}/acknowledge` → `200`.

> Proves: aggregation APIs work and the Phase 13 alert system fires and is
> operable.

## Output

```
== Beat 1: Normal request ==
  [estimate] status=200 budget=ALLOW cost=0.0010175
  [usage] status=201 actual_cost=0.0003375 variance=0.0003375

== Beat 2: Large request (blocked before provider) ==
  [estimate] status=200 budget=BLOCK
  [generate] status=403 code=BUDGET_EXCEEDED

== Beat 3: Multiple requests -> threshold + alert ==
  [summary] requests=7 cost=0.0023625000
  [by-model] model=gpt-4o cost=0.0023625000
  [alerts] count=1
  [ack] alert_id=1 -> 200

Demo complete: all three beats passed.
```

## Going further with a real key

To see the real `POST /v1/generate` dial OpenAI, set `APP_GENERATE_ENABLED=true`
and `APP_OPENAI_API_KEY=sk-...` and run the service (`docker compose up --build`
or `make run`). The demo itself stays deterministic and free.
