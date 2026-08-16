# Production Scenarios (PRD §37)

How the service behaves in the failure/distributed cases the PRD cares about.

## 1. Budget BLOCK before any provider spend

A large request against a nearly-exhausted STRICT budget: `POST /v1/generate`
reserves, the decision is BLOCK, the reservation is mid-committed (so the
`DECISION` event + alert are durable), the LLM is **never called**, and the
client gets `403 BUDGET_EXCEEDED`. No money is spent.

## 2. LLM provider down / times out

After a successful reserve (UoW1 committed), the provider call fails:
`GenerationService` calls `release(E)`, mid-commits the release, and raises
`502 PROVIDER_ERROR`. No SUCCESS usage row is written; the reservation does not
leak.

## 3. Retry / duplicate request_id

- **Sequential duplicate:** `record_new` (or the pre-flight check) finds the
  row → `409 GENERATION_ALREADY_RECORDED`, no second LLM call, no second
  reserve.
- **Concurrent duplicate:** both reserve; the loser of the unique `request_id`
  insert gets 409 from `record_new`, then `release(E)` (no settle). One extra
  provider call is the accepted cost.
- **After a 5xx:** there may be no usage row, so a retry with the same
  `request_id` re-calls the LLM and re-reserves. Mitigation: use a **new**
  `request_id` after a 5xx.

## 4. LLM succeeds but usage persistence fails

The money is spent at OpenAI but the usage row fails to persist → the request
returns 5xx (fail loudly, per PRD Scenario 8). The reservation is released; a
retry with a new `request_id` re-records. An outbox/durable-queue is the
eventual design; v1 does not fake success.

## 5. Estimate drastically differs from actual

`UsageService.record` computes `variance_amount`/`variance_percent` from the
estimate vs actual. When the actual crosses the anomaly rules (historical
multiplier or variance %), a `COST_ANOMALY` alert is created (Phase 13).
`settle` handles `actual > estimate` via `apply_overage` — consuming exactly
the reserved `E`, never stealing other in-flight reservations.

## 6. Alert subsystem fails

Alerts are soft-fail by contract: if the alert DB call raises, the money
transaction (usage insert, budget reserve) still commits. Proven by
`test_alert_soft_fail_still_commits_usage`.

## 7. Process crash after reserve, before settle

`reserved_amount` leaks until the period rolls over (MONTHLY/DAILY new
`period_key`). Documented accepted risk; a reaper is a future option.

## 8. Estimate used as a hold (anti-pattern)

`POST /v1/cost/estimate` is evaluate-only and never reserves. Treating it as a
hold double-reserves with generate — use generate as the single reservation
path.
