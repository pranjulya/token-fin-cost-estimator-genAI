"""Shared fixtures for integration tests.

Point the app at the dedicated test database BEFORE importing any app module
(the async engine is created at import time). Tables are truncated before
each test so tests are isolated.
"""

from __future__ import annotations

import os

os.environ["APP_DATABASE_URL"] = "postgresql+psycopg://localhost:5432/token_cost_estimator_test"
# Phase 17: default API keys for the test suite. Existing integration tests
# authenticate as the user key; tests needing admin use the admin key explicitly.
os.environ["APP_API_KEYS"] = "test-user-key"
os.environ["APP_ADMIN_API_KEYS"] = "test-admin-key"
os.environ["APP_RATE_LIMIT_PER_MINUTE"] = "1000"
os.environ["APP_RATE_LIMIT_GENERATE_PER_MINUTE"] = "1000"

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db import models  # noqa: E402, F401  (register tables)
from app.db.base import Base  # noqa: E402
from app.db.session import async_engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _create_tables():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables(_create_tables):
    async with async_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    yield


@pytest_asyncio.fixture(autouse=True)
async def _clear_log_contextvars():
    """Clear structlog contextvars before/after each test (Phase 16 middleware)."""
    import structlog

    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver", headers={"X-API-Key": "test-user-key"}
    ) as c:
        yield c


@pytest_asyncio.fixture
async def admin_client():
    """Client authenticated with the admin API key (Phase 17)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver", headers={"X-API-Key": "test-admin-key"}
    ) as c:
        yield c


# Async session factory usable directly by repository-level tests.
from sqlalchemy.ext.asyncio import async_sessionmaker as _asm  # noqa: E402

from app.db.session import async_engine as _engine  # noqa: E402

session_factory = _asm(_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session():
    async with session_factory() as session:
        yield session
