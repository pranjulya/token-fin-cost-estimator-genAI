"""Unit tests for global exception handlers (app/api/handlers.py).

Focus: the SQLAlchemyError and generic Exception handlers must log the
traceback (so production is debuggable) while returning a generic envelope.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.handlers import register_exception_handlers


def _make_app_with_route(exception: Exception) -> FastAPI:
    app = FastAPI()

    @app.get("/boom")
    async def boom():
        raise exception

    register_exception_handlers(app)
    return app


def test_db_error_logs_exception_and_returns_generic():
    app = _make_app_with_route(OperationalError("SELECT", {}, Exception("conn refused")))
    with patch("app.api.handlers.structlog.get_logger") as mock_get_logger:
        mock_logger = mock_get_logger.return_value
        resp = TestClient(app, raise_server_exceptions=False).get("/boom")

    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "DATABASE_ERROR"
    assert "conn refused" not in body["error"]["message"]  # client stays generic
    mock_get_logger.assert_called_once_with("app.errors")
    mock_logger.exception.assert_called_once()
    assert mock_logger.exception.call_args.args[0] == "db_error"
    assert mock_logger.exception.call_args.kwargs["endpoint"] == "GET /boom"


def test_internal_error_logs_exception_and_returns_generic():
    app = _make_app_with_route(RuntimeError("secret detail"))
    with patch("app.api.handlers.structlog.get_logger") as mock_get_logger:
        mock_logger = mock_get_logger.return_value
        resp = TestClient(app, raise_server_exceptions=False).get("/boom")

    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "secret detail" not in body["error"]["message"]
    mock_logger.exception.assert_called_once()
    assert mock_logger.exception.call_args.args[0] == "unhandled_exception"
