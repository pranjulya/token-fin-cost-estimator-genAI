# ADR-005 — Store pricing version with usage records

- **Status:** Accepted (implemented)
- **Date:** 2026-08-15
- **Related:** ADR-001, ADR-004

## Context

Prices change over time. If a usage row only stores the model, its monetary
cost becomes ambiguous the moment pricing is re-created — history would either
re-price (wrong) or be unverifiable.

## Decision

`model_pricing` rows carry a monotonically increasing `version`; each
`usage_records` row snapshots `pricing_version` (plus provider/model and the
computed `actual_cost`). Historical spend is therefore frozen: the money shown
for an old record is exactly what it cost under the pricing in effect at
record time.

## Consequences

- **Good:** stable historical records (a PRD Definition-of-Done requirement);
  audit can always reconstruct "what did we charge for this request".
- **Good:** the calculator gets a complete price context from the row alone.
- **Cost:** an extra `version` column + seed logic to bump it; `effective_from`
  windows in the pricing lookup must pick the version active at record time.
