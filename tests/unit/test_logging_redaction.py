"""Unit tests for the Phase 17 structlog redaction processor."""

from __future__ import annotations

from app.core.logging import redact_processor


def test_redacts_api_key():
    out = redact_processor(None, "info", {"api_key": "sk-secret", "request_id": "r1"})
    assert out["api_key"] == "[REDACTED]"
    assert out["request_id"] == "r1"


def test_redacts_authorization_and_token():
    out = redact_processor(
        None, "info", {"authorization": "Bearer abc", "openai_api_key": "sk-1", "count": 1}
    )
    assert out["authorization"] == "[REDACTED]"
    assert out["openai_api_key"] == "[REDACTED]"
    assert out["count"] == 1


def test_does_not_redact_normal_keys():
    out = redact_processor(
        None, "info", {"request_id": "r1", "provider": "openai", "model": "gpt-4o"}
    )
    assert out == {"request_id": "r1", "provider": "openai", "model": "gpt-4o"}


def test_case_insensitive():
    out = redact_processor(None, "info", {"API_KEY": "abc", "ApiToken": "xyz"})
    assert out["API_KEY"] == "[REDACTED]"
    assert out["ApiToken"] == "[REDACTED]"
