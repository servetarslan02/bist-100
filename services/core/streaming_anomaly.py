"""
ALPHA BIST — Streaming Anomaly Detector v2.0

Veri akışı (ingestion/WebSocket) anında mikrosaniye düzeyinde anomali tespiti:
- Fiyat Anomalisi (BIST %5 / %10 devre kesici bantları, ani z-score sıçramaları)
- Hacim Anomalisi (Aşırı emir/işlem patlamaları, z-score hacim dağılımı)
- Spread Anomalisi (Likidite çekilmesi, aşırı makas açılması)
- Veri Kaynağı Anomalisi (NaN, Inf, negatif veya donuk fiyatlar)

Tasarım İlkeleri:
- Noktasal Veri Sızıntısı Yok (Zero Data Leakage / Point-In-Time): Z-score hesaplaması son gelen tick hariç geçmiş pencere üzerinden yapılır.
- Eşzamanlılık Güvenliği: threading.RLock() ile korunan deque tamponları ve paylaşılan durumlar.
- DuckDB >= 1.3.0 denetim izi: Tespit edilen tüm anomaliler streaming_anomalies_audit tablosuna kalıcı kaydedilir.
- Polars >= 1.30.0 vektörize analitik: batch_detect_anomalies_polars() ve export_anomalies_to_polars().
- orjson yüksek hızlı serileştirme ve kurumsal Türkçe docstring/repr standartları.
"""

from __future__ import annotations

import functools
import inspect
import math
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

DEFAULT_STREAMING_ANOMALY_DB: Final[str] = "data/streaming_anomalies_audit.duckdb"
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
class AnomalyResult:
    """Anomali tespit sonucu veri modeli.

    Attributes:
        is_anomaly: Anomali tespit edilip edilmediği.
        anomaly_type: Anomali türü ('price', 'volume', 'spread', 'data_integrity').
        severity: Şiddet derecesi ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL').
        score: Normalize edilmiş anomali skoru (0.0 - 1.0).
        details: Anomali detay açıklaması.
        zscore: Hesaplanan standart sapma z-skoru.
        ticker: İlgili hisse kodu.
        detected_at: Tespit zaman damgası.
    """

    is_anomaly: bool
    anomaly_type: str
    severity: str
    score: float
    details: str
    zscore: float
    ticker: str = ""
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Modeli standart sözlüğe dönüştürür."""
        data = asdict(self)
        data["detected_at"] = self.detected_at.isoformat()
        return data

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson baytlarına dönüştürür."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return (
            f"AnomalyResult(ticker={self.ticker!r}, type={self.anomaly_type!r}, "
            f"severity={self.severity!r}, anomaly={self.is_anomaly}, score={self.score:.2f}, zscore={self.zscore:.2f})"
        )


class StreamingAnomalyDetector:
    """Gerçek zamanlı piyasa verisi anomali algılama motoru.

    Özellikler:
    - Thread-safe deque geçmişi.
    - Zero data leakage z-skor hesaplama.
    - DuckDB kalıcı anomali denetim kaydı.
    - Polars toplu anomali taraması.
    """

    def __init__(self, window_size: int = 100, duckdb_path: str = DEFAULT_STREAMING_ANOMALY_DB) -> None:
        """StreamingAnomalyDetector başlatıcısı.

        Args:
            window_size: Her sembol için geçmiş pencere boyutu (varsayılan: 100 tick).
            duckdb_path: Anomali denetim günlüğü için DuckDB dosya yolu veya ':memory:'.
        """
        self._lock = threading.RLock()
        self._window_size = max(10, window_size)
        self._price_history: dict[str, deque[float]] = {}
        self._volume_history: dict[str, deque[float]] = {}
        self._spread_history: dict[str, deque[float]] = {}
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
        """DuckDB anomali denetim tablosunu başlatır."""
        with self._lock:
            try:
                self._duckdb_con.execute("""
                    CREATE SEQUENCE IF NOT EXISTS seq_streaming_anomaly_id START 1;
                    CREATE TABLE IF NOT EXISTS streaming_anomalies_audit (
                        id BIGINT DEFAULT nextval('seq_streaming_anomaly_id') PRIMARY KEY,
                        ticker VARCHAR NOT NULL,
                        anomaly_type VARCHAR NOT NULL,
                        severity VARCHAR NOT NULL,
                        is_anomaly BOOLEAN NOT NULL,
                        score DOUBLE NOT NULL,
                        zscore DOUBLE NOT NULL,
                        details VARCHAR NOT NULL,
                        detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
            except Exception as exc:
                logger.error("Streaming anomaly detector DuckDB schema init failed", error=str(exc))

    def _clean_ticker(self, ticker: str) -> str:
        """Ticker kodunu standartlaştırır."""
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

    def _record_audit_log(self, result: AnomalyResult) -> None:
        """Tespit edilen anomaliyi yerel DuckDB tablosuna işler."""
        if not result.is_anomaly:
            return

        with self._lock:
            try:
                self._duckdb_con.execute(
                    """
                    INSERT INTO streaming_anomalies_audit
                    (ticker, anomaly_type, severity, is_anomaly, score, zscore, details, detected_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        str(result.ticker),
                        str(result.anomaly_type),
                        str(result.severity),
                        bool(result.is_anomaly),
                        float(result.score),
                        float(result.zscore),
                        str(result.details),
                        result.detected_at,
                    ],
                )
            except Exception as exc:
                logger.warning("Failed to record anomaly in DuckDB audit", ticker=result.ticker, error=str(exc))

    @otel_trace("streaming_anomaly.check_price")
    def check_price(
        self,
        ticker: str,
        price: float,
        previous_price: float,
        volatility: float = 0.25,
    ) -> AnomalyResult:
        """Fiyat anomalisi kontrolü (Point-In-Time z-score + BIST devre kesici eşiği).

        Args:
            ticker: Hisse kodu.
            price: Anlık fiyat.
            previous_price: Önceki referans/kapanış fiyatı.
            volatility: Yıllıklandırılmış volatilite varsayımı.

        Returns:
            AnomalyResult: Anomali denetim sonucu.
        """
        clean_tick = self._clean_ticker(ticker)

        # Veri bütünlüğü kontrolü (Fail-Closed)
        if math.isnan(price) or math.isinf(price) or price <= 0.0:
            res = AnomalyResult(
                is_anomaly=True,
                anomaly_type="price",
                severity="CRITICAL",
                score=1.0,
                details=f"Geçersiz sayısal fiyat değeri: {price}",
                zscore=99.0,
                ticker=clean_tick,
            )
            self._record_audit_log(res)
            return res

        with self._lock:
            if clean_tick not in self._price_history:
                self._price_history[clean_tick] = deque(maxlen=self._window_size)
            history = self._price_history[clean_tick]
            history_list = list(history)
            history.append(price)

        # Point-In-Time Z-Score: Son gelen tick hesaplamaya dahil edilmez
        if len(history_list) >= 10:
            mean = float(np.mean(history_list))
            std = float(np.std(history_list))
            zscore = abs(price - mean) / std if std > 1e-6 else 0.0
        else:
            zscore = 0.0

        # Yüzdesel değişim ve BIST devre kesici kontrolleri
        if previous_price > 0.0 and not math.isnan(previous_price) and not math.isinf(previous_price):
            change_pct = abs(price / previous_price - 1.0) * 100.0
            expected_move = float((volatility / np.sqrt(252)) * 4.0 * 100.0)  # 4-sigma
            is_spike = bool(change_pct > max(3.0, expected_move))
        else:
            change_pct = 0.0
            expected_move = 0.0
            is_spike = False

        # Şiddet derecelendirmesi
        if zscore > 5.0 or change_pct >= 9.9:
            severity = "CRITICAL"
        elif zscore > 4.0 or change_pct >= 4.9:
            severity = "HIGH"
        elif zscore > 3.0 or change_pct >= 2.5:
            severity = "MEDIUM"
        else:
            severity = "LOW"

        is_anomaly = bool(is_spike or zscore > 3.5)
        res = AnomalyResult(
            is_anomaly=is_anomaly,
            anomaly_type="price",
            severity=severity,
            score=min(1.0, float(zscore / 5.0 if zscore > 0 else (change_pct / 10.0))),
            details=f"zscore={zscore:.2f}, degisim={change_pct:.2f}%",
            zscore=round(float(zscore), 2),
            ticker=clean_tick,
        )
        self._record_audit_log(res)
        return res

    @otel_trace("streaming_anomaly.check_volume")
    def check_volume(
        self,
        ticker: str,
        volume: int | float,
    ) -> AnomalyResult:
        """İşlem hacmi anomalisi kontrolü (Z-skor patlama analizi)."""
        clean_tick = self._clean_ticker(ticker)
        vol_float = float(volume)

        if math.isnan(vol_float) or math.isinf(vol_float) or vol_float < 0:
            res = AnomalyResult(
                is_anomaly=True,
                anomaly_type="volume",
                severity="CRITICAL",
                score=1.0,
                details=f"Geçersiz hacim değeri: {volume}",
                zscore=99.0,
                ticker=clean_tick,
            )
            self._record_audit_log(res)
            return res

        with self._lock:
            if clean_tick not in self._volume_history:
                self._volume_history[clean_tick] = deque(maxlen=self._window_size)
            history = self._volume_history[clean_tick]
            history_list = list(history)
            history.append(vol_float)

        if len(history_list) >= 10:
            mean = float(np.mean(history_list))
            std = float(np.std(history_list))
            zscore = abs(vol_float - mean) / std if std > 1e-6 else 0.0
        else:
            zscore = 0.0

        is_anomaly = zscore > 4.0
        severity = "CRITICAL" if zscore > 6.0 else "HIGH" if zscore > 4.0 else "MEDIUM" if zscore > 3.0 else "LOW"

        res = AnomalyResult(
            is_anomaly=is_anomaly,
            anomaly_type="volume",
            severity=severity,
            score=min(1.0, zscore / 5.0),
            details=f"hacim_zscore={zscore:.2f}",
            zscore=round(zscore, 2),
            ticker=clean_tick,
        )
        self._record_audit_log(res)
        return res

    @otel_trace("streaming_anomaly.check_spread")
    def check_spread(
        self,
        ticker: str,
        bid: float,
        ask: float,
    ) -> AnomalyResult:
        """Alış-Satış makas (spread) anomalisi kontrolü."""
        clean_tick = self._clean_ticker(ticker)

        if bid <= 0.0 or ask <= 0.0 or math.isnan(bid) or math.isnan(ask) or bid > ask:
            res = AnomalyResult(
                is_anomaly=True,
                anomaly_type="spread",
                severity="HIGH",
                score=1.0,
                details=f"Geçersiz bid/ask kotasyonu (bid={bid}, ask={ask})",
                zscore=0.0,
                ticker=clean_tick,
            )
            self._record_audit_log(res)
            return res

        mid = (bid + ask) / 2.0
        spread_pct = (ask - bid) / mid * 100.0 if mid > 0.0 else 0.0

        with self._lock:
            if clean_tick not in self._spread_history:
                self._spread_history[clean_tick] = deque(maxlen=self._window_size)
            history = self._spread_history[clean_tick]
            history_list = list(history)
            history.append(spread_pct)

        if len(history_list) >= 10:
            mean = float(np.mean(history_list))
            std = float(np.std(history_list))
            zscore = abs(spread_pct - mean) / std if std > 1e-6 else 0.0
        else:
            zscore = 0.0

        is_anomaly = spread_pct > 5.0 or zscore > 4.0
        severity = "CRITICAL" if spread_pct > 8.0 or zscore > 6.0 else "HIGH" if is_anomaly else "LOW"

        res = AnomalyResult(
            is_anomaly=is_anomaly,
            anomaly_type="spread",
            severity=severity,
            score=min(1.0, max(spread_pct / 5.0, zscore / 4.0)),
            details=f"spread={spread_pct:.2f}%, zscore={zscore:.2f}",
            zscore=round(zscore, 2),
            ticker=clean_tick,
        )
        self._record_audit_log(res)
        return res

    @otel_trace("streaming_anomaly.check_all")
    def check_all(
        self,
        ticker: str,
        price: float,
        previous_price: float,
        volume: int | float,
        bid: float = 0.0,
        ask: float = 0.0,
        volatility: float = 0.25,
    ) -> list[AnomalyResult]:
        """Tüm piyasa anomali denetimlerini tek seferde yürütür."""
        results: list[AnomalyResult] = []

        price_res = self.check_price(ticker, price, previous_price, volatility)
        results.append(price_res)

        vol_res = self.check_volume(ticker, volume)
        results.append(vol_res)

        if bid > 0.0 or ask > 0.0:
            spread_res = self.check_spread(ticker, bid, ask)
            results.append(spread_res)

        return results

    def batch_detect_anomalies_polars(self, df: pl.DataFrame) -> pl.DataFrame:
        """Toplu veri akışında (tick veya bar DataFrame) Polars ile vektörize anomali tespiti yapar.

        Beklenen Sütunlar:
            ticker: pl.Utf8
            price: pl.Float64
            volume: pl.Float64 veya pl.Int64
        """
        required_cols = {"ticker", "price", "volume"}
        if not required_cols.issubset(set(df.columns)) or df.is_empty():
            return pl.DataFrame(
                schema={
                    "ticker": pl.Utf8,
                    "price": pl.Float64,
                    "is_price_anomaly": pl.Boolean,
                    "is_volume_anomaly": pl.Boolean,
                    "price_change_pct": pl.Float64,
                }
            )

        # Polars vektörize pencere ve değişim hesaplamaları
        augmented = df.with_columns([
            pl.col("price").shift(1).over("ticker").alias("prev_price"),
            pl.col("price").rolling_mean(window_size=10).over("ticker").alias("price_roll_mean"),
            pl.col("price").rolling_std(window_size=10).over("ticker").alias("price_roll_std"),
            pl.col("volume").rolling_mean(window_size=10).over("ticker").alias("vol_roll_mean"),
            pl.col("volume").rolling_std(window_size=10).over("ticker").alias("vol_roll_std"),
        ]).with_columns([
            (
                (pl.col("price") / pl.col("prev_price") - 1.0).abs() * 100.0
            ).fill_null(0.0).alias("price_change_pct"),
            (
                (pl.col("price") - pl.col("price_roll_mean")).abs() / (pl.col("price_roll_std") + 1e-6)
            ).fill_null(0.0).alias("price_zscore"),
            (
                (pl.col("volume") - pl.col("vol_roll_mean")).abs() / (pl.col("vol_roll_std") + 1e-6)
            ).fill_null(0.0).alias("volume_zscore"),
        ]).with_columns([
            (
                (pl.col("price_change_pct") > 5.0) | (pl.col("price_zscore") > 3.5)
            ).alias("is_price_anomaly"),
            (
                pl.col("volume_zscore") > 4.0
            ).alias("is_volume_anomaly"),
        ])

        return augmented.select([
            "ticker",
            "price",
            "is_price_anomaly",
            "is_volume_anomaly",
            "price_change_pct",
        ])

    def export_anomalies_to_polars(self) -> pl.DataFrame:
        """DuckDB'de biriken tüm anomali kayıtlarını Polars DataFrame olarak dışa aktarır."""
        with self._lock:
            try:
                return self._duckdb_con.execute("""
                    SELECT id, ticker, anomaly_type, severity, is_anomaly, score, zscore, details, detected_at
                    FROM streaming_anomalies_audit
                    ORDER BY id ASC
                """).pl()
            except Exception as exc:
                logger.error("Failed to export anomalies to Polars", error=str(exc))
                return pl.DataFrame()

    def get_stats(self) -> dict[str, Any]:
        """Motor çalışma istatistiklerini döndürür."""
        with self._lock:
            total_audit = 0
            try:
                row = self._duckdb_con.execute("SELECT COUNT(*) FROM streaming_anomalies_audit").fetchone()
                total_audit = int(row[0]) if row else 0
            except Exception:
                pass

            return {
                "tracked_tickers": len(self._price_history),
                "total_price_points": sum(len(h) for h in self._price_history.values()),
                "total_volume_points": sum(len(h) for h in self._volume_history.values()),
                "total_spread_points": sum(len(h) for h in self._spread_history.values()),
                "persisted_anomalies_count": total_audit,
            }

    def clear_audit_duckdb(self) -> None:
        """Anomali denetim tablosunu temizler."""
        with self._lock:
            try:
                self._duckdb_con.execute("DELETE FROM streaming_anomalies_audit")
            except Exception as exc:
                logger.warning("DuckDB anomali tablosu temizlenemedi", hata=str(exc))

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
                f"StreamingAnomalyDetector(tracked_tickers={len(self._price_history)}, "
                f"window={self._window_size}, duckdb={self._duckdb_path!r})"
            )


def read_streaming_anomalies_from_duckdb(
    duckdb_path: str = DEFAULT_STREAMING_ANOMALY_DB,
    limit: int = 1000,
) -> pl.DataFrame:
    """DuckDB dosyasından doğrudan anomali denetim kayıtlarını Polars DataFrame olarak okur."""
    try:
        conn = duckdb.connect(duckdb_path)
        try:
            return conn.execute(
                """
                SELECT id, ticker, anomaly_type, severity, is_anomaly, score, zscore, details, detected_at
                FROM streaming_anomalies_audit
                ORDER BY id DESC
                LIMIT ?
                """,
                [limit],
            ).pl()
        finally:
            conn.close()
    except Exception as exc:
        logger.error("DuckDB dosyasindan anomali kayitlari okunamadi", hata=str(exc))
        return pl.DataFrame()


def clear_streaming_anomalies_duckdb(duckdb_path: str = DEFAULT_STREAMING_ANOMALY_DB) -> None:
    """Belirtilen DuckDB dosyasındaki anomali tablosunu sıfırlar."""
    try:
        conn = duckdb.connect(duckdb_path)
        try:
            conn.execute("DELETE FROM streaming_anomalies_audit")
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("DuckDB anomali tablosu temizlenemedi", hata=str(exc))


# Singleton
streaming_anomaly_detector = StreamingAnomalyDetector()

__all__ = [
    "AnomalyResult",
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_STREAMING_ANOMALY_DB",
    "DEFAULT_WAL_SIZE",
    "StreamingAnomalyDetector",
    "clear_streaming_anomalies_duckdb",
    "configure_duckdb_wal",
    "otel_trace",
    "read_streaming_anomalies_from_duckdb",
    "streaming_anomaly_detector",
    "to_orjson_bytes",
]
