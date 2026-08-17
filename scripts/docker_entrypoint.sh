#!/bin/sh
set -e

# Apply DB migrations, then start the app.
# APP_DATABASE_URL is required for migrations + app (set in docker-compose).
# APP_SEED_ON_BOOT=true (dev default) also seeds idempotent pricing.
alembic upgrade head

if [ "${APP_SEED_ON_BOOT:-false}" = "true" ]; then
    python scripts/seed_pricing.py
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
