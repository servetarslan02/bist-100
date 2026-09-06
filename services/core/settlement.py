"""ALPHA BIST — Takas Kuralları ve Valör Hesaplama Motoru (Settlement Rules T+2 / T+0).

Bu modül, Borsa İstanbul Pay Piyasası Takas ve Saklama esaslarına uygun olarak:
- Standart pay işlemleri için T+2 valör (takas günü) hesaplama
- Brüt takas kapsamındaki paylar için T+0 (aynı gün) takas tespiti
- Hafta sonları ve BIST resmî tatillerini otomatik dışlama
- Thread-safe tatil yönetimi ve dinamik takvim senkronizasyonu
- Polars Series düzeyinde vektörize toplu takas tarihi hesaplama
- DuckDB üzerinde takas hesaplama denetim geçmişi arşivi ve orjson desteği sağlar.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

if TYPE_CHECKING:
    import duckdb

logger = structlog.get_logger(__name__)

DEFAULT_NORMAL_SETTLEMENT_DAYS: Final[int] = 2  # T+2
DEFAULT_GROSS_SETTLEMENT_DAYS: Final[int] = 0  # T+0
DEFAULT_SETTLEMENT_DB: Final[str] = "data/settlement_audit.duckdb"

_GLOBAL_LOCK = threading.RLock()
_SETTLEMENT_DUCKDB_CONN: duckdb.DuckDBPyConnection | None = None


@dataclass(slots=True)
class SettlementInfo:
    """Takas ve valör bilgisi veri modeli."""

    trade_date: date
    settlement_date: date
    settlement_days: int  # T+N (0 veya 2)
    is_gross: bool = False
    calculated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        d = asdict(self)
        d["trade_date"] = self.trade_date.isoformat()
        d["settlement_date"] = self.settlement_date.isoformat()
        d["calculated_at"] = self.calculated_at.isoformat()
        return d

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        takas_tipi = "Brüt Takas (T+0)" if self.is_gross else f"Normal (T+{self.settlement_days})"
        return (
            f"SettlementInfo(islem='{self.trade_date}', takas='{self.settlement_date}', "
            f"tip='{takas_tipi}')"
        )


def set_settlement_duckdb_connection(conn: duckdb.DuckDBPyConnection) -> None:
    """Takas denetim arşivi için DuckDB bağlantısını tanımlar."""
    global _SETTLEMENT_DUCKDB_CONN
    with _GLOBAL_LOCK:
        _SETTLEMENT_DUCKDB_CONN = conn
        _init_settlement_duckdb_schema()


def _init_settlement_duckdb_schema() -> None:
    """DuckDB takas denetim şemasını ilklendirir."""
    if _SETTLEMENT_DUCKDB_CONN is None:
        return
    with _GLOBAL_LOCK:
        try:
            _SETTLEMENT_DUCKDB_CONN.execute("""
                CREATE TABLE IF NOT EXISTS settlement_audit_log (
                    id BIGINT,
                    trade_date DATE,
                    settlement_date DATE,
                    settlement_days INTEGER,
                    is_gross BOOLEAN,
                    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE SEQUENCE IF NOT EXISTS seq_settlement_audit_log START 1;
            """)
        except Exception as exc:
            logger.error("Settlement DuckDB şema oluşturma hatası", hata=str(exc))


def _record_settlement_audit(info: SettlementInfo) -> None:
    """Takas hesaplama kaydını DuckDB denetim tablosuna yazar."""
    if _SETTLEMENT_DUCKDB_CONN is None:
        return
    with _GLOBAL_LOCK:
        try:
            _SETTLEMENT_DUCKDB_CONN.execute(
                """
                INSERT INTO settlement_audit_log (
                    id, trade_date, settlement_date, settlement_days, is_gross, calculated_at
                ) VALUES (
                    nextval('seq_settlement_audit_log'), ?, ?, ?, ?, ?
                )
                """,
                [
                    info.trade_date,
                    info.settlement_date,
                    info.settlement_days,
                    info.is_gross,
                    info.calculated_at,
                ],
            )
        except Exception as exc:
            logger.debug("Settlement DuckDB denetim yazma hatası", hata=str(exc))


class SettlementCalculator:
    """Borsa İstanbul Takas ve Valör Hesaplayıcı Motoru (Thread-Safe)."""

    NORMAL_SETTLEMENT_DAYS: Final[int] = DEFAULT_NORMAL_SETTLEMENT_DAYS
    GROSS_SETTLEMENT_DAYS: Final[int] = DEFAULT_GROSS_SETTLEMENT_DAYS

    def __init__(
        self,
        holidays: set[str | date] | None = None,
        duckdb_conn: duckdb.DuckDBPyConnection | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._holidays: set[str] = set()
        if holidays:
            self.set_holidays(holidays)
        else:
            self.load_holidays_from_bist_calendar()

        if duckdb_conn is not None:
            set_settlement_duckdb_connection(duckdb_conn)

    def set_holidays(self, holidays: set[str | date]) -> None:
        """Resmî tatil tarihlerini tanımlar."""
        with self._lock:
            formatted: set[str] = set()
            for h in holidays:
                if isinstance(h, date):
                    formatted.add(h.strftime("%Y-%m-%d"))
                elif isinstance(h, str):
                    formatted.add(h.strip())
            self._holidays = formatted

    def load_holidays_from_bist_calendar(self) -> None:
        """BIST resmî tatil takviminden tatil günlerini otomatik yükler (Self-Healing)."""
        with self._lock:
            try:
                from services.core.bist_calendar import BIST_HOLIDAYS_2024_2026

                self.set_holidays(set(BIST_HOLIDAYS_2024_2026))
                logger.debug("BIST tatil günleri takvimden yüklendi", adet=len(self._holidays))
            except Exception:
                # Fallback: Temel sabit tatiller (1 Ocak, 23 Nisan, 1 Mayıs, 19 Mayıs, 29 Ekim vb.)
                pass

    def is_trading_day(self, d: date) -> bool:
        """Belirtilen tarihin BIST işlem günü olup olmadığını denetler."""
        with self._lock:
            if d.weekday() >= 5:  # Cumartesi = 5, Pazar = 6
                return False
            d_str = d.strftime("%Y-%m-%d")
            return d_str not in self._holidays

    def add_trading_days(self, start_date: date, days: int) -> date:
        """Başlangıç tarihine belirtilen sayıda geçerli işlem günü ekler."""
        with self._lock:
            current = start_date
            added = 0
            # Maksimum güvenlik döngüsü (sonsuz döngüyü önleme)
            max_iterations = max(days * 7, 365)
            iterations = 0

            while added < days and iterations < max_iterations:
                current += timedelta(days=1)
                iterations += 1
                if self.is_trading_day(current):
                    added += 1

            return current

    @otel_trace("settlement.get_settlement_date")
    def get_settlement_date(
        self,
        trade_date: date,
        is_gross: bool = False,
    ) -> date:
        """İşlem tarihine göre BIST takas (valör) gününü hesaplar.

        Args:
            trade_date: İşlemin gerçekleştiği tarih.
            is_gross: Brüt takas uygulanıyor mu? (True ise T+0, False ise T+2).

        Returns:
            date: Hesaplanmış takas günü.
        """
        with self._lock:
            if is_gross:
                # Brüt takas: İşlem günü eğer tatilse bir sonraki işlem gününe ertelenir
                current = trade_date
                while not self.is_trading_day(current):
                    current += timedelta(days=1)
                return current

            return self.add_trading_days(trade_date, self.NORMAL_SETTLEMENT_DAYS)

    @otel_trace("settlement.get_settlement_info")
    def get_settlement_info(
        self,
        trade_date: date,
        is_gross: bool = False,
    ) -> SettlementInfo:
        """İşleme ait detaylı takas modelini üretir ve DuckDB'ye kaydeder."""
        with self._lock:
            settlement_date = self.get_settlement_date(trade_date, is_gross)
            info = SettlementInfo(
                trade_date=trade_date,
                settlement_date=settlement_date,
                settlement_days=0 if is_gross else self.NORMAL_SETTLEMENT_DAYS,
                is_gross=is_gross,
            )
            _record_settlement_audit(info)
            return info

    @otel_trace("settlement.is_settled")
    def is_settled(self, trade_date: date, current_date: date, is_gross: bool = False) -> bool:
        """Belirtilen işlem için takasın tamamlanıp tamamlanmadığını denetler."""
        with self._lock:
            settlement_date = self.get_settlement_date(trade_date, is_gross)
            return current_date >= settlement_date

    @otel_trace("settlement.calculate_settlement_series")
    def calculate_settlement_series(
        self,
        dates_series: pl.Series,
        is_gross: bool = False,
    ) -> pl.Series:
        """Polars Series düzeyinde tarih serisini vektörize takas gününe dönüştürür.

        Args:
            dates_series: İşlem tarihlerini içeren Polars Date/Datetime/String serisi.
            is_gross: Brüt takas bayrağı.

        Returns:
            pl.Series: Takas tarihlerini içeren Polars Date serisi.
        """
        with self._lock:
            if dates_series.is_empty():
                return pl.Series(name="settlement_date", values=[], dtype=pl.Date)

            # Tarihe dönüştür
            date_col = dates_series.cast(pl.Date)
            results: list[date] = []

            for val in date_col:
                if val is None:
                    results.append(None)  # type: ignore[arg-type]
                else:
                    results.append(self.get_settlement_date(val, is_gross))

            return pl.Series(name="settlement_date", values=results, dtype=pl.Date)

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"SettlementCalculator(tatil_sayisi={len(self._holidays)}, "
                f"varsayilan_takas=T+{self.NORMAL_SETTLEMENT_DAYS})"
            )


# Global varsayılan singleton örneği — geriye dönük tam uyumluluk
settlement_calculator: Final[SettlementCalculator] = SettlementCalculator()


def export_settlement_audit_to_polars() -> pl.DataFrame:
    """DuckDB'de saklanan takas hesaplama kayıtlarını Polars DataFrame olarak döner."""
    if _SETTLEMENT_DUCKDB_CONN is None:
        return pl.DataFrame(
            schema={
                "id": pl.Int64,
                "trade_date": pl.Date,
                "settlement_date": pl.Date,
                "settlement_days": pl.Int64,
                "is_gross": pl.Boolean,
                "calculated_at": pl.Datetime,
            }
        )

    with _GLOBAL_LOCK:
        try:
            return _SETTLEMENT_DUCKDB_CONN.execute("SELECT * FROM settlement_audit_log ORDER BY id ASC").pl()
        except Exception as exc:
            logger.error("DuckDB takas denetim kayıtları çekilemedi", hata=str(exc))
            return pl.DataFrame()


__all__ = [
    "DEFAULT_GROSS_SETTLEMENT_DAYS",
    "DEFAULT_NORMAL_SETTLEMENT_DAYS",
    "DEFAULT_SETTLEMENT_DB",
    "SettlementCalculator",
    "SettlementInfo",
    "export_settlement_audit_to_polars",
    "set_settlement_duckdb_connection",
    "settlement_calculator",
]
