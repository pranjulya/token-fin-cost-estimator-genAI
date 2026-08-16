# ADR-002 — PostgreSQL as the durable system of record

- **Status:** Accepted (implemented)
- **Date:** 2026-08-15
- **Related:** ADR-003, ADR-005

## Context

The service must durably persist usage, pricing history, budget state, audit
events, and alerts, and answer aggregation queries over them. A single system
of record reduces consistency risk versus splitting state across stores.

## Decision

PostgreSQL 14 is the one durable store. SQLAlchemy 2.0 (async) + Alembic for
schema management. All transactions — including budget atomicity (see
ADR-003) — run in Postgres.

## Consequences

- **Good:** one consistency domain, ACID transactions, `FOR UPDATE` row locks,
  JSON metadata for alerts, mature tooling.
- **Good:** no cross-store reconciliation between money and budget state.
- **Cost:** Postgres is the scaling focus — aggregation must stay index-backed
  and read replicas are the escape hatch (not in v1).
- **Rejected alternatives:** a separate ledger store (e.g. Kafka) — unnecessary
  complexity at this scale; SQLite — no row locks/JSON for prod semantics.
