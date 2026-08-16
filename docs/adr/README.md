# Architecture Decision Records

This directory records the project's significant design decisions. Each ADR is
a self-contained document: context, decision, consequences (and rejected
alternatives where relevant).

| ID | Decision | Status |
|---|---|---|
| [ADR-001](ADR-001-decimal-money.md) | Decimal for all monetary values | Accepted · implemented |
| [ADR-002](ADR-002-postgres-system-of-record.md) | PostgreSQL as the durable system of record | Accepted · implemented |
| [ADR-003](ADR-003-postgres-for-update-not-redis.md) | Atomic budget reservations via Postgres `FOR UPDATE` (not Redis) | Accepted · implemented · PRD deviation |
| [ADR-004](ADR-004-pricing-provider-separated.md) | Pricing provider separated from cost calculator | Accepted · implemented |
| [ADR-005](ADR-005-pricing-version-on-usage.md) | Pricing version stored on usage records | Accepted · implemented |
| [ADR-006](ADR-006-fail-closed-budget.md) | Fail closed when strict budget enforcement is unavailable | Accepted · implemented |
| [ADR-007](ADR-007-no-raw-prompt-persistence.md) | Avoid raw prompt persistence by default | Accepted · implemented |

See also the [architecture overview](../architecture.md) and
[security](../security.md) documents.
