"""Global exception handlers: translate exceptions into the PRD error envelope.

{"error": {"code": ..., "message": ..., "request_id": ...}}
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppError, ErrorCode
from app.schemas.common import ErrorDetail, GenericError

VALIDATION_STATUS = 422


def _request_id(request: Request, exc: AppError | None = None) -> str:
    # Prefer the exception's business request_id (e.g. client-supplied body id
    # referenced in the error message), then the middleware-bound correlation
    # id, then the header, then a fresh id for direct calls.
    if exc is not None and getattr(exc, "request_id", None):
        return exc.request_id
    bound = structlog.contextvars.get_contextvars().get("request_id")
    if bound:
        return bound
    return request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:16]}"


def _error_response(code: str, message: str, request_id: str, status: int) -> JSONResponse:
    body = GenericError(error=ErrorDetail(code=code, message=message, request_id=request_id))
    return JSONResponse(status_code=status, content=body.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(exc.code, exc.message, _request_id(request, exc), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []))
        msg = f"Validation error{(' at ' + loc) if loc else ''}: {first.get('msg', '')}"
        return _error_response(
            ErrorCode.VALIDATION_ERROR, msg, _request_id(request), VALIDATION_STATUS
        )

    @app.exception_handler(SQLAlchemyError)
    async def _db_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        return _error_response(
            ErrorCode.DATABASE_ERROR, "Database operation failed.", _request_id(request), 500
        )

    @app.exception_handler(Exception)
    async def _internal_error(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(
            ErrorCode.INTERNAL_ERROR, "Internal server error.", _request_id(request), 500
        )
