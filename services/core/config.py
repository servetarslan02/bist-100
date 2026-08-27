"""ALPHA BIST - Configuration Management v2.0

P0-1: Security hardened.
- Production'da insecure default'lara izin verilmez.
- Startup validation zorunlu.
- Environment ayrımı (development/staging/production).
- Secret minimum length kontrolü.
"""

import logging
import os
import sys

try:
    from pydantic import Field, field_validator, model_validator
    from pydantic_settings import BaseSettings, SettingsConfigDict

    _PYDANTIC_V2 = True
except ImportError:
    from pydantic.v1 import BaseSettings, Field, root_validator, validator

    _PYDANTIC_V2 = False

logger = logging.getLogger(__name__)

# Insecure defaults that MUST NOT be used in production
_INSECURE_VALUES = {
    "change-this",
    "change-me",
    "password",
    "secret",
    "alpha_secure_2026",
    "admin",
    "default",
    "",
    "test",
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
    postgres_replica_host: str | None = Field(default=None, alias="POSTGRES_REPLICA_HOST")
    postgres_replica_port: int = Field(default=5433, alias="POSTGRES_REPLICA_PORT")

    # Sharding
    sharding_enabled: bool = Field(default=False, alias="SHARDING_ENABLED")

    # ClickHouse
    clickhouse_host: str = Field(default="localhost", alias="CLICKHOUSE_HOST")
    clickhouse_port: int = Field(default=9000, alias="CLICKHOUSE_PORT")
    clickhouse_http_port: int = Field(default=8123, alias="CLICKHOUSE_HTTP_PORT")
    clickhouse_db: str = Field(default="alpha_bist", alias="CLICKHOUSE_DB")
    clickhouse_user: str = Field(default="default", alias="CLICKHOUSE_USER")
    clickhouse_password: str = Field(default="", alias="CLICKHOUSE_PASSWORD")

    # QuestDB (tick verisi için)
    questdb_host: str = Field(default="localhost", alias="QUESTDB_HOST")
    questdb_http_port: int = Field(default=9009, alias="QUESTDB_HTTP_PORT")
    questdb_pg_port: int = Field(default=8812, alias="QUESTDB_PG_PORT")
    questdb_ilp_port: int = Field(default=9009, alias="QUESTDB_ILP_PORT")

    # Redis
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_password: str = Field(default="", alias="REDIS_PASSWORD")

    # F-027: Connection Pool Settings (PgBouncer compatible)
    pg_pool_size: int = Field(default=20, alias="PG_POOL_SIZE")
    pg_max_overflow: int = Field(default=10, alias="PG_MAX_OVERFLOW")
    pg_pool_timeout: int = Field(default=30, alias="PG_POOL_TIMEOUT")
    pg_pool_recycle: int = Field(default=1800, alias="PG_POOL_RECYCLE")  # 30 dk

    # NATS (yüksek throughput, düşük gecikme)
    nats_url: str = Field(default="nats://localhost:4222", alias="NATS_URL")

    # gRPC
    grpc_port: int = Field(default=50051, alias="GRPC_PORT")

    # LLM
    ollama_base_url: str = Field(default="http://host.docker.internal:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="gemma4:12b-q4_0", alias="OLLAMA_MODEL")
    llm_context_size: int = Field(default=8192, alias="LLM_CONTEXT_SIZE")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-3.7-flash", alias="GEMINI_MODEL")

    # Data Sources
    tcmb_evds_api_key: str | None = Field(default=None, alias="TCMB_EVDS_API_KEY")
    news_api_key: str | None = Field(default=None, alias="NEWS_API_KEY")
    alpha_vantage_key: str | None = Field(default=None, alias="ALPHA_VANTAGE_KEY")

    # Security — NO defaults in production
    secret_key: str = Field(default="", alias="SECRET_KEY")
    jwt_secret: str = Field(default="", alias="JWT_SECRET")

    # MLflow
    mlflow_tracking_uri: str = Field(default="http://localhost:5000", alias="MLFLOW_TRACKING_URI")

    # Broker
    broker_type: str = Field(default="paper", alias="BROKER_TYPE")
    broker_api_key: str | None = Field(default=None, alias="BROKER_API_KEY")
    broker_api_secret: str | None = Field(default=None, alias="BROKER_API_SECRET")
    broker_account_id: str | None = Field(default=None, alias="BROKER_ACCOUNT_ID")

    # KAP
    kap_api_key: str | None = Field(default=None, alias="KAP_API_KEY")

    # DB Pool
    db_pool_min: int = Field(default=2, alias="DB_POOL_MIN")
    db_pool_max: int = Field(default=10, alias="DB_POOL_MAX")
    db_command_timeout: int = Field(default=30, alias="DB_COMMAND_TIMEOUT")

    # Scheduler intervals (saniye)
    interval_feature_calculation: int = Field(default=300, alias="INTERVAL_FEATURE_CALCULATION")
    interval_live_inference: int = Field(default=300, alias="INTERVAL_LIVE_INFERENCE")
    interval_health_check: int = Field(default=60, alias="INTERVAL_HEALTH_CHECK")
    interval_market_data: int = Field(default=120, alias="INTERVAL_MARKET_DATA")
    interval_ranking: int = Field(default=600, alias="INTERVAL_RANKING")

    # =====================================================
    # Market State Settings
    # =====================================================

    # Breadth Engine
    breadth_mcclellan_ema_short: int = Field(default=19, alias="BREADTH_MCCLELLAN_EMA_SHORT")
    breadth_mcclellan_ema_long: int = Field(default=39, alias="BREADTH_MCCLELLAN_EMA_LONG")
    breadth_thrust_threshold: float = Field(default=0.615, alias="BREADTH_THRUST_THRESHOLD")
    breadth_liquidity_volume_min: float = Field(default=10000, alias="BREADTH_LIQUIDITY_VOLUME_MIN")

    # Regime Detection
    regime_hmm_weight: float = Field(default=0.30, alias="REGIME_HMM_WEIGHT")
    regime_score_weight: float = Field(default=0.50, alias="REGIME_SCORE_WEIGHT")
    regime_gmm_weight: float = Field(default=0.20, alias="REGIME_GMM_WEIGHT")
    regime_rolling_window: int = Field(default=63, alias="REGIME_ROLLING_WINDOW")
    regime_confidence_min: float = Field(default=0.30, alias="REGIME_CONFIDENCE_MIN")
    regime_transition_stability_window: int = Field(default=20, alias="REGIME_TRANSITION_STABILITY_WINDOW")

    # Risk Appetite Weights
    risk_appetite_breadth_weight: float = Field(default=0.30, alias="RISK_APPETITE_BREADTH_WEIGHT")
    risk_appetite_momentum_weight: float = Field(default=0.20, alias="RISK_APPETITE_MOMENTUM_WEIGHT")
    risk_appetite_volatility_weight: float = Field(default=0.20, alias="RISK_APPETITE_VOLATILITY_WEIGHT")
    risk_appetite_rsi_weight: float = Field(default=0.10, alias="RISK_APPETITE_RSI_WEIGHT")
    risk_appetite_sentiment_weight: float = Field(default=0.10, alias="RISK_APPETITE_SENTIMENT_WEIGHT")
    risk_appetite_macro_weight: float = Field(default=0.10, alias="RISK_APPETITE_MACRO_WEIGHT")

    # Multi-Timeframe
    multi_tf_intraday_interval: str = Field(default="15min", alias="MULTI_TF_INTRADAY_INTERVAL")
    multi_tf_daily_interval: str = Field(default="1d", alias="MULTI_TF_DAILY_INTERVAL")
    multi_tf_weekly_interval: str = Field(default="1w", alias="MULTI_TF_WEEKLY_INTERVAL")
    multi_tf_monthly_interval: str = Field(default="1M", alias="MULTI_TF_MONTHLY_INTERVAL")

    # Liquidity State
    liquidity_spread_threshold: float = Field(default=0.02, alias="LIQUIDITY_SPREAD_THRESHOLD")
    liquidity_volume_participation_min: float = Field(default=0.005, alias="LIQUIDITY_VOLUME_PARTICIPATION_MIN")

    # Sentiment State
    sentiment_news_weight: float = Field(default=0.50, alias="SENTIMENT_NEWS_WEIGHT")
    sentiment_social_weight: float = Field(default=0.30, alias="SENTIMENT_SOCIAL_WEIGHT")
    sentiment_options_weight: float = Field(default=0.20, alias="SENTIMENT_OPTIONS_WEIGHT")

    @property
    def is_production(self) -> bool:
        """Production ortaminda mi?"""
        return self.app_env.lower() in ("production", "prod", "staging")

    @property
    def postgres_url(self) -> str:
        """Async PostgreSQL connection URL."""
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def postgres_url_sync(self) -> str:
        """Sync PostgreSQL connection URL."""
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def redis_url(self) -> str:
        """Redis connection URL."""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    if _PYDANTIC_V2:
        model_config = SettingsConfigDict(extra="allow")

        @model_validator(mode="after")
        def _validate_production_security(self):
            """Production'da insecure configuration kontrolü."""
            if not self.is_production:
                return self
            config = self.__dict__
            errors = []
            secret_key = config.get("secret_key", "")
            jwt_secret = config.get("jwt_secret", "")
            postgres_password = config.get("postgres_password", "")
            app_debug = config.get("app_debug", True)
            if not secret_key or secret_key in _INSECURE_VALUES:
                errors.append("SECRET_KEY is insecure or empty")
            elif len(secret_key) < _MIN_SECRET_LENGTH:
                errors.append(f"SECRET_KEY too short (min {_MIN_SECRET_LENGTH} chars)")

            if not jwt_secret or jwt_secret in _INSECURE_VALUES:
                errors.append("JWT_SECRET is insecure or empty")
            elif len(jwt_secret) < _MIN_SECRET_LENGTH:
                errors.append(f"JWT_SECRET too short (min {_MIN_SECRET_LENGTH} chars)")

            if not postgres_password or postgres_password in _INSECURE_VALUES:
                errors.append("POSTGRES_PASSWORD is insecure or empty")

            if app_debug:
                errors.append("APP_DEBUG must be False in production")

            if errors:
                error_msg = "\n".join(f"  - {e}" for e in errors)
                logger.critical(f"\n{'=' * 60}\nPRODUCTION SECURITY VIOLATION:\n{error_msg}\n{'=' * 60}")
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

    else:

        class Config:
            extra = "allow"

        @root_validator
        def _validate_production_security_v1(cls, values):
            config = values
            if str(config.get("app_env", "development")).lower() not in ("production", "prod", "staging"):
                return values
            errors = []
            secret_key = config.get("secret_key", "")
            jwt_secret = config.get("jwt_secret", "")
            postgres_password = config.get("postgres_password", "")
            app_debug = config.get("app_debug", True)
            if not secret_key or secret_key in _INSECURE_VALUES:
                errors.append("SECRET_KEY is insecure or empty")
            elif len(secret_key) < _MIN_SECRET_LENGTH:
                errors.append(f"SECRET_KEY too short (min {_MIN_SECRET_LENGTH} chars)")

            if not jwt_secret or jwt_secret in _INSECURE_VALUES:
                errors.append("JWT_SECRET is insecure or empty")
            elif len(jwt_secret) < _MIN_SECRET_LENGTH:
                errors.append(f"JWT_SECRET too short (min {_MIN_SECRET_LENGTH} chars)")

            if not postgres_password or postgres_password in _INSECURE_VALUES:
                errors.append("POSTGRES_PASSWORD is insecure or empty")

            if app_debug:
                errors.append("APP_DEBUG must be False in production")

            if errors:
                error_msg = "\n".join(f"  - {e}" for e in errors)
                logger.critical(f"\n{'=' * 60}\nPRODUCTION SECURITY VIOLATION:\n{error_msg}\n{'=' * 60}")
                sys.exit(1)
            return values

        @validator("app_port")
        def _validate_port_v1(cls, v: int) -> int:
            if not 1 <= v <= 65535:
                raise ValueError(f"Invalid port: {v}")
            return v

        @validator("postgres_port")
        def _validate_pg_port_v1(cls, v: int) -> int:
            if not 1 <= v <= 65535:
                raise ValueError(f"Invalid PostgreSQL port: {v}")
            return v


def get_settings() -> Settings:
    """Settings'i güvenli şekilde yükle."""
    if os.path.exists(".env"):
        try:
            with open(".env", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        value = v.strip()
                        if not (value.startswith(('"', "'")) and value.endswith(('"', "'"))):
                            value = value.split(" #", 1)[0].rstrip()
                        os.environ.setdefault(k.strip(), value.strip('"').strip("'"))
        except Exception:
            logger.warning("Caught Exception in get_settings", exc_info=True)

    try:
        s = Settings()
        env_label = "PRODUCTION" if getattr(s, "is_production", False) else "DEVELOPMENT"
        logger.info(f"Configuration loaded [{env_label}]")
        return s
    except Exception as e:
        logger.warning(f"Configuration loading note: {e} — using construct() defaults")
        try:
            return Settings.construct()
        except Exception:
            return Settings()


settings = get_settings()
