"""ALPHA BIST — Günlük Rapor Üretici ve Performans Arşivleme Motoru (Reporting).

- Günlük portföy, işlem ve risk raporu üretimi (Daily Report Generator)
- DuckDB üzerinde kalıcı rapor arşivi (Daily Reports Audit Archive)
- Polars (Polars >= 1.30) ve orjson desteği
- Thread-safe (RLock) ve geriye dönük tam uyumluluk (queue.py desteği)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import orjson
import polars as pl
import structlog

if TYPE_CHECKING:
    import duckdb

try:
    from services.core.otel import otel_trace
except ImportError:
    import functools

    def otel_trace(name: str):
        """Merkezi OTel tracer bulunamadığında kullanılan yerel fallback dekoratörü."""

        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            return wrapper

        return decorator

logger = structlog.get_logger(__name__)

_lock = threading.RLock()
_duckdb_conn: duckdb.DuckDBPyConnection | None = None

DEFAULT_REPORT_TYPE: Final[str] = "daily"


@dataclass
class DailyReport:
    """Günlük portföy ve risk raporu modeli."""

    report_date: str
    portfolio_value: float
    cash: float
    positions_count: int
    trades_today: int
    daily_pnl: float
    total_pnl: float
    drawdown: float
    risk_level: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"DailyReport(date='{self.report_date}', equity={self.portfolio_value:.2f}, "
            f"daily_pnl={self.daily_pnl:.2f}, trades={self.trades_today}, risk='{self.risk_level}')"
        )

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür (Geriye dönük tam uyumlu şema)."""
        return {
            "date": self.report_date,
            "portfolio_value": self.portfolio_value,
            "cash": self.cash,
            "positions": self.positions_count,
            "trades_today": self.trades_today,
            "daily_pnl": self.daily_pnl,
            "total_pnl": self.total_pnl,
            "drawdown": self.drawdown,
            "risk_level": self.risk_level,
            "created_at": self.created_at.isoformat(),
        }

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisine serileştirir."""
        return orjson.dumps(self.to_dict())


def set_duckdb_connection(conn: duckdb.DuckDBPyConnection) -> None:
    """Rapor arşivi için DuckDB bağlantısını tanımlar ve şemayı kurar."""
    global _duckdb_conn
    with _lock:
        _duckdb_conn = conn
        try:
            _duckdb_conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_reports_archive (
                    id BIGINT,
                    report_date VARCHAR,
                    portfolio_value DOUBLE,
                    cash DOUBLE,
                    positions_count INTEGER,
                    trades_today INTEGER,
                    daily_pnl DOUBLE,
                    total_pnl DOUBLE,
                    drawdown DOUBLE,
                    risk_level VARCHAR,
                    full_report_json VARCHAR,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE SEQUENCE IF NOT EXISTS seq_daily_reports START 1;
            """)
        except Exception as exc:
            logger.error("Rapor DuckDB şema oluşturma hatası", hata=str(exc))


def save_report_to_duckdb(report: DailyReport | dict[str, Any]) -> None:
    """Rapor kaydını DuckDB arşivine yazar."""
    if _duckdb_conn is None:
        return

    data = report.to_dict() if isinstance(report, DailyReport) else report
    with _lock:
        try:
            json_str = orjson.dumps(data).decode("utf-8")
            _duckdb_conn.execute(
                """
                INSERT INTO daily_reports_archive (
                    id, report_date, portfolio_value, cash, positions_count,
                    trades_today, daily_pnl, total_pnl, drawdown, risk_level,
                    full_report_json, created_at
                ) VALUES (
                    nextval('seq_daily_reports'), ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, CURRENT_TIMESTAMP
                )
                """,
                [
                    str(data.get("date", "")),
                    float(data.get("portfolio_value", 0.0)),
                    float(data.get("cash", 0.0)),
                    int(data.get("positions", 0)),
                    int(data.get("trades_today", 0)),
                    float(data.get("daily_pnl", 0.0)),
                    float(data.get("total_pnl", 0.0)),
                    float(data.get("drawdown", 0.0)),
                    str(data.get("risk_level", "UNKNOWN")),
                    json_str,
                ],
            )
        except Exception as exc:
            logger.error("Rapor DuckDB arşivleme hatası", hata=str(exc))


@otel_trace("reporting.generate_daily_report")
def generate_daily_report(
    portfolio: dict[str, Any] | None = None,
    trades: list[dict[str, Any]] | None = None,
    risk_metrics: dict[str, Any] | None = None,
    save_to_archive: bool = True,
) -> dict[str, Any]:
    """Günlük portföy ve risk raporu oluşturur.

    Args:
        portfolio: Portföy özeti (equity, cash, positions, daily_pnl, total_pnl)
        trades: Gün içinde gerçekleşen işlem listesi
        risk_metrics: Risk metrikleri (drawdown, risk_level vb.)
        save_to_archive: DuckDB arşivine kaydedilsin mi?

    Returns:
        dict[str, Any]: Standart rapor sözlüğü.
    """
    port = portfolio or {}
    trd = trades or []
    risk = risk_metrics or {}

    pos_data = port.get("positions", {})
    pos_count = len(pos_data) if isinstance(pos_data, (dict, list)) else 0

    report = DailyReport(
        report_date=datetime.now(UTC).strftime("%Y-%m-%d"),
        portfolio_value=float(port.get("equity", 0.0)),
        cash=float(port.get("cash", 0.0)),
        positions_count=pos_count,
        trades_today=len(trd),
        daily_pnl=float(port.get("daily_pnl", 0.0)),
        total_pnl=float(port.get("total_pnl", 0.0)),
        drawdown=float(risk.get("drawdown", 0.0)),
        risk_level=str(risk.get("risk_level", "UNKNOWN")),
    )

    if save_to_archive:
        save_report_to_duckdb(report)

    logger.info(
        "Günlük rapor üretildi",
        tarih=report.report_date,
        portfoy_degeri=report.portfolio_value,
        gunluk_pnl=report.daily_pnl,
        islem_adedi=report.trades_today,
    )

    return report.to_dict()


@otel_trace("reporting.generate_report")
def generate_report(report_type: str = DEFAULT_REPORT_TYPE, **kwargs: Any) -> dict[str, Any]:
    """Geriye dönük uyumlu sarmalayıcı (queue.py ve harici tetikleyiciler için)."""
    logger.info("Rapor oluşturma çağrısı", tip=report_type)
    return generate_daily_report(
        portfolio=kwargs.get("portfolio"),
        trades=kwargs.get("trades"),
        risk_metrics=kwargs.get("risk_metrics"),
        save_to_archive=kwargs.get("save_to_archive", True),
    )


def export_reports_to_polars(reports: list[dict[str, Any]] | list[DailyReport] | None = None) -> pl.DataFrame:
    """Rapor listesini veya DuckDB arşivini Polars DataFrame olarak dışa aktarır."""
    if reports is not None:
        raw_list = [r.to_dict() if isinstance(r, DailyReport) else r for r in reports]
        if not raw_list:
            return pl.DataFrame(
                schema={
                    "date": pl.Utf8,
                    "portfolio_value": pl.Float64,
                    "cash": pl.Float64,
                    "positions": pl.Int64,
                    "trades_today": pl.Int64,
                    "daily_pnl": pl.Float64,
                    "total_pnl": pl.Float64,
                    "drawdown": pl.Float64,
                    "risk_level": pl.Utf8,
                }
            )
        return pl.DataFrame(raw_list)

    # DuckDB'den sorgula
    if _duckdb_conn is not None:
        with _lock:
            try:
                return _duckdb_conn.execute(
                    """
                    SELECT report_date as date, portfolio_value, cash, positions_count as positions,
                           trades_today, daily_pnl, total_pnl, drawdown, risk_level, created_at
                    FROM daily_reports_archive
                    ORDER BY id DESC
                    """
                ).pl()
            except Exception as exc:
                logger.error("DuckDB Polars rapor sorgulama hatası", hata=str(exc))

    return pl.DataFrame()


__all__ = [
    "DEFAULT_REPORT_TYPE",
    "DailyReport",
    "export_reports_to_polars",
    "generate_daily_report",
    "generate_report",
    "save_report_to_duckdb",
    "set_duckdb_connection",
]
