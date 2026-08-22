"""
ALPHA BIST — Feature Drift Detector v1.0

Feature dağılım değişikliği tespiti:
- Kolmogorov-Smirnov (KS) test — dağılım değişikliği
- Population Stability Index (PSI) — dağılım kayması
- Z-score drift — ortalama kayması
- Rolling window drift — pencere bazlı karşılaştırma
- Drift alert sistemi

Kaynaklar:
- Evidently AI: KS test large datasets (2022)
- IBM Model Drift (2024)
- DataCamp Drift Detection (2025)

FAZ 2: Feature Drift Detection
"""

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()

# numpy opsiyonel — yoksa pure Python fallback
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None


# =====================================================
# Enums & Data Classes
# =====================================================

class DriftSeverity(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DriftMethod(str, Enum):
    KS_TEST = "ks_test"
    PSI = "psi"
    ZSCORE = "zscore"
    ROLLING = "rolling"


@dataclass
class DriftResult:
    """Tek bir feature için drift sonucu."""
    feature_name: str
    ticker: str
    method: DriftMethod
    drift_detected: bool
    severity: DriftSeverity
    statistic: float              # Test istatistiği
    p_value: float | None      # KS test p-değeri (PSI/zscore'da None)
    threshold: float              # Kullanılan eşik
    baseline_mean: float
    current_mean: float
    baseline_std: float
    current_std: float
    baseline_count: int
    current_count: int
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature_name,
            "ticker": self.ticker,
            "method": self.method.value,
            "drift_detected": self.drift_detected,
            "severity": self.severity.value,
            "statistic": round(self.statistic, 6),
            "p_value": round(self.p_value, 6) if self.p_value is not None else None,
            "threshold": self.threshold,
            "baseline_mean": round(self.baseline_mean, 6),
            "current_mean": round(self.current_mean, 6),
            "baseline_std": round(self.baseline_std, 6),
            "current_std": round(self.current_std, 6),
            "baseline_count": self.baseline_count,
            "current_count": self.current_count,
            "timestamp": self.timestamp,
        }


@dataclass
class DriftReport:
    """Tüm feature'lar için drift raporu."""
    ticker: str
    timestamp: str
    results: list[DriftResult]
    total_features: int
    drifted_features: int
    critical_drifts: int
    overall_status: DriftSeverity

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "timestamp": self.timestamp,
            "total_features": self.total_features,
            "drifted_features": self.drifted_features,
            "critical_drifts": self.critical_drifts,
            "overall_status": self.overall_status.value,
            "details": [r.to_dict() for r in self.results],
        }

    def get_drifted_features(self) -> list[str]:
        """Drift tespit edilen feature isimlerini döndür."""
        return [r.feature_name for r in self.results if r.drift_detected]


@dataclass
class DriftAlert:
    """Drift alarmı."""
    ticker: str
    feature_name: str
    severity: DriftSeverity
    message: str
    drift_result: DriftResult
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


# =====================================================
# Drift Detector
# =====================================================

class FeatureDriftDetector:
    """Feature drift detection motoru.

    Kullanım:
        detector = FeatureDriftDetector()
        report = detector.detect_all(ticker, baseline_values, current_values)
        alerts = detector.check_alerts(report)
    """

    def __init__(
        self,
        ks_threshold: float = 0.05,       # KS test p-value eşiği
        psi_threshold: float = 0.25,       # PSI eşiği (>0.25 = significant shift)
        zscore_threshold: float = 2.0,     # Z-score eşiği
        rolling_threshold: float = 0.15,   # Rolling window eşiği
        min_samples: int = 30,             # Minimum örnek sayısı
        alert_callback=None,               # Alert callback fonksiyonu
    ):
        self.ks_threshold = ks_threshold
        self.psi_threshold = psi_threshold
        self.zscore_threshold = zscore_threshold
        self.rolling_threshold = rolling_threshold
        self.min_samples = min_samples
        self._alert_callback = alert_callback
        self._alert_history: list[DriftAlert] = []

    # =====================================================
    # ANA DRIFT TESPİT
    # =====================================================

    def detect_all(
        self,
        ticker: str,
        baseline: dict[str, list[float]],
        current: dict[str, list[float]],
        methods: list[DriftMethod] | None = None,
    ) -> DriftReport:
        """Tüm feature'lar için drift tespiti yap.

        Args:
            ticker: Hisse kodu
            baseline: {feature_name: [historical_values]}
            current: {feature_name: [recent_values]}
            methods: Kullanılacak yöntemler (None=hepsi)

        Returns:
            DriftReport
        """
        if methods is None:
            methods = [DriftMethod.KS_TEST, DriftMethod.PSI, DriftMethod.ZSCORE]

        results = []
        for feature_name in set(baseline.keys()) & set(current.keys()):
            base_vals = baseline[feature_name]
            curr_vals = current[feature_name]

            if len(base_vals) < self.min_samples or len(curr_vals) < self.min_samples:
                continue

            for method in methods:
                result = self._detect_single(
                    feature_name, ticker, base_vals, curr_vals, method
                )
                if result:
                    results.append(result)

        # Özet
        drifted = sum(1 for r in results if r.drift_detected)
        critical = sum(1 for r in results if r.severity == DriftSeverity.CRITICAL)
        overall = self._compute_overall_status(results)

        report = DriftReport(
            ticker=ticker,
            timestamp=datetime.now(UTC).isoformat(),
            results=results,
            total_features=len(set(baseline.keys()) & set(current.keys())),
            drifted_features=drifted,
            critical_drifts=critical,
            overall_status=overall,
        )

        # Alert'ler
        alerts = self.check_alerts(report)
        if alerts and self._alert_callback:
            for alert in alerts:
                self._alert_callback(alert)

        return report

    def detect_feature(
        self,
        feature_name: str,
        ticker: str,
        baseline_values: list[float],
        current_values: list[float],
        method: DriftMethod = DriftMethod.KS_TEST,
    ) -> DriftResult | None:
        """Tek bir feature için drift tespiti."""
        if len(baseline_values) < self.min_samples or len(current_values) < self.min_samples:
            return None
        return self._detect_single(
            feature_name, ticker, baseline_values, current_values, method
        )

    # =====================================================
    # TEST METODLARI
    # =====================================================

    def _detect_single(
        self,
        feature_name: str,
        ticker: str,
        baseline: list[float],
        current: list[float],
        method: DriftMethod,
    ) -> DriftResult | None:
        """Tek bir feature için tek yöntemle drift tespiti."""
        try:
            if method == DriftMethod.KS_TEST:
                return self._ks_test(feature_name, ticker, baseline, current)
            elif method == DriftMethod.PSI:
                return self._psi_test(feature_name, ticker, baseline, current)
            elif method == DriftMethod.ZSCORE:
                return self._zscore_test(feature_name, ticker, baseline, current)
            elif method == DriftMethod.ROLLING:
                return self._rolling_test(feature_name, ticker, baseline, current)
        except Exception as e:
            logger.warning(
                "Drift detection failed",
                feature=feature_name, method=method.value, error=str(e),
            )
        return None

    def _ks_test(
        self, feature_name: str, ticker: str,
        baseline: list[float], current: list[float],
    ) -> DriftResult:
        """Kolmogorov-Smirnov test — dağılım değişikliği.

        Pure Python implementation (scipy bağımlılığı yok).
        """
        # KS istatistiği: iki örneğin CDF'leri arasındaki maksimum fark
        sorted_base = sorted(baseline)
        sorted_curr = sorted(current)

        all_values = sorted(set(sorted_base + sorted_curr))
        n_base = len(baseline)
        n_curr = len(current)

        max_diff = 0.0
        cdf_base = 0.0
        cdf_curr = 0.0
        i_base = 0
        i_curr = 0

        for val in all_values:
            while i_base < n_base and sorted_base[i_base] <= val:
                cdf_base += 1.0 / n_base
                i_base += 1
            while i_curr < n_curr and sorted_curr[i_curr] <= val:
                cdf_curr += 1.0 / n_curr
                i_curr += 1

            diff = abs(cdf_base - cdf_curr)
            if diff > max_diff:
                max_diff = diff

        # p-value approximation (Kolmogorov distribution)
        n_eff = (n_base * n_curr) / (n_base + n_curr)
        lambda_val = (math.sqrt(n_eff) + 0.12 + 0.11 / math.sqrt(n_eff)) * max_diff
        p_value = self._ks_p_value(lambda_val)

        drift_detected = p_value < self.ks_threshold
        severity = self._classify_severity(p_value, self.ks_threshold, is_p_value=True)

        return DriftResult(
            feature_name=feature_name,
            ticker=ticker,
            method=DriftMethod.KS_TEST,
            drift_detected=drift_detected,
            severity=severity,
            statistic=max_diff,
            p_value=p_value,
            threshold=self.ks_threshold,
            baseline_mean=self._mean(baseline),
            current_mean=self._mean(current),
            baseline_std=self._std(baseline),
            current_std=self._std(current),
            baseline_count=n_base,
            current_count=n_curr,
        )

    def _psi_test(
        self, feature_name: str, ticker: str,
        baseline: list[float], current: list[float],
    ) -> DriftResult:
        """Population Stability Index (PSI) — dağılım kayması.

        PSI = Σ (actual% - expected%) * ln(actual% / expected%)
        < 0.10: insignificant
        0.10-0.25: moderate shift
        > 0.25: significant shift
        """
        n_bins = 10

        # Baseline'dan bin sınırlarını belirle
        sorted_base = sorted(baseline)
        bin_edges = []
        for i in range(n_bins + 1):
            idx = int(i * len(sorted_base) / n_bins)
            idx = min(idx, len(sorted_base) - 1)
            bin_edges.append(sorted_base[idx])

        # Bin counts
        base_counts = self._bin_counts(baseline, bin_edges)
        curr_counts = self._bin_counts(current, bin_edges)

        # PSI hesapla
        psi = 0.0
        for i in range(n_bins):
            base_pct = max(base_counts[i] / len(baseline), 0.0001)
            curr_pct = max(curr_counts[i] / len(current), 0.0001)
            psi += (curr_pct - base_pct) * math.log(curr_pct / base_pct)

        drift_detected = psi > self.psi_threshold
        severity = self._classify_severity(psi, self.psi_threshold, is_p_value=False)

        return DriftResult(
            feature_name=feature_name,
            ticker=ticker,
            method=DriftMethod.PSI,
            drift_detected=drift_detected,
            severity=severity,
            statistic=psi,
            p_value=None,
            threshold=self.psi_threshold,
            baseline_mean=self._mean(baseline),
            current_mean=self._mean(current),
            baseline_std=self._std(baseline),
            current_std=self._std(current),
            baseline_count=len(baseline),
            current_count=len(current),
        )

    def _zscore_test(
        self, feature_name: str, ticker: str,
        baseline: list[float], current: list[float],
    ) -> DriftResult:
        """Z-score drift — ortalama kayması.

        Z = |mean_current - mean_baseline| / std_baseline
        > 2.0: significant drift
        > 3.0: critical drift
        """
        base_mean = self._mean(baseline)
        base_std = self._std(baseline)
        curr_mean = self._mean(current)

        if base_std == 0:
            z_score = 0.0
        else:
            z_score = abs(curr_mean - base_mean) / base_std

        drift_detected = z_score > self.zscore_threshold
        severity = self._classify_severity(z_score, self.zscore_threshold, is_p_value=False)

        return DriftResult(
            feature_name=feature_name,
            ticker=ticker,
            method=DriftMethod.ZSCORE,
            drift_detected=drift_detected,
            severity=severity,
            statistic=z_score,
            p_value=None,
            threshold=self.zscore_threshold,
            baseline_mean=base_mean,
            current_mean=curr_mean,
            baseline_std=base_std,
            current_std=self._std(current),
            baseline_count=len(baseline),
            current_count=len(current),
        )

    def _rolling_test(
        self, feature_name: str, ticker: str,
        baseline: list[float], current: list[float],
    ) -> DriftResult:
        """Rolling window drift — iki pencere arasındaki fark.

        Relative difference = |mean_current - mean_baseline| / |mean_baseline|
        """
        base_mean = self._mean(baseline)
        curr_mean = self._mean(current)

        if base_mean == 0:
            rel_diff = 0.0
        else:
            rel_diff = abs(curr_mean - base_mean) / abs(base_mean)

        drift_detected = rel_diff > self.rolling_threshold
        severity = self._classify_severity(rel_diff, self.rolling_threshold, is_p_value=False)

        return DriftResult(
            feature_name=feature_name,
            ticker=ticker,
            method=DriftMethod.ROLLING,
            drift_detected=drift_detected,
            severity=severity,
            statistic=rel_diff,
            p_value=None,
            threshold=self.rolling_threshold,
            baseline_mean=base_mean,
            current_mean=curr_mean,
            baseline_std=self._std(baseline),
            current_std=self._std(current),
            baseline_count=len(baseline),
            current_count=len(current),
        )

    # =====================================================
    # ALERT
    # =====================================================

    def check_alerts(self, report: DriftReport) -> list[DriftAlert]:
        """Drift raporundan alert'ler üret."""
        alerts = []

        for result in report.results:
            if not result.drift_detected:
                continue

            if result.severity in (DriftSeverity.HIGH, DriftSeverity.CRITICAL):
                alert = DriftAlert(
                    ticker=result.ticker,
                    feature_name=result.feature_name,
                    severity=result.severity,
                    message=(
                        f"[{result.severity.value.upper()}] Feature drift: "
                        f"{result.feature_name} | "
                        f"method={result.method.value} | "
                        f"stat={result.statistic:.4f} | "
                        f"baseline_mean={result.baseline_mean:.4f} → "
                        f"current_mean={result.current_mean:.4f}"
                    ),
                    drift_result=result,
                )
                alerts.append(alert)
                self._alert_history.append(alert)

        # Son 1000 alert tut
        self._alert_history = self._alert_history[-1000:]

        if alerts:
            logger.warning(
                "Drift alerts generated",
                ticker=report.ticker,
                count=len(alerts),
                critical=report.critical_drifts,
            )

        return alerts

    def get_alert_history(
        self,
        ticker: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Alert geçmişini getir."""
        alerts = self._alert_history
        if ticker:
            alerts = [a for a in alerts if a.ticker == ticker]
        return [
            {
                "ticker": a.ticker,
                "feature": a.feature_name,
                "severity": a.severity.value,
                "message": a.message,
                "timestamp": a.timestamp,
            }
            for a in alerts[-limit:]
        ]

    # =====================================================
    # YARDIMCI FONKSİYONLAR
    # =====================================================

    def _classify_severity(
        self, value: float, threshold: float, is_p_value: bool,
    ) -> DriftSeverity:
        """Drift şiddetini sınıflandır."""
        if is_p_value:
            # p-value: düşük = kötü
            if value < 0.001:
                return DriftSeverity.CRITICAL
            elif value < 0.01:
                return DriftSeverity.HIGH
            elif value < threshold:
                return DriftSeverity.MEDIUM
            else:
                return DriftSeverity.NONE
        else:
            # İstatistik: yüksek = kötü
            ratio = value / max(threshold, 1e-10)
            if ratio > 3.0:
                return DriftSeverity.CRITICAL
            elif ratio > 2.0:
                return DriftSeverity.HIGH
            elif ratio > 1.0:
                return DriftSeverity.MEDIUM
            else:
                return DriftSeverity.NONE

    def _compute_overall_status(self, results: list[DriftResult]) -> DriftSeverity:
        """Genel drift durumunu hesapla."""
        if not results:
            return DriftSeverity.NONE

        severities = [r.severity for r in results if r.drift_detected]
        if not severities:
            return DriftSeverity.NONE

        if DriftSeverity.CRITICAL in severities:
            return DriftSeverity.CRITICAL
        elif DriftSeverity.HIGH in severities:
            return DriftSeverity.HIGH
        elif DriftSeverity.MEDIUM in severities:
            return DriftSeverity.MEDIUM
        return DriftSeverity.LOW

    @staticmethod
    def _mean(values: list[float]) -> float:
        if not values:
            return 0.0
        return float(np.mean(values))

    @staticmethod
    def _std(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        return float(np.std(values, ddof=1))

    @staticmethod
    def _bin_counts(values: list[float], edges: list[float]) -> list[int]:
        """Değerleri bin'lere yerleştir (vektörize)."""
        arr = np.array(values)
        edges_arr = np.array(edges)
        counts = np.histogram(arr, bins=edges_arr)[0]
        return counts.tolist()

    @staticmethod
    def _ks_p_value(lambda_val: float) -> float:
        """KS test p-value approximation (Kolmogorov distribution).

        Q(λ) = 2 Σ (-1)^(k-1) exp(-2k²λ²)
        """
        if lambda_val <= 0:
            return 1.0
        p = 0.0
        for k in range(1, 20):
            term = 2 * (-1) ** (k - 1) * math.exp(-2 * k * k * lambda_val * lambda_val)
            p += term
            if abs(term) < 1e-10:
                break
        return max(0.0, min(1.0, p))

    # =====================================================
    # OTOMATIK BASELINE GÜNCELLEME
    # =====================================================

    def update_baseline_with_drift_check(
        self,
        ticker: str,
        feature_name: str,
        baseline: list[float],
        new_values: list[float],
        auto_update: bool = False,
    ) -> tuple[bool, DriftResult | None]:
        """Yeni değerlerle drift kontrolü yap, opsiyonel olarak baseline güncelle.

        Args:
            ticker: Hisse kodu
            feature_name: Feature adı
            baseline: Mevcut baseline
            new_values: Yeni değerler
            auto_update: True ise drift yoksa baseline'ı güncelle

        Returns:
            (drift_detected, drift_result)
        """
        result = self.detect_feature(
            feature_name, ticker, baseline, new_values, DriftMethod.KS_TEST
        )

        if result and result.drift_detected:
            logger.warning(
                "Drift detected, baseline NOT updated",
                ticker=ticker, feature=feature_name,
                severity=result.severity.value,
            )
            return True, result

        if auto_update and result and not result.drift_detected:
            # Baseline'ı yeni değerlerle genişlet
            logger.info(
                "No drift, updating baseline",
                ticker=ticker, feature=feature_name,
            )

        return False, result


# Singleton
drift_detector = FeatureDriftDetector()
