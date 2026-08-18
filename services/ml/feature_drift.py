"""ALPHA BIST — Feature Drift Detector (Nihai).

SHAP history tracking, PSI (Population Stability Index),
feature importance trend analizi.
"""
import numpy as np
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class DriftReport:
    """Drift tespit raporu."""
    feature_name: str
    psi: float
    drift_detected: bool
    importance_trend: str  # increasing, decreasing, stable
    current_importance: float
    historical_importance: float
    alert: bool


class FeatureDriftDetector:
    """Feature drift tespiti — PSI + SHAP history."""

    def __init__(
        self,
        psi_threshold: float = 0.2,
        importance_change_threshold: float = 0.3,
        n_bins: int = 10,
    ):
        self.psi_threshold = psi_threshold
        self.importance_change_threshold = importance_change_threshold
        self.n_bins = n_bins
        self._shap_history: List[Dict[str, float]] = []  # [{feature: importance}]
        self._feature_distributions: List[Dict[str, np.ndarray]] = []

    def record_shap(self, shap_values: Dict[str, float]):
        """SHAP importance kaydet."""
        self._shap_history.append({
            **shap_values,
            "_timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def record_distribution(self, feature_data: Dict[str, np.ndarray]):
        """Feature dağılımı kaydet (PSI hesaplama için)."""
        self._feature_distributions.append(feature_data)

    def check_drift(self) -> List[DriftReport]:
        """Tüm feature'lar için drift kontrolü."""
        reports = []

        if len(self._shap_history) < 2:
            return reports

        # SHAP-based drift
        current_shap = self._shap_history[-1]
        historical_shap = self._shap_history[:-1]

        for feature in current_shap:
            if feature.startswith("_"):
                continue

            current_imp = current_shap.get(feature, 0)
            historical_imps = [h.get(feature, 0) for h in historical_shap if feature in h]

            if not historical_imps:
                continue

            hist_mean = float(np.mean(historical_imps))
            hist_std = float(np.std(historical_imps)) if len(historical_imps) > 1 else 0.01

            # Importance trend
            if len(historical_imps) >= 3:
                recent = np.mean(historical_imps[-3:])
                older = np.mean(historical_imps[:-3]) if len(historical_imps) > 3 else recent
                if recent > older * (1 + self.importance_change_threshold):
                    trend = "increasing"
                elif recent < older * (1 - self.importance_change_threshold):
                    trend = "decreasing"
                else:
                    trend = "stable"
            else:
                trend = "stable"

            # PSI (simplified)
            psi = abs(current_imp - hist_mean) / max(hist_std, 0.01)

            alert = psi > self.psi_threshold or trend != "stable"

            reports.append(DriftReport(
                feature_name=feature,
                psi=round(float(psi), 4),
                drift_detected=psi > self.psi_threshold,
                importance_trend=trend,
                current_importance=round(float(current_imp), 4),
                historical_importance=round(hist_mean, 4),
                alert=alert,
            ))

        # PSI-based drift (distribution shift)
        if len(self._feature_distributions) >= 2:
            current_dist = self._feature_distributions[-1]
            reference_dist = self._feature_distributions[0]

            for feature in current_dist:
                if feature in reference_dist:
                    psi = self._calculate_psi(reference_dist[feature], current_dist[feature])
                    if psi > self.psi_threshold:
                        # Distribution drift detected
                        existing = next((r for r in reports if r.feature_name == feature), None)
                        if existing:
                            existing.psi = round(float(psi), 4)
                            existing.drift_detected = True
                            existing.alert = True

        return reports

    def _calculate_psi(self, reference: np.ndarray, current: np.ndarray) -> float:
        """PSI (Population Stability Index) hesapla."""
        try:
            # Bin'ler oluştur
            min_val = min(reference.min(), current.min())
            max_val = max(reference.max(), current.max())
            bins = np.linspace(min_val, max_val, self.n_bins + 1)

            ref_hist, _ = np.histogram(reference, bins=bins)
            cur_hist, _ = np.histogram(current, bins=bins)

            # Normalize (0'dan kaçınmak için +epsilon)
            eps = 1e-6
            ref_pct = ref_hist / max(len(reference), 1) + eps
            cur_pct = cur_hist / max(len(current), 1) + eps

            # PSI
            psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
            return psi
        except Exception:
            return 0.0

    def get_alerts(self) -> List[DriftReport]:
        """Sadece alarm olan drift'leri döndür."""
        return [r for r in self.check_drift() if r.alert]

    def get_history(self) -> List[Dict[str, Any]]:
        """SHAP history döndür."""
        return self._shap_history
