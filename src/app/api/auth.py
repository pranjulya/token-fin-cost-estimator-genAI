"""API-key authentication + authorization (PRD Phase 17).

Dependencies (not middleware) so tests can override them via
``app.dependency_overrides``. Admin keys are a superset of user keys: any valid
key can call user routes; admin routes require an admin key.

DEV-ONLY bypass: when APP_AUTH_DISABLED=true, every dependency returns a
synthetic key so local development needs no keys. The boot guard refuses this
in non-development environments (see app/main.py).
"""

from __future__ import annotations

from fastapi import Depends, Header

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, AuthorizationError

SCHEME = "bearer"

# Synthetic key returned when APP_AUTH_DISABLED=true (dev only).
DEV_BYPASS_KEY = "dev-bypass"


def _extract_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> str:
    """Pull the API key from X-API-Key or Authorization: Bearer <key>."""
    if x_api_key:
        return x_api_key.strip()
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == SCHEME:
            return token.strip()
    return ""


def _bypass() -> bool:
    return get_settings().auth_disabled


def get_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> str:
    """Validate the caller's API key. Raises AuthenticationError (401)."""
    if _bypass():
        return DEV_BYPASS_KEY
    key = _extract_key(x_api_key, authorization)
    if not key or not get_settings().is_valid_key(key):
        raise AuthenticationError("Missing or invalid API key.")
    return key


def require_admin(
    key: str = Depends(get_api_key),
) -> str:
    """Require an admin-scoped key. Raises AuthorizationError (403)."""
    if _bypass():
        return DEV_BYPASS_KEY
    if not get_settings().is_admin_key(key):
        raise AuthorizationError("Admin API key required.")
    return key
