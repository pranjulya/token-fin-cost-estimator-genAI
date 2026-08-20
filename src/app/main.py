"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.handlers import register_exception_handlers
from app.api.middleware import ObservabilityMiddleware
from app.api.v1.router import api_router, health_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db import models  # noqa: F401  (register tables/metadata)
from app.db.session import async_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger = get_logger("app")
    logger.info("starting", app=get_settings().app_name, env=get_settings().environment)
    yield
    logger.info("shutdown")
    # Release the connection pool so the process exits cleanly.
    await async_engine.dispose()
    # Close the pooled LLM httpx client if one was created.
    try:
        from app.providers.llm import _cached_provider

        provider = _cached_provider("openai")
        await provider.aclose()
    except Exception:  # noqa: S110 - shutdown must not raise
        logger.warning("llm_client_close_failed")


def create_app() -> FastAPI:
    settings = get_settings()
    prod = settings.environment != "development"

    # Production boot guard: refuse to start without API keys and hide docs.
    # A FinOps service must never boot with auth disabled in prod.
    if prod:
        if not settings.api_keys or not settings.admin_api_keys:
            raise RuntimeError(
                "APP_API_KEYS and APP_ADMIN_API_KEYS are required when "
                f"APP_ENVIRONMENT='{settings.environment}' (not 'development')."
            )
        if settings.auth_disabled:
            raise RuntimeError(
                "APP_AUTH_DISABLED is not allowed when "
                f"APP_ENVIRONMENT='{settings.environment}' (not 'development')."
            )

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if prod else "/docs",
        redoc_url=None if prod else "/redoc",
        openapi_url=None if prod else "/openapi.json",
    )
    app.add_middleware(ObservabilityMiddleware)
    # CORS: enabled only when origins are configured (empty = disabled).
    origins = settings.cors_origin_list
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router)
    return app


app = create_app()
