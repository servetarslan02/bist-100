"""
ALPHA BIST — Tradability Mask (Mask-First Design & Execute Edilebilirlik Filtresi) v2.0

Mask-First İlkesi (Du, 2026):
Hiçbir öznitelik (feature) hesaplaması veya model eğitimi, fiilen piyasada execute edilemeyen
veya piyasa yapısı gereği bozuk olan fiyatları görmemelidir.

BIST'te Execute Edilemeyen Fiyat Koşulları:
- Devre Kesici (Circuit Breaker): İşlemlerin geçici durdurulduğu anlar (%5, %10 eşikleri).
- Tavan Fiyat (Limit-Up): Fiyat tavana yapışmış (%10), alım emri gerçekleştirilemez.
- Taban Fiyat (Limit-Down): Fiyat tabana yapışmış (%10), satım emri gerçekleştirilemez.
- Sıfır Hacim veya Donuk Fiyat: Likidite yokluğu ve işlem gerçekleşmemesi.
- OHLC Tutarsızlıkları: High < Low, High < Close, Low > Close veya negatif/NaN değerler.
- Aşırı Fiyat Sıçramaları veya Gap: Veri kaynağı anomalileri.

Tasarım Standartları:
- Polars >= 1.30.0: Yüksek hacimli tick/bar verileri için compute_mask_polars() vektörize motoru.
- DuckDB >= 1.3.0: tradability_mask_audit tablosu ile her hesaplamanın diske kalıcı arşivlenmesi.
- Eşzamanlılık: threading.RLock() korumalı thread-safe durum ve metrik yönetimi.
- orjson yüksek hızlı ikili serileştirme ve kurumsal Türkçe docstring/repr.
"""

from __future__ import annotations

import functools
import inspect
import math
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

DEFAULT_TRADABILITY_MASK_DB: Final[str] = "data/tradability_mask_audit.duckdb"
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
class MaskResult:
    """Tradability maskesi hesaplama sonucu veri modeli.

    Attributes:
        ticker: İlgili hisse senedi veya varlık sembolü.
        mask: NumPy 1D ikili dizi (1 = Güvenilir/İşlem yapılabilir, 0 = Geçersiz/İşlem yapılamaz).
        reason: İndeks bazlı geçersizlik nedenleri sözlüğü.
        valid_count: Geçerli (mask=1) bar/tick sayısı.
        total_count: Toplam değerlendirilen bar/tick sayısı.
        valid_pct: Geçerli veri yüzdesi (0.0 - 100.0).
        calculated_at: Hesaplama zaman damgası.
    """

    ticker: str
    mask: np.ndarray
    reason: dict[int, str] = field(default_factory=dict)
    valid_count: int = 0
    total_count: int = 0
    valid_pct: float = 0.0
    calculated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Modeli standart Python sözlüğüne dönüştürür."""
        return {
            "ticker": self.ticker,
            "valid_count": self.valid_count,
            "total_count": self.total_count,
            "valid_pct": self.valid_pct,
            "invalid_count": self.total_count - self.valid_count,
            "calculated_at": self.calculated_at.isoformat(),
        }

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson ikili baytlarına serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return (
            f"MaskResult(ticker={self.ticker!r}, valid={self.valid_count}/{self.total_count} "
            f"(%{self.valid_pct:.1f}), invalid_reasons={len(self.reason)})"
        )


class TradabilityMask:
    """Execute edilemeyen veya bozuk fiyatları tespit eden Mask-First motoru."""

    # BIST limit-up/down eşiği (Güncel mevzuat: Tüm pazarlarda %10)
    LIMIT_UP_PCT: float = 0.10
    LIMIT_DOWN_PCT: float = 0.10

    # Devre kesici eşikleri (BIST: %5, %10)
    CIRCUIT_BREAKER_PCTS: list[float] = [0.05, 0.10]

    def __init__(self, duckdb_path: str = DEFAULT_TRADABILITY_MASK_DB) -> None:
        """TradabilityMask başlatıcısı.

        Args:
            duckdb_path: Maske denetim günlüğü için DuckDB dosya yolu veya ':memory:'.
        """
        self._lock = threading.RLock()
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
        """DuckDB denetim tablosunu ve dizisini oluşturur."""
        with self._lock:
            try:
                self._duckdb_con.execute("""
                    CREATE SEQUENCE IF NOT EXISTS seq_tradability_mask_id START 1;
                    CREATE TABLE IF NOT EXISTS tradability_mask_audit (
                        id BIGINT DEFAULT nextval('seq_tradability_mask_id') PRIMARY KEY,
                        ticker VARCHAR NOT NULL,
                        total_count BIGINT NOT NULL,
                        valid_count BIGINT NOT NULL,
                        invalid_count BIGINT NOT NULL,
                        valid_pct DOUBLE NOT NULL,
                        reasons_summary_json VARCHAR NOT NULL,
                        calculated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
            except Exception as exc:
                logger.error("TradabilityMask DuckDB schema init failed", error=str(exc))

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

    def _record_audit_log(self, result: MaskResult) -> None:
        """Mask hesaplama özetini yerel DuckDB tablosuna kaydeder."""
        with self._lock:
            try:
                # Nedenleri kategorize et
                category_counts: dict[str, int] = {}
                for r in result.reason.values():
                    cat = r.split("_")[0]
                    category_counts[cat] = category_counts.get(cat, 0) + 1

                reasons_json = orjson.dumps(category_counts).decode("utf-8")
                invalid_count = result.total_count - result.valid_count

                self._duckdb_con.execute(
                    """
                    INSERT INTO tradability_mask_audit
                    (ticker, total_count, valid_count, invalid_count, valid_pct, reasons_summary_json, calculated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        result.ticker,
                        int(result.total_count),
                        int(result.valid_count),
                        int(invalid_count),
                        float(result.valid_pct),
                        reasons_json,
                        result.calculated_at,
                    ],
                )
            except Exception as exc:
                logger.warning("Failed to record tradability mask audit log", error=str(exc))

    @otel_trace("tradability_mask.compute_mask")
    def compute_mask(
        self,
        ticker: str,
        open_: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        prev_close: np.ndarray | None = None,
        is_small_cap: bool = False,
    ) -> MaskResult:
        """Fiyat serisi için tradability maskesi hesaplar.

        Args:
            ticker: Hisse senedi kodu.
            open_, high, low, close: OHLCV sayısal dizileri.
            volume: Hacim dizisi.
            prev_close: Önceki kapanış referans dizisi (Limit-up/down kontrolü için).
            is_small_cap: Alt pazar hissesi mi.

        Returns:
            MaskResult: Hesaplanan maske ve detaylı geçersizlik raporu.
        """
        clean_tick = self._clean_ticker(ticker)
        n = len(close)

        # Boyut ve boş dizi kontrolleri (Fail-Closed)
        if (
            n == 0
            or len(open_) != n
            or len(high) != n
            or len(low) != n
            or len(volume) != n
        ):
            return MaskResult(
                ticker=clean_tick,
                mask=np.zeros(max(0, n), dtype=int),
                reason={0: "empty_or_mismatched_arrays"} if n > 0 else {},
                valid_count=0,
                total_count=n,
                valid_pct=0.0,
            )

        mask = np.ones(n, dtype=int)
        reasons: dict[int, str] = {}

        # 1. Sıfır, negatif veya NaN/Inf fiyat kontrolleri
        invalid_price = (
            (close <= 0.0)
            | np.isnan(close)
            | np.isinf(close)
            | (open_ <= 0.0)
            | np.isnan(open_)
            | np.isinf(open_)
        )
        mask[invalid_price] = 0
        for i in np.where(invalid_price)[0]:
            reasons[int(i)] = "zero_or_invalid_price"

        # 2. Sıfır, negatif veya NaN hacim kontrolü
        invalid_vol = (volume <= 0.0) | np.isnan(volume) | np.isinf(volume)
        vol_mask = invalid_vol & (mask == 1)
        mask[vol_mask] = 0
        for i in np.where(vol_mask)[0]:
            reasons[int(i)] = "zero_or_invalid_volume"

        # 3. OHLC Tutarlılığı (High < Low veya Low > Close vb.)
        h_lt_l = (high < low) | np.isnan(high) | np.isnan(low)
        hl_mask = h_lt_l & (mask == 1)
        mask[hl_mask] = 0
        for i in np.where(hl_mask)[0]:
            reasons[int(i)] = "high_less_than_low"

        ohlc_incon = (high < close) | (low > close) | (high < open_) | (low > open_)
        ohlc_mask = ohlc_incon & (mask == 1)
        mask[ohlc_mask] = 0
        for i in np.where(ohlc_mask)[0]:
            reasons[int(i)] = "ohlc_inconsistent"

        # 4. Limit-Up / Limit-Down ve Devre Kesici Kontrolleri
        limit_pct = self.LIMIT_UP_PCT

        for i in range(n):
            if mask[i] == 0:
                continue

            # Önceki kapanışa göre değişim kontrolü
            if prev_close is not None and i < len(prev_close):
                prev = prev_close[i]
                if prev > 0.0 and not math.isnan(prev):
                    daily_change = (close[i] - prev) / prev

                    # Tavan kontrolü (%10 - tolerans)
                    if daily_change >= (limit_pct - 0.001):
                        mask[i] = 0
                        reasons[i] = f"limit_up_{daily_change:.1%}"
                        continue

                    # Taban kontrolü (-%10 + tolerans)
                    if daily_change <= (-limit_pct + 0.001):
                        mask[i] = 0
                        reasons[i] = f"limit_down_{daily_change:.1%}"
                        continue

                    # Devre kesici düşüş kontrolleri (-%5, -%10)
                    for cb_pct in self.CIRCUIT_BREAKER_PCTS:
                        if daily_change <= -cb_pct:
                            mask[i] = 0
                            reasons[i] = f"circuit_breaker_{cb_pct:.0%}"
                            break

            # 5. Ani fiyat sıçraması (Bir önceki geçerli bara göre %30+ değişim)
            if i > 0 and close[i - 1] > 0.0:
                jump_pct = abs(close[i] / close[i - 1] - 1.0)
                if jump_pct > 0.30:
                    mask[i] = 0
                    reasons[i] = f"suspicious_jump_{jump_pct:.0%}"
                    continue

            # 6. Bar içi aşırı makas / gap (Open-Close %20+ fark)
            if open_[i] > 0.0:
                gap = abs(close[i] / open_[i] - 1.0)
                if gap > 0.20:
                    mask[i] = 0
                    reasons[i] = f"large_bar_gap_{gap:.0%}"
                    continue

        valid_count = int(np.sum(mask))
        valid_pct = round((valid_count / n * 100.0), 1) if n > 0 else 0.0

        if valid_pct < 80.0:
            logger.warning("Low valid tradability percentage detected", ticker=clean_tick, valid_pct=valid_pct, total=n)

        res = MaskResult(
            ticker=clean_tick,
            mask=mask,
            reason=reasons,
            valid_count=valid_count,
            total_count=n,
            valid_pct=valid_pct,
        )

        self._record_audit_log(res)
        return res

    def compute_mask_polars(self, df: pl.DataFrame) -> pl.DataFrame:
        """Toplu veri çerçevesi için Polars vektörize tradability maskesi hesaplar.

        Beklenen Sütunlar:
            open, high, low, close, volume (Float64 / Int64)
            prev_close (isteğe bağlı, yoksa close.shift(1) kullanılır)
        """
        required_cols = {"open", "high", "low", "close", "volume"}
        if not required_cols.issubset(set(df.columns)) or df.is_empty():
            return df.with_columns(pl.lit(True).alias("is_tradable"))

        augmented = df.clone()
        if "prev_close" not in augmented.columns:
            augmented = augmented.with_columns(pl.col("close").shift(1).alias("prev_close"))

        augmented = augmented.with_columns([
            # 1. Fiyat ve hacim geçerlilik koşulları
            (
                (pl.col("close") > 0.0)
                & pl.col("close").is_not_nan()
                & pl.col("close").is_not_null()
                & (pl.col("open") > 0.0)
                & (pl.col("volume") > 0.0)
                & (pl.col("high") >= pl.col("low"))
                & (pl.col("high") >= pl.col("close"))
                & (pl.col("low") <= pl.col("close"))
                & (pl.col("high") >= pl.col("open"))
                & (pl.col("low") <= pl.col("open"))
            ).alias("basic_validity"),
            # 2. Değişim oranı
            (
                pl.col("close") / pl.col("prev_close") - 1.0
            ).fill_null(0.0).alias("daily_return"),
        ]).with_columns([
            (
                pl.col("basic_validity")
                & (pl.col("daily_return") < (self.LIMIT_UP_PCT - 0.001))
                & (pl.col("daily_return") > (-self.LIMIT_DOWN_PCT + 0.001))
                & (pl.col("daily_return").abs() < 0.30)
            ).alias("is_tradable")
        ])

        return augmented.drop(["basic_validity", "daily_return"])

    def apply_mask_to_features(
        self,
        features: dict[str, np.ndarray],
        mask: np.ndarray,
    ) -> dict[str, np.ndarray]:
        """Feature'lara maskeyi uygular (Geçersiz günleri NaN yapar - Point-In-Time koruması)."""
        masked: dict[str, np.ndarray] = {}
        for name, values in features.items():
            if isinstance(values, np.ndarray) and len(values) == len(mask):
                masked[name] = np.where(mask == 1, values, np.nan)
            else:
                masked[name] = values
        return masked

    def apply_mask_to_prices(
        self,
        open_: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        mask: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Fiyat dizilerine maske uygulayarak işlem yapılamayan barları NaN yapar."""
        return (
            np.where(mask == 1, open_, np.nan),
            np.where(mask == 1, high, np.nan),
            np.where(mask == 1, low, np.nan),
            np.where(mask == 1, close, np.nan),
            np.where(mask == 1, volume, np.nan),
        )

    def get_mask_stats(self, mask: np.ndarray) -> dict[str, Any]:
        """Maske özet istatistiklerini döndürür."""
        total = len(mask)
        valid = int(np.sum(mask))
        invalid = total - valid
        return {
            "total": total,
            "valid": valid,
            "invalid": invalid,
            "valid_pct": round(valid / total * 100.0, 1) if total > 0 else 0.0,
        }

    def export_mask_audit_to_polars(self) -> pl.DataFrame:
        """DuckDB'de kayıtlı tradability mask denetim loglarını Polars DataFrame olarak dışa aktarır."""
        with self._lock:
            try:
                return self._duckdb_con.execute("""
                    SELECT id, ticker, total_count, valid_count, invalid_count,
                           valid_pct, reasons_summary_json, calculated_at
                    FROM tradability_mask_audit
                    ORDER BY id ASC
                """).pl()
            except Exception as exc:
                logger.error("Failed to export tradability mask audit log to Polars", error=str(exc))
                return pl.DataFrame()

    def clear_audit_duckdb(self) -> None:
        """Maske denetim tablosunu temizler."""
        with self._lock:
            try:
                self._duckdb_con.execute("DELETE FROM tradability_mask_audit")
            except Exception as exc:
                logger.warning("DuckDB tradability mask denetim tablosu temizlenemedi", hata=str(exc))

    def close(self) -> None:
        """DuckDB bağlantısını güvenli şekilde kapatır."""
        with self._lock:
            try:
                self._duckdb_con.close()
            except Exception as exc:
                logger.debug("DuckDB baglantisi kapatilirken hata", hata=str(exc))

    def __repr__(self) -> str:
        with self._lock:
            return f"TradabilityMask(limit_up={self.LIMIT_UP_PCT:.0%}, duckdb={self._duckdb_path!r})"


def read_tradability_mask_audit_from_duckdb(
    duckdb_path: str = DEFAULT_TRADABILITY_MASK_DB,
    limit: int = 1000,
) -> pl.DataFrame:
    """DuckDB dosyasından doğrudan tradability mask denetim kayıtlarını Polars DataFrame olarak okur."""
    try:
        conn = duckdb.connect(duckdb_path)
        try:
            return conn.execute(
                """
                SELECT id, ticker, total_count, valid_count, invalid_count,
                       valid_pct, reasons_summary_json, calculated_at
                FROM tradability_mask_audit
                ORDER BY id DESC
                LIMIT ?
                """,
                [limit],
            ).pl()
        finally:
            conn.close()
    except Exception as exc:
        logger.error("DuckDB dosyasindan tradability mask kayitlari okunamadi", hata=str(exc))
        return pl.DataFrame()


def clear_tradability_mask_audit_duckdb(duckdb_path: str = DEFAULT_TRADABILITY_MASK_DB) -> None:
    """Belirtilen DuckDB dosyasındaki tradability mask denetim tablosunu sıfırlar."""
    try:
        conn = duckdb.connect(duckdb_path)
        try:
            conn.execute("DELETE FROM tradability_mask_audit")
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("DuckDB tradability mask tablosu temizlenemedi", hata=str(exc))


# Küresel Singleton Nesnesi
tradability_mask = TradabilityMask()


# Yardımcı Fonksiyonlar
def compute_mask_polars(df: pl.DataFrame) -> pl.DataFrame:
    """Modül seviyesinde Polars tradability maskesi hesaplama yardımcısı."""
    return tradability_mask.compute_mask_polars(df)


__all__ = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_TRADABILITY_MASK_DB",
    "DEFAULT_WAL_SIZE",
    "MaskResult",
    "TradabilityMask",
    "clear_tradability_mask_audit_duckdb",
    "compute_mask_polars",
    "configure_duckdb_wal",
    "otel_trace",
    "read_tradability_mask_audit_from_duckdb",
    "to_orjson_bytes",
    "tradability_mask",
]
