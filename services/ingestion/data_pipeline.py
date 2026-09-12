"""
ALPHA BIST — Data Pipeline with Quality Gate

Ingestion → Data Quality v2 → Feature Engine → Scanner

Özellikler:
- Her veri akışında quality score
- Başarısız veri reddetme + sebep kaydı
- Audit trail
- Pipeline metrics

Kullanım:
    pipeline = DataPipeline()
    result = pipeline.process(market_data)
"""

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import polars as pl
import structlog

from ..core.data_quality import DataQualityChecker as DataQualityV2
from ..core.data_quality import QualityReport
from ..core.tradability_mask import TradabilityMask
from ..features.calculator import FeatureCalculator

logger = structlog.get_logger()

# FeatureEngine büyük harf sütun adları bekler (Close, High, vb.)
_FEATURE_COLS: dict[str, str] = {
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "volume": "Volume",
}


@dataclass
class PipelineResult:
    """Tek bir hisse için pipeline işlem sonucu.

    Attributes:
        ticker: Hisse sembolü.
        accepted: Veri kabul edildi mi.
        quality_report: Kalite kontrol raporu.
        features: Hesaplanan özellikler (kabul edildiyse).
        rejection_reason: Reddetme sebebi (reddedildiyse).
        processing_time_ms: İşlem süresi (milisaniye).
    """

    ticker: str
    accepted: bool
    quality_report: QualityReport | None
    features: dict[str, Any] | None
    rejection_reason: str = ""
    processing_time_ms: float = 0.0

    def __repr__(self) -> str:
        return (
            f"PipelineResult(ticker={self.ticker!r}, "
            f"accepted={self.accepted}, "
            f"reason={self.rejection_reason!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Sonucu sözlüğe dönüştürür.

        Returns:
            PipelineResult sözlük gösterimi.
        """
        return {
            "ticker": self.ticker,
            "accepted": self.accepted,
            "quality_score": self.quality_report.quality_score if self.quality_report else 0,
            "features_count": len(self.features) if self.features else 0,
            "rejection_reason": self.rejection_reason,
            "processing_time_ms": round(self.processing_time_ms, 2),
        }


@dataclass
class PipelineReport:
    """Toplu pipeline işlem raporu.

    Attributes:
        total: Toplam işlenen hisse sayısı.
        accepted: Kabul edilen hisse sayısı.
        rejected: Reddedilen hisse sayısı.
        avg_quality_score: Ortalama kalite puanı.
        results: Tüm PipelineResult listesi.
        audit_log: Denetim kayıtları.
        elapsed_s: Toplam işlem süresi (saniye).
    """

    total: int
    accepted: int
    rejected: int
    avg_quality_score: float
    results: list[PipelineResult]
    audit_log: list[dict[str, Any]]
    elapsed_s: float

    def __repr__(self) -> str:
        return (
            f"PipelineReport(total={self.total}, "
            f"accepted={self.accepted}, "
            f"rejected={self.rejected}, "
            f"avg_quality={self.avg_quality_score:.1f})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Raporu sözlüğe dönüştürür.

        Returns:
            PipelineReport sözlük gösterimi.
        """
        return {
            "total": self.total,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "acceptance_rate": round(self.accepted / max(self.total, 1) * 100, 1),
            "avg_quality_score": round(self.avg_quality_score, 1),
            "elapsed_s": round(self.elapsed_s, 2),
            "rejection_reasons": self._count_rejections(),
        }

    def _count_rejections(self) -> dict[str, int]:
        """Reddetme sebeplerini sayar.

        Returns:
            {sebep: sayı} sözlüğü.
        """
        reasons: dict[str, int] = {}
        for r in self.results:
            if not r.accepted and r.rejection_reason:
                reasons[r.rejection_reason] = reasons.get(r.rejection_reason, 0) + 1
        return reasons


class DataPipeline:
    """Data Quality Gate ile veri pipeline.

    Veriyi kalite kontrolünden geçirir, özellik hesaplar
    ve audit kaydı tutar.

    Args:
        min_quality_score: Kabul için minimum kalite puanı.
        require_passing: Kalite kontrol geçme zorunluluğu.
    """

    def __init__(
        self,
        min_quality_score: float = 70.0,
        require_passing: bool = True,
    ) -> None:
        """DataPipeline örneği oluşturur.

        Args:
            min_quality_score: Kabul için minimum kalite puanı (0-100).
            require_passing: Kalite kontrol geçme zorunluluğu.
        """
        self._dq = DataQualityV2()
        self._calc = FeatureCalculator()
        self._tm = TradabilityMask()
        self._min_quality_score = min_quality_score
        self._require_passing = require_passing
        self._audit_log: list[dict[str, Any]] = []

    def process(self, market_data: dict[str, pl.DataFrame]) -> PipelineReport:
        """Tüm market verisini işler.

        Args:
            market_data: {ticker: DataFrame} sözlüğü.

        Returns:
            PipelineReport: Toplu işlem raporu.
        """
        start = time.time()
        results: list[PipelineResult] = []
        quality_scores: list[float] = []

        for ticker, df in market_data.items():
            result = self._process_single(ticker, df)
            results.append(result)
            if result.quality_report:
                quality_scores.append(result.quality_report.quality_score)

        elapsed = time.time() - start
        accepted = sum(1 for r in results if r.accepted)
        avg_score = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0

        return PipelineReport(
            total=len(results),
            accepted=accepted,
            rejected=len(results) - accepted,
            avg_quality_score=avg_score,
            results=results,
            audit_log=self._audit_log[-100:],
            elapsed_s=elapsed,
        )

    def _process_single(self, ticker: str, df: pl.DataFrame) -> PipelineResult:
        """Tek bir hisseyi işler.

        Args:
            ticker: Hisse sembolü.
            df: OHLCV Polars DataFrame.

        Returns:
            PipelineResult: İşlem sonucu.
        """
        start = time.time()

        # 1. Data Quality kontrolü
        quality = self._dq.full_quality_check(df, ticker)

        # 2. Quality gate — passed kontrolü
        if self._require_passing and not quality.passed:
            reason = self._get_primary_rejection_reason(quality)
            self._add_audit(ticker, "rejected", reason, quality.quality_score)
            return PipelineResult(
                ticker=ticker,
                accepted=False,
                quality_report=quality,
                features=None,
                rejection_reason=reason,
                processing_time_ms=(time.time() - start) * 1000,
            )

        # 3. Quality gate — minimum puan kontrolü
        if quality.quality_score < self._min_quality_score:
            reason = f"quality_score={quality.quality_score:.0f} < {self._min_quality_score}"
            self._add_audit(ticker, "rejected", reason, quality.quality_score)
            return PipelineResult(
                ticker=ticker,
                accepted=False,
                quality_report=quality,
                features=None,
                rejection_reason=reason,
                processing_time_ms=(time.time() - start) * 1000,
            )

        # 4. Sütun adlarını çöz (FeatureEngine büyük harf bekler)
        col_map = self._resolve_columns(df)

        # 5. Feature hesaplama
        try:
            mask = self._tm.compute_mask(
                ticker,
                df[col_map["open"]].to_numpy(),
                df[col_map["high"]].to_numpy(),
                df[col_map["low"]].to_numpy(),
                df[col_map["close"]].to_numpy(),
                df[col_map["volume"]].to_numpy(),
            )
            # FeatureEngine büyük harf sütun adları bekler — DataFrame'i doğrudan geç
            features = self._calc.compute_all_features(df, mask=mask.mask, ticker=ticker)

            if not features:
                self._add_audit(ticker, "rejected", "features_empty", quality.quality_score)
                return PipelineResult(
                    ticker=ticker,
                    accepted=False,
                    quality_report=quality,
                    features=None,
                    rejection_reason="features_empty",
                    processing_time_ms=(time.time() - start) * 1000,
                )

            self._add_audit(ticker, "accepted", "", quality.quality_score)
            return PipelineResult(
                ticker=ticker,
                accepted=True,
                quality_report=quality,
                features=features,
                processing_time_ms=(time.time() - start) * 1000,
            )

        except Exception as exc:
            logger.error("Feature hesaplama hatası", ticker=ticker, error=str(exc))
            self._add_audit(ticker, "error", str(exc), quality.quality_score)
            return PipelineResult(
                ticker=ticker,
                accepted=False,
                quality_report=quality,
                features=None,
                rejection_reason=f"feature_error: {exc}",
                processing_time_ms=(time.time() - start) * 1000,
            )

    def _resolve_columns(self, df: pl.DataFrame) -> dict[str, str]:
        """DataFrame sütun adlarını büyük/küçük harf uyumuyla çözer.

        FeatureEngine büyük harf (Close, High, vb.) bekler.
        Bu method, numpy çıkışı için eşleme sağlar.

        Args:
            df: Polars DataFrame.

        Returns:
            {küçük_harf_ad: gerçek_sütun_adı} sözlüğü.

        Raises:
            ValueError: Zorunlu sütun bulunamazsa.
        """
        cols_lower = {c.lower(): c for c in df.columns}
        mapping: dict[str, str] = {}
        for expected_lower, expected_upper in _FEATURE_COLS.items():
            # Önce büyük harfi dene, sonra küçük harfi
            if expected_upper in df.columns:
                mapping[expected_lower] = expected_upper
            elif expected_lower in cols_lower:
                mapping[expected_lower] = cols_lower[expected_lower]
            else:
                raise ValueError(
                    f"DataFrame'de '{expected_upper}' sütunu bulunamıyor. Mevcut: {df.columns}"
                )
        return mapping

    def _get_primary_rejection_reason(self, quality: QualityReport) -> str:
        """Birincil reddetme sebebini bulur.

        Args:
            quality: Kalite raporu.

        Returns:
            Reddetme sebebi string'i.
        """
        critical = [i for i in quality.issues if i.severity == "CRITICAL"]
        if critical:
            return f"{critical[0].check}: {critical[0].message}"
        warnings = [i for i in quality.issues if i.severity == "WARNING"]
        if warnings:
            return f"{warnings[0].check}: {warnings[0].message}"
        return "quality_failed"

    def _add_audit(self, ticker: str, action: str, reason: str, quality_score: float) -> None:
        """Audit kaydı ekler.

        Args:
            ticker: Hisse sembolü.
            action: İşlem türü ("accepted", "rejected", "error").
            reason: Reddetme sebebi.
            quality_score: Kalite puanı.
        """
        self._audit_log.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "ticker": ticker,
                "action": action,
                "reason": reason,
                "quality_score": round(quality_score, 1),
            }
        )
        if len(self._audit_log) > 1000:
            self._audit_log = self._audit_log[-1000:]


# Singleton
data_pipeline = DataPipeline()


__all__ = [
    "PipelineResult",
    "PipelineReport",
    "DataPipeline",
    "data_pipeline",
]
