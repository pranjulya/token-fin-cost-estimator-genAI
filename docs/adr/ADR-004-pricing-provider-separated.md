# ADR-004 — Separate pricing provider from cost calculator

- **Status:** Accepted (implemented)
- **Date:** 2026-08-15
- **Related:** ADR-005, ADR-001

## Context

"Cost = tokens × price" seems trivial, but pricing is a moving target (model
additions, price changes, effective-date windows, caching tiers). If the
calculator hard-codes prices, every price change is a code deploy and history
re-prices.

## Decision

A `PricingProvider` abstraction supplies price lookups
(`get_pricing(provider, model) -> ModelPrice`), backed by the versioned
`model_pricing` table (ADR-005). The cost calculator (`cost_calculator.py`) is
a pure function of a price + token counts — independently testable with no
DB/network. The calculator and the provider are swapped independently.

## Consequences

- **Good:** new models/prices are data, not code; calculator is unit-tested in
  isolation; vendor pricing quirks (caching tiers) live in one place.
- **Good:** estimate and generate share the exact same price path, so they
  can't disagree on cost.
- **Cost:** one more interface to wire; pricing rows must be seeded (idempotent
  `scripts/seed_pricing.py`).
