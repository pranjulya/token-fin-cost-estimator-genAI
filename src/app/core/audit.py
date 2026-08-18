"""Structured audit events for admin mutations (PRD Phase 17)."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger

logger = get_logger("app.audit")


def audit(event: str, *, actor: str, request_id: str | None = None, **fields: Any) -> None:
    """Emit a structured audit event. The actor is a key prefix/hash, never raw."""
    logger.info(event, actor=actor, request_id=request_id, **fields)


def key_actor(key: str) -> str:
    """Derive a safe actor label from an API key (never log the raw key)."""
    if len(key) < 8:
        return f"key:{key[:4]}***"
    return f"key:{key[:4]}...{key[-4:]}"
