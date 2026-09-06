"""ALPHA BIST — Risk Yönetimi ve Optimizasyon Konfigürasyonu (Risk Config).

Tüm risk, portföy optimizasyonu, backtest ve devre kesici parametreleri burada merkezileştirilmiştir.
Sert kodlanmış (hardcoded) değerler yasaktır; tüm motorlar bu konfigürasyonları referans alır.
DuckDB denetim izi, Polars entegrasyonu, orjson serileştirme ve thread-safe güncelleme içerir.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import orjson
import polars as pl
import structlog
from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    import duckdb

logger = structlog.get_logger(__name__)

_config_lock = threading.RLock()
_duckdb_conn: duckdb.DuckDBPyConnection | None = None


def set_duckdb_connection(conn: duckdb.DuckDBPyConnection) -> None:
    """Risk konfigürasyonu denetim tablosunu DuckDB üzerinde ilklendirir."""
    global _duckdb_conn
    with _config_lock:
        _duckdb_conn = conn
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


def _record_config_audit(config_type: str, payload: dict[str, Any]) -> None:
    """Konfigürasyon değişikliklerini DuckDB denetim tablosuna yazar."""
    if _duckdb_conn is None:
        return
    with _config_lock:
        try:
            json_str = orjson.dumps(payload).decode("utf-8")
            _duckdb_conn.execute(
                """
                INSERT INTO risk_config_audit (id, config_type, payload_json, updated_at)
                VALUES (nextval('seq_risk_config_audit'), ?, ?, CURRENT_TIMESTAMP)
                """,
                [config_type, json_str],
            )
        except Exception as exc:
            logger.debug("Risk config DuckDB audit kayıt hatası", hata=str(exc))


class BaseRiskConfigModel(BaseModel):
    """Tüm risk konfigürasyon modelleri için orjson ve repr tabanlı ortak temel sınıf."""

    model_config = {"arbitrary_types_allowed": True, "validate_assignment": True}

    def to_dict(self) -> dict[str, Any]:
        """Modeli standart Python sözlüğüne dönüştürür."""
        return self.model_dump()

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson bayt dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

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


__all__ = [
    "BacktestConfig",
    "BaseRiskConfigModel",
    "CircuitBreakerConfig",
    "PortfolioOptimizerConfig",
    "RiskManagerConfig",
    "backtest_config",
    "circuit_breaker_config",
    "export_all_risk_configs_to_polars",
    "portfolio_config",
    "risk_config",
    "set_duckdb_connection",
]
