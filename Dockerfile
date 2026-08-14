# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Layer-cache dependency install: copy manifests first, then lockfile.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy source, migrations, and scripts.
COPY src/ src/
COPY migrations/ migrations/
COPY scripts/ scripts/
COPY alembic.ini ./

# The entrypoint runs migrations + seed, then starts uvicorn.
COPY scripts/docker_entrypoint.sh /usr/local/bin/docker_entrypoint
RUN chmod +x /usr/local/bin/docker_entrypoint

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/docker_entrypoint"]
