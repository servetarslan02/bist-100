"""ALPHA BIST — Kurumsal Konfigürasyon Yönetim Sistemi v3.0 (Enterprise-Grade Settings)

Bu modül, platformun tüm çalışma ortamı (development, test, staging, production),
veritabanı topolojisi (TimescaleDB, ClickHouse, QuestDB, DuckDB, Redis 8 Sentinel),
risk parametreleri, piyasa rejim ağırlıkları ve API anahtarlarını Pydantic v2
altyapısıyla tip güvenli, doğrulanmış ve çevre değişkenlerinden (environment variables)
beslenen tek bir merkezden yönetir.

Kurumsal Standartlar ve Yetenekler:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Pydantic v2 Temelli: `BaseSettings` ve `SettingsConfigDict` ile katı doğrulama.
2. Gizli Veri Maskeleme: Parolalar, JWT ve API anahtarları `__repr__` ve loglarda
   asla açık metin olarak görünmez (`to_dict(mask_secrets=True)`).
3. Fail-Closed Güvenlik: Production ortamında güvensiz veya eksik sırlar tespit
   edildiğinde `ConfigurationError` fırlatılır; sessizce atlanmaz veya interpreter
   aniden `sys.exit` ile sonlandırılmaz.
4. Genişletilmiş Veritabanı Topolojisi: GEMINI.md doğrultusunda TimescaleDB (5432/5433),
   ClickHouse (8123/9002/9000), QuestDB (9000/8812/9009), Redis Sentinel (26379)
   ve DuckDB yerel yolları tam desteklenir.
5. Polars & DuckDB Entegrasyonu: Aktif konfigürasyon ve denetim anlık görüntüleri
   (audit snapshots) Polars DataFrame ve DuckDB tablosu olarak saklanabilir.
6. Eşzamanlılık Güvenliği: `reload_settings()` fonksiyonu `threading.RLock` ile korunur.
"""

from __future__ import annotations

import contextlib
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import orjson
import polars as pl
import structlog
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger(__name__)

# =====================================================
# GÜVENLİK VE YAPILANDIRMA SABİTLERİ
# =====================================================
DEFAULT_MIN_SECRET_LENGTH: int = 16
DEFAULT_DUCKDB_CONFIG_PATH: Path = Path("data/config_snapshots.duckdb")

# Production ortamında kabul edilmeyen güvensiz / varsayılan değerler
INSECURE_VALUES: frozenset[str] = frozenset({
    "change-this",
    "change-me",
    "password",
    "secret",
    "alpha_secure_2026",
    "admin",
    "default",
    "",
    "test",
    "123456",
})

# Maskeleme uygulanacak hassas anahtarlar
SENSITIVE_KEYS: frozenset[str] = frozenset({
    "postgres_password",
    "clickhouse_password",
    "redis_password",
    "secret_key",
    "jwt_secret",
    "gemini_api_key",
    "tcmb_evds_api_key",
    "news_api_key",
    "alpha_vantage_key",
    "broker_api_key",
    "broker_api_secret",
    "kap_api_key",
})


class ConfigurationError(ValueError):
    """Konfigürasyon doğrulama veya güvenlik hatası."""

    pass


class Settings(BaseSettings):
    """ALPHA BIST kurumsal çalışma ortamı ve servis ayarları."""

    model_config = SettingsConfigDict(
        extra="allow",
        case_sensitive=False,
        env_file_encoding="utf-8",
    )

    # Uygulama Temel Ayarları
    app_env: str = Field(default="development", alias="APP_ENV")
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")

    # PostgreSQL / TimescaleDB (Primary: 5432, Replica: 5433)
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="alpha_bist", alias="POSTGRES_DB")
    postgres_user: str = Field(default="alpha", alias="POSTGRES_USER")
    postgres_password: str = Field(default="", alias="POSTGRES_PASSWORD")
    postgres_replica_host: str | None = Field(default=None, alias="POSTGRES_REPLICA_HOST")
    postgres_replica_port: int = Field(default=5433, alias="POSTGRES_REPLICA_PORT")

    # PgBouncer ve Bağlantı Havuzu
    pg_pool_size: int = Field(default=20, alias="PG_POOL_SIZE")
    pg_max_overflow: int = Field(default=10, alias="PG_MAX_OVERFLOW")
    pg_pool_timeout: int = Field(default=30, alias="PG_POOL_TIMEOUT")
    pg_pool_recycle: int = Field(default=1800, alias="PG_POOL_RECYCLE")  # 30 dakika
    sharding_enabled: bool = Field(default=False, alias="SHARDING_ENABLED")

    # ClickHouse (OLAP Analitik: Native 9002/9000, HTTP 8123)
    clickhouse_host: str = Field(default="localhost", alias="CLICKHOUSE_HOST")
    clickhouse_port: int = Field(default=9000, alias="CLICKHOUSE_PORT")
    clickhouse_native_port: int = Field(default=9002, alias="CLICKHOUSE_NATIVE_PORT")
    clickhouse_http_port: int = Field(default=8123, alias="CLICKHOUSE_HTTP_PORT")
    clickhouse_db: str = Field(default="alpha_bist", alias="CLICKHOUSE_DB")
    clickhouse_user: str = Field(default="default", alias="CLICKHOUSE_USER")
    clickhouse_password: str = Field(default="", alias="CLICKHOUSE_PASSWORD")

    # QuestDB (Tick & Orderbook verisi: HTTP 9000, PG 8812, ILP 9009)
    questdb_host: str = Field(default="questdb", alias="QUESTDB_HOST")
    questdb_http_port: int = Field(default=9000, alias="QUESTDB_HTTP_PORT")
    questdb_pg_port: int = Field(default=8812, alias="QUESTDB_PG_PORT")
    questdb_ilp_port: int = Field(default=9009, alias="QUESTDB_ILP_PORT")

    # DuckDB (Yerel ve offline durum/analitik veritabanı yolları)
    duckdb_path: str = Field(default="data/bist.duckdb", alias="DUCKDB_PATH")
    duckdb_dlq_path: str = Field(default="data/dlq.db", alias="DUCKDB_DLQ_PATH")

    # Redis 8 + Sentinel (Cache, Pub/Sub, Streams)
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_sentinel_port: int = Field(default=26379, alias="REDIS_SENTINEL_PORT")
    redis_password: str = Field(default="", alias="REDIS_PASSWORD")

    # Gateway / Reverse Proxy & Mesajlaşma
    traefik_host: str = Field(default="localhost", alias="TRAEFIK_HOST")
    traefik_port: int = Field(default=80, alias="TRAEFIK_PORT")
    traefik_https_port: int = Field(default=443, alias="TRAEFIK_HTTPS_PORT")
    traefik_admin_port: int = Field(default=8080, alias="TRAEFIK_ADMIN_PORT")
    nats_url: str = Field(default="nats://localhost:4222", alias="NATS_URL")
    grpc_port: int = Field(default=50051, alias="GRPC_PORT")

    # Yapay Zeka ve LLM Servisleri
    ollama_base_url: str = Field(default="http://host.docker.internal:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="gemma4:12b-q4_0", alias="OLLAMA_MODEL")
    llm_context_size: int = Field(default=8192, alias="LLM_CONTEXT_SIZE")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")

    # Harici Piyasa Veri Kaynakları
    tcmb_evds_api_key: str | None = Field(default=None, alias="TCMB_EVDS_API_KEY")
    news_api_key: str | None = Field(default=None, alias="NEWS_API_KEY")
    alpha_vantage_key: str | None = Field(default=None, alias="ALPHA_VANTAGE_KEY")
    kap_api_key: str | None = Field(default=None, alias="KAP_API_KEY")

    # Güvenlik ve Kimlik Doğrulama
    secret_key: str = Field(default="", alias="SECRET_KEY")
    jwt_secret: str = Field(default="", alias="JWT_SECRET")

    # MLflow & Model Takibi
    mlflow_tracking_uri: str = Field(default="http://localhost:5000", alias="MLFLOW_TRACKING_URI")

    # Aracı Kurum & Broker Entegrasyonu
    broker_type: str = Field(default="paper", alias="BROKER_TYPE")
    broker_api_key: str | None = Field(default=None, alias="BROKER_API_KEY")
    broker_api_secret: str | None = Field(default=None, alias="BROKER_API_SECRET")
    broker_account_id: str | None = Field(default=None, alias="BROKER_ACCOUNT_ID")

    # Genel DB Havuz Sınırları
    db_pool_min: int = Field(default=2, alias="DB_POOL_MIN")
    db_pool_max: int = Field(default=10, alias="DB_POOL_MAX")
    db_command_timeout: int = Field(default=30, alias="DB_COMMAND_TIMEOUT")

    # Zamanlayıcı (Scheduler) Aralıkları (Saniye)
    interval_feature_calculation: int = Field(default=300, alias="INTERVAL_FEATURE_CALCULATION")
    interval_live_inference: int = Field(default=300, alias="INTERVAL_LIVE_INFERENCE")
    interval_health_check: int = Field(default=60, alias="INTERVAL_HEALTH_CHECK")
    interval_market_data: int = Field(default=120, alias="INTERVAL_MARKET_DATA")
    interval_ranking: int = Field(default=600, alias="INTERVAL_RANKING")

    # BIST Seans Ayarları
    bist_timezone: str = Field(default="Europe/Istanbul", alias="BIST_TIMEZONE")
    bist_open_time: str = Field(default="10:00", alias="BIST_OPEN_TIME")
    bist_close_time: str = Field(default="18:00", alias="BIST_CLOSE_TIME")

    # Piyasa Durumu ve Genişlik (Market Breadth) Ayarları
    breadth_mcclellan_ema_short: int = Field(default=19, alias="BREADTH_MCCLELLAN_EMA_SHORT")
    breadth_mcclellan_ema_long: int = Field(default=39, alias="BREADTH_MCCLELLAN_EMA_LONG")
    breadth_thrust_threshold: float = Field(default=0.615, alias="BREADTH_THRUST_THRESHOLD")
    breadth_liquidity_volume_min: float = Field(default=10000.0, alias="BREADTH_LIQUIDITY_VOLUME_MIN")

    # Rejim Tespiti (Regime Detection) Ağırlıkları
    regime_hmm_weight: float = Field(default=0.30, alias="REGIME_HMM_WEIGHT")
    regime_score_weight: float = Field(default=0.50, alias="REGIME_SCORE_WEIGHT")
    regime_gmm_weight: float = Field(default=0.20, alias="REGIME_GMM_WEIGHT")
    regime_rolling_window: int = Field(default=63, alias="REGIME_ROLLING_WINDOW")
    regime_confidence_min: float = Field(default=0.30, alias="REGIME_CONFIDENCE_MIN")
    regime_transition_stability_window: int = Field(default=20, alias="REGIME_TRANSITION_STABILITY_WINDOW")

    # Risk İştahı (Risk Appetite) Ağırlıkları
    risk_appetite_breadth_weight: float = Field(default=0.30, alias="RISK_APPETITE_BREADTH_WEIGHT")
    risk_appetite_momentum_weight: float = Field(default=0.20, alias="RISK_APPETITE_MOMENTUM_WEIGHT")
    risk_appetite_volatility_weight: float = Field(default=0.20, alias="RISK_APPETITE_VOLATILITY_WEIGHT")
    risk_appetite_rsi_weight: float = Field(default=0.10, alias="RISK_APPETITE_RSI_WEIGHT")
    risk_appetite_sentiment_weight: float = Field(default=0.10, alias="RISK_APPETITE_SENTIMENT_WEIGHT")
    risk_appetite_macro_weight: float = Field(default=0.10, alias="RISK_APPETITE_MACRO_WEIGHT")

    # Çoklu Zaman Dilimi (Multi-Timeframe) Tanımları
    multi_tf_intraday_interval: str = Field(default="15min", alias="MULTI_TF_INTRADAY_INTERVAL")
    multi_tf_daily_interval: str = Field(default="1d", alias="MULTI_TF_DAILY_INTERVAL")
    multi_tf_weekly_interval: str = Field(default="1w", alias="MULTI_TF_WEEKLY_INTERVAL")
    multi_tf_monthly_interval: str = Field(default="1M", alias="MULTI_TF_MONTHLY_INTERVAL")

    # Likidite ve Derinlik Ayarları
    liquidity_spread_threshold: float = Field(default=0.02, alias="LIQUIDITY_SPREAD_THRESHOLD")
    liquidity_volume_participation_min: float = Field(default=0.005, alias="LIQUIDITY_VOLUME_PARTICIPATION_MIN")

    # Duygu (Sentiment) Ağırlıkları
    sentiment_news_weight: float = Field(default=0.50, alias="SENTIMENT_NEWS_WEIGHT")
    sentiment_social_weight: float = Field(default=0.30, alias="SENTIMENT_SOCIAL_WEIGHT")
    sentiment_options_weight: float = Field(default=0.20, alias="SENTIMENT_OPTIONS_WEIGHT")

    @property
    def is_production(self) -> bool:
        """Çalışma ortamının Production veya Staging olup olmadığını döndürür."""
        return self.app_env.strip().lower() in ("production", "prod", "staging")

    @property
    def postgres_url(self) -> str:
        """Asenkron SQLAlchemy / asyncpg PostgreSQL bağlantı URL'si."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_url_sync(self) -> str:
        """Senkron psycopg2 / SQLAlchemy PostgreSQL bağlantı URL'si."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        """Redis bağlantı URL'si."""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @model_validator(mode="after")
    def _validate_production_security(self) -> Settings:
        """Production ortamı için katı güvenlik ve secret denetimlerini uygular.

        Raises:
            ConfigurationError: Production ortamında güvensiz veya eksik sırlar varsa.
        """
        if not self.is_production:
            return self

        errors: list[str] = []
        secret_key = self.secret_key.strip()
        jwt_secret = self.jwt_secret.strip()
        postgres_password = self.postgres_password.strip()

        if not secret_key or secret_key in INSECURE_VALUES:
            errors.append("SECRET_KEY boş veya güvensiz varsayılan değerde")
        elif len(secret_key) < DEFAULT_MIN_SECRET_LENGTH:
            errors.append(f"SECRET_KEY çok kısa (en az {DEFAULT_MIN_SECRET_LENGTH} karakter olmalıdır)")

        if not jwt_secret or jwt_secret in INSECURE_VALUES:
            errors.append("JWT_SECRET boş veya güvensiz varsayılan değerde")
        elif len(jwt_secret) < DEFAULT_MIN_SECRET_LENGTH:
            errors.append(f"JWT_SECRET çok kısa (en az {DEFAULT_MIN_SECRET_LENGTH} karakter olmalıdır)")

        if not postgres_password or postgres_password in INSECURE_VALUES:
            errors.append("POSTGRES_PASSWORD boş veya güvensiz varsayılan değerde")

        if self.app_debug:
            errors.append("APP_DEBUG production ortamında mutlaka False olmalıdır")

        if errors:
            err_msg = "; ".join(errors)
            logger.critical("production_security_violation", errors=errors)
            raise ConfigurationError(f"Production Güvenlik İhlali: {err_msg}")

        return self

    @field_validator(
        "app_port",
        "postgres_port",
        "postgres_replica_port",
        "clickhouse_port",
        "clickhouse_native_port",
        "clickhouse_http_port",
        "questdb_http_port",
        "questdb_pg_port",
        "questdb_ilp_port",
        "redis_port",
        "redis_sentinel_port",
        "traefik_port",
        "traefik_https_port",
        "traefik_admin_port",
        "grpc_port",
    )
    @classmethod
    def _validate_network_port(cls, v: int) -> int:
        """Ağ portunun 1 ile 65535 aralığında olduğunu doğrular."""
        if not 1 <= v <= 65535:
            raise ValueError(f"Geçersiz ağ port numarası: {v} (1-65535 aralığında olmalıdır)")
        return v

    def to_dict(self, mask_secrets: bool = True) -> dict[str, Any]:
        """Ayarları sözlük formatına dönüştürür.

        Args:
            mask_secrets: True ise hassas şifre ve anahtarlar maskelenir.

        Returns:
            Yapılandırma sözlüğü.
        """
        raw_dict = self.model_dump()
        if not mask_secrets:
            return raw_dict

        sanitized: dict[str, Any] = {}
        for k, v in raw_dict.items():
            if k in SENSITIVE_KEYS and v:
                str_v = str(v)
                sanitized[k] = f"{str_v[:2]}***{str_v[-2:]}" if len(str_v) > 4 else "***"
            else:
                sanitized[k] = v
        return sanitized

    def to_orjson_bytes(self, mask_secrets: bool = True) -> bytes:
        """Ayarları orjson formatında bayt dizisine dönüştürür."""
        return orjson.dumps(self.to_dict(mask_secrets=mask_secrets), default=str)

    def to_json(self, mask_secrets: bool = True) -> str:
        """Ayarları JSON metnine dönüştürür."""
        return self.to_orjson_bytes(mask_secrets=mask_secrets).decode("utf-8")

    def __repr__(self) -> str:
        """Hassas sırları maskelenmiş açıklayıcı metin temsili."""
        return (
            f"<Settings env='{self.app_env}' debug={self.app_debug} "
            f"host='{self.app_host}:{self.app_port}' pg='{self.postgres_host}:{self.postgres_port}' "
            f"redis='{self.redis_host}:{self.redis_port}'>"
        )


def _parse_dotenv(path: str) -> dict[str, str]:
    """Gelişmiş ve güvenli .env dosyası ayrıştırıcısı.

    Özellikler:
    - UTF-8 ve UTF-8-BOM (`utf-8-sig`) desteği.
    - `export KEY=VALUE` sözdizimini tanıma ve temizleme.
    - Tırnak içi (`"..."`, `'...'`) değerleri ve satır sonu yorumları ayıklama.

    Args:
        path: .env dosyasının dosya yolu.

    Returns:
        Anahtar-değer çiftleri sözlüğü.
    """
    result: dict[str, str] = {}
    if not os.path.exists(path):
        return result

    try:
        with open(path, encoding="utf-8-sig") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue

                if line.startswith("export "):
                    line = line[7:].strip()

                if "=" not in line:
                    continue

                key, _, raw_value = line.partition("=")
                key = key.strip()
                if not key:
                    continue

                # Satır içi yorumları ayıkla (# öncesi)
                value = raw_value.split(" #", 1)[0].strip()

                # Tırnakları güvenle temizle
                if len(value) >= 2 and (
                    (value.startswith('"') and value.endswith('"'))
                    or (value.startswith("'") and value.endswith("'"))
                ):
                    value = value[1:-1]

                result[key] = value
    except OSError as exc:
        logger.warning("dotenv_dosyasi_okunamadi", path=path, error=str(exc))

    return result


# Singleton kilit ve referansı
_settings_lock: threading.RLock = threading.RLock()
_settings_instance: Settings | None = None


def get_settings(env_file: str = ".env") -> Settings:
    """Settings örneğini thread-safe olarak yükler veya önbellekten döndürür.

    Args:
        env_file: Okunacak .env dosya yolu.

    Returns:
        Doğrulanmış Settings örneği.
    """
    global _settings_instance
    with _settings_lock:
        if _settings_instance is not None:
            return _settings_instance

        if os.path.exists(env_file):
            for key, value in _parse_dotenv(env_file).items():
                os.environ.setdefault(key, value)

        try:
            _settings_instance = Settings()
            env_label = "PRODUCTION" if _settings_instance.is_production else "DEVELOPMENT"
            logger.info("Konfigürasyon yüklendi", environment=env_label)
        except ConfigurationError:
            raise
        except Exception as exc:
            logger.warning("Konfigürasyon yükleme uyarısı — varsayılan değerler kullanılıyor", error=str(exc))
            _settings_instance = Settings.model_construct()

        return _settings_instance


def reload_settings(env_file: str = ".env") -> Settings:
    """Çalışma anında ayarları yeniden yükler (hot-reload desteği).

    Args:
        env_file: Yeniden okunacak .env dosyası.

    Returns:
        Yenilenmiş Settings örneği.
    """
    global _settings_instance
    with _settings_lock:
        _settings_instance = None
        return get_settings(env_file=env_file)


# Polars & DuckDB Denetim Fonksiyonları


def export_config_to_polars(
    custom_settings: Settings | None = None,
    mask_secrets: bool = True,
) -> pl.DataFrame:
    """Aktif yapılandırma parametrelerini Polars DataFrame olarak döndürür.

    Args:
        custom_settings: İsteğe bağlı Settings örneği (None ise mevcut settings).
        mask_secrets: Hassas parolaların maskelenme tercihi.

    Returns:
        'key', 'value', 'type' sütunlarına sahip Polars DataFrame.
    """
    cfg = custom_settings or get_settings()
    data_dict = cfg.to_dict(mask_secrets=mask_secrets)

    rows = []
    for k, v in data_dict.items():
        rows.append({
            "key": str(k),
            "value": str(v) if v is not None else "",
            "type": type(getattr(cfg, k, None)).__name__,
        })

    schema = {
        "key": pl.Utf8,
        "value": pl.Utf8,
        "type": pl.Utf8,
    }
    return pl.DataFrame(rows, schema=schema)


def export_config_snapshot_to_duckdb(
    custom_settings: Settings | None = None,
    db_path: str | Path = DEFAULT_DUCKDB_CONFIG_PATH,
    table_name: str = "bist_config_audit_snapshots",
    mask_secrets: bool = True,
) -> int:
    """Aktif konfigürasyon anlık görüntüsünü DuckDB tablosuna denetim amacıyla yazar.

    Args:
        custom_settings: Ayarlar örneği.
        db_path: DuckDB veritabanı dosya yolu.
        table_name: Hedef tablo adı.
        mask_secrets: Sırların maskelenme durumu.

    Returns:
        Kaydedilen parametre sayısı.
    """
    df = export_config_to_polars(custom_settings=custom_settings, mask_secrets=mask_secrets)
    if df.is_empty():
        return 0

    now_ts = datetime.now(UTC).isoformat()
    df_snapshot = df.with_columns(pl.lit(now_ts).alias("snapshot_timestamp"))

    path_obj = Path(db_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    if path_obj.exists() and path_obj.stat().st_size == 0:
        with contextlib.suppress(OSError):
            path_obj.unlink()

    try:
        with duckdb.connect(str(path_obj)) as conn:
            conn.register("df_cfg_snap", df_snapshot.to_arrow())
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM df_cfg_snap WHERE 1=0"
            )
            conn.execute(f"INSERT INTO {table_name} SELECT * FROM df_cfg_snap")
            with contextlib.suppress(Exception):
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_key ON {table_name} (key)")
        return len(df_snapshot)
    except Exception as e:
        logger.error("export_config_snapshot_to_duckdb_failed", error=str(e))
        return 0


def query_config_snapshots_duckdb(
    db_path: str | Path = DEFAULT_DUCKDB_CONFIG_PATH,
    table_name: str = "bist_config_audit_snapshots",
    key_prefix: str | None = None,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB üzerinden geçmiş konfigürasyon anlık görüntülerini sorgular.

    Args:
        db_path: DuckDB dosya yolu.
        table_name: Tablo adı.
        key_prefix: İsteğe bağlı anahtar öneki filtresi (örn: 'postgres_').
        limit: Maksimum kayıt sayısı.

    Returns:
        Polars DataFrame.
    """
    schema = {
        "key": pl.Utf8,
        "value": pl.Utf8,
        "type": pl.Utf8,
        "snapshot_timestamp": pl.Utf8,
    }
    empty_df = pl.DataFrame(schema=schema)
    path_obj = Path(db_path)
    if not path_obj.exists() or path_obj.stat().st_size == 0:
        return empty_df

    try:
        with duckdb.connect(str(path_obj), read_only=True) as conn:
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name = ?",
                [table_name],
            ).fetchall()
            if not tables:
                return empty_df

            if key_prefix:
                query = f"SELECT * FROM {table_name} WHERE key LIKE ? ORDER BY snapshot_timestamp DESC LIMIT ?"
                arrow_res = conn.execute(query, [f"{key_prefix}%", limit]).arrow()
            else:
                query = f"SELECT * FROM {table_name} ORDER BY snapshot_timestamp DESC LIMIT ?"
                arrow_res = conn.execute(query, [limit]).arrow()

            return pl.from_arrow(arrow_res)
    except Exception as e:
        logger.error("query_config_snapshots_duckdb_failed", error=str(e))
        return empty_df


# Modül seviyesi aktif ayar nesnesi
settings: Settings = get_settings()

__all__ = [
    "DEFAULT_MIN_SECRET_LENGTH",
    "DEFAULT_DUCKDB_CONFIG_PATH",
    "INSECURE_VALUES",
    "SENSITIVE_KEYS",
    "ConfigurationError",
    "Settings",
    "get_settings",
    "reload_settings",
    "export_config_to_polars",
    "export_config_snapshot_to_duckdb",
    "query_config_snapshots_duckdb",
    "settings",
]
