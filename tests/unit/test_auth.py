"""Unit tests for Phase 17 API-key auth + authorization.

Uses os.environ + get_settings.cache_clear() (restored after each test) so the
shared cached Settings singleton is never mutated in place.
"""

from __future__ import annotations

import pytest

from app.api.auth import DEV_BYPASS_KEY, _extract_key, get_api_key, require_admin
from app.core.config import get_settings
from app.core.exceptions import AuthorizationError

_ENV_KEYS = ("APP_API_KEYS", "APP_ADMIN_API_KEYS")


@pytest.fixture
def key_settings(monkeypatch):
    monkeypatch.setenv("APP_API_KEYS", "user-1,user-2")
    monkeypatch.setenv("APP_ADMIN_API_KEYS", "admin-1")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


def test_extract_key_from_x_api_key():
    assert _extract_key(x_api_key="  user-1 ", authorization=None) == "user-1"


def test_extract_key_from_bearer():
    assert _extract_key(x_api_key=None, authorization="Bearer admin-1") == "admin-1"


def test_extract_key_missing():
    assert _extract_key(x_api_key=None, authorization=None) == ""


def test_get_api_key_valid(key_settings):
    assert key_settings.is_valid_key("user-1")
    assert key_settings.is_valid_key("admin-1")


def test_get_api_key_invalid(key_settings):
    assert not key_settings.is_valid_key("nope")


def test_admin_is_superset(key_settings):
    assert key_settings.is_valid_key("admin-1")
    assert key_settings.is_admin_key("admin-1")
    assert not key_settings.is_admin_key("user-1")


def test_require_admin_raises_on_user_key(key_settings):
    with pytest.raises(AuthorizationError):
        require_admin("user-1")


def test_require_admin_accepts_admin_key(key_settings):
    assert require_admin("admin-1") == "admin-1"


def test_authentication_error_status():
    from app.core.exceptions import AuthenticationError

    assert AuthenticationError("x").status_code == 401


def test_auth_disabled_bypasses_validation(monkeypatch):
    """APP_AUTH_DISABLED=true returns the synthetic key without any header."""
    monkeypatch.setenv("APP_AUTH_DISABLED", "true")
    monkeypatch.setenv("APP_API_KEYS", "")
    monkeypatch.setenv("APP_ADMIN_API_KEYS", "")
    get_settings.cache_clear()
    try:
        assert get_api_key(x_api_key=None, authorization=None) == DEV_BYPASS_KEY
        assert require_admin(DEV_BYPASS_KEY) == DEV_BYPASS_KEY
    finally:
        get_settings.cache_clear()


def test_auth_enabled_still_rejects_missing_key(monkeypatch):
    """Without APP_AUTH_DISABLED, no header still means 401."""
    monkeypatch.setenv("APP_AUTH_DISABLED", "false")
    monkeypatch.setenv("APP_API_KEYS", "user-1")
    monkeypatch.setenv("APP_ADMIN_API_KEYS", "admin-1")
    get_settings.cache_clear()
    try:
        from app.core.exceptions import AuthenticationError

        with pytest.raises(AuthenticationError):
            get_api_key(x_api_key=None, authorization=None)  # no headers at all
    finally:
        get_settings.cache_clear()
