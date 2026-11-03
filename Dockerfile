# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# PYTHONPATH is required because uv sync --no-install-project never puts
# `app` on site-packages; uvicorn/seed import `app` from /app/src.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken \
    PATH="/app/.venv/bin:/usr/local/bin:${PATH}"

WORKDIR /app

# Layer-cache dependency install: copy manifests first, then lockfile.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# tiktoken downloads its BPE files on first use. Bake them into the image so
# token counting works offline (classrooms, proxies, air-gapped hosts). Best
# effort: if the build host is offline the app still runs, using the heuristic
# token estimate until the files can be fetched.
RUN mkdir -p /opt/tiktoken \
    && (python -c "import tiktoken; [tiktoken.get_encoding(e) for e in ('o200k_base', 'cl100k_base')]" \
        || echo "WARNING: tiktoken encodings not pre-fetched; runtime will fall back to heuristic counts") \
    && chmod -R a+rX /opt/tiktoken

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
