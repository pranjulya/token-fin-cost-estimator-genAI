# Makefile — dev workflow for the GenAI token cost estimator
.PHONY: help setup test test-unit test-integration test-db seed run migrate lint format typecheck security-check demo

PY := uv run python

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup:  ## Install deps + create databases + run migrations + seed pricing
	uv sync
	psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='token_cost_estimator'" | grep -q 1 || psql -d postgres -c "CREATE DATABASE token_cost_estimator;"
	psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='token_cost_estimator_test'" | grep -q 1 || psql -d postgres -c "CREATE DATABASE token_cost_estimator_test;"
	uv run alembic upgrade head
	uv run python scripts/seed_pricing.py

test-db:  ## Create the test database (idempotent)
	psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='token_cost_estimator_test'" | grep -q 1 || psql -d postgres -c "CREATE DATABASE token_cost_estimator_test;"

test: test-db  ## Run the full test suite
	uv run pytest -p no:cacheprovider

test-unit:  ## Unit tests only
	uv run pytest tests/unit -p no:cacheprovider

test-integration: test-db  ## Integration tests (real Postgres)
	uv run pytest tests/integration -p no:cacheprovider

seed:  ## Load realistic OpenAI pricing
	uv run python scripts/seed_pricing.py

migrate:  ## Apply pending migrations
	uv run alembic upgrade head

revision:  ## Autogenerate a migration: make revision m="message"
	uv run alembic revision --autogenerate -m "$(m)"

run:  ## Start the dev server on :8000
	uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

lint:  ## Lint and format-check with ruff
	uv run ruff check src tests scripts
	uv run ruff format --check src tests scripts

format:  ## Auto-format with ruff
	uv run ruff format src tests scripts
	uv run ruff check --fix src tests scripts

typecheck:  ## Run mypy on src/
	uv run mypy src

security-check:  ## Dependency audit + committed-secret grep
	bash scripts/security_scan.sh

demo:  ## Run the Phase 22 portfolio demo (team budget = $10 walkthrough)
	uv run python scripts/demo.py