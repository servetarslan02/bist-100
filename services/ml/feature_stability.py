"""ALPHA BIST — Feature Stability Analysis v1.0

Feature stabilitesini analiz eder:
- PSI (Population Stability Index) per feature
- Distribution shift detection (KS test)
- Feature correlation stability
- Stability scoring (0-1)
- Unstable feature alerting

Kullanım:
    from services.ml.feature_stability import feature_stability

    # Feature dağılımlarını kaydet
    feature_stability.record_distribution(feature_data, timestamp="2026-01-01")

    # Stabilite kontrolü
    report = feature_stability.check_stability()

    # Unstable feature'ları al
    unstable = feature_stability.get_unstable_features()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class FeatureStabilityReport:
    """Tek feature stabilite raporu."""

    feature_name: str
    psi: float
    ks_statistic: float
    ks_p_value: float
    distribution_shifted: bool
    correlation_stable: bool
    stability_score: float  # 0-1, 1 = tamamen stabil
    severity: str  # OK, WARNING, ALERT, CRITICAL
    details: str


@dataclass
class StabilitySummary:
    """Genel stabilite özeti."""

    total_features: int
    stable_features: int
    warning_features: int
    alert_features: int
    critical_features: int
    overall_stability_score: float
    unstable_features: list[str]
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class FeatureStabilityAnalyzer:
    """Feature stabilite analiz motoru.

    Özellikler:
    - PSI per feature (distribution shift)
    - KS test (statistical significance)
    - Correlation stability (feature ilişkileri değişimi)
    - Stability scoring (0-1)
    - Alert sistemi
    """

    def __init__(
        self,
        psi_warning: float = 0.1,
        psi_alert: float = 0.25,
        psi_critical: float = 1.0,
        ks_alpha: float = 0.05,
        min_samples: int = 50,
    ):
        """Otomatik eklendi."""
        self.psi_warning = psi_warning
        self.psi_alert = psi_alert
        self.psi_critical = psi_critical
        self.ks_alpha = ks_alpha
        self.min_samples = min_samples
        self._distributions: list[dict[str, np.ndarray]] = []
        self._timestamps: list[str] = []
        self._correlation_matrices: list[tuple[np.ndarray, list[str]]] = []

    def record_distribution(
        self,
        feature_data: dict[str, np.ndarray],
        timestamp: str | None = None,
    ) -> None:
        """Feature dağılımı kaydet.

        Args:
            feature_data: {feature_name: values_array}
            timestamp: Zaman damgası
        """
        self._distributions.append(feature_data)
        self._timestamps.append(timestamp or datetime.now(UTC).isoformat())

        # Son 100 kaydı tut
        if len(self._distributions) > 100:
            self._distributions = self._distributions[-100:]
            self._timestamps = self._timestamps[-100:]

    def record_correlation(
        self,
        feature_data: dict[str, np.ndarray],
    ) -> None:
        """Feature korelasyon matrisi kaydet."""
        names = sorted(feature_data.keys())
        if len(names) < 2:
            return

        try:
            arrays = [feature_data[n] for n in names]
            min_len = min(len(a) for a in arrays)
            matrix = np.column_stack([a[:min_len] for a in arrays])
            corr = np.corrcoef(matrix.T)
            self._correlation_matrices.append((corr, names))

            if len(self._correlation_matrices) > 50:
                self._correlation_matrices = self._correlation_matrices[-50:]
        except Exception as e:
            logger.warning("correlation_record_failed", error=str(e))

    def check_stability(self) -> StabilitySummary:
        """Tüm feature'lar için stabilite kontrolü.

        Returns:
            StabilitySummary
        """
        if len(self._distributions) < 2:
            return StabilitySummary(
                total_features=0,
                stable_features=0,
                warning_features=0,
                alert_features=0,
                critical_features=0,
                overall_stability_score=1.0,
                unstable_features=[],
            )

        reference = self._distributions[0]
        current = self._distributions[-1]

        reports: list[FeatureStabilityReport] = []

        for feature_name in current:
            if feature_name not in reference:
                continue

            report = self._check_feature_stability(
                feature_name,
                reference[feature_name],
                current[feature_name],
            )
            reports.append(report)

        # Korelasyon stabilitesi
        if len(self._correlation_matrices) >= 2:
            corr_stable = self._check_correlation_stability()
            for report in reports:
                if report.feature_name in corr_stable:
                    report.correlation_stable = corr_stable[report.feature_name]
                    if not report.correlation_stable and report.severity == "OK":
                        report.severity = "WARNING"
                        report.details += " [Korelasyon değişimi]"

        # Özet
        stable = sum(1 for r in reports if r.severity == "OK")
        warning = sum(1 for r in reports if r.severity == "WARNING")
        alert = sum(1 for r in reports if r.severity == "ALERT")
        critical = sum(1 for r in reports if r.severity == "CRITICAL")
        unstable = [r.feature_name for r in reports if r.severity in ("ALERT", "CRITICAL")]

        overall_score = float(np.mean([r.stability_score for r in reports])) if reports else 1.0

        return StabilitySummary(
            total_features=len(reports),
            stable_features=stable,
            warning_features=warning,
            alert_features=alert,
            critical_features=critical,
            overall_stability_score=round(overall_score, 4),
            unstable_features=unstable,
        )

    def get_unstable_features(self, threshold: float = 0.7) -> list[str]:
        """Stability skoru eşiğin altında olan feature'ları döndür."""
        summary = self.check_stability()
        return summary.unstable_features

    def get_feature_report(self, feature_name: str) -> FeatureStabilityReport | None:
        """Tek feature için detaylı rapor."""
        if len(self._distributions) < 2:
            return None

        reference = self._distributions[0]
        current = self._distributions[-1]

        if feature_name not in reference or feature_name not in current:
            return None

        return self._check_feature_stability(
            feature_name,
            reference[feature_name],
            current[feature_name],
        )

    def _check_feature_stability(
        self,
        feature_name: str,
        reference: np.ndarray,
        current: np.ndarray,
    ) -> FeatureStabilityReport:
        """Tek feature için stabilite kontrolü."""
        # PSI
        psi = self._calculate_psi(reference, current)

        # KS test
        ks_stat, ks_p = self._ks_test(reference, current)

        # Distribution shifted
        shifted = psi > self.psi_alert or ks_p < self.ks_alpha

        # Stability score (1 - normalized_psi)
        stability_score = max(0.0, 1.0 - psi / self.psi_critical)

        # Severity
        if psi > self.psi_critical:
            severity = "CRITICAL"
        elif psi > self.psi_alert:
            severity = "ALERT"
        elif psi > self.psi_warning:
            severity = "WARNING"
        else:
            severity = "OK"

        # Details
        details = f"PSI={psi:.4f}, KS={ks_stat:.4f}, p={ks_p:.4f}"
        if shifted:
            details += " [SHIFT DETECTED]"

        return FeatureStabilityReport(
            feature_name=feature_name,
            psi=round(psi, 4),
            ks_statistic=round(ks_stat, 4),
            ks_p_value=round(ks_p, 4),
            distribution_shifted=shifted,
            correlation_stable=True,  # Varsayılan, sonra güncellenir
            stability_score=round(stability_score, 4),
            severity=severity,
            details=details,
        )

    def _calculate_psi(self, reference: np.ndarray, current: np.ndarray) -> float:
        """PSI hesapla."""
        try:
            ref_sorted = np.sort(reference[~np.isnan(reference)])
            n = len(ref_sorted)
            if n < 10:
                return 0.0

            boundaries = [ref_sorted[int(n * i / 10)] for i in range(1, 10)]
            bins = [-np.inf] + list(boundaries) + [np.inf]

            ref_hist, _ = np.histogram(reference[~np.isnan(reference)], bins=bins)
            cur_hist, _ = np.histogram(current[~np.isnan(current)], bins=bins)

            eps = 1e-4
            ref_pct = ref_hist / max(len(reference), 1) + eps
            cur_pct = cur_hist / max(len(current), 1) + eps

            psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
            return max(0.0, psi)
        except Exception:
            return 0.0

    def _ks_test(self, reference: np.ndarray, current: np.ndarray) -> tuple[float, float]:
        """KS test hesapla."""
        try:
            from scipy.stats import ks_2samp

            ref_clean = reference[~np.isnan(reference)]
            cur_clean = current[~np.isnan(current)]

            if len(ref_clean) < 10 or len(cur_clean) < 10:
                return 0.0, 1.0

            stat, p_value = ks_2samp(ref_clean, cur_clean)
            return float(stat), float(p_value)
        except Exception:
            return 0.0, 1.0

    def _check_correlation_stability(self) -> dict[str, bool]:
        """Korelasyon stabilitesi kontrolü."""
        if len(self._correlation_matrices) < 2:
            return {}

        ref_corr, ref_names = self._correlation_matrices[0]
        cur_corr, cur_names = self._correlation_matrices[-1]

        common = [n for n in ref_names if n in cur_names]
        if len(common) < 2:
            return {}

        result: dict[str, bool] = {}
        for name in common:
            ref_idx = ref_names.index(name)
            cur_idx = cur_names.index(name)

            ref_row = ref_corr[ref_idx]
            cur_row = cur_corr[cur_idx]

            # Korelasyon farkı
            max_diff = float(np.max(np.abs(ref_row - cur_row)))
            result[name] = max_diff < 0.3  # %30'dan az değişim = stabil

        return result


# Singleton
feature_stability = FeatureStabilityAnalyzer()
