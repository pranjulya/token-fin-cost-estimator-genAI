# ADR-001 — Use Decimal for monetary values

- **Status:** Accepted (implemented)
- **Date:** 2026-08-15
- **Related:** ADR-002, ADR-005

## Context

LLM costs are per-million-token fractions of a cent (e.g. `$0.00002` for a
request). Floats cannot represent most decimal fractions exactly, so summing
many small costs accumulates error. Money must be exact and auditable.

## Decision

All monetary values — pricing rates, estimated/actual costs, variances, budget
limits, reserved/committed amounts — are `Decimal` throughout the Python code
(`utils/money.py`), stored as PostgreSQL `NUMERIC(20,10)`, and serialized to
JSON as **strings** (never floats). Per-token conversions use integer-safe
division; totals are quantized before being stored.

## Consequences

- **Good:** exact arithmetic, no float drift in aggregation, auditable ledger.
- **Good:** JSON `"0.00002"` survives round-trips without precision loss.
- **Cost:** schema/Pydantic discipline — every money field must be Decimal, and
  clients must treat money as strings.
- **Rejected alternatives:** float (drift), integer micro-USD (awkward for
  rates + readability, still viable but less readable at the boundary).
