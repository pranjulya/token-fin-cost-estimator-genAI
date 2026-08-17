#!/bin/sh
set -e

# Apply DB migrations, then start the app.
# APP_DATABASE_URL is required for migrations + app (set in docker-compose).
#
# Migrations run on every boot (idempotent). For production, a common split is
# to run `alembic upgrade head` as a one-shot migrate job / init container and
# let the app container skip it entirely; the entrypoint keeps it here so the
# dev story stays one command.
#
# APP_SEED_PRICING=true (dev default) also seeds idempotent pricing; prod must
# seed explicitly and leave this off.
alembic upgrade head

if [ "${APP_SEED_PRICING:-false}" = "true" ]; then
    python scripts/seed_pricing.py
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
