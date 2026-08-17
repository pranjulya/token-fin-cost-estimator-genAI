# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:/usr/local/bin:${PATH}"

WORKDIR /app

# Layer-cache dependency install: copy manifests first, then lockfile.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source, migrations, and scripts.
COPY src/ src/
COPY migrations/ migrations/
COPY scripts/ scripts/
COPY alembic.ini ./

# The entrypoint runs migrations + optional seed, then starts uvicorn.
COPY scripts/docker_entrypoint.sh /usr/local/bin/docker_entrypoint
RUN chmod +x /usr/local/bin/docker_entrypoint \
    && useradd --create-home --uid 10001 appuser \
    # The runtime user owns only what it must write; source stays root-owned
    # and read-only so a compromised process cannot tamper with code.
    && chown -R root:root /app

# Run as non-root (production hygiene).
USER appuser

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/docker_entrypoint"]
