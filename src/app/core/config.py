"""Application configuration loaded from environment / .env."""

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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
