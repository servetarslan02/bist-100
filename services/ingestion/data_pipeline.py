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
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

from ..core.data_quality import DataQualityChecker as DataQualityV2, QualityReport
from ..features.calculator import FeatureCalculator
from ..core.tradability_mask import TradabilityMask

logger = structlog.get_logger()


@dataclass
class PipelineResult:
    ticker: str
    accepted: bool
    quality_report: Optional[QualityReport]
    features: Optional[Dict[str, Any]]
    rejection_reason: str = ""
    processing_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
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
    total: int
    accepted: int
    rejected: int
    avg_quality_score: float
    results: List[PipelineResult]
    audit_log: List[Dict[str, Any]]
    elapsed_s: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "acceptance_rate": round(self.accepted / max(self.total, 1) * 100, 1),
            "avg_quality_score": round(self.avg_quality_score, 1),
            "elapsed_s": round(self.elapsed_s, 2),
            "rejection_reasons": self._count_rejections(),
        }

    def _count_rejections(self) -> Dict[str, int]:
        reasons = {}
        for r in self.results:
            if not r.accepted and r.rejection_reason:
                reasons[r.rejection_reason] = reasons.get(r.rejection_reason, 0) + 1
        return reasons


class DataPipeline:
    """Data Quality Gate ile veri pipeline."""

    def __init__(
        self,
        min_quality_score: float = 70.0,
        require_passing: bool = True,
    ):
        self._dq = DataQualityV2()
        self._calc = FeatureCalculator()
        self._tm = TradabilityMask()
        self._min_quality_score = min_quality_score
        self._require_passing = require_passing
        self._audit_log: List[Dict[str, Any]] = []

    def process(self, market_data: Dict[str, pd.DataFrame]) -> PipelineReport:
        """Tüm market verisini işle."""
        start = time.time()
        results = []
        quality_scores = []

        for ticker, df in market_data.items():
            result = self._process_single(ticker, df)
            results.append(result)
            if result.quality_report:
                quality_scores.append(result.quality_report.quality_score)

        elapsed = time.time() - start
        accepted = sum(1 for r in results if r.accepted)

        return PipelineReport(
            total=len(results),
            accepted=accepted,
            rejected=len(results) - accepted,
            avg_quality_score=np.mean(quality_scores) if quality_scores else 0,
            results=results,
            audit_log=self._audit_log[-100:],
            elapsed_s=elapsed,
        )

    def _process_single(self, ticker: str, df: pd.DataFrame) -> PipelineResult:
        """Tek hisseyi işle."""
        start = time.time()

        # 1. Data Quality kontrolü
        quality = self._dq.full_quality_check(df, ticker)

        # 2. Quality gate
        if self._require_passing and not quality.passed:
            reason = self._get_primary_rejection_reason(quality)
            self._add_audit(ticker, "rejected", reason, quality.quality_score)
            return PipelineResult(
                ticker=ticker, accepted=False,
                quality_report=quality, features=None,
                rejection_reason=reason,
                processing_time_ms=(time.time() - start) * 1000,
            )

        if quality.quality_score < self._min_quality_score:
            reason = f"quality_score={quality.quality_score:.0f} < {self._min_quality_score}"
            self._add_audit(ticker, "rejected", reason, quality.quality_score)
            return PipelineResult(
                ticker=ticker, accepted=False,
                quality_report=quality, features=None,
                rejection_reason=reason,
                processing_time_ms=(time.time() - start) * 1000,
            )

        # 3. Feature hesaplama
        try:
            mask = self._tm.compute_mask(
                ticker, df['Open'].values, df['High'].values,
                df['Low'].values, df['Close'].values, df['Volume'].values,
            )
            features = self._calc.compute_all_features(df, mask=mask.mask, ticker=ticker)

            if not features:
                self._add_audit(ticker, "rejected", "features_empty", quality.quality_score)
                return PipelineResult(
                    ticker=ticker, accepted=False,
                    quality_report=quality, features=None,
                    rejection_reason="features_empty",
                    processing_time_ms=(time.time() - start) * 1000,
                )

            self._add_audit(ticker, "accepted", "", quality.quality_score)
            return PipelineResult(
                ticker=ticker, accepted=True,
                quality_report=quality, features=features,
                processing_time_ms=(time.time() - start) * 1000,
            )

        except Exception as e:
            self._add_audit(ticker, "error", str(e), quality.quality_score)
            return PipelineResult(
                ticker=ticker, accepted=False,
                quality_report=quality, features=None,
                rejection_reason=f"feature_error: {e}",
                processing_time_ms=(time.time() - start) * 1000,
            )

    def _get_primary_rejection_reason(self, quality: QualityReport) -> str:
        """Birincil reddetme sebebini bul."""
        critical = [i for i in quality.issues if i.severity == "CRITICAL"]
        if critical:
            return f"{critical[0].check}: {critical[0].message}"
        warnings = [i for i in quality.issues if i.severity == "WARNING"]
        if warnings:
            return f"{warnings[0].check}: {warnings[0].message}"
        return "quality_failed"

    def _add_audit(self, ticker: str, action: str, reason: str, quality_score: float):
        """Audit kaydı."""
        self._audit_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": ticker,
            "action": action,
            "reason": reason,
            "quality_score": round(quality_score, 1),
        })


# Singleton
data_pipeline = DataPipeline()
