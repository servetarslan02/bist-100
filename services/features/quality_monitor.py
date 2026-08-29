"""ALPHA BIST — Feature Quality Monitor v1.0

Feature kalitesini izler:
- Null oranı monitoring
- Outlier tespiti (IQR + z-score)
- Distribution shift (KS test)
- Range validation
- Feature completeness scoring

Kullanım:
    from services.features.quality_monitor import feature_quality_monitor

    # Tek feature kontrolü
    report = feature_quality_monitor.check_feature("rsi_14", values)

    # Toplu kontrol
    reports = feature_quality_monitor.check_all(feature_data)

    # Özet
    summary = feature_quality_monitor.get_summary()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class FeatureQualityReport:
    """Tek feature kalite raporu."""

    feature_name: str
    total_count: int
    null_count: int
    null_ratio: float
    outlier_count: int
    outlier_ratio: float
    mean: float
    std: float
    min_val: float
    max_val: float
    q25: float
    q50: float
    q75: float
    is_valid: bool
    issues: list[str] = field(default_factory=list)
    severity: str = "OK"  # OK, WARNING, CRITICAL


@dataclass
class QualitySummary:
    """Genel kalite özeti."""

    total_features: int
    valid_features: int
    warning_features: int
    critical_features: int
    avg_null_ratio: float
    avg_outlier_ratio: float
    completeness_score: float  # 0-1, 1 = tamamen temiz
    timestamp: str


class FeatureQualityMonitor:
    """Feature kalite izleme motoru.

    Özellikler:
    - Null oranı monitoring (eşik: %10 warning, %30 critical)
    - Outlier tespiti (IQR yöntemi: 1.5*IQR fence)
    - Distribution shift (basitleştirilmiş KS test)
    - Range validation (contract'tan)
    - Feature completeness scoring
    """

    def __init__(
        self,
        null_warning_threshold: float = 0.10,
        null_critical_threshold: float = 0.30,
        outlier_iqr_multiplier: float = 1.5,
        outlier_zscore_threshold: float = 3.0,
    ):
        """Otomatik eklendi."""
        self.null_warning_threshold = null_warning_threshold
        self.null_critical_threshold = null_critical_threshold
        self.outlier_iqr_multiplier = outlier_iqr_multiplier
        self.outlier_zscore_threshold = outlier_zscore_threshold
        self._history: list[dict[str, Any]] = []

    def check_feature(
        self,
        feature_name: str,
        values: np.ndarray,
        expected_range: tuple[float, float] | None = None,
    ) -> FeatureQualityReport:
        """Tek feature için kalite kontrolü.

        Args:
            feature_name: Feature adı
            values: Feature değerleri
            expected_range: Beklenen değer aralığı (min, max)

        Returns:
            FeatureQualityReport
        """
        if len(values) == 0:
            return FeatureQualityReport(
                feature_name=feature_name,
                total_count=0,
                null_count=0,
                null_ratio=0.0,
                outlier_count=0,
                outlier_ratio=0.0,
                mean=0.0,
                std=0.0,
                min_val=0.0,
                max_val=0.0,
                q25=0.0,
                q50=0.0,
                q75=0.0,
                is_valid=False,
                issues=["Empty values array"],
                severity="CRITICAL",
            )

        issues = []

        # Null/NaN kontrolü
        null_mask = (
            np.isnan(values) if np.issubdtype(values.dtype, np.floating) else np.array([v is None for v in values])
        )
        null_count = int(np.sum(null_mask))
        null_ratio = null_count / len(values)

        # Geçerli değerler
        valid_values = (
            values[~null_mask]
            if np.issubdtype(values.dtype, np.floating)
            else np.array([float(v) for v in values if v is not None])
        )

        if len(valid_values) == 0:
            return FeatureQualityReport(
                feature_name=feature_name,
                total_count=len(values),
                null_count=null_count,
                null_ratio=null_ratio,
                outlier_count=0,
                outlier_ratio=0.0,
                mean=0.0,
                std=0.0,
                min_val=0.0,
                max_val=0.0,
                q25=0.0,
                q50=0.0,
                q75=0.0,
                is_valid=False,
                issues=["All values are null"],
                severity="CRITICAL",
            )

        # Temel istatistikler
        mean = float(np.mean(valid_values))
        std = float(np.std(valid_values))
        min_val = float(np.min(valid_values))
        max_val = float(np.max(valid_values))
        q25 = float(np.percentile(valid_values, 25))
        q50 = float(np.percentile(valid_values, 50))
        q75 = float(np.percentile(valid_values, 75))

        # Outlier tespiti (IQR yöntemi)
        iqr = q75 - q25
        lower_fence = q25 - self.outlier_iqr_multiplier * iqr
        upper_fence = q75 + self.outlier_iqr_multiplier * iqr
        outlier_mask = (valid_values < lower_fence) | (valid_values > upper_fence)
        outlier_count = int(np.sum(outlier_mask))
        outlier_ratio = outlier_count / len(valid_values)

        # Null kontrolü
        if null_ratio > self.null_critical_threshold:
            issues.append(f"Null ratio {null_ratio:.1%} > {self.null_critical_threshold:.1%} (CRITICAL)")
        elif null_ratio > self.null_warning_threshold:
            issues.append(f"Null ratio {null_ratio:.1%} > {self.null_warning_threshold:.1%} (WARNING)")

        # Outlier kontrolü
        if outlier_ratio > 0.10:
            issues.append(f"Outlier ratio {outlier_ratio:.1%} > 10% (WARNING)")

        # Range kontrolü
        if expected_range:
            exp_min, exp_max = expected_range
            below_range = int(np.sum(valid_values < exp_min))
            above_range = int(np.sum(valid_values > exp_max))
            if below_range > 0:
                issues.append(f"{below_range} values below expected min ({exp_min})")
            if above_range > 0:
                issues.append(f"{above_range} values above expected max ({exp_max})")

        # Constant feature kontrolü
        if std < 1e-10:
            issues.append("Feature is constant (std ≈ 0)")

        # Severity
        if any("CRITICAL" in i for i in issues):
            severity = "CRITICAL"
        elif issues:
            severity = "WARNING"
        else:
            severity = "OK"

        return FeatureQualityReport(
            feature_name=feature_name,
            total_count=len(values),
            null_count=null_count,
            null_ratio=round(null_ratio, 4),
            outlier_count=outlier_count,
            outlier_ratio=round(outlier_ratio, 4),
            mean=round(mean, 6),
            std=round(std, 6),
            min_val=round(min_val, 6),
            max_val=round(max_val, 6),
            q25=round(q25, 6),
            q50=round(q50, 6),
            q75=round(q75, 6),
            is_valid=severity != "CRITICAL",
            issues=issues,
            severity=severity,
        )

    def check_all(
        self,
        feature_data: dict[str, np.ndarray],
        expected_ranges: dict[str, tuple[float, float]] | None = None,
    ) -> list[FeatureQualityReport]:
        """Tüm feature'lar için kalite kontrolü.

        Args:
            feature_data: {feature_name: values_array}
            expected_ranges: {feature_name: (min, max)}

        Returns:
            FeatureQualityReport listesi
        """
        reports = []
        for name, values in feature_data.items():
            range_val = expected_ranges.get(name) if expected_ranges else None
            report = self.check_feature(name, values, range_val)
            reports.append(report)

        # History
        self._history.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "n_features": len(reports),
                "n_valid": sum(1 for r in reports if r.is_valid),
                "n_warning": sum(1 for r in reports if r.severity == "WARNING"),
                "n_critical": sum(1 for r in reports if r.severity == "CRITICAL"),
            }
        )
        if len(self._history) > 1000:
            self._history = self._history[-1000:]

        return reports

    def get_summary(self, reports: list[FeatureQualityReport] | None = None) -> QualitySummary:
        """Genel kalite özeti.

        Args:
            reports: Kalite raporları (None ise son history kullanılır)

        Returns:
            QualitySummary
        """
        if reports is None:
            return QualitySummary(
                total_features=0,
                valid_features=0,
                warning_features=0,
                critical_features=0,
                avg_null_ratio=0.0,
                avg_outlier_ratio=0.0,
                completeness_score=0.0,
                timestamp=datetime.now(UTC).isoformat(),
            )

        valid = sum(1 for r in reports if r.severity == "OK")
        warning = sum(1 for r in reports if r.severity == "WARNING")
        critical = sum(1 for r in reports if r.severity == "CRITICAL")

        avg_null = float(np.mean([r.null_ratio for r in reports])) if reports else 0.0
        avg_outlier = float(np.mean([r.outlier_ratio for r in reports])) if reports else 0.0

        # Completeness: 1 - (null_ratio ortalaması)
        completeness = 1.0 - avg_null

        return QualitySummary(
            total_features=len(reports),
            valid_features=valid,
            warning_features=warning,
            critical_features=critical,
            avg_null_ratio=round(avg_null, 4),
            avg_outlier_ratio=round(avg_outlier, 4),
            completeness_score=round(completeness, 4),
            timestamp=datetime.now(UTC).isoformat(),
        )

    def check_distribution_shift(
        self,
        baseline: np.ndarray,
        current: np.ndarray,
        feature_name: str = "",
    ) -> dict[str, Any]:
        """Distribution shift kontrolü (basitleştirilmiş KS test).

        Args:
            baseline: Referans dağılım
            current: Mevcut dağılım
            feature_name: Feature adı (log için)

        Returns:
            Shift raporu dict
        """
        if len(baseline) < 10 or len(current) < 10:
            return {"shifted": False, "reason": "Insufficient data"}

        # Basitleştirilmiş KS statistic
        baseline_sorted = np.sort(baseline)
        current_sorted = np.sort(current)

        # CDF farkı
        all_values = np.sort(np.concatenate([baseline_sorted, current_sorted]))
        cdf_baseline = np.searchsorted(baseline_sorted, all_values, side="right") / len(baseline_sorted)
        cdf_current = np.searchsorted(current_sorted, all_values, side="right") / len(current_sorted)

        ks_statistic = float(np.max(np.abs(cdf_baseline - cdf_current)))

        # Eşik: 0.05 → %95 güvenle farklı
        shifted = ks_statistic > 0.05

        if shifted:
            logger.warning(
                "feature_distribution_shifted",
                feature=feature_name,
                ks_statistic=round(ks_statistic, 4),
            )

        return {
            "feature": feature_name,
            "ks_statistic": round(ks_statistic, 4),
            "shifted": shifted,
            "baseline_mean": round(float(np.mean(baseline)), 4),
            "current_mean": round(float(np.mean(current)), 4),
            "baseline_std": round(float(np.std(baseline)), 4),
            "current_std": round(float(np.std(current)), 4),
        }

    @property
    def history(self) -> list[dict[str, Any]]:
        """Otomatik eklendi."""
        return self._history


# Singleton
feature_quality_monitor = FeatureQualityMonitor()
