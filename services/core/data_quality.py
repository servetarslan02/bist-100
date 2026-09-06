"""ALPHA BIST — Veri Kalitesi, Bütünlük Kontratları ve İşlem Görebilirlik Maskesi v3.0 (Data Quality & Tradability Mask)

F-024: Great Expectations tarzı Polars-native kontrat doğrulama motorudur.
Canlı piyasa akışında ve geçmiş veri DataFrame'lerinde BIST işlem ve mevzuat kurallarına
(devre kesici, tavan/taban limitleri, negatif/sıfır fiyatlar, OHLC geometrisi, hacim ve likidite)
göre veri kalitesini denetler.

Kritik Kural (K-01): Execute edilemeyen / anormal fiyat verisini modele veya canlı emre sokma!
TradabilityMask ile anormal hisseleri maskele, portföy ve karar motorunu koru.

Bileşenler:
1. Expectation Hiyerarşisi (Pozitif Fiyat, OHLC Geometrisi, Devre Kesici Limitleri, Likidite/Hacim Profili)
2. ExpectationsSuite (Çoklu kural çalıştırma, OpenTelemetry metrik sayacı)
3. DataQualityEngine (Hisse bazında canlı TradabilityMask üretimi ve ham veriye maske uygulama)
4. DataQualityChecker (Polars DataFrame tam kalite analizi: duplike tarih, gap, null sayımı, skorlama)
5. Polars ve DuckDB Analitik Raporlama Entegrasyonu
"""

from __future__ import annotations

import contextlib
import copy as _copy
import math
import threading
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import orjson
import polars as pl
import structlog
from opentelemetry import metrics

from services.core.constants import (
    BIST_MAX_DAILY_PRICE_LIMIT_PCT,
    MIN_VOLUME_FOR_TRADING,
)
from services.core.duckdb_store import configure_duckdb_wal
from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)
meter = metrics.get_meter("alpha.data.quality")

# =====================================================
# SABİTLER (DEFAULT CONSTANTS)
# =====================================================
DEFAULT_CIRCUIT_BREAKER_LIMIT_PCT: float = BIST_MAX_DAILY_PRICE_LIMIT_PCT  # %10.0 BIST tavan/taban
DEFAULT_INTRADAY_VOLATILITY_LIMIT_PCT: float = 15.0  # Gün içi aşırı volatilite sınırı (%15)
DEFAULT_MIN_VOLUME_THRESHOLD: float = float(MIN_VOLUME_FOR_TRADING)  # 1000 lot
DEFAULT_QUALITY_DUCKDB_PATH: str = "data/quality_audit.duckdb"
DEFAULT_QUALITY_AUDIT_TABLE: str = "bist_data_quality_audit"
DEFAULT_MAX_GAP_DAYS: int = 5

# OpenTelemetry Metrikleri
VIOLATIONS_COUNTER = meter.create_counter(
    "alpha.data.quality.violations.total",
    description="Toplam veri kalitesi kural ihlali sayısı",
)
QUALITY_SCORE_GAUGE = meter.create_gauge(
    "alpha.data.quality.score",
    description="Denetim başına genel veri kalitesi puanı (0-100)",
)


# =====================================================
# VERİ MODELLERİ (DATACLASSES)
# =====================================================
@dataclass(slots=True)
class TradabilityMask:
    """Hisse senedi anlık işlem görebilirlik (tradability) maske durumu.

    Attributes:
        ticker: BIST hisse kodu.
        timestamp: Maskeleme zaman damgası (UTC).
        is_tradable: Hisse işleme uygun mu?
        reasons: Uygunsuzluk veya uyarı gerekçeleri listesi.
        price_mask: Fiyat güven katsayısı (0.0: Güvensiz/işleme kapalı, 1.0: Tam güvenli).
        volume_mask: Hacim güven katsayısı (0.0: Sıfır hacim/halt, 1.0: Normal).
    """

    ticker: str
    timestamp: datetime
    is_tradable: bool
    reasons: list[str] = field(default_factory=list)
    price_mask: float = 1.0
    volume_mask: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return {
            "ticker": self.ticker,
            "timestamp": self.timestamp.isoformat(),
            "is_tradable": self.is_tradable,
            "reasons": list(self.reasons),
            "price_mask": float(self.price_mask),
            "volume_mask": float(self.volume_mask),
        }

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisi üretir."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        return (
            f"<TradabilityMask ticker={self.ticker} tradable={self.is_tradable} "
            f"price_mask={self.price_mask:.2f} vol_mask={self.volume_mask:.2f} "
            f"reasons={self.reasons[:2]}>"
        )


@dataclass(slots=True)
class ExpectationResult:
    """Tek bir kural doğrulamasının neticesi.

    Attributes:
        expectation_name: Doğrulanan kuralın adı.
        passed: Kural başarıyla geçti mi?
        details: Hata veya başarı açıklaması.
        severity: Önem derecesi ('CRITICAL', 'ERROR', 'WARNING', 'INFO').
        affected_rows: Kuraldan etkilenen satır adedi.
    """

    expectation_name: str
    passed: bool
    details: str
    severity: str = "ERROR"
    affected_rows: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return asdict(self)

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisi üretir."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        return (
            f"<ExpectationResult name='{self.expectation_name}' passed={self.passed} "
            f"severity={self.severity} affected={self.affected_rows}>"
        )


@dataclass(slots=True)
class QualityIssue:
    """Kalite kontrolünde tespit edilen aykırılık detayı.

    Attributes:
        check: Denetim adı.
        severity: Önem derecesi.
        message: Açıklayıcı Türkçe mesaj.
        details: Ek yapılandırılmış detaylar.
        affected_rows: Etkilenen satır sayısı.
    """

    check: str
    severity: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    affected_rows: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return asdict(self)

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        return f"<QualityIssue check='{self.check}' severity={self.severity} rows={self.affected_rows}>"


@dataclass(slots=True)
class QualityReport:
    """DataFrame bazlı veri kalitesi tam denetim raporu.

    Attributes:
        ticker: BIST hisse sembolü.
        total_rows: İncelenen toplam satır adedi.
        issues: Tespit edilen kalite kusurları listesi.
        quality_score: Genel kalite puanı (0.0 - 100.0).
        passed: Kritik kusur olmaksızın geçti mi?
    """

    ticker: str
    total_rows: int
    issues: list[QualityIssue] = field(default_factory=list)
    quality_score: float = 100.0
    passed: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return {
            "ticker": self.ticker,
            "total_rows": self.total_rows,
            "issues": [i.to_dict() for i in self.issues],
            "quality_score": float(self.quality_score),
            "passed": bool(self.passed),
        }

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisi üretir."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        return (
            f"<QualityReport ticker={self.ticker} score={self.quality_score:.1f} "
            f"passed={self.passed} issues_count={len(self.issues)} rows={self.total_rows}>"
        )


# =====================================================
# EXPECTATION SOYUT SINIFI VE KONTROL KURALLARI
# =====================================================
class Expectation(ABC):
    """Veri kalitesi kural taban soyut sınıfı (Expectation Base)."""

    def __repr__(self) -> str:
        """Kural metin temsili."""
        return f"<{self.__class__.__name__}>"

    @abstractmethod
    def get_name(self) -> str:
        """Kuralın tekil adını döndürür."""
        pass

    @abstractmethod
    def validate_row(self, data: dict[str, Any]) -> ExpectationResult:
        """Tekil satır veya anlık akış sözlüğü için kuralı doğrular."""
        pass

    @abstractmethod
    def validate_df(self, df: pl.DataFrame) -> ExpectationResult:
        """Toplu Polars DataFrame için kuralı vektörel olarak doğrular."""
        pass


class ExpectColumnValuesToBePositive(Expectation):
    """Fiyat ve sayısal sütunların kesinlikle pozitif (> 0) olmasını zorunlu kılan kural."""

    def __init__(self, columns: list[str]) -> None:
        """Başlatıcı.

        Args:
            columns: Pozitif olması gereken sütun isimleri.
        """
        self.columns = columns

    def __repr__(self) -> str:
        """Kural metin temsili."""
        return f"<ExpectColumnValuesToBePositive columns={self.columns}>"

    def get_name(self) -> str:
        """Kural adı."""
        return f"ExpectColumnValuesToBePositive({','.join(self.columns)})"

    def validate_row(self, data: dict[str, Any]) -> ExpectationResult:
        """Satır bazında sıfır veya negatif fiyat denetimi."""
        failed_cols: list[str] = []
        for col in self.columns:
            val = data.get(col)
            if val is not None:
                try:
                    f_val = float(val)
                    if not math.isfinite(f_val) or f_val <= 0.0:
                        failed_cols.append(col)
                except (ValueError, TypeError):
                    failed_cols.append(col)

        if failed_cols:
            return ExpectationResult(
                expectation_name=self.get_name(),
                passed=False,
                details=f"Sıfır veya negatif sütunlar tespit edildi: {','.join(failed_cols)}",
                severity="CRITICAL",
                affected_rows=len(failed_cols),
            )
        return ExpectationResult(self.get_name(), True, "OK", "INFO", 0)

    def validate_df(self, df: pl.DataFrame) -> ExpectationResult:
        """Polars DataFrame üzerinde pozitiflik denetimi."""
        if not isinstance(df, pl.DataFrame) or df.is_empty():
            return ExpectationResult(self.get_name(), True, "Boş veya geçersiz DataFrame", "INFO", 0)

        total_failed = 0
        failed_col_names: list[str] = []

        for col in self.columns:
            if col in df.columns:
                series = df[col]
                if series.dtype.is_numeric():
                    if series.dtype.is_float():
                        cond = (series <= 0.0) | series.is_null() | series.is_nan()
                    else:
                        cond = (series <= 0) | series.is_null()
                    invalid_count = int(cond.fill_null(False).sum() or 0)
                    if invalid_count > 0:
                        total_failed += invalid_count
                        failed_col_names.append(f"{col}({invalid_count})")

        passed = total_failed == 0
        details = f"Pozitiflik ihlali: {', '.join(failed_col_names)}" if not passed else "OK"
        return ExpectationResult(
            expectation_name=self.get_name(),
            passed=passed,
            details=details,
            severity="CRITICAL" if not passed else "INFO",
            affected_rows=total_failed,
        )


class ExpectOHLCGeometry(Expectation):
    """Bar geometrisini (High >= Low, High >= Open/Close, Low <= Open/Close) denetleyen kural."""

    def __repr__(self) -> str:
        """Kural metin temsili."""
        return "<ExpectOHLCGeometry>"

    def get_name(self) -> str:
        """Kural adı."""
        return "ExpectOHLCGeometry"

    def validate_row(self, data: dict[str, Any]) -> ExpectationResult:
        """Satır bazında OHLC geometri denetimi."""
        h = data.get("high")
        l_val = data.get("low")
        o = data.get("open_price", data.get("open"))
        c = data.get("close")

        if any(x is None for x in (h, l_val, o, c)):
            return ExpectationResult(self.get_name(), True, "Eksik OHLC verisi, kontrol atlandı", "INFO", 0)

        try:
            fh, fl, fo, fc = float(h), float(l_val), float(o), float(c)
        except (ValueError, TypeError):
            return ExpectationResult(self.get_name(), False, "Geçersiz sayısal OHLC formatı", "CRITICAL", 1)

        if not (math.isfinite(fh) and math.isfinite(fl) and math.isfinite(fo) and math.isfinite(fc)):
            return ExpectationResult(self.get_name(), False, "OHLC içinde NaN veya Sonsuz (Inf) değer", "CRITICAL", 1)

        if fh < fl or fo > fh or fo < fl or fc > fh or fc < fl:
            return ExpectationResult(
                expectation_name=self.get_name(),
                passed=False,
                details=f"Anormal fiyat yapısı (H={fh}, L={fl}, O={fo}, C={fc})",
                severity="CRITICAL",
                affected_rows=1,
            )

        return ExpectationResult(self.get_name(), True, "OK", "INFO", 0)

    def validate_df(self, df: pl.DataFrame) -> ExpectationResult:
        """Polars DataFrame üzerinde vektörel OHLC geometri denetimi."""
        if not isinstance(df, pl.DataFrame) or df.is_empty():
            return ExpectationResult(self.get_name(), True, "Boş veya geçersiz DataFrame", "INFO", 0)

        h_col = next((c for c in ("high", "High", "HIGH") if c in df.columns), None)
        l_col = next((c for c in ("low", "Low", "LOW") if c in df.columns), None)
        o_col = next((c for c in ("open", "Open", "OPEN", "open_price") if c in df.columns), None)
        c_col = next((c for c in ("close", "Close", "CLOSE") if c in df.columns), None)

        if not all((h_col, l_col, o_col, c_col)):
            return ExpectationResult(self.get_name(), True, "OHLC sütunları tam bulunamadı", "INFO", 0)

        condition = (
            (pl.col(h_col) < pl.col(l_col))
            | (pl.col(o_col) > pl.col(h_col))
            | (pl.col(o_col) < pl.col(l_col))
            | (pl.col(c_col) > pl.col(h_col))
            | (pl.col(c_col) < pl.col(l_col))
        )
        violations = int(df.select(condition.sum()).item() or 0)
        passed = violations == 0

        return ExpectationResult(
            expectation_name=self.get_name(),
            passed=passed,
            details=f"{violations} satırda OHLC geometrisi bozuk" if not passed else "OK",
            severity="CRITICAL" if not passed else "INFO",
            affected_rows=violations,
        )


class ExpectCircuitBreakerLimits(Expectation):
    """Günlük fiyat değişiminin BIST devre kesici ve tavan/taban sınırları içinde olduğunu denetler."""

    def __init__(self, limit_pct: float = DEFAULT_CIRCUIT_BREAKER_LIMIT_PCT) -> None:
        """Başlatıcı.

        Args:
            limit_pct: Maksimum izin verilen yüzde fiyat marjı (örn. %10.0).
        """
        self.limit_pct = max(1.0, float(limit_pct))

    def __repr__(self) -> str:
        """Kural metin temsili."""
        return f"<ExpectCircuitBreakerLimits limit_pct={self.limit_pct}%>"

    def get_name(self) -> str:
        """Kural adı."""
        return f"ExpectCircuitBreakerLimits(limit_pct={self.limit_pct}%)"

    def validate_row(self, data: dict[str, Any]) -> ExpectationResult:
        """Satır bazında tavan/taban aşımı denetimi."""
        c = data.get("close")
        p = data.get("prev_close")

        if c is not None and p is not None:
            try:
                fc, fp = float(c), float(p)
                if math.isfinite(fc) and math.isfinite(fp) and fp > 0.0:
                    pct_change = abs(fc / fp - 1.0) * 100.0
                    if pct_change > self.limit_pct + 0.1:  # Küçük tolerans payı
                        return ExpectationResult(
                            expectation_name=self.get_name(),
                            passed=False,
                            details=f"Tavan/taban sınırı aşıldı: %{pct_change:.2f} > %{self.limit_pct:.1f}",
                            severity="CRITICAL",
                            affected_rows=1,
                        )
            except (ValueError, TypeError, ZeroDivisionError):
                pass

        return ExpectationResult(self.get_name(), True, "OK", "INFO", 0)

    def validate_df(self, df: pl.DataFrame) -> ExpectationResult:
        """Polars DataFrame üzerinde vektörel tavan/taban marj denetimi."""
        if not isinstance(df, pl.DataFrame) or df.is_empty():
            return ExpectationResult(self.get_name(), True, "Boş veya geçersiz DataFrame", "INFO", 0)

        c_col = next((c for c in ("close", "Close", "CLOSE") if c in df.columns), None)
        if not c_col:
            return ExpectationResult(self.get_name(), True, "Close sütunu bulunamadı", "INFO", 0)

        # Eğer prev_close sütunu yoksa shift(1) ile oluştur
        if "prev_close" in df.columns:
            prev_series = pl.col("prev_close")
        else:
            prev_series = pl.col(c_col).shift(1)

        pct_change_expr = ((pl.col(c_col) / prev_series) - 1.0).abs() * 100.0
        condition = (prev_series > 0.0) & (pct_change_expr > (self.limit_pct + 0.1))

        violations = int(df.select(condition.fill_null(False).sum()).item() or 0)
        passed = violations == 0

        return ExpectationResult(
            expectation_name=self.get_name(),
            passed=passed,
            details=f"{violations} satırda tavan/taban sınırı aşıldı" if not passed else "OK",
            severity="CRITICAL" if not passed else "INFO",
            affected_rows=violations,
        )


class ExpectVolumeLiquidityProfile(Expectation):
    """Hacim ve likidite anomalilerini (sıfır hacim, halt, yetersiz likidite) denetleyen kural."""

    def __init__(self, min_volume: float = DEFAULT_MIN_VOLUME_THRESHOLD) -> None:
        """Başlatıcı.

        Args:
            min_volume: Minimum kabul edilebilir günlük işlem hacmi (lot).
        """
        self.min_volume = max(0.0, float(min_volume))

    def __repr__(self) -> str:
        """Kural metin temsili."""
        return f"<ExpectVolumeLiquidityProfile min_vol={self.min_volume:.0f}>"

    def get_name(self) -> str:
        """Kural adı."""
        return f"ExpectVolumeLiquidityProfile(min_vol={self.min_volume})"

    def validate_row(self, data: dict[str, Any]) -> ExpectationResult:
        """Satır bazında hacim ve likidite kontrolü."""
        vol = data.get("volume")
        if vol is not None:
            try:
                f_vol = float(vol)
                if not math.isfinite(f_vol) or f_vol < 0.0:
                    return ExpectationResult(self.get_name(), False, "Geçersiz/Negatif hacim", "CRITICAL", 1)

                if f_vol == 0.0:
                    h, l_val, c, o = (
                        data.get("high"),
                        data.get("low"),
                        data.get("close"),
                        data.get("open_price", data.get("open")),
                    )
                    if c is not None and c == o and c == h and c == l_val:
                        return ExpectationResult(
                            self.get_name(), False, "Sıfır hacim ve tahta durdurulmuş (Halt)", "CRITICAL", 1
                        )
                    return ExpectationResult(self.get_name(), False, "Sıfır hacim", "ERROR", 1)

                if 0.0 < f_vol < self.min_volume:
                    return ExpectationResult(
                        self.get_name(), False, f"Düşük likidite ({f_vol:.0f} < {self.min_volume:.0f})", "WARNING", 1
                    )
            except (ValueError, TypeError):
                return ExpectationResult(self.get_name(), False, "Hacim sayısal formata dönüştürülemedi", "ERROR", 1)

        return ExpectationResult(self.get_name(), True, "OK", "INFO", 0)

    def validate_df(self, df: pl.DataFrame) -> ExpectationResult:
        """Polars DataFrame üzerinde vektörel hacim ve likidite denetimi."""
        if not isinstance(df, pl.DataFrame) or df.is_empty():
            return ExpectationResult(self.get_name(), True, "Boş veya geçersiz DataFrame", "INFO", 0)

        v_col = next((c for c in ("volume", "Volume", "VOLUME") if c in df.columns), None)
        if not v_col:
            return ExpectationResult(self.get_name(), True, "Volume sütunu bulunamadı", "INFO", 0)

        zero_vol = int((df[v_col] == 0.0).sum() or 0)
        low_vol = int(((df[v_col] > 0.0) & (df[v_col] < self.min_volume)).sum() or 0)

        if zero_vol > 0:
            return ExpectationResult(
                expectation_name=self.get_name(),
                passed=False,
                details=f"{zero_vol} satırda sıfır hacim tespit edildi",
                severity="ERROR",
                affected_rows=zero_vol,
            )

        if low_vol > 0:
            return ExpectationResult(
                expectation_name=self.get_name(),
                passed=False,
                details=f"{low_vol} satırda düşük likidite tespit edildi",
                severity="WARNING",
                affected_rows=low_vol,
            )

        return ExpectationResult(self.get_name(), True, "OK", "INFO", 0)


# =====================================================
# EXPECTATIONS SUITE
# =====================================================
class ExpectationsSuite:
    """Veri kalitesi kurallarını toplayan, yöneten ve çalıştıran suit."""

    def __init__(self, name: str) -> None:
        """Başlatıcı.

        Args:
            name: Kural paketi adı.
        """
        self.name = name
        self.expectations: list[Expectation] = []

    def __repr__(self) -> str:
        """ExpectationsSuite metin temsili."""
        return f"<ExpectationsSuite name='{self.name}' rules_count={len(self.expectations)}>"

    def add_expectation(self, exp: Expectation) -> ExpectationsSuite:
        """Pakete yeni bir kural ekler.

        Args:
            exp: Eklenecek Expectation kuralı.

        Returns:
            Kendisi (akıcı arayüz zincirleme için).
        """
        self.expectations.append(exp)
        return self

    def validate_row(self, ticker: str, data: dict[str, Any]) -> list[ExpectationResult]:
        """Tekil satır verisini tüm kurallara karşı doğrular.

        Args:
            ticker: Hisse sembolü.
            data: Satır verisi sözlüğü.

        Returns:
            list[ExpectationResult]: Kural sonuçları listesi.
        """
        results: list[ExpectationResult] = []
        for exp in self.expectations:
            res = exp.validate_row(data)
            results.append(res)
            if not res.passed:
                VIOLATIONS_COUNTER.add(
                    1,
                    {"ticker": ticker, "expectation": res.expectation_name, "severity": res.severity},
                )
        return results

    def validate_df(self, ticker: str, df: pl.DataFrame) -> list[ExpectationResult]:
        """DataFrame verisini tüm kurallara karşı doğrular.

        Args:
            ticker: Hisse sembolü.
            df: Polars DataFrame.

        Returns:
            list[ExpectationResult]: Kural sonuçları listesi.
        """
        results: list[ExpectationResult] = []
        for exp in self.expectations:
            res = exp.validate_df(df)
            results.append(res)
            if not res.passed:
                VIOLATIONS_COUNTER.add(
                    res.affected_rows or 1,
                    {"ticker": ticker, "expectation": res.expectation_name, "severity": res.severity},
                )
        return results


def build_default_financial_suite() -> ExpectationsSuite:
    """BIST finansal kontratları için standart kural paketini oluşturur.

    Returns:
        ExpectationsSuite: Yapılandırılmış finansal kurallar suiti.
    """
    suite = ExpectationsSuite("BIST_Financial_Contracts_v3")
    suite.add_expectation(
        ExpectColumnValuesToBePositive(["close", "open_price", "high", "low", "open", "High", "Low", "Close"])
    )
    suite.add_expectation(ExpectOHLCGeometry())
    suite.add_expectation(ExpectCircuitBreakerLimits(DEFAULT_CIRCUIT_BREAKER_LIMIT_PCT))
    suite.add_expectation(ExpectVolumeLiquidityProfile(DEFAULT_MIN_VOLUME_THRESHOLD))
    return suite


# =====================================================
# DATA QUALITY & TRADABILITY ENGINE
# =====================================================
class DataQualityEngine:
    """Canlı hisse akışında veri kalitesini denetleyen ve TradabilityMask üreten motor."""

    def __init__(
        self,
        suite: ExpectationsSuite | None = None,
        duckdb_path: str | Path = DEFAULT_QUALITY_DUCKDB_PATH,
    ) -> None:
        """Başlatıcı.

        Args:
            suite: Kural paketi (varsayılan: build_default_financial_suite()).
            duckdb_path: Denetim kayıtları DuckDB veritabanı yolu.
        """
        self._masks: dict[str, TradabilityMask] = {}
        self.suite = suite or build_default_financial_suite()
        self._duckdb_path = Path(duckdb_path)
        self._lock = threading.RLock()

        logger.info("data_quality_engine_baslatildi", suite_name=self.suite.name)

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        with self._lock:
            return (
                f"<DataQualityEngine suite='{self.suite.name}' "
                f"masks_tracked={len(self._masks)} untradable={self.get_untradable_count()}>"
            )

    @otel_trace("data_quality.check_tradability")
    def check_tradability(
        self,
        ticker: str,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        prev_close: float,
        timestamp: datetime | None = None,
    ) -> TradabilityMask:
        """Hisse verisini denetleyip TradabilityMask durumunu üretir.

        Args:
            ticker: Hisse sembolü.
            open_price: Açılış fiyatı.
            high: En yüksek fiyat.
            low: En düşük fiyat.
            close: Kapanış/son fiyat.
            volume: İşlem hacmi (lot).
            prev_close: Önceki seans kapanış fiyatı.
            timestamp: İsteğe bağlı zaman damgası.

        Returns:
            TradabilityMask: İşlem görebilirlik maskesi.
        """
        data = {
            "open_price": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "prev_close": prev_close,
        }

        results = self.suite.validate_row(ticker, data)

        reasons: list[str] = []
        is_tradable = True
        price_mask = 1.0
        volume_mask = 1.0

        for res in results:
            if not res.passed:
                reasons.append(res.details)
                if res.severity == "CRITICAL":
                    is_tradable = False
                    price_mask = 0.0
                    if "Sıfır hacim" in res.details or "Halt" in res.details:
                        volume_mask = 0.0
                elif res.severity == "ERROR":
                    is_tradable = False
                    if "Sıfır hacim" in res.details:
                        volume_mask = 0.0
                    else:
                        price_mask = 0.0
                elif res.severity == "WARNING":
                    if "Düşük likidite" in res.details:
                        volume_mask = min(volume_mask, 0.5)

        # Aşırı gün içi volatilite kontrolü (%15 üzeri marj)
        if prev_close > 0.0 and math.isfinite(prev_close):
            intraday_range = (high - low) / prev_close * 100.0
            if math.isfinite(intraday_range) and intraday_range > DEFAULT_INTRADAY_VOLATILITY_LIMIT_PCT:
                reasons.append(f"Aşırı volatilite: %{intraday_range:.1f}")
                price_mask = min(price_mask, 0.3)

        mask = TradabilityMask(
            ticker=ticker,
            timestamp=timestamp or datetime.now(UTC),
            is_tradable=is_tradable,
            reasons=reasons if reasons else ["OK"],
            price_mask=price_mask,
            volume_mask=volume_mask,
        )

        with self._lock:
            self._masks[ticker] = mask

        if not is_tradable:
            logger.warning("hisse_isleme_uygun_degil_maskelendi", ticker=ticker, reasons=reasons)

        return mask

    @otel_trace("data_quality.apply_mask")
    def apply_mask(
        self,
        raw_data: dict[str, Any],
        mask: TradabilityMask,
        *,
        copy: bool = False,
    ) -> dict[str, Any]:
        """Ham piyasa veri sözlüğüne TradabilityMask filtrelerini uygular.

        Args:
            raw_data: Ham veri sözlüğü.
            mask: Uygulanacak TradabilityMask.
            copy: Derin kopyalama yapılsın mı?

        Returns:
            dict: Maskelenmiş veri sözlüğü.
        """
        data = _copy.deepcopy(raw_data) if copy else raw_data
        if mask.price_mask == 0.0:
            for col in ("open", "high", "low", "close", "open_price"):
                if col in data:
                    data[col] = None
        if mask.volume_mask == 0.0 and "volume" in data:
            data["volume"] = None
        return data

    def get_mask(self, ticker: str) -> TradabilityMask | None:
        """Hisseye ait son kayıtlı maskeyi döndürür."""
        with self._lock:
            return self._masks.get(ticker)

    def get_untradable_count(self) -> int:
        """İşleme uygun olmayan hisse sayısını döndürür."""
        with self._lock:
            return sum(1 for m in self._masks.values() if not m.is_tradable)

    def get_mask_stats(self) -> dict[str, Any]:
        """Tüm takip edilen hisselerin maskeleme istatistiklerini döndürür."""
        with self._lock:
            total = len(self._masks)
            untradable = sum(1 for m in self._masks.values() if not m.is_tradable)
            reasons: dict[str, int] = {}
            for m in self._masks.values():
                for r in m.reasons:
                    if r != "OK":
                        reasons[r] = reasons.get(r, 0) + 1

        return {
            "total_checked": total,
            "untradable": untradable,
            "tradable_pct": round((total - untradable) / total * 100.0, 1) if total else 0.0,
            "reasons_breakdown": reasons,
        }

    def export_masks_to_polars(self) -> pl.DataFrame:
        """Mevcut tüm hisse maskelerini Polars DataFrame olarak dışa aktarır."""
        with self._lock:
            masks = list(self._masks.values())

        schema = {
            "ticker": pl.Utf8,
            "timestamp": pl.Utf8,
            "is_tradable": pl.Boolean,
            "price_mask": pl.Float64,
            "volume_mask": pl.Float64,
            "reasons": pl.Utf8,
        }
        if not masks:
            return pl.DataFrame(schema=schema)

        data = [
            {
                "ticker": m.ticker,
                "timestamp": m.timestamp.isoformat(),
                "is_tradable": m.is_tradable,
                "price_mask": float(m.price_mask),
                "volume_mask": float(m.volume_mask),
                "reasons": orjson.dumps(m.reasons).decode("utf-8"),
            }
            for m in masks
        ]
        return pl.DataFrame(data, schema=schema)


# =====================================================
# DATA QUALITY CHECKER (DATAFRAME KONTROL MOTORU)
# =====================================================
class DataQualityChecker:
    """Polars DataFrame üzerinde tarih, null, gap ve kural denetimi yapan motor."""

    def __init__(self, suite: ExpectationsSuite | None = None) -> None:
        """Başlatıcı.

        Args:
            suite: Kural paketi (varsayılan: build_default_financial_suite()).
        """
        self.suite = suite or build_default_financial_suite()

    def __repr__(self) -> str:
        """DataQualityChecker metin temsili."""
        return f"<DataQualityChecker suite={self.suite!r}>"

    @otel_trace("data_quality.full_quality_check")
    def full_quality_check(self, df: pl.DataFrame, ticker: str = "UNKNOWN") -> QualityReport:
        """DataFrame için tam kalite kontrolü yapar ve puan üretir.

        Args:
            df: Denetlenecek Polars DataFrame.
            ticker: Hisse kodu.

        Returns:
            QualityReport: Kalite değerlendirme raporu.
        """
        issues: list[QualityIssue] = []
        total_rows = len(df) if isinstance(df, pl.DataFrame) else 0

        if total_rows == 0:
            return QualityReport(ticker=ticker, total_rows=0, issues=[], quality_score=0.0, passed=False)

        # 1. Expectations kurallarını çalıştır
        results = self.suite.validate_df(ticker, df)
        for res in results:
            if not res.passed:
                issues.append(
                    QualityIssue(
                        check=res.expectation_name,
                        severity=res.severity,
                        message=res.details,
                        affected_rows=res.affected_rows,
                    )
                )

        # 2. Tarih/Timestamp denetimleri
        date_col = next((c for c in ("date", "Date", "timestamp", "Timestamp", "time") if c in df.columns), None)

        if date_col is not None:
            # Duplike tarih kontrolü
            dup_count = int(df[date_col].is_duplicated().sum() or 0)
            if dup_count > 0:
                issues.append(
                    QualityIssue(
                        check="duplicate_dates",
                        severity="CRITICAL",
                        message=f"{dup_count} adet duplike tarih kaydı tespit edildi",
                        affected_rows=dup_count,
                    )
                )

            # Sıralama kontrolü
            if not df[date_col].is_sorted():
                issues.append(
                    QualityIssue(
                        check="unsorted_timestamps",
                        severity="WARNING",
                        message="Zaman damgası sıralı değil (artan sırada olmalıdır)",
                        affected_rows=total_rows,
                    )
                )

            # Büyük zaman boşluğu kontrolü (> 5 gün)
            if total_rows > 1:
                try:
                    date_series = df[date_col]
                    if date_series.dtype in (pl.Utf8, pl.String):
                        date_series = date_series.str.to_date(strict=False)
                    date_diffs = date_series.diff().dt.total_days()
                    large_gaps = int((date_diffs > DEFAULT_MAX_GAP_DAYS).sum() or 0)
                    if large_gaps > 0:
                        issues.append(
                            QualityIssue(
                                check="large_gaps",
                                severity="WARNING",
                                message=f"{large_gaps} adet >{DEFAULT_MAX_GAP_DAYS} gün zaman boşluğu tespit edildi",
                                affected_rows=large_gaps,
                            )
                        )
                except Exception:
                    logger.debug("tarih_araligi_fark_kontrolu_yapilamadi", ticker=ticker)

        # 3. Eksik değer (null/nan) denetimi
        checked_cols = ("close", "Close", "open", "Open", "high", "High", "low", "Low", "volume", "Volume")
        for col_name in checked_cols:
            if col_name in df.columns:
                missing = int(df[col_name].null_count())
                if missing > 0:
                    sev = "CRITICAL" if col_name.lower() == "close" else "WARNING"
                    issues.append(
                        QualityIssue(
                            check=f"missing_{col_name}",
                            severity=sev,
                            message=f"'{col_name}' sütununda {missing} adet eksik değer",
                            affected_rows=missing,
                        )
                    )

        # Skorlama formülü: 100 - (Kritik * 20) - (Hata * 10) - (Uyarı * 5)
        critical_cnt = sum(1 for i in issues if i.severity == "CRITICAL")
        error_cnt = sum(1 for i in issues if i.severity == "ERROR")
        warning_cnt = sum(1 for i in issues if i.severity == "WARNING")
        score = max(0.0, 100.0 - (critical_cnt * 20.0) - (error_cnt * 10.0) - (warning_cnt * 5.0))

        QUALITY_SCORE_GAUGE.set(score, {"ticker": ticker})

        return QualityReport(
            ticker=ticker,
            total_rows=total_rows,
            issues=issues,
            quality_score=score,
            passed=(critical_cnt == 0 and error_cnt == 0),
        )


# =====================================================
# MODÜL SEVİYESİNDE SINGLETON VE DUCKDB FONKSİYONLARI
# =====================================================
data_quality = DataQualityEngine()
data_quality_checker = DataQualityChecker()


def get_data_quality_engine() -> DataQualityEngine:
    """Merkezi DataQualityEngine tekil nesnesini döndürür."""
    return data_quality


def get_data_quality_checker() -> DataQualityChecker:
    """Merkezi DataQualityChecker tekil nesnesini döndürür."""
    return data_quality_checker


def check_tradability(
    ticker: str,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    prev_close: float,
    timestamp: datetime | None = None,
) -> TradabilityMask:
    """Hisse tradability durumunu hızlıca denetler."""
    return data_quality.check_tradability(
        ticker=ticker,
        open_price=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        prev_close=prev_close,
        timestamp=timestamp,
    )


def export_masks_to_polars() -> pl.DataFrame:
    """Mevcut hisse maskelerini Polars DataFrame olarak dışa aktarır."""
    return data_quality.export_masks_to_polars()


def export_quality_to_duckdb(
    db_path: str | Path = DEFAULT_QUALITY_DUCKDB_PATH,
    table_name: str = DEFAULT_QUALITY_AUDIT_TABLE,
) -> int:
    """Mevcut hisse maskelerini DuckDB tablosuna aktarır.

    Args:
        db_path: DuckDB veritabanı dosya yolu.
        table_name: Hedef tablo adı.

    Returns:
        int: Eklenen kayıt sayısı.
    """
    df = export_masks_to_polars()
    if df.is_empty():
        return 0

    path_obj = Path(db_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    if path_obj.exists() and path_obj.stat().st_size == 0:
        with contextlib.suppress(OSError):
            path_obj.unlink()

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.register("df_masks", df.to_arrow())
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM df_masks WHERE 1=0"
            )
            conn.execute(f"INSERT INTO {table_name} SELECT * FROM df_masks")
        return len(df)
    except Exception as e:
        logger.error("export_quality_to_duckdb_failed", error=str(e))
        return 0


def query_quality_duckdb(
    db_path: str | Path = DEFAULT_QUALITY_DUCKDB_PATH,
    table_name: str = DEFAULT_QUALITY_AUDIT_TABLE,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB üzerinden geçmiş veri kalitesi maskelerini sorgular.

    Args:
        db_path: DuckDB veritabanı yolu.
        table_name: Tablo adı.
        limit: Maksimum satır sayısı.

    Returns:
        pl.DataFrame: Sorgu sonucu.
    """
    schema = {
        "ticker": pl.Utf8,
        "timestamp": pl.Utf8,
        "is_tradable": pl.Boolean,
        "price_mask": pl.Float64,
        "volume_mask": pl.Float64,
        "reasons": pl.Utf8,
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

            query = f"SELECT * FROM {table_name} ORDER BY timestamp DESC LIMIT ?"
            arrow_res = conn.execute(query, [limit]).arrow()
            return pl.from_arrow(arrow_res)
    except Exception as e:
        logger.error("query_quality_duckdb_failed", error=str(e))
        return empty_df


__all__ = [
    "DEFAULT_CIRCUIT_BREAKER_LIMIT_PCT",
    "DEFAULT_INTRADAY_VOLATILITY_LIMIT_PCT",
    "DEFAULT_MAX_GAP_DAYS",
    "DEFAULT_MIN_VOLUME_THRESHOLD",
    "DEFAULT_QUALITY_AUDIT_TABLE",
    "DEFAULT_QUALITY_DUCKDB_PATH",
    "DataQualityChecker",
    "DataQualityEngine",
    "ExpectCircuitBreakerLimits",
    "ExpectColumnValuesToBePositive",
    "ExpectOHLCGeometry",
    "ExpectVolumeLiquidityProfile",
    "Expectation",
    "ExpectationResult",
    "ExpectationsSuite",
    "QualityIssue",
    "QualityReport",
    "TradabilityMask",
    "build_default_financial_suite",
    "check_tradability",
    "data_quality",
    "data_quality_checker",
    "export_masks_to_polars",
    "export_quality_to_duckdb",
    "get_data_quality_checker",
    "get_data_quality_engine",
    "query_quality_duckdb",
]
