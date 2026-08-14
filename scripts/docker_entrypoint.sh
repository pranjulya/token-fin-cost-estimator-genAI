#!/bin/sh
set -e

# Apply DB migrations, seed idempotent pricing, then start the app.
# APP_DATABASE_URL is required for migrations + app (set in docker-compose).
alembic upgrade head
python scripts/seed_pricing.py

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
