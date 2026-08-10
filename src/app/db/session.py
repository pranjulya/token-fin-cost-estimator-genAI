"""Database engine and session management.

The service is async (SQLAlchemy 2.0 + psycopg async). A separate synchronous
engine is provided for Alembic, which does not support async by default.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def _async_url() -> str:
    url = get_settings().database_url
    # Normalize psycopg: async driver string.
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _sync_url() -> str:
    return _async_url().replace("postgresql+psycopg://", "postgresql+psycopg://", 1)


async_engine = create_async_engine(_async_url(), pool_pre_ping=True, future=True)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

# Sync engine for Alembic scripts and quick introspection.
sync_engine = create_engine(_sync_url(), pool_pre_ping=True, future=True)
SyncSessionLocal = sessionmaker(bind=sync_engine, class_=Session, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async session with transaction handling."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
