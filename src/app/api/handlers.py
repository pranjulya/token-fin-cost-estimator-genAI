"""Global exception handlers: translate exceptions into the PRD error envelope.

{"error": {"code": ..., "message": ..., "request_id": ...}}
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppError, ErrorCode, RateLimitError
from app.schemas.common import ErrorDetail, GenericError

VALIDATION_STATUS = 422


def _request_id(request: Request, exc: AppError | None = None) -> str:
    # Prefer the exception's business request_id (e.g. client-supplied body id
    # referenced in the error message), then the middleware-bound correlation
    # id, then the header, then a fresh id for direct calls.
    if exc is not None and getattr(exc, "request_id", None):
        return str(exc.request_id)
    bound = structlog.contextvars.get_contextvars().get("request_id")
    if bound:
        return str(bound)
    return request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:16]}"


def _error_response(code: str, message: str, request_id: str, status: int) -> JSONResponse:
    body = GenericError(error=ErrorDetail(code=code, message=message, request_id=request_id))
    return JSONResponse(status_code=status, content=body.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RateLimitError)
    async def _rate_limit_error(request: Request, exc: RateLimitError) -> JSONResponse:
        # Attach Retry-After so clients know when to try again (429 semantics).
        headers = None
        if exc.retry_after_seconds is not None:
            headers = {"Retry-After": str(exc.retry_after_seconds)}
        body = GenericError(
            error=ErrorDetail(
                code=exc.code, message=exc.message, request_id=_request_id(request, exc)
            )
        )
        return JSONResponse(status_code=exc.status_code, content=body.model_dump(), headers=headers)

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

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
        # Convert bare FastAPI HTTPExceptions (e.g. route-level 404s) into the
        # PRD error envelope (Phase 18 contract), mapping status to a real code.
        code = {
            401: ErrorCode.UNAUTHORIZED,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.NOT_FOUND,
        }.get(exc.status_code, ErrorCode.VALIDATION_ERROR)
        return _error_response(code, str(exc.detail), _request_id(request), exc.status_code)

    @app.exception_handler(SQLAlchemyError)
    async def _db_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        # Log the full traceback (with correlation id) so prod DB failures are
        # diagnosable; keep the client message generic.
        request_id = _request_id(request)
        logger = structlog.get_logger("app.errors")
        logger.exception(
            "db_error",
            request_id=request_id,
            endpoint=f"{request.method} {request.url.path}",
        )
        return _error_response(
            ErrorCode.DATABASE_ERROR, "Database operation failed.", request_id, 500
        )

    @app.exception_handler(Exception)
    async def _internal_error(request: Request, exc: Exception) -> JSONResponse:
        # Log the full traceback with the correlation id bound so production
        # exceptions are diagnosable without leaking details to the client.
        request_id = _request_id(request)
        logger = structlog.get_logger("app.errors")
        logger.exception(
            "unhandled_exception",
            request_id=request_id,
            endpoint=f"{request.method} {request.url.path}",
        )
        return _error_response(ErrorCode.INTERNAL_ERROR, "Internal server error.", request_id, 500)
