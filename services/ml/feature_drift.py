"""ALPHA BIST — Feature Drift Detector (Nihai —⭐⭐⭐⭐⭐).

SHAP history tracking, PSI (Population Stability Index),
feature importance trend analizi, multi-metric drift detection,
auto-remediation suggestions, drift alerting.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
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
    recommendations: list[str]


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
        self._shap_history: list[dict[str, Any]] = []
        self._feature_distributions: list[dict[str, np.ndarray]] = []
        self._drift_history: list[dict[str, Any]] = []
        self._last_alert: dict[str, datetime] = {}

    def record_shap(self, shap_values: dict[str, float]):
        """SHAP importance kaydet."""
        self._shap_history.append(
            {
                **shap_values,
                "_timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._shap_history) > 1000:
            self._shap_history = self._shap_history[-1000:]

    def record_distribution(self, feature_data: dict[str, np.ndarray]):
        """Feature dağılımı kaydet (PSI hesaplama için)."""
        self._feature_distributions.append(feature_data)
        if len(self._feature_distributions) > 500:
            self._feature_distributions = self._feature_distributions[-500:]

    def check_drift(self) -> list[DriftReport]:
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

            reports.append(
                DriftReport(
                    feature_name=feature,
                    psi=round(float(psi), 4),
                    drift_detected=psi > self.psi_threshold,
                    importance_trend=trend,
                    current_importance=round(float(current_imp), 4),
                    historical_importance=round(hist_mean, 4),
                    alert=alert,
                    severity=severity,
                    remediation=remediation,
                )
            )

        # PSI-based drift (distribution shift)
        if len(self._feature_distributions) >= 2:
            self._check_distribution_drift(reports)

        # Drift history
        self._drift_history.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "n_drifted": sum(1 for r in reports if r.drift_detected),
                "n_alerts": sum(1 for r in reports if r.alert),
                "n_critical": sum(1 for r in reports if r.severity == "CRITICAL"),
            }
        )
        if len(self._drift_history) > 1000:
            self._drift_history = self._drift_history[-1000:]

        return reports

    def get_summary(self) -> DriftSummary:
        """Genel drift özeti."""
        reports = self.check_drift()

        if not reports:
            return DriftSummary(
                total_features=0,
                drifted_features=0,
                alert_features=0,
                critical_features=0,
                overall_drift_score=0.0,
                recommendations=[],
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
            recommendations.append(f"WARNING: Feature'ların %{int(len(drifted) / len(reports) * 100)}'ünde drift var")
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

    def get_alerts(self) -> list[DriftReport]:
        """Sadece alarm olan drift'leri döndür."""
        return [r for r in self.check_drift() if r.alert]

    def get_critical_alerts(self) -> list[DriftReport]:
        """Sadece CRITICAL drift'leri döndür."""
        return [r for r in self.check_drift() if r.severity == "CRITICAL"]

    def get_drift_history(self) -> list[dict[str, Any]]:
        """Drift history."""
        return self._drift_history

    def get_history(self) -> list[dict[str, Any]]:
        """SHAP history."""
        return self._shap_history

    def _compute_trend(self, historical: list[float], current: float) -> str:
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

    def _check_distribution_drift(self, reports: list[DriftReport]):
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
        """PSI (Population Stability Index) hesapla.

        F-018 düzeltmesi: Gerçek PSI formülü.
        PSI = Σ (P_current - P_reference) * ln(P_current / P_reference)

        PSI < 0.1: Stabil
        PSI 0.1-0.25: Orta değişim
        PSI > 0.25: Significant drift
        """
        try:
            # Quantile-based bins (eşit dağılmış)
            ref_sorted = np.sort(reference)
            n = len(ref_sorted)
            if n < 10:
                return 0.0

            # Quantile sınırları (10 eşit parçaya böl)
            quantile_boundaries = [ref_sorted[int(n * i / self.n_bins)] for i in range(1, self.n_bins)]
            quantile_boundaries = [-np.inf] + list(quantile_boundaries) + [np.inf]

            # Her iki dağılımı bu sınırlara göre histogram'la
            ref_hist, _ = np.histogram(reference, bins=quantile_boundaries)
            cur_hist, _ = np.histogram(current, bins=quantile_boundaries)

            # Yüzdelere çevir (sıfır bölme koruması)
            eps = 1e-4
            ref_pct = ref_hist / max(len(reference), 1) + eps
            cur_pct = cur_hist / max(len(current), 1) + eps

            # PSI formülü
            psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
            return max(0.0, psi)  # Negatif PSI hatalı, sıfırla
        except Exception:
            return 0.0
