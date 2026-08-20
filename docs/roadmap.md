# Roadmap — "Next Quarter" Items

The P0/P1 hardening is done: hashed keys, boot guard, CORS, NOT_FOUND, pooled
HTTP client, mypy strict, ruff B/UP/S, 80% coverage gate, CI that runs the
container, Dependabot, optional metrics scrape token, and the
reserve→settle idempotency ledger. Everything below is **explicitly deferred**
— each is worth doing, none is needed to ship today.

## 1. Shared rate limit (Redis / API gateway)

**Why defer:** the in-memory per-key token bucket (with amortized eviction +
`Retry-After`) is correct for a single replica. It multiplies the effective
limit across replicas, which only matters once you run >1.

**Path:** keep the `RateLimiter` interface; swap the `_limiter()` singleton for
a Redis-backed token bucket (e.g. `redis-py` + a Lua INCRBY/EXPIRE script) or
move the limit to an API gateway (Kong/nginx). The dependency injection is
already isolated to `app/api/ratelimit.py`. See `docs/security.md` → Rate
limiting.

## 2. OpenTelemetry instead of log spans

**Why defer:** the lightweight `span()` events (structlog `span_completed`) give
the trace chain without a collector. OTel adds value once you have a tracing
backend (Jaeger/Tempo) and cross-service traces.

**Path:** `opentelemetry-api`/`-sdk`, a `TracerProvider` in `lifespan`, replace
`app/core/metrics.py::span()` with `tracer.start_as_current_span()`, and an OTLP
exporter behind a `APP_TRACING_ENABLED` flag. Metric names stay the same.

## 3. Real IdP / key rotation

**Why defer:** `APP_AUTH_HASH_KEYS` already keeps keys hashed at rest with
constant-time compare, and rotation is an ops flow (regenerate hashes in the
secret manager). A full IdP is a deployment decision, not a code one.

**Path:** `require_admin` gains an OIDC bearer-token check (issuer + audience)
alongside the API-key path; keys move to KMS/AWS Secrets Manager with a
rotation lambda. See `docs/security.md` → Hashed keys at rest.

## 4. Second LLMProvider (e.g. Anthropic stub)

**Why defer:** the `LLMProvider` Protocol already proves the seam — business
logic never touches a vendor SDK. A second provider is a ~40-line file + a
config entry + a factory branch; there's no code change needed until a real
Anthropic use case exists.

**Path:** `providers/llm/anthropic_provider.py` (httpx, Messages API),
`ANTHROPIC_API_KEY`/`ANTHROPIC_BASE_URL` settings, and an `anthropic` branch in
`get_llm_provider`. See `docs/architecture.md` → Provider abstractions.

## 5. Read replica / daily rollup

**Why defer:** aggregation queries are index-backed and the ledger is small.
A read replica or a nightly `rollup_daily` materialized view only pays off when
volume makes the aggregation queries slow.

**Path:** a second engine URL for reads (`APP_READ_DATABASE_URL`) wired via
SQLAlchemy bindings, or a `scripts/rollup_daily.py` cron writing
provider/model/day cost rows. See `docs/database.md`.

## 6. Kubernetes manifest

**Why defer (explicitly):** the Docker hardening already exists — non-root
`appuser`, read-only source, `/health` + `/ready`, resource-friendly image. A
k8s manifest is only useful as a **demo artifact** (show deploy), not because
the service needs k8s.

**Path:** if you want it, add `deploy/k8s.yaml` (Deployment + Service +
`docker-compose.prod.yml` envs as a Secret), plus a liveness/readiness probe on
`/health`/`/ready`. See `docs/security.md` → Deployment notes.
