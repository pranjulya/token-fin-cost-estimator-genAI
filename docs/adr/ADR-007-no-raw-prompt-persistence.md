# ADR-007 — Avoid raw prompt persistence by default

- **Status:** Accepted (implemented)
- **Date:** 2026-08-15
- **Related:** ADR-001

## Context

Prompt text can contain secrets, PII, or IP. Persisting it alongside cost data
creates a data-retention and security burden for no FinOps value, and logging
it risks leaking sensitive content.

## Decision

`usage_records` stores **no prompt/completion text** — only counts, costs, and
attribution metadata (team/app/user/endpoint/environment). Requests to the
provider carry the prompt in-memory only. The structured log pipeline redacts
any key matching `api_key|token|secret|password|authorization`, so even
accidental logging cannot leak credentials.

## Consequences

- **Good:** smaller, cheaper ledger; no sensitive-content retention policy;
  audit-safe logs.
- **Good:** aligns with the security posture (Phase 17): no secrets in logs or
  DB.
- **Cost:** you cannot replay "what did we actually send" from the ledger —
  the ledger answers *how much* and *to whom*, by design. If prompt auditing is
  ever required, it must be a separate, opt-in, encrypted store.
