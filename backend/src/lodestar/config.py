"""Typed configuration loaded from environment variables (12-factor).

Secrets are SecretStr so they never appear in logs, reprs or tracebacks.
Production refuses to boot with weak or default secrets.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Reads the repo-root .env when run from backend/ (later files win). Real env vars override both.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), env_prefix="LS_", extra="ignore")

    env: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:5173"]

    database_url: str = "postgresql+asyncpg://lodestar:lodestar@localhost:5432/lodestar"
    db_pool_size: int = 10
    db_max_overflow: int = 5
    redis_url: str = "redis://localhost:6379/0"

    # --- auth
    # local: single-user, no login (bind to localhost only). password: owner account + JWT.
    # Production requires password.
    auth_mode: Literal["local", "password"] = "local"
    jwt_secret: SecretStr = SecretStr("dev-only-change-me-dev-only-change-me")
    jwt_issuer: str = "lodestar"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 7
    allow_registration: bool = False
    # Comma-separated Fernet keys; the first encrypts, all decrypt (zero-downtime rotation).
    field_encryption_keys: SecretStr = SecretStr("")

    # --- rate limits
    rate_limit_per_minute: int = 120
    login_attempts_per_minute: int = 5
    analyses_per_hour: int = 30

    # --- data
    # auto: live data when a CoinGecko key is configured, otherwise demo (synthetic, offline, bannered).
    data_mode: Literal["auto", "demo", "live"] = "auto"
    coingecko_api_key: SecretStr | None = None
    coingecko_plan: Literal["public", "demo", "pro"] = "public"
    rpc_urls: dict[str, str] = {
        "ethereum": "https://ethereum-rpc.publicnode.com",
        "polygon": "https://polygon-bor-rpc.publicnode.com",
    }
    news_feeds: list[str] = [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss",
        "https://decrypt.co/feed",
    ]
    snapshot_cache_ttl_seconds: int = 60
    history_cache_ttl_seconds: int = 60 * 30
    fundamentals_cache_ttl_seconds: int = 60 * 60 * 6
    candles_cache_ttl_seconds: int = 60 * 30

    # --- pipeline
    max_agent_steps: int = Field(default=6, ge=2, le=12)
    max_repairs: int = Field(default=2, ge=0, le=2)
    mismatch_tolerance_pct: float = 1.5
    demo_step_delay_ms: int = 350  # demo mode only: pace steps so the live timeline is watchable
    celery_broker_url: str | None = None  # defaults to redis_url

    # --- LLM
    llm_enabled: bool = True
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("LS_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
    )
    llm_model: str = "claude-opus-5-5"
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    llm_max_tokens: int = 16000
    llm_timeout_seconds: float = 120.0
    llm_server_fallbacks: bool = True

    # --- scheduling (UTC)
    daily_report_hour_utc: int = 6

    @property
    def is_production(self) -> bool:
        return self.env in ("staging", "production")

    @property
    def effective_data_mode(self) -> Literal["demo", "live"]:
        if self.data_mode == "auto":
            return "live" if self.coingecko_api_key and self.coingecko_api_key.get_secret_value() else "demo"
        return self.data_mode

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_enabled and self.anthropic_api_key and self.anthropic_api_key.get_secret_value())

    @model_validator(mode="after")
    def _guard_production_secrets(self) -> Settings:
        if self.is_production:
            if len(self.jwt_secret.get_secret_value()) < 32 or "change-me" in self.jwt_secret.get_secret_value():
                raise ValueError("LS_JWT_SECRET must be a random value of at least 32 characters in production")
            if not self.field_encryption_keys.get_secret_value():
                raise ValueError("LS_FIELD_ENCRYPTION_KEYS is required in production")
            if self.auth_mode != "password":
                raise ValueError("LS_AUTH_MODE=password is required in production")
            if any(o == "*" for o in self.cors_origins):
                raise ValueError("Wildcard CORS is not allowed in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
