"""ALPHA BIST - Configuration Management v2.0

P0-1: Security hardened.
- Production'da insecure default'lara izin verilmez.
- Startup validation zorunlu.
- Environment ayrımı (development/staging/production).
- Secret minimum length kontrolü.
"""

import sys
import os
import logging
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator, model_validator
from typing import Optional

logger = logging.getLogger(__name__)

# Insecure defaults that MUST NOT be used in production
_INSECURE_VALUES = {
    "change-this", "change-me", "password", "secret",
    "alpha_secure_2026", "admin", "default", "", "test",
}

_MIN_SECRET_LENGTH = 16

class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # App
    app_env: str = Field(default="development", alias="APP_ENV")
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")

    # PostgreSQL
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="alpha_bist", alias="POSTGRES_DB")
    postgres_user: str = Field(default="alpha", alias="POSTGRES_USER")
    postgres_password: str = Field(default="", alias="POSTGRES_PASSWORD")

    # ClickHouse
    clickhouse_host: str = Field(default="localhost", alias="CLICKHOUSE_HOST")
    clickhouse_port: int = Field(default=9000, alias="CLICKHOUSE_PORT")
    clickhouse_http_port: int = Field(default=8123, alias="CLICKHOUSE_HTTP_PORT")
    clickhouse_db: str = Field(default="alpha_bist", alias="CLICKHOUSE_DB")
    clickhouse_user: str = Field(default="default", alias="CLICKHOUSE_USER")
    clickhouse_password: str = Field(default="", alias="CLICKHOUSE_PASSWORD")

    # Redis
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_password: str = Field(default="", alias="REDIS_PASSWORD")

    # Redpanda (Kafka-compatible)
    redpanda_brokers: str = Field(default="localhost:9092", alias="REDPANDA_BROKERS")

    # LLM
    ollama_base_url: str = Field(default="http://host.docker.internal:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="gemma4:12b-q4_0", alias="OLLAMA_MODEL")
    llm_context_size: int = Field(default=8192, alias="LLM_CONTEXT_SIZE")

    # Data Sources
    tcmb_evds_api_key: Optional[str] = Field(default=None, alias="TCMB_EVDS_API_KEY")
    news_api_key: Optional[str] = Field(default=None, alias="NEWS_API_KEY")
    alpha_vantage_key: Optional[str] = Field(default=None, alias="ALPHA_VANTAGE_KEY")

    # Security — NO defaults in production
    secret_key: str = Field(default="", alias="SECRET_KEY")
    jwt_secret: str = Field(default="", alias="JWT_SECRET")

    # MLflow
    mlflow_tracking_uri: str = Field(default="http://localhost:5000", alias="MLFLOW_TRACKING_URI")

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in ("production", "prod", "staging")

    @property
    def postgres_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def postgres_url_sync(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @model_validator(mode="after")
    def _validate_production_security(self) -> "Settings":
        """Production'da insecure configuration kontrolü.
        Bu fonksiyon startup'ta çalışır ve insecure config varsa FAIL.
        """
        if not self.is_production:
            return self

        errors = []

        # Secret key kontrolü
        if not self.secret_key or self.secret_key in _INSECURE_VALUES:
            errors.append("SECRET_KEY is insecure or empty")
        elif len(self.secret_key) < _MIN_SECRET_LENGTH:
            errors.append(f"SECRET_KEY too short (min {_MIN_SECRET_LENGTH} chars)")

        # JWT secret kontrolü
        if not self.jwt_secret or self.jwt_secret in _INSECURE_VALUES:
            errors.append("JWT_SECRET is insecure or empty")
        elif len(self.jwt_secret) < _MIN_SECRET_LENGTH:
            errors.append(f"JWT_SECRET too short (min {_MIN_SECRET_LENGTH} chars)")

        # PostgreSQL password kontrolü
        if not self.postgres_password or self.postgres_password in _INSECURE_VALUES:
            errors.append("POSTGRES_PASSWORD is insecure or empty")

        # Debug mode kontrolü
        if self.app_debug:
            errors.append("APP_DEBUG must be False in production")

        if errors:
            error_msg = "\n".join(f"  - {e}" for e in errors)
            logger.critical(f"\n{'='*60}\nPRODUCTION SECURITY VIOLATION:\n{error_msg}\n{'='*60}")
            sys.exit(1)

        return self

    @field_validator("app_port")
    @classmethod
    def _validate_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError(f"Invalid port: {v}")
        return v

    @field_validator("postgres_port")
    @classmethod
    def _validate_pg_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError(f"Invalid PostgreSQL port: {v}")
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "allow"


def get_settings() -> Settings:
    """Settings'i güvenli şekilde yükle.
    Başarısız olursa sys.exit.
    """
    try:
        s = Settings()
        env_label = "PRODUCTION" if s.is_production else "DEVELOPMENT"
        logger.info(f"Configuration loaded [{env_label}]")
        return s
    except Exception as e:
        logger.critical(f"Configuration loading FAILED: {e}")
        sys.exit(1)


settings = get_settings()
