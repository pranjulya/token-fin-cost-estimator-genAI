"""Application configuration loaded from environment / .env."""

from decimal import Decimal
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings. Values come from env vars or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_", extra="ignore")

    app_name: str = "token-cost-estimator"
    environment: str = "development"
    debug: bool = False

    database_url: str = Field(
        default="postgresql+psycopg://pranjulyabajpai@localhost:5432/token_cost_estimator"
    )

    # Estimate guardrails
    max_prompt_chars: int = 200_000
    max_expected_output_tokens: int = 1_000_000

    # Observability
    log_level: str = "info"

    # CORS (empty = disabled). Comma-separated origins.
    cors_origins: str = ""

    # Alert / anomaly tuning (Phase 13). Env prefix APP_ (e.g. APP_ALERTS_ENABLED).
    # alerts_enabled is read once at startup (get_settings is lru-cached) — a
    # change requires a process restart.
    alerts_enabled: bool = True
    alert_anomaly_min_samples: int = 10
    alert_anomaly_lookback: int = 100
    alert_anomaly_multiplier: Decimal = Decimal("50")
    alert_anomaly_absolute_min_usd: Decimal = Decimal("5.00")
    alert_anomaly_critical_usd: Decimal = Decimal("10.00")
    # Stored variance_percent threshold; 400 => actual >= 5x estimate.
    alert_anomaly_variance_percent: Decimal = Decimal("400")

    # LLM provider (Phase 14). Env prefix APP_ (e.g. APP_OPENAI_API_KEY).
    # generate_enabled is read once at startup (get_settings is lru-cached) —
    # flipping it requires a process restart.
    generate_enabled: bool = False
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_timeout_seconds: float = 60

    # Observability (Phase 16).
    metrics_enabled: bool = True
    service_name: str = "token-cost-estimator"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
