"""ALPHA BIST — Risk Yönetimi ve Optimizasyon Konfigürasyonu (Risk Config).

Tüm risk, portföy optimizasyonu, backtest ve devre kesici parametreleri burada merkezileştirilmiştir.
Sert kodlanmış (hardcoded) değerler yasaktır; tüm motorlar bu konfigürasyonları referans alır.
DuckDB denetim izi, Polars entegrasyonu, orjson serileştirme ve thread-safe güncelleme içerir.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog
from pydantic import BaseModel, Field, field_validator

logger = structlog.get_logger(__name__)

_config_lock = threading.RLock()
_duckdb_conn: duckdb.DuckDBPyConnection | None = None

DEFAULT_RISK_CONFIG_DUCKDB_PATH: Final[str] = "data/risk_config_audit.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"


def configure_duckdb_wal(
    conn: duckdb.DuckDBPyConnection,
    checkpoint_threshold: str = DEFAULT_CHECKPOINT_SIZE,
    wal_autocheckpoint: str = DEFAULT_WAL_SIZE,
) -> None:
    """DuckDB WAL parametrelerini optimize eder."""
    try:
        conn.execute(f"SET checkpoint_threshold = '{checkpoint_threshold}';")
        conn.execute(f"SET wal_autocheckpoint = '{wal_autocheckpoint}';")
    except Exception as e:
        logger.warning("risk_config_duckdb_wal_yapilandirma_uyarisi", hata=str(e))


def set_duckdb_connection(conn: duckdb.DuckDBPyConnection) -> None:
    """Risk konfigürasyonu denetim tablosunu DuckDB üzerinde ilklendirir."""
    global _duckdb_conn
    with _config_lock:
        _duckdb_conn = conn
        configure_duckdb_wal(_duckdb_conn)
        try:
            _duckdb_conn.execute("""
                CREATE TABLE IF NOT EXISTS risk_config_audit (
                    id BIGINT,
                    config_type VARCHAR,
                    payload_json VARCHAR,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE SEQUENCE IF NOT EXISTS seq_risk_config_audit START 1;
            """)
        except Exception as exc:
            logger.error("Risk config DuckDB şema hatası", hata=str(exc))


def _get_active_duckdb(writable: bool = False) -> tuple[duckdb.DuckDBPyConnection | None, bool]:
    """Aktif DuckDB bağlantısını ve kapatılması gerekip gerekmediğini döndürür."""
    with _config_lock:
        if _duckdb_conn is not None:
            return _duckdb_conn, False

    p = Path(DEFAULT_RISK_CONFIG_DUCKDB_PATH)
    if not writable and not p.exists():
        return None, False

    try:
        if writable:
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = duckdb.connect(str(p))
            configure_duckdb_wal(conn)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS risk_config_audit (
                    id BIGINT,
                    config_type VARCHAR,
                    payload_json VARCHAR,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE SEQUENCE IF NOT EXISTS seq_risk_config_audit START 1;
            """)
            return conn, True
        else:
            conn = duckdb.connect(str(p), read_only=True)
            tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
            if "risk_config_audit" not in tables:
                conn.close()
                return None, False
            return conn, True
    except Exception as exc:
        logger.debug("risk_config_duckdb_aktif_baglanti_hatasi", hata=str(exc))
        return None, False


def _record_config_audit(config_type: str, payload: dict[str, Any]) -> None:
    """Konfigürasyon değişikliklerini DuckDB denetim tablosuna yazar."""
    conn, should_close = _get_active_duckdb(writable=True)
    if conn is None:
        return
    with _config_lock:
        try:
            json_str = orjson.dumps(payload, default=str).decode("utf-8")
            conn.execute(
                """
                INSERT INTO risk_config_audit (id, config_type, payload_json, updated_at)
                VALUES (nextval('seq_risk_config_audit'), ?, ?, CURRENT_TIMESTAMP)
                """,
                [config_type, json_str],
            )
        except Exception as exc:
            logger.debug("Risk config DuckDB audit kayıt hatası", hata=str(exc))
        finally:
            if should_close:
                conn.close()


class BaseRiskConfigModel(BaseModel):
    """Tüm risk konfigürasyon modelleri için orjson ve repr tabanlı ortak temel sınıf."""

    model_config = {"arbitrary_types_allowed": True, "validate_assignment": True}

    def to_dict(self) -> dict[str, Any]:
        """Modeli standart Python sözlüğüne dönüştürür."""
        return self.model_dump()

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson bayt dizisine serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    def update_from_dict(self, updates: dict[str, Any]) -> None:
        """Sözlük üzerinden parametreleri güvenle günceller ve denetim kaydı oluşturur."""
        with _config_lock:
            for k, v in updates.items():
                if hasattr(self, k):
                    setattr(self, k, v)
            _record_config_audit(self.__class__.__name__, self.to_dict())
            logger.info("Risk konfigürasyonu güncellendi", model=self.__class__.__name__, guncellemeler=list(updates.keys()))


class RiskManagerConfig(BaseRiskConfigModel):
    """Risk Yönetim Motoru (Risk Manager) parametreleri."""

    max_position_pct: float = Field(default=0.10, description="Tek hisse max portföy ağırlığı (%10)")
    max_sector_pct: float = Field(default=0.25, description="Tek sektör max portföy ağırlığı (%25)")
    max_drawdown_pct: float = Field(default=0.15, description="Maksimum kabul edilebilir drawdown eşiği (%15)")
    stop_loss_pct: float = Field(default=0.07, description="Varsayılan stop loss eşiği (%7)")
    trailing_stop_pct: float = Field(default=0.05, description="İz süren stop eşiği (%5)")
    max_open_positions: int = Field(default=15, description="Maksimum eşzamanlı açık pozisyon sayısı")
    min_cash_ratio: float = Field(default=0.10, description="Minimum nakit rezerv oranı (%10)")
    volatility_cap: float = Field(default=0.50, description="Maksimum izin verilen volatilite tavanı (%50)")
    correlation_threshold: float = Field(default=0.70, description="Yüksek hisse korelasyonu uyarı eşiği")

    @field_validator("max_position_pct", "max_sector_pct", "max_drawdown_pct", "min_cash_ratio")
    @classmethod
    def validate_ratios(cls, v: float) -> float:
        """Oranların [0.0, 1.0] aralığında olduğunu doğrular."""
        if not (0.0 < v <= 1.0):
            msg = f"Oran değeri 0 ile 1 arasında olmalıdır, alınan: {v}"
            raise ValueError(msg)
        return v

    def __repr__(self) -> str:
        return (
            f"RiskManagerConfig(max_pos={self.max_position_pct:.1%}, max_sec={self.max_sector_pct:.1%}, "
            f"max_dd={self.max_drawdown_pct:.1%}, stop_loss={self.stop_loss_pct:.1%}, "
            f"max_open={self.max_open_positions})"
        )


class BacktestConfig(BaseRiskConfigModel):
    """Backtest motoru yürütme ve maliyet parametreleri."""

    base_slippage_pct: float = Field(default=0.05, description="Baz slippage oranı (%)")
    max_participation: float = Field(default=0.10, description="Günlük işlem hacmine (ADV) max katılım oranı (%10)")
    default_commission_pct: float = Field(default=0.0015, description="Varsayılan aracı kurum komisyonu (%0.15)")
    min_commission_tl: float = Field(default=1.0, description="İşlem başına asgari komisyon tutarı (TL)")

    def __repr__(self) -> str:
        return (
            f"BacktestConfig(slippage={self.base_slippage_pct}%, adv_part={self.max_participation:.1%}, "
            f"comm={self.default_commission_pct:.2%}, min_comm={self.min_commission_tl} TL)"
        )


class PortfolioOptimizerConfig(BaseRiskConfigModel):
    """Portföy optimizasyonu ve rebalance kısıtları."""

    max_position_pct: float = Field(default=0.10, description="Tek hissede max ağırlık (%10)")
    min_position_pct: float = Field(default=0.015, description="Min pozisyon eşiği — tozluluk filtresi (%1.5)")
    max_sector_pct: float = Field(default=0.35, description="Sektör tavanı (%35)")
    max_total_exposure: float = Field(default=0.92, description="Toplam hisse senedi maruziyeti (%92)")
    min_cash_buffer_pct: float = Field(default=0.08, description="Zorunlu nakit rezervi (%8)")
    turnover_penalty_lambda: float = Field(default=0.015, description="Turnover ceza katsayısı")
    transaction_cost_pct: float = Field(default=0.0015, description="İşlem maliyeti (%0.15)")
    hysteresis_threshold: float = Field(default=0.02, description="Hysteresis eşiği (%2)")
    l2_regularization: float = Field(default=0.002, description="L2 regularization cezası")

    def __repr__(self) -> str:
        return (
            f"PortfolioOptimizerConfig(max_pos={self.max_position_pct:.1%}, min_pos={self.min_position_pct:.1%}, "
            f"max_exposure={self.max_total_exposure:.1%}, cash_buffer={self.min_cash_buffer_pct:.1%})"
        )


class CircuitBreakerConfig(BaseRiskConfigModel):
    """Otomatik devre kesici parametreleri."""

    failure_threshold: int = Field(default=5, description="Ardışık hata eşiği")
    recovery_timeout_seconds: int = Field(default=60, description="Kurtarma deneme bekleme süresi (saniye)")

    def __repr__(self) -> str:
        return f"CircuitBreakerConfig(failure_threshold={self.failure_threshold}, recovery_timeout={self.recovery_timeout_seconds}s)"


# Global Singleton Örnekleri
risk_config: Final[RiskManagerConfig] = RiskManagerConfig()
backtest_config: Final[BacktestConfig] = BacktestConfig()
portfolio_config: Final[PortfolioOptimizerConfig] = PortfolioOptimizerConfig()
circuit_breaker_config: Final[CircuitBreakerConfig] = CircuitBreakerConfig()


def export_all_risk_configs_to_polars() -> pl.DataFrame:
    """Tüm aktif risk konfigürasyonlarını Polars DataFrame olarak dışa aktarır."""
    with _config_lock:
        configs = [
            ("RiskManager", risk_config.to_dict()),
            ("Backtest", backtest_config.to_dict()),
            ("PortfolioOptimizer", portfolio_config.to_dict()),
            ("CircuitBreaker", circuit_breaker_config.to_dict()),
        ]

    rows = []
    now = datetime.now(UTC)
    for category, cfg_dict in configs:
        for param, val in cfg_dict.items():
            rows.append(
                {
                    "category": category,
                    "parameter": param,
                    "value_str": str(val),
                    "is_numeric": isinstance(val, (int, float)),
                    "exported_at": now,
                }
            )

    return pl.DataFrame(rows)


def read_risk_config_audit_from_duckdb(
    db_path: str = DEFAULT_RISK_CONFIG_DUCKDB_PATH,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB denetim tablosundaki konfigürasyon geçmişini Polars DataFrame olarak okur."""
    empty_schema = {
        "id": pl.Int64,
        "config_type": pl.String,
        "payload_json": pl.String,
        "updated_at": pl.Datetime,
    }
    conn, should_close = _get_active_duckdb(writable=False)
    if conn is None:
        return pl.DataFrame(schema=empty_schema)
    try:
        return conn.execute(
            """
            SELECT id, config_type, payload_json, updated_at
            FROM risk_config_audit
            ORDER BY id DESC LIMIT ?
            """,
            [limit],
        ).pl()
    except Exception as e:
        logger.error("read_risk_config_audit_duckdb_hatasi", hata=str(e))
        return pl.DataFrame(schema=empty_schema)
    finally:
        if should_close:
            conn.close()


def clear_risk_config_audit_duckdb(db_path: str = DEFAULT_RISK_CONFIG_DUCKDB_PATH) -> bool:
    """DuckDB denetim tablosundaki tüm kayıtları temizler."""
    conn, should_close = _get_active_duckdb(writable=True)
    if conn is None:
        return True
    try:
        conn.execute("DELETE FROM risk_config_audit")
        return True
    except Exception as e:
        logger.error("clear_risk_config_audit_duckdb_hatasi", hata=str(e))
        return False
    finally:
        if should_close:
            conn.close()


def to_orjson_bytes(data: Any) -> bytes:
    """Veriyi orjson ile güvenli bayt dizisine serileştirir."""
    return orjson.dumps(data, default=str)


__all__ = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_RISK_CONFIG_DUCKDB_PATH",
    "DEFAULT_WAL_SIZE",
    "BacktestConfig",
    "BaseRiskConfigModel",
    "CircuitBreakerConfig",
    "PortfolioOptimizerConfig",
    "RiskManagerConfig",
    "backtest_config",
    "circuit_breaker_config",
    "clear_risk_config_audit_duckdb",
    "configure_duckdb_wal",
    "export_all_risk_configs_to_polars",
    "portfolio_config",
    "read_risk_config_audit_from_duckdb",
    "risk_config",
    "set_duckdb_connection",
    "to_orjson_bytes",
]
