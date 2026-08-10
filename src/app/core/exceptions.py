"""Domain error codes and exception types.

These map to the standardized error envelope:
    {"error": {"code": ..., "message": ..., "request_id": ...}}
(Matching the PRD # 30 error model.)
"""

from __future__ import annotations


class ErrorCode(str):
    """Canonical machine-readable error codes exposed on the API."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    MODEL_NOT_SUPPORTED = "MODEL_NOT_SUPPORTED"
    MODEL_PRICING_NOT_FOUND = "MODEL_PRICING_NOT_FOUND"
    TOKENIZATION_FAILED = "TOKENIZATION_FAILED"
    USAGE_RECONCILIATION_FAILED = "USAGE_RECONCILIATION_FAILED"
    DATABASE_ERROR = "DATABASE_ERROR"
    REDIS_UNAVAILABLE = "REDIS_UNAVAILABLE"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """Base class for all domain exceptions."""

    code: str = ErrorCode.INTERNAL_ERROR
    status_code: int = 500

    def __init__(self, message: str, *, request_id: str | None = None):
        super().__init__(message)
        self.message = message
        self.request_id = request_id


class ModelPricingNotFoundError(AppError):
    code = ErrorCode.MODEL_PRICING_NOT_FOUND
    status_code = 404

    def __init__(self, provider: str, model: str, *, request_id: str | None = None):
        super().__init__(
            f"No pricing configuration found for provider='{provider}' model='{model}'.",
            request_id=request_id,
        )


class ModelNotSupportedError(AppError):
    code = ErrorCode.MODEL_NOT_SUPPORTED
    status_code = 422

    def __init__(self, provider: str, model: str, *, request_id: str | None = None):
        super().__init__(
            f"Model '{model}' is not supported by provider '{provider}'.",
            request_id=request_id,
        )


class TokenizationError(AppError):
    code = ErrorCode.TOKENIZATION_FAILED
    status_code = 422


class ReconciliationError(AppError):
    code = ErrorCode.USAGE_RECONCILIATION_FAILED
    status_code = 500


class DatabaseError(AppError):
    code = ErrorCode.DATABASE_ERROR
    status_code = 500


class InvalidRequestError(AppError):
    """Generic 4xx client error (validation beyond Pydantic)."""

    code = ErrorCode.VALIDATION_ERROR
    status_code = 422
