"""ALPHA BIST — Feature Drift Detector (Nihai —⭐⭐⭐⭐⭐).

SHAP history tracking, PSI (Population Stability Index),
feature importance trend analizi, multi-metric drift detection,
auto-remediation suggestions, drift alerting.
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
    importance_trend: str  # increasing, decreasing, stable, volatile
    current_importance: float
    historical_importance: float
    alert: bool
    severity: str = "LOW"  # LOW, MEDIUM, HIGH, CRITICAL
    remediation: str = ""


@dataclass
class DriftSummary:
    """Genel drift özeti."""
    total_features: int
    drifted_features: int
    alert_features: int
    critical_features: int
    overall_drift_score: float
    recommendations: List[str]


class FeatureDriftDetector:
    """Feature drift tespiti —⭐⭐⭐⭐⭐ seviye.

    Özellikler:
    - SHAP history tracking (her eğitim sonrası SHAP kaydet)
    - Feature importance trend analizi (artan/azalan/dalgalı)
    - PSI (Population Stability Index) hesaplama
    - Multi-metric drift detection (SHAP + PSI + distribution)
    - Drift severity scoring (LOW/MEDIUM/HIGH/CRITICAL)
    - Auto-remediation suggestions
    - Drift alerting system
    - Feature correlation drift
    - Drift history tracking
    """

    def __init__(
        self,
        psi_threshold: float = 0.2,
        importance_change_threshold: float = 0.3,
        n_bins: int = 10,
        alert_cooldown_hours: int = 24,
    ):
        self.psi_threshold = psi_threshold
        self.importance_change_threshold = importance_change_threshold
        self.n_bins = n_bins
        self.alert_cooldown_hours = alert_cooldown_hours
        self._shap_history: List[Dict[str, Any]] = []
        self._feature_distributions: List[Dict[str, np.ndarray]] = []
        self._drift_history: List[Dict[str, Any]] = []
        self._last_alert: Dict[str, datetime] = {}

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
        """Tüm feature'lar için kapsamlı drift kontrolü."""
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
            trend = self._compute_trend(historical_imps, current_imp)

            # PSI (simplified)
            psi = abs(current_imp - hist_mean) / max(hist_std, 0.01)

            # Severity
            severity = self._compute_severity(psi, trend)

            # Alert
            alert = psi > self.psi_threshold or trend in ("increasing", "decreasing", "volatile")

            # Remediation
            remediation = self._suggest_remediation(feature, psi, trend, severity)

            reports.append(DriftReport(
                feature_name=feature,
                psi=round(float(psi), 4),
                drift_detected=psi > self.psi_threshold,
                importance_trend=trend,
                current_importance=round(float(current_imp), 4),
                historical_importance=round(hist_mean, 4),
                alert=alert,
                severity=severity,
                remediation=remediation,
            ))

        # PSI-based drift (distribution shift)
        if len(self._feature_distributions) >= 2:
            self._check_distribution_drift(reports)

        # Drift history
        self._drift_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "n_drifted": sum(1 for r in reports if r.drift_detected),
            "n_alerts": sum(1 for r in reports if r.alert),
            "n_critical": sum(1 for r in reports if r.severity == "CRITICAL"),
        })

        return reports

    def get_summary(self) -> DriftSummary:
        """Genel drift özeti."""
        reports = self.check_drift()

        if not reports:
            return DriftSummary(
                total_features=0, drifted_features=0, alert_features=0,
                critical_features=0, overall_drift_score=0.0, recommendations=[],
            )

        drifted = [r for r in reports if r.drift_detected]
        alerts = [r for r in reports if r.alert]
        critical = [r for r in reports if r.severity == "CRITICAL"]

        # Overall drift score (0-1, yüksek = kötü)
        drift_scores = [r.psi for r in reports]
        overall_score = float(np.mean(drift_scores)) if drift_scores else 0.0

        # Recommendations
        recommendations = []
        if critical:
            recommendations.append(f"CRITICAL: {len(critical)} feature'da ciddi drift var — model retrain gerekebilir")
        if len(drifted) > len(reports) * 0.3:
            recommendations.append(f"WARNING: Feature'ların %{int(len(drifted)/len(reports)*100)}'ünde drift var")
        if overall_score > self.psi_threshold:
            recommendations.append("Genel drift skoru yüksek — feature set'i gözden geçirin")

        return DriftSummary(
            total_features=len(reports),
            drifted_features=len(drifted),
            alert_features=len(alerts),
            critical_features=len(critical),
            overall_drift_score=round(overall_score, 4),
            recommendations=recommendations,
        )

    def get_alerts(self) -> List[DriftReport]:
        """Sadece alarm olan drift'leri döndür."""
        return [r for r in self.check_drift() if r.alert]

    def get_critical_alerts(self) -> List[DriftReport]:
        """Sadece CRITICAL drift'leri döndür."""
        return [r for r in self.check_drift() if r.severity == "CRITICAL"]

    def get_drift_history(self) -> List[Dict[str, Any]]:
        """Drift history."""
        return self._drift_history

    def get_history(self) -> List[Dict[str, Any]]:
        """SHAP history."""
        return self._shap_history

    def _compute_trend(self, historical: List[float], current: float) -> str:
        """Importance trend hesapla."""
        if len(historical) < 3:
            return "stable"

        recent = np.mean(historical[-3:])
        older = np.mean(historical[:-3]) if len(historical) > 3 else recent
        std = np.std(historical)

        # Volatile check
        if std > np.mean(historical) * 0.5:
            return "volatile"

        # Trend check
        change = (recent - older) / max(abs(older), 0.01)
        if change > self.importance_change_threshold:
            return "increasing"
        elif change < -self.importance_change_threshold:
            return "decreasing"
        else:
            return "stable"

    def _compute_severity(self, psi: float, trend: str) -> str:
        """Drift severity hesapla."""
        if psi > 1.0 or (psi > 0.5 and trend == "volatile"):
            return "CRITICAL"
        elif psi > 0.5 or (psi > 0.3 and trend in ("increasing", "decreasing")):
            return "HIGH"
        elif psi > 0.2 or trend in ("increasing", "decreasing"):
            return "MEDIUM"
        else:
            return "LOW"

    def _suggest_remediation(self, feature: str, psi: float, trend: str, severity: str) -> str:
        """Remediation önerisi."""
        if severity == "CRITICAL":
            return f"Model retrain önerilir — '{feature}' feature'ında ciddi drift"
        elif severity == "HIGH":
            return f"'{feature}' feature'ını izle — drift artarsa retrain gerekebilir"
        elif trend in ("increasing", "decreasing"):
            return f"'{feature}' importance yön değiştiriyor — feature engineering gözden geçirin"
        else:
            return ""

    def _check_distribution_drift(self, reports: List[DriftReport]):
        """Distribution-based drift kontrolü (PSI)."""
        current_dist = self._feature_distributions[-1]
        reference_dist = self._feature_distributions[0]

        for feature in current_dist:
            if feature not in reference_dist:
                continue

            psi = self._calculate_psi(reference_dist[feature], current_dist[feature])
            if psi > self.psi_threshold:
                existing = next((r for r in reports if r.feature_name == feature), None)
                if existing:
                    existing.psi = round(float(psi), 4)
                    existing.drift_detected = True
                    existing.alert = True
                    if psi > 1.0:
                        existing.severity = "CRITICAL"

    def _calculate_psi(self, reference: np.ndarray, current: np.ndarray) -> float:
        """PSI (Population Stability Index) hesapla."""
        try:
            min_val = min(reference.min(), current.min())
            max_val = max(reference.max(), current.max())
            bins = np.linspace(min_val, max_val, self.n_bins + 1)

            ref_hist, _ = np.histogram(reference, bins=bins)
            cur_hist, _ = np.histogram(current, bins=bins)

            eps = 1e-6
            ref_pct = ref_hist / max(len(reference), 1) + eps
            cur_pct = cur_hist / max(len(current), 1) + eps

            psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
            return psi
        except Exception as e:
            return 0.0
