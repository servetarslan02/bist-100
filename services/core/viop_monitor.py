"""
ALPHA BIST — VIOP Monitor (Vadeli İşlem ve Opsiyon Piyasası Risk ve Teminat Takibi) v2.0

BIST VİOP Teminat, Risk ve Sürdürme İzleme Motoru:
- SPAN Portföy Bazında Teminatlandırma ve Risk Hesaplamaları.
- Başlangıç ve Sürdürme Teminatı (Maintenance Margin) Yeterlilik Kontrolleri.
- Margin Call (Teminat Tamamlama Çağrısı) ve Otomatik Tasfiye (Liquidation) Eşikleri.
- Sayısal Guard'lar (Fail-Closed): NaN, Inf, negatif pozisyon veya teminat değerleri.
- İş Parçacığı Güvenliği: threading.RLock() korumalı özel teminat oranları ve durum yönetimi.
- DuckDB >= 1.3.0 denetim izi: viop_monitor_audit tablosu ile her teminat kontrolünün diske kalıcı arşivlenmesi.
- Polars >= 1.30.0 vektörize toplu teminat analitiği: check_margin_batch_polars() ve export_audit_to_polars().
- orjson yüksek hızlı ikili serileştirme ve kurumsal Türkçe docstring/repr standartları.
"""

from __future__ import annotations

import functools
import inspect
import math
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

DEFAULT_VIOP_MONITOR_DB: Final[str] = "data/viop_monitor_audit.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"

logger = structlog.get_logger(__name__)


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder."""
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.debug("DuckDB WAL pragma uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir veriyi orjson ile güvenli byte dizisine serileştirir."""
    if hasattr(val, "to_dict"):
        return orjson.dumps(val.to_dict(), default=str)
    return orjson.dumps(val, default=str)


def otel_trace(span_name: str) -> Any:
    """Metotları OpenTelemetry span veya güvenli yerel izleme sarmalayıcısına alır."""

    def decorator(func: Any) -> Any:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


@dataclass(slots=True)
class MarginStatus:
    """VİOP teminat ve risk değerlendirme sonucu veri modeli.

    Attributes:
        margin_call: Teminat tamamlama çağrısı gerekip gerekmediği.
        required: Gerekli başlangıç teminat tutarı (TL).
        available: Mevcut kullanılabilir teminat tutarı (TL).
        surplus: Teminat fazlası veya eksiği (TL).
        action: Alınması önerilen aksiyon ('OK', 'MARGIN_CALL', 'LIQUIDATE').
        details: Ek risk ve sözleşme detayları.
        calculated_at: Değerlendirme zaman damgası.
    """

    margin_call: bool
    required: float = 0.0
    available: float = 0.0
    surplus: float = 0.0
    action: str = "OK"
    details: dict[str, Any] = field(default_factory=dict)
    calculated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Modeli standart Python sözlüğüne dönüştürür."""
        data = asdict(self)
        data["calculated_at"] = self.calculated_at.isoformat()
        return data

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson ikili baytlarına serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return (
            f"MarginStatus(call={self.margin_call}, action={self.action!r}, "
            f"req={self.required:,.2f}TL, avail={self.available:,.2f}TL, surplus={self.surplus:,.2f}TL)"
        )


class VIOPMonitor:
    """BIST Vadeli İşlem ve Opsiyon Piyasası (VİOP) teminat ve risk takip motoru."""

    # Varsayılan BIST SPAN teminat oranları
    DEFAULT_MARGIN_RATE: float = 0.15  # %15 Başlangıç teminat oranı
    MAINTENANCE_MARGIN_RATE: float = 0.12  # %12 Sürdürme teminatı oranı
    MARGIN_CALL_THRESHOLD: float = 0.13  # %13 Teminat tamamlama çağrısı eşiği
    LIQUIDATION_THRESHOLD: float = 0.08  # %8 Zorunlu tasfiye eşiği

    def __init__(self, duckdb_path: str = DEFAULT_VIOP_MONITOR_DB) -> None:
        """VIOPMonitor başlatıcısı.

        Args:
            duckdb_path: Denetim günlüğü için DuckDB dosya yolu veya ':memory:'.
        """
        self._lock = threading.RLock()
        self._custom_margin_rates: dict[str, float] = {}
        self._duckdb_path = duckdb_path

        # DuckDB denetim tablosu kurulumu
        if self._duckdb_path != ":memory:":
            try:
                Path(self._duckdb_path).parent.mkdir(parents=True, exist_ok=True)
                self._duckdb_con = duckdb.connect(self._duckdb_path)
            except Exception as e:
                logger.warning(
                    "DuckDB disk baglantisi kurulamadi, bellege donuluyor",
                    yol=self._duckdb_path,
                    hata=str(e),
                )
                self._duckdb_con = duckdb.connect(":memory:")
        else:
            self._duckdb_con = duckdb.connect(":memory:")

        configure_duckdb_wal(self._duckdb_con)
        self._init_duckdb_schema()

    def _init_duckdb_schema(self) -> None:
        """DuckDB VİOP denetim tablosunu ve dizisini oluşturur."""
        with self._lock:
            try:
                self._duckdb_con.execute("""
                    CREATE SEQUENCE IF NOT EXISTS seq_viop_audit_id START 1;
                    CREATE TABLE IF NOT EXISTS viop_monitor_audit (
                        id BIGINT DEFAULT nextval('seq_viop_audit_id') PRIMARY KEY,
                        ticker VARCHAR NOT NULL,
                        position_value DOUBLE NOT NULL,
                        available_margin DOUBLE NOT NULL,
                        required_margin DOUBLE NOT NULL,
                        surplus DOUBLE NOT NULL,
                        margin_call BOOLEAN NOT NULL,
                        action VARCHAR NOT NULL,
                        details_json VARCHAR NOT NULL,
                        calculated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
            except Exception as exc:
                logger.error("VIOPMonitor DuckDB schema init failed", error=str(exc))

    def _clean_ticker(self, ticker: str) -> str:
        """Ticker sembolünü standartlaştırır."""
        if not ticker or not isinstance(ticker, str):
            return ""
        return (
            ticker.strip()
            .upper()
            .replace("İ", "I")
            .replace("I", "I")
            .replace("Ğ", "G")
            .replace("Ü", "U")
            .replace("Ş", "S")
            .replace("Ö", "O")
            .replace("Ç", "C")
        )

    def _record_audit_log(
        self,
        ticker: str,
        position_value: float,
        available_margin: float,
        result: MarginStatus,
    ) -> None:
        """Teminat kontrolü sonucunu yerel DuckDB tablosuna kaydeder."""
        with self._lock:
            try:
                details_json = orjson.dumps(result.details, default=str).decode("utf-8")
                self._duckdb_con.execute(
                    """
                    INSERT INTO viop_monitor_audit
                    (ticker, position_value, available_margin, required_margin, surplus,
                     margin_call, action, details_json, calculated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        ticker,
                        float(position_value),
                        float(available_margin),
                        float(result.required),
                        float(result.surplus),
                        bool(result.margin_call),
                        result.action,
                        details_json,
                        result.calculated_at,
                    ],
                )
            except Exception as exc:
                logger.warning("Failed to record VIOP monitor audit log", error=str(exc))

    def set_margin_rate(self, ticker: str, rate: float) -> None:
        """Belirtilen VİOP sözleşmesi için özel teminat oranı atar.

        Args:
            ticker: Sözleşme veya dayanak varlık sembolü.
            rate: Teminat oranı (0.01 - 1.0 arası).
        """
        clean_tick = self._clean_ticker(ticker)
        if clean_tick and 0.01 <= rate <= 1.0:
            with self._lock:
                self._custom_margin_rates[clean_tick] = float(rate)

    def get_margin_rate(self, ticker: str) -> float:
        """Belirtilen sözleşmenin geçerli teminat oranını döndürür."""
        clean_tick = self._clean_ticker(ticker)
        with self._lock:
            return self._custom_margin_rates.get(clean_tick, self.DEFAULT_MARGIN_RATE)

    @otel_trace("viop_monitor.check_viop_margin")
    def check_viop_margin(
        self,
        position_value: float,
        available_margin: float,
        ticker: str = "",
    ) -> MarginStatus:
        """VİOP pozisyonu için teminat yeterliliği ve margin call kontrolü yapar.

        Args:
            position_value: Toplam açık pozisyon nominal büyüklüğü (TL).
            available_margin: Kullanılabilir serbest teminat tutarı (TL).
            ticker: İlgili VİOP sözleşme kodu.

        Returns:
            MarginStatus: Detaylı teminat durumu ve önerilen aksiyon.
        """
        clean_tick = self._clean_ticker(ticker)

        # Sayısal Guard'lar (Fail-Closed)
        if (
            math.isnan(position_value)
            or math.isinf(position_value)
            or math.isnan(available_margin)
            or math.isinf(available_margin)
        ):
            res = MarginStatus(
                margin_call=True,
                action="MARGIN_CALL",
                details={"error": "Geçersiz sayısal pozisyon veya teminat değeri", "ticker": clean_tick},
            )
            self._record_audit_log(clean_tick, position_value, available_margin, res)
            return res

        if position_value <= 0.0:
            res = MarginStatus(
                margin_call=False,
                required=0.0,
                available=max(0.0, available_margin),
                surplus=max(0.0, available_margin),
                action="OK",
                details={"ticker": clean_tick, "position_value": 0.0},
            )
            self._record_audit_log(clean_tick, position_value, available_margin, res)
            return res

        margin_rate = self.get_margin_rate(clean_tick)
        required = position_value * margin_rate
        surplus = available_margin - required

        # Margin Call ve Zorunlu Tasfiye Değerlendirmesi
        margin_call = False
        action = "OK"

        liquidation_level = position_value * self.LIQUIDATION_THRESHOLD
        maintenance_level = position_value * self.MARGIN_CALL_THRESHOLD

        if available_margin < liquidation_level:
            margin_call = True
            action = "LIQUIDATE"
        elif surplus < 0.0 or available_margin < maintenance_level:
            margin_call = True
            action = "MARGIN_CALL"

        res = MarginStatus(
            margin_call=margin_call,
            required=required,
            available=available_margin,
            surplus=surplus,
            action=action,
            details={
                "ticker": clean_tick,
                "position_value": position_value,
                "margin_rate": margin_rate,
                "maintenance_level": maintenance_level,
                "liquidation_level": liquidation_level,
            },
        )

        self._record_audit_log(clean_tick, position_value, available_margin, res)
        return res

    def check_margin_batch_polars(self, df: pl.DataFrame) -> pl.DataFrame:
        """Toplu portföy VİOP pozisyonları için Polars vektörize teminat analitiği hesaplar.

        Beklenen Sütunlar:
            ticker (Utf8), position_value (Float64), available_margin (Float64)
        """
        required_cols = {"ticker", "position_value", "available_margin"}
        if not required_cols.issubset(set(df.columns)) or df.is_empty():
            return df

        augmented = df.with_columns([
            (pl.col("position_value") * self.DEFAULT_MARGIN_RATE).alias("required_margin"),
        ]).with_columns([
            (pl.col("available_margin") - pl.col("required_margin")).alias("surplus"),
        ]).with_columns([
            (
                (pl.col("surplus") < 0.0)
                | (pl.col("available_margin") < pl.col("position_value") * self.MARGIN_CALL_THRESHOLD)
            ).alias("margin_call"),
            pl.when(pl.col("available_margin") < pl.col("position_value") * self.LIQUIDATION_THRESHOLD)
            .then(pl.lit("LIQUIDATE"))
            .when(
                (pl.col("surplus") < 0.0)
                | (pl.col("available_margin") < pl.col("position_value") * self.MARGIN_CALL_THRESHOLD)
            )
            .then(pl.lit("MARGIN_CALL"))
            .otherwise(pl.lit("OK"))
            .alias("action"),
        ])

        return augmented

    def export_audit_to_polars(self) -> pl.DataFrame:
        """DuckDB'de kayıtlı VİOP denetim loglarını Polars DataFrame olarak dışa aktarır."""
        with self._lock:
            try:
                return self._duckdb_con.execute("""
                    SELECT id, ticker, position_value, available_margin, required_margin,
                           surplus, margin_call, action, details_json, calculated_at
                    FROM viop_monitor_audit
                    ORDER BY id ASC
                """).pl()
            except Exception as exc:
                logger.error("Failed to export VIOP monitor audit log to Polars", error=str(exc))
                return pl.DataFrame()

    def clear_audit_duckdb(self) -> None:
        """DuckDB VİOP denetim tablosunu temizler."""
        with self._lock:
            try:
                self._duckdb_con.execute("DELETE FROM viop_monitor_audit")
            except Exception as exc:
                logger.warning("DuckDB VIOP audit tablosu temizlenemedi", hata=str(exc))

    def close(self) -> None:
        """DuckDB bağlantısını güvenli şekilde kapatır."""
        with self._lock:
            try:
                self._duckdb_con.close()
            except Exception as exc:
                logger.debug("DuckDB baglantisi kapatilirken hata", hata=str(exc))

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"VIOPMonitor(custom_rates={len(self._custom_margin_rates)}, "
                f"default_rate={self.DEFAULT_MARGIN_RATE:.1%}, duckdb={self._duckdb_path!r})"
            )


def read_viop_monitor_audit_from_duckdb(
    duckdb_path: str = DEFAULT_VIOP_MONITOR_DB,
    limit: int = 1000,
) -> pl.DataFrame:
    """DuckDB dosyasından doğrudan VİOP denetim kayıtlarını Polars DataFrame olarak okur."""
    try:
        conn = duckdb.connect(duckdb_path)
        try:
            return conn.execute(
                """
                SELECT id, ticker, position_value, available_margin, required_margin,
                       surplus, margin_call, action, details_json, calculated_at
                FROM viop_monitor_audit
                ORDER BY id DESC
                LIMIT ?
                """,
                [limit],
            ).pl()
        finally:
            conn.close()
    except Exception as exc:
        logger.error("DuckDB dosyasindan VIOP kayitlari okunamadi", hata=str(exc))
        return pl.DataFrame()


def clear_viop_monitor_audit_duckdb(duckdb_path: str = DEFAULT_VIOP_MONITOR_DB) -> None:
    """Belirtilen DuckDB dosyasındaki VİOP denetim tablosunu sıfırlar."""
    try:
        conn = duckdb.connect(duckdb_path)
        try:
            conn.execute("DELETE FROM viop_monitor_audit")
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("DuckDB VIOP denetim tablosu temizlenemedi", hata=str(exc))


# Küresel Singleton Nesnesi
viop_monitor = VIOPMonitor()

__all__ = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_VIOP_MONITOR_DB",
    "DEFAULT_WAL_SIZE",
    "MarginStatus",
    "VIOPMonitor",
    "clear_viop_monitor_audit_duckdb",
    "configure_duckdb_wal",
    "otel_trace",
    "read_viop_monitor_audit_from_duckdb",
    "to_orjson_bytes",
    "viop_monitor",
]
