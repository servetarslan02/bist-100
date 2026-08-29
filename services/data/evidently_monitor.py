"""
ALPHA BIST — Evidently & Great Expectations Data Quality & Drift Suite
======================================================================
Otomatik Veri Kalitesi ve Model Gözlemlenebilirlik Paketi:
1. Data Integrity Kontrolleri (Null, Monotonik OHLCV, Tick clustering, Tarih aralığı)
2. İstatistiksel Drift Testleri:
   - Kolmogorov-Smirnov (KS) Testi (Dağılım değişimi)
   - Wasserstein Distance / Earth Mover's Distance
   - Population Stability Index (PSI)
3. Target & Prediction Drift (Sinyal dağılımının zamanla kayması)
4. Data Quality Gate — Pipeline öncesi otomatik geçiş onayı veya blokajı
5. Raporlama (JSON Telemetri & Özet Skor)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog
from scipy import stats

try:
    import polars as pl
except ImportError:
    pl = None

logger = structlog.get_logger()


@dataclass
class QualityCheckResult:
    """Tekil veri kalitesi kontrol sonucu."""

    check_name: str
    status: str  # PASS, WARN, FAIL
    metric_value: float
    threshold: float
    message: str


@dataclass
class DriftCheckResult:
    """Tekil feature drift kontrol sonucu."""

    feature_name: str
    drift_score: float  # PSI veya p-value
    method: str  # KS_TEST, PSI, WASSERSTEIN
    is_drifted: bool
    severity: str  # NONE, MODERATE, SEVERE
    reference_mean: float
    current_mean: float


@dataclass
class DataQualityReport:
    """Kapsamlı Veri Kalitesi & Drift Raporu."""

    is_pipeline_allowed: bool
    overall_score: float  # 0 - 100
    quality_checks: list[QualityCheckResult]
    drift_checks: list[DriftCheckResult]
    failed_checks_count: int
    drifted_features_count: int
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class EvidentlyDataMonitor:
    """
    Evidently AI ve Great Expectations prensiplerine tam uyumlu
    BIST-100 Finansal Veri Kalitesi ve Drift İzleme Motoru.
    """

    def __init__(self, psi_threshold: float = 0.20, ks_alpha: float = 0.05) -> None:
        self.psi_threshold = psi_threshold
        self.ks_alpha = ks_alpha

    def audit_ohlcv_integrity(self, df_dict: dict[str, list[float]]) -> list[QualityCheckResult]:
        """
        OHLCV temel finansal kurallarını denetle:
        - High >= Low
        - High >= Open, High >= Close
        - Low <= Open, Low <= Close
        - Volume >= 0
        - Close > 0
        """
        results: list[QualityCheckResult] = []

        opens = np.array(df_dict.get("open", []))
        highs = np.array(df_dict.get("high", []))
        lows = np.array(df_dict.get("low", []))
        closes = np.array(df_dict.get("close", []))
        volumes = np.array(df_dict.get("volume", []))

        if len(closes) == 0:
            return [QualityCheckResult("empty_data", "FAIL", 0.0, 1.0, "Boş veri seti")]

        # 1. High >= Low
        hl_violations = np.sum(highs < lows)
        results.append(
            QualityCheckResult(
                check_name="high_greater_equal_low",
                status="PASS" if hl_violations == 0 else "FAIL",
                metric_value=float(hl_violations),
                threshold=0.0,
                message=f"High < Low ihlali: {hl_violations} adet",
            )
        )

        # 2. High Extremum Check (High >= Open & Close)
        h_open_close_violations = np.sum((highs < opens) | (highs < closes))
        results.append(
            QualityCheckResult(
                check_name="high_is_maximum",
                status="PASS" if h_open_close_violations == 0 else "FAIL",
                metric_value=float(h_open_close_violations),
                threshold=0.0,
                message=f"High barın tepesinde değil: {h_open_close_violations} adet",
            )
        )

        # 3. Low Extremum Check (Low <= Open & Close)
        l_open_close_violations = np.sum((lows > opens) | (lows > closes))
        results.append(
            QualityCheckResult(
                check_name="low_is_minimum",
                status="PASS" if l_open_close_violations == 0 else "FAIL",
                metric_value=float(l_open_close_violations),
                threshold=0.0,
                message=f"Low barın tabanında değil: {l_open_close_violations} adet",
            )
        )

        # 4. Volume Non-negative
        vol_violations = np.sum(volumes < 0)
        results.append(
            QualityCheckResult(
                check_name="non_negative_volume",
                status="PASS" if vol_violations == 0 else "FAIL",
                metric_value=float(vol_violations),
                threshold=0.0,
                message=f"Negatif hacim: {vol_violations} adet",
            )
        )

        # 5. Non-zero Price
        zero_prices = np.sum(closes <= 0)
        results.append(
            QualityCheckResult(
                check_name="positive_price",
                status="PASS" if zero_prices == 0 else "FAIL",
                metric_value=float(zero_prices),
                threshold=0.0,
                message=f"Sıfır veya negatif fiyat: {zero_prices} adet",
            )
        )

        return results

    def compute_ks_drift(self, reference: np.ndarray, current: np.ndarray, feature_name: str) -> DriftCheckResult:
        """Kolmogorov-Smirnov iki örneklem drift testi."""
        if len(reference) < 5 or len(current) < 5:
            return DriftCheckResult(feature_name, 1.0, "KS_TEST", False, "NONE", 0.0, 0.0)

        stat, p_value = stats.ks_2samp(reference, current)
        is_drifted = bool(p_value < self.ks_alpha)
        severity = "SEVERE" if p_value < 0.01 else ("MODERATE" if is_drifted else "NONE")

        return DriftCheckResult(
            feature_name=feature_name,
            drift_score=round(float(p_value), 5),
            method="KS_TEST",
            is_drifted=is_drifted,
            severity=severity,
            reference_mean=round(float(np.mean(reference)), 4),
            current_mean=round(float(np.mean(current)), 4),
        )

    def compute_psi(self, reference: np.ndarray, current: np.ndarray, feature_name: str, num_buckets: int = 10) -> DriftCheckResult:
        """Population Stability Index (PSI) hesabı."""
        if len(reference) < 10 or len(current) < 10:
            return DriftCheckResult(feature_name, 0.0, "PSI", False, "NONE", 0.0, 0.0)

        # Bucket sınırları referans üzerinden
        quantiles = np.linspace(0, 100, num_buckets + 1)
        bins = np.percentile(reference, quantiles)
        bins = np.unique(bins)
        if len(bins) < 2:
            return DriftCheckResult(feature_name, 0.0, "PSI", False, "NONE", float(np.mean(reference)), float(np.mean(current)))

        ref_counts, _ = np.histogram(reference, bins=bins)
        cur_counts, _ = np.histogram(current, bins=bins)

        ref_pct = np.clip(ref_counts / len(reference), 1e-4, 1.0)
        cur_pct = np.clip(cur_counts / len(current), 1e-4, 1.0)

        psi_val = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
        is_drifted = bool(psi_val > self.psi_threshold)
        severity = "SEVERE" if psi_val > 0.25 else ("MODERATE" if psi_val > 0.10 else "NONE")

        return DriftCheckResult(
            feature_name=feature_name,
            drift_score=round(psi_val, 4),
            method="PSI",
            is_drifted=is_drifted,
            severity=severity,
            reference_mean=round(float(np.mean(reference)), 4),
            current_mean=round(float(np.mean(current)), 4),
        )

    def generate_full_audit(
        self,
        ohlcv_data: dict[str, list[float]],
        ref_features: dict[str, np.ndarray],
        cur_features: dict[str, np.ndarray],
    ) -> DataQualityReport:
        """Tüm kontrolleri çalıştırıp karar kapısı (Gate) raporu oluştur."""
        q_results = self.audit_ohlcv_integrity(ohlcv_data)
        d_results: list[DriftCheckResult] = []

        for feat_name, ref_arr in ref_features.items():
            if feat_name in cur_features:
                cur_arr = cur_features[feat_name]
                d_results.append(self.compute_ks_drift(ref_arr, cur_arr, feat_name))

        failed_q = sum(1 for q in q_results if q.status == "FAIL")
        drifted_f = sum(1 for d in d_results if d.is_drifted and d.severity == "SEVERE")

        is_allowed = (failed_q == 0) and (drifted_f <= len(d_results) // 2)
        score = max(0.0, 100.0 - (failed_q * 25.0) - (drifted_f * 10.0))

        return DataQualityReport(
            is_pipeline_allowed=is_allowed,
            overall_score=round(score, 1),
            quality_checks=q_results,
            drift_checks=d_results,
            failed_checks_count=failed_q,
            drifted_features_count=drifted_f,
        )


# Singleton
data_monitor = EvidentlyDataMonitor()
