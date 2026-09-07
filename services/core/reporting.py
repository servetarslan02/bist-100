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
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

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
DEFAULT_REPORTING_DUCKDB_PATH: Final[str] = "data/daily_reports.duckdb"
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
        logger.warning("reporting_duckdb_wal_yapilandirma_uyarisi", hata=str(e))


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
        return orjson.dumps(self.to_dict(), default=str)


def set_duckdb_connection(conn: duckdb.DuckDBPyConnection) -> None:
    """Rapor arşivi için DuckDB bağlantısını tanımlar ve şemayı kurar."""
    global _duckdb_conn
    with _lock:
        _duckdb_conn = conn
        configure_duckdb_wal(_duckdb_conn)
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


def _get_active_duckdb(writable: bool = False) -> tuple[duckdb.DuckDBPyConnection | None, bool]:
    """Aktif DuckDB bağlantısını ve kapatılması gerekip gerekmediğini döndürür."""
    with _lock:
        if _duckdb_conn is not None:
            return _duckdb_conn, False

    p = Path(DEFAULT_REPORTING_DUCKDB_PATH)
    if not writable and not p.exists():
        return None, False

    try:
        if writable:
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = duckdb.connect(str(p))
            configure_duckdb_wal(conn)
            conn.execute("""
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
            return conn, True
        else:
            conn = duckdb.connect(str(p), read_only=True)
            tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
            if "daily_reports_archive" not in tables:
                conn.close()
                return None, False
            return conn, True
    except Exception as exc:
        logger.debug("reporting_duckdb_aktif_baglanti_hatasi", hata=str(exc))
        return None, False


def save_report_to_duckdb(report: DailyReport | dict[str, Any], db_path: str | None = None) -> None:
    """Rapor kaydını DuckDB arşivine yazar."""
    conn, should_close = _get_active_duckdb(writable=True)
    if conn is None:
        return

    data = report.to_dict() if isinstance(report, DailyReport) else report
    with _lock:
        try:
            json_str = orjson.dumps(data, default=str).decode("utf-8")
            conn.execute(
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
        finally:
            if should_close:
                conn.close()


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
    conn, should_close = _get_active_duckdb(writable=False)
    if conn is not None:
        try:
            return conn.execute(
                """
                SELECT report_date as date, portfolio_value, cash, positions_count as positions,
                       trades_today, daily_pnl, total_pnl, drawdown, risk_level, created_at
                FROM daily_reports_archive
                ORDER BY id DESC
                """
            ).pl()
        except Exception as exc:
            logger.error("DuckDB Polars rapor sorgulama hatası", hata=str(exc))
        finally:
            if should_close:
                conn.close()

    return pl.DataFrame()


def read_reports_from_duckdb(
    db_path: str = DEFAULT_REPORTING_DUCKDB_PATH,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB arşivindeki raporları Polars DataFrame olarak okur."""
    empty_schema = {
        "date": pl.String,
        "portfolio_value": pl.Float64,
        "cash": pl.Float64,
        "positions": pl.Int64,
        "trades_today": pl.Int64,
        "daily_pnl": pl.Float64,
        "total_pnl": pl.Float64,
        "drawdown": pl.Float64,
        "risk_level": pl.String,
        "created_at": pl.Datetime,
    }
    conn, should_close = _get_active_duckdb(writable=False)
    if conn is None:
        return pl.DataFrame(schema=empty_schema)
    try:
        return conn.execute(
            """
            SELECT report_date as date, portfolio_value, cash, positions_count as positions,
                   trades_today, daily_pnl, total_pnl, drawdown, risk_level, created_at
            FROM daily_reports_archive
            ORDER BY id DESC LIMIT ?
            """,
            [limit],
        ).pl()
    except Exception as e:
        logger.error("read_reports_from_duckdb_hatasi", hata=str(e))
        return pl.DataFrame(schema=empty_schema)
    finally:
        if should_close:
            conn.close()


def clear_reports_duckdb(db_path: str = DEFAULT_REPORTING_DUCKDB_PATH) -> bool:
    """DuckDB arşivindeki tüm raporları temizler."""
    conn, should_close = _get_active_duckdb(writable=True)
    if conn is None:
        return True
    try:
        conn.execute("DELETE FROM daily_reports_archive")
        return True
    except Exception as e:
        logger.error("clear_reports_duckdb_hatasi", hata=str(e))
        return False
    finally:
        if should_close:
            conn.close()


def to_orjson_bytes(data: Any) -> bytes:
    """Veriyi orjson ile güvenli bayt dizisine serileştirir."""
    return orjson.dumps(data, default=str)


__all__ = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_REPORTING_DUCKDB_PATH",
    "DEFAULT_REPORT_TYPE",
    "DEFAULT_WAL_SIZE",
    "DailyReport",
    "clear_reports_duckdb",
    "configure_duckdb_wal",
    "export_reports_to_polars",
    "generate_daily_report",
    "generate_report",
    "read_reports_from_duckdb",
    "save_report_to_duckdb",
    "set_duckdb_connection",
    "to_orjson_bytes",
]
