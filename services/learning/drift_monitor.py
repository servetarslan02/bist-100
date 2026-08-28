"""ALPHA BIST — Feature & Prediction Drift Monitor v1.0
Evidently-style istatistiksel veri kayması (drift) izleme motoru.

Özellikler:
1. Continuous değişkenler için Kolmogorov-Smirnov (KS) Testi.
2. Categorical/Prediction dağılımları için Population Stability Index (PSI).
3. OpenTelemetry/Prometheus ile native uyum (Gauge metric export).
"""

from __future__ import annotations

import numpy as np
from scipy import stats
import structlog
from opentelemetry import metrics
from dataclasses import dataclass
from typing import Sequence

logger = structlog.get_logger()

# OTel Meter
meter = metrics.get_meter("alpha.learning.drift")

# OTel Gauges for Monitoring
feature_drift_gauge = meter.create_gauge(
    name="alpha.ml.feature_drift",
    description="Feature drift indicator (KS p-value or PSI score)",
)

prediction_drift_gauge = meter.create_gauge(
    name="alpha.ml.prediction_drift",
    description="Prediction drift indicator (PSI score)",
)

@dataclass
class DriftResult:
    feature_name: str
    drift_score: float
    is_drifted: bool
    drift_type: str  # "KS" veya "PSI"
    threshold: float


class DataDriftMonitor:
    """İstatistiksel veri ve tahmin kayması (drift) ölçüm motoru."""

    def __init__(self, ks_threshold: float = 0.05, psi_threshold: float = 0.2):
        """
        Args:
            ks_threshold: KS test p-value eşiği (p < threshold ise drift var)
            psi_threshold: PSI eşiği (PSI > threshold ise drift var)
        """
        self.ks_threshold = ks_threshold
        self.psi_threshold = psi_threshold
        # Basit bellek içi referans (baseline) verisi
        self._reference_data: dict[str, np.ndarray] = {}

    def set_reference(self, feature_name: str, data: Sequence[float]) -> None:
        """Baseline (referans/eğitim) dağılımını ayarlar."""
        self._reference_data[feature_name] = np.asarray(data, dtype=np.float64)
        logger.debug("reference_distribution_set", feature=feature_name, n_samples=len(data))

    def check_continuous_drift(self, feature_name: str, current_data: Sequence[float]) -> DriftResult | None:
        """Sürekli değişkenler için Kolmogorov-Smirnov testi ile drift kontrolü."""
        if feature_name not in self._reference_data:
            return None
        
        ref_data = self._reference_data[feature_name]
        curr_data = np.asarray(current_data, dtype=np.float64)
        
        if len(ref_data) < 10 or len(curr_data) < 10:
            return None
        
        # KS Test
        statistic, p_value = stats.ks_2samp(ref_data, curr_data)
        is_drifted = bool(p_value < self.ks_threshold)
        
        # OTel'e metrik gönder (p-value, 0'a yakınsa kötü)
        feature_drift_gauge.set(float(p_value), {"feature": feature_name, "test": "KS"})
        
        if is_drifted:
            logger.warning(
                "feature_drift_detected",
                feature=feature_name,
                test="KS",
                p_value=p_value,
                statistic=statistic
            )
            
        return DriftResult(
            feature_name=feature_name,
            drift_score=float(p_value),
            is_drifted=is_drifted,
            drift_type="KS",
            threshold=self.ks_threshold
        )

    def compute_psi(self, expected: np.ndarray, actual: np.ndarray, buckets: int = 10) -> float:
        """Population Stability Index (PSI) hesaplar."""
        def build_buckets(data, breakpoints):
            # Verilen breakpoint'lere göre histogram oluştur ve yüzdelik oranları bul
            counts, _ = np.histogram(data, bins=breakpoints)
            return counts / max(1, len(data))

        # Referans veri üzerinden eşik (breakpoint) değerleri oluştur (Yüzdelikler)
        # Min ve Max arasına percentiles
        breakpoints = np.percentile(expected, np.linspace(0, 100, buckets + 1))
        # Uç değerleri güvene al
        breakpoints[0] = -np.inf
        breakpoints[-1] = np.inf
        
        expected_fractions = build_buckets(expected, breakpoints)
        actual_fractions = build_buckets(actual, breakpoints)
        
        # 0'a bölme ve log(0) hatasını engellemek için eps ekle
        eps = 1e-4
        expected_fractions = np.clip(expected_fractions, eps, 1.0)
        actual_fractions = np.clip(actual_fractions, eps, 1.0)
        
        psi_value = np.sum((actual_fractions - expected_fractions) * np.log(actual_fractions / expected_fractions))
        return float(psi_value)

    def check_prediction_drift(self, model_name: str, current_predictions: Sequence[float]) -> DriftResult | None:
        """Model çıktıları için Population Stability Index (PSI) ile drift kontrolü."""
        ref_key = f"pred_{model_name}"
        if ref_key not in self._reference_data:
            return None
            
        ref_data = self._reference_data[ref_key]
        curr_data = np.asarray(current_predictions, dtype=np.float64)
        
        if len(ref_data) < 20 or len(curr_data) < 20:
            return None
            
        psi_score = self.compute_psi(ref_data, curr_data)
        is_drifted = bool(psi_score > self.psi_threshold)
        
        # OTel metrik
        prediction_drift_gauge.set(psi_score, {"model": model_name, "test": "PSI"})
        
        if is_drifted:
            logger.warning(
                "prediction_drift_detected",
                model=model_name,
                test="PSI",
                psi_score=psi_score
            )
            
        return DriftResult(
            feature_name=model_name,
            drift_score=psi_score,
            is_drifted=is_drifted,
            drift_type="PSI",
            threshold=self.psi_threshold
        )

# Global Singleton
drift_monitor = DataDriftMonitor()
