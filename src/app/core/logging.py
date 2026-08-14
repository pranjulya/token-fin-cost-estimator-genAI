"""Structured JSON logging via structlog.

Prints a short human-readable text format during development and switches to
JSON in production. Sensitive prompt content is never logged — callers must
not pass raw prompt text into log bindings. Secret-shaped keys are redacted by
a processor (Phase 17).
"""

from __future__ import annotations

import logging
import logging.config
import sys

import structlog

from app.core.config import get_settings

# Keys whose values are redacted from every log event (Phase 17).
_SECRET_KEY_MARKERS = ("api_key", "apikey", "token", "secret", "password", "authorization")


def redact_processor(_logger, _method, event_dict):
    """Replace values of secret-shaped keys with [REDACTED]."""
    for key in list(event_dict):
        lowered = key.lower()
        if any(marker in lowered for marker in _SECRET_KEY_MARKERS):
            event_dict[key] = "[REDACTED]"
    return event_dict


def _shared_processors() -> list:
    timestamper = structlog.processors.TimeStamper(fmt="iso")
    return [
        structlog.contextvars.merge_contextvars,
        redact_processor,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]


def configure_logging() -> None:
    """Configure the root logger and structlog. Idempotent."""
    settings = get_settings()
    # Avoid re-configuring / duplicate handlers on repeated calls (tests).
    root = logging.getLogger()
    if root.handlers:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root.setLevel(level)

    if settings.environment.lower() == "production":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "plain": {
                "()": structlog.stdlib.ProcessorFormatter,
                "foreign_pre_chain": _shared_processors(),
                "processors": [
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    renderer,
                ],
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "plain",
                "stream": sys.stdout,
            },
        },
        "loggers": {
            "": {"handlers": ["default"], "level": level},
            "uvicorn": {"handlers": ["default"], "level": "WARNING"},
        },
    }
    logging.config.dictConfig(log_config)  # type: ignore[attr-defined]
    structlog.configure(
        processors=_shared_processors() + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name or "app")
