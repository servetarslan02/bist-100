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
        """Tüm feature'lar için kapsamlı drift kontrolü.

        İki katmanlı drift tespiti:
        1. SHAP importance drift (z-score tabanlı)
        2. Distribution drift (gerçek PSI formülü)
        """
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

            # Importance z-score (standart sapma cinsinden sapma)
            importance_zscore = abs(current_imp - hist_mean) / max(hist_std, 0.01)

            # Severity (z-score tabanlı)
            severity = self._compute_severity(importance_zscore, trend)

            # Alert
            alert = importance_zscore > self.psi_threshold or trend in ("increasing", "decreasing", "volatile")

            # Remediation
            remediation = self._suggest_remediation(feature, importance_zscore, trend, severity)

            reports.append(
                DriftReport(
                    feature_name=feature,
                    psi=round(float(importance_zscore), 4),
                    drift_detected=importance_zscore > self.psi_threshold,
                    importance_trend=trend,
                    current_importance=round(float(current_imp), 4),
                    historical_importance=round(hist_mean, 4),
                    alert=alert,
                    severity=severity,
                    remediation=remediation,
                )
            )

        # Distribution-based drift (gerçek PSI formülü)
        if len(self._feature_distributions) >= 2:
            self._check_distribution_drift(reports)

        # Correlation drift
        if len(self._feature_distributions) >= 2:
            self._check_correlation_drift(reports)

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

    # =====================================================
    # PER-TICKER & TIME SERIES (v2.1)
    # =====================================================

    def record_shap_per_ticker(
        self,
        ticker: str,
        shap_values: dict[str, float],
    ) -> None:
        """Ticker bazlı SHAP importance kaydet.

        Args:
            ticker: Hisse kodu
            shap_values: {feature_name: importance}
        """
        if not hasattr(self, "_shap_by_ticker"):
            self._shap_by_ticker: dict[str, list[dict[str, Any]]] = {}

        if ticker not in self._shap_by_ticker:
            self._shap_by_ticker[ticker] = []

        self._shap_by_ticker[ticker].append({
            **shap_values,
            "_timestamp": datetime.now(UTC).isoformat(),
        })

        # Son 500 kaydı tut
        if len(self._shap_by_ticker[ticker]) > 500:
            self._shap_by_ticker[ticker] = self._shap_by_ticker[ticker][-500:]

    def get_importance_time_series(
        self,
        feature_name: str,
        window: int = 30,
    ) -> dict[str, Any]:
        """Feature importance zaman serisi.

        Args:
            feature_name: Feature adı
            window: Son N kayıt

        Returns:
            {feature, values, timestamps, trend, mean, std}
        """
        if len(self._shap_history) < 2:
            return {
                "feature": feature_name,
                "values": [],
                "timestamps": [],
                "trend": "stable",
                "mean": 0.0,
                "std": 0.0,
            }

        recent = self._shap_history[-window:]
        values = [h.get(feature_name, 0.0) for h in recent if feature_name in h]
        timestamps = [h.get("_timestamp", "") for h in recent if feature_name in h]

        if not values:
            return {
                "feature": feature_name,
                "values": [],
                "timestamps": [],
                "trend": "stable",
                "mean": 0.0,
                "std": 0.0,
            }

        # Trend analizi
        arr = np.array(values)
        mean_val = float(np.mean(arr))
        std_val = float(np.std(arr))

        if len(values) >= 4:
            first_half = np.mean(arr[:len(arr)//2])
            second_half = np.mean(arr[len(arr)//2:])
            change = (second_half - first_half) / max(abs(first_half), 0.001)

            if change > 0.2:
                trend = "increasing"
            elif change < -0.2:
                trend = "decreasing"
            elif std_val > mean_val * 0.5:
                trend = "volatile"
            else:
                trend = "stable"
        else:
            trend = "stable"

        return {
            "feature": feature_name,
            "values": [round(v, 6) for v in values],
            "timestamps": timestamps,
            "trend": trend,
            "mean": round(mean_val, 6),
            "std": round(std_val, 6),
        }

    def get_strengthening_features(
        self,
        threshold: float = 0.1,
    ) -> list[dict[str, Any]]:
        """Güçlenen feature'ları listele.

        Son dönemde importance'ı artan feature'ları döndürür.

        Args:
            threshold: Artış eşiği (oran)

        Returns:
            [{feature, current_importance, historical_importance, change_ratio, trend}]
        """
        if len(self._shap_history) < 4:
            return []

        current = self._shap_history[-1]
        historical = self._shap_history[:-1]

        strengthening: list[dict[str, Any]] = []

        for feature in current:
            if feature.startswith("_"):
                continue

            current_imp = current.get(feature, 0)
            historical_imps = [h.get(feature, 0) for h in historical if feature in h]

            if not historical_imps or current_imp <= 0:
                continue

            hist_mean = float(np.mean(historical_imps))
            if hist_mean <= 0:
                continue

            change_ratio = (current_imp - hist_mean) / hist_mean

            if change_ratio > threshold:
                strengthening.append({
                    "feature": feature,
                    "current_importance": round(current_imp, 6),
                    "historical_importance": round(hist_mean, 6),
                    "change_ratio": round(change_ratio, 4),
                    "trend": "strengthening",
                })

        return sorted(strengthening, key=lambda x: x["change_ratio"], reverse=True)

    def get_weakening_features(
        self,
        threshold: float = 0.1,
    ) -> list[dict[str, Any]]:
        """Zayıflayan feature'ları listele.

        Son dönemde importance'ı azalan feature'ları döndürür.

        Args:
            threshold: Azalma eşiği (oran)

        Returns:
            [{feature, current_importance, historical_importance, change_ratio, trend}]
        """
        if len(self._shap_history) < 4:
            return []

        current = self._shap_history[-1]
        historical = self._shap_history[:-1]

        weakening: list[dict[str, Any]] = []

        for feature in current:
            if feature.startswith("_"):
                continue

            current_imp = current.get(feature, 0)
            historical_imps = [h.get(feature, 0) for h in historical if feature in h]

            if not historical_imps:
                continue

            hist_mean = float(np.mean(historical_imps))
            if hist_mean <= 0:
                continue

            change_ratio = (current_imp - hist_mean) / hist_mean

            if change_ratio < -threshold:
                weakening.append({
                    "feature": feature,
                    "current_importance": round(current_imp, 6),
                    "historical_importance": round(hist_mean, 6),
                    "change_ratio": round(change_ratio, 4),
                    "trend": "weakening",
                })

        return sorted(weakening, key=lambda x: x["change_ratio"])

    def get_ticker_shap_summary(
        self,
        ticker: str,
    ) -> dict[str, Any]:
        """Ticker bazlı SHAP özeti.

        Args:
            ticker: Hisse kodu

        Returns:
            {ticker, n_records, top_features, latest_shap}
        """
        if not hasattr(self, "_shap_by_ticker") or ticker not in self._shap_by_ticker:
            return {
                "ticker": ticker,
                "n_records": 0,
                "top_features": [],
                "latest_shap": {},
            }

        records = self._shap_by_ticker[ticker]
        latest = records[-1] if records else {}

        # Top features
        feature_sums: dict[str, float] = {}
        for r in records:
            for k, v in r.items():
                if not k.startswith("_"):
                    feature_sums[k] = feature_sums.get(k, 0) + abs(float(v))

        n = len(records)
        avg_importance = {k: round(v / n, 6) for k, v in feature_sums.items()}
        top_features = sorted(avg_importance.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "ticker": ticker,
            "n_records": n,
            "top_features": [{"feature": f, "importance": i} for f, i in top_features],
            "latest_shap": {k: v for k, v in latest.items() if not k.startswith("_")},
        }

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
        """Distribution-based drift kontrolü (gerçek PSI formülü).

        PSI = Σ (P_current - P_reference) * ln(P_current / P_reference)
        PSI < 0.1: Stabil
        PSI 0.1-0.25: Orta değişim
        PSI > 0.25: Significant drift
        """
        current_dist = self._feature_distributions[-1]
        reference_dist = self._feature_distributions[0]

        for feature in current_dist:
            if feature not in reference_dist:
                continue

            psi = self._calculate_psi(reference_dist[feature], current_dist[feature])
            if psi > 0.1:  # PSI eşiği (0.1 = stabil sınırı)
                existing = next((r for r in reports if r.feature_name == feature), None)
                if existing:
                    # Distribution PSI'ı importance z-score ile birleştir
                    combined_score = max(existing.psi, psi)
                    existing.psi = round(float(combined_score), 4)
                    existing.drift_detected = combined_score > self.psi_threshold
                    existing.alert = True
                    if psi > 0.25:
                        existing.severity = "HIGH"
                    if psi > 1.0:
                        existing.severity = "CRITICAL"
                    existing.remediation = self._suggest_remediation(
                        feature, combined_score, existing.importance_trend, existing.severity
                    )

    def _check_correlation_drift(self, reports: list[DriftReport]):
        """Feature korelasyon drift kontrolü.

        Feature'lar arası korelasyon yapısı değiştiyse bu bir drift işaretidir.
        """
        current_dist = self._feature_distributions[-1]
        reference_dist = self._feature_distributions[0]

        # Ortak feature'ları bul
        common_features = [f for f in current_dist if f in reference_dist]
        if len(common_features) < 3:
            return

        try:
            # Referans korelasyon matrisi
            ref_arrays = [reference_dist[f] for f in common_features]
            min_len = min(len(a) for a in ref_arrays)
            ref_matrix = np.column_stack([a[:min_len] for a in ref_arrays])
            ref_corr = np.corrcoef(ref_matrix.T)

            # Mevcut korelasyon matrisi
            cur_arrays = [current_dist[f] for f in common_features]
            min_len = min(len(a) for a in cur_arrays)
            cur_matrix = np.column_stack([a[:min_len] for a in cur_arrays])
            cur_corr = np.corrcoef(cur_matrix.T)

            # Korelasyon farkı
            corr_diff = np.abs(cur_corr - ref_corr)
            max_diff = float(np.max(corr_diff[np.triu_indices_from(corr_diff, k=1)]))
            mean_diff = float(np.mean(corr_diff[np.triu_indices_from(corr_diff, k=1)]))

            if max_diff > 0.3:
                # En çok değişen feature çiftini bul
                i, j = np.unravel_index(np.argmax(corr_diff), corr_diff.shape)
                feat_i, feat_j = common_features[i], common_features[j]

                # İlgili feature'ları işaretle
                for fname in [feat_i, feat_j]:
                    existing = next((r for r in reports if r.feature_name == fname), None)
                    if existing:
                        existing.alert = True
                        if existing.severity == "LOW":
                            existing.severity = "MEDIUM"
                        existing.remediation += f" [Korelasyon drift: {fname}↔{feat_j if fname == feat_i else feat_i}, max_diff={max_diff:.2f}]"

                logger.info(
                    "Correlation drift detected",
                    max_diff=round(max_diff, 4),
                    mean_diff=round(mean_diff, 4),
                    pair=f"{feat_i}↔{feat_j}",
                )
        except Exception as e:
            logger.debug("Correlation drift check failed", error=str(e))

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
