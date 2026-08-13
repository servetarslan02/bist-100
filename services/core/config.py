"""ALPHA BIST - Configuration Management"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
import os


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
    postgres_password: str = Field(default="alpha_secure_2026", alias="POSTGRES_PASSWORD")

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

    # Security
    secret_key: str = Field(default="change-this", alias="SECRET_KEY")
    jwt_secret: str = Field(default="change-this", alias="JWT_SECRET")

    # MLflow
    mlflow_tracking_uri: str = Field(default="http://localhost:5000", alias="MLFLOW_TRACKING_URI")

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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "allow"


settings = Settings()
