"""
ALPHA BIST — Advanced Drift Detector v1.0

Çoklu yöntemle drift tespiti:
- PSI (Population Stability Index) — veri dağılımı değişimi
- KS Test (Kolmogorov-Smirnov) — dağılım karşılaştırma
- ADWIN (Adaptive Windowing) — adaptif pencere
- Page-Hinkley — kümülatif sapma
- Z-score — anlık sapma
- Concept Drift — performans bazlı

Drift Type Sınıflandırması:
- MINOR_DRIFT: PSI 0.1-0.2 → İzle
- MAJOR_DATA_DRIFT: PSI > 0.5 → Acil retrain
- SIGNIFICANT_DISTRIBUTION_SHIFT: KS p < 0.01 → Retrain
- GRADUAL_DRIFT: Page-Hinkley drift → Scheduled retrain
- SUDDEN_SHIFT: ADWIN drift → Acil retrain
- EXTREME_OUTLIER: Z-score > 5 → Veri kalitesi kontrolü
- CONCEPT_DRIFT: Performance decay → Retrain + feature review

KURAL: En az 2 yöntem hemfikir olmalı → drift kararı.
"""

import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import structlog

from services.learning.config.learning_config import learning_settings
from services.learning.utils.statistical_tests import (
    StatisticalTests, PSIResult, KSTestResult,
    PageHinkleyResult, ADWINResult,
)

logger = structlog.get_logger()


@dataclass
class DriftResult:
    """Tek feature için drift sonucu."""
    feature_name: str
    drift_detected: bool
    drift_type: str  # MINOR, MAJOR, SIGNIFICANT, GRADUAL, SUDDEN, EXTREME, CONCEPT
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    methods_agreed: int  # Kaç yöntem drift tespit etti
    details: Dict[str, Any]


@dataclass
class ComprehensiveDriftReport:
    """Kapsamlı drift raporu."""
    timestamp: str
    overall_drift: bool
    drift_type: str
    severity: str
    affected_features: List[str]
    feature_results: Dict[str, DriftResult]
    concept_drift: Dict[str, Any]
    recommendation: str  # MONITOR, RETRAIN, INVESTIGATE
    agreement_count: int  # Kaç yöntem hemfikir


class AdvancedDriftDetector:
    """Gelişmiş drift detection motoru — çoklu yöntem."""

    def __init__(self):
        self._baseline_distributions: Dict[str, Dict] = {}  # feature → {mean, std, data}
        self._drift_history: List[ComprehensiveDriftReport] = []
        self._performance_history: List[Dict] = []  # concept drift için
        self._last_report: Optional[ComprehensiveDriftReport] = None

    def set_baseline(
        self,
        feature_data: Dict[str, np.ndarray],
        performance_data: Optional[List[Dict]] = None,
    ):
        """Baseline dağılımları ayarla.

        Args:
            feature_data: {feature_name: data_array}
            performance_data: [{sharpe, win_rate, accuracy, date}]
        """
        for name, data in feature_data.items():
            data = np.asarray(data, dtype=np.float64)
            data = data[np.isfinite(data)]
            if len(data) > 0:
                self._baseline_distributions[name] = {
                    "data": data.copy(),
                    "mean": float(np.mean(data)),
                    "std": float(np.std(data)),
                    "count": len(data),
                }

        if performance_data:
            self._performance_history = performance_data

        logger.info("Baseline set", features=len(self._baseline_distributions),
                   performance_records=len(self._performance_history))

    def detect_all_drift(
        self,
        current_data: Dict[str, np.ndarray],
        current_performance: Optional[Dict[str, float]] = None,
        min_agreement: int = 2,
    ) -> ComprehensiveDriftReport:
        """Tüm drift türlerini tespit et.

        Args:
            current_data: {feature_name: current_data_array}
            current_performance: Mevcut performans metrikleri
            min_agreement: Drift kararı için minimum yöntem anlaşması

        Returns:
            ComprehensiveDriftReport
        """
        cfg = learning_settings.drift
        feature_results = {}
        all_drift_types = []
        all_severities = []

        # Her feature için drift tespit
        for name, current in current_data.items():
            if name not in self._baseline_distributions:
                continue

            baseline = self._baseline_distributions[name]
            result = self._detect_feature_drift(name, baseline, current, cfg)
            feature_results[name] = result

            if result.drift_detected:
                all_drift_types.append(result.drift_type)
                all_severities.append(result.severity)

        # Concept drift (performans bazlı)
        concept = self._detect_concept_drift(current_performance, cfg)

        # Genel drift kararı
        drifted_features = [f for f, r in feature_results.items() if r.drift_detected]
        overall_drift = len(drifted_features) >= max(1, len(feature_results) * 0.2)  # %20+ feature drift

        # Drift type belirle
        if concept.get("concept_drift"):
            drift_type = "CONCEPT_DRIFT"
            severity = "HIGH"
        elif "MAJOR_DATA_DRIFT" in all_drift_types:
            drift_type = "MAJOR_DATA_DRIFT"
            severity = "CRITICAL"
        elif "SIGNIFICANT_DISTRIBUTION_SHIFT" in all_drift_types:
            drift_type = "SIGNIFICANT_DISTRIBUTION_SHIFT"
            severity = "HIGH"
        elif "SUDDEN_SHIFT" in all_drift_types:
            drift_type = "SUDDEN_SHIFT"
            severity = "HIGH"
        elif "GRADUAL_DRIFT" in all_drift_types:
            drift_type = "GRADUAL_DRIFT"
            severity = "MEDIUM"
        elif overall_drift:
            drift_type = "COMBINED_MINOR_DRIFT"
            severity = "MEDIUM"
        else:
            drift_type = "STABLE"
            severity = "LOW"

        # Recommendation
        recommendation = self._recommend(drift_type, severity, len(drifted_features), concept)

        report = ComprehensiveDriftReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            overall_drift=overall_drift or concept.get("concept_drift", False),
            drift_type=drift_type,
            severity=severity,
            affected_features=drifted_features,
            feature_results=feature_results,
            concept_drift=concept,
            recommendation=recommendation,
            agreement_count=len([r for r in feature_results.values() if r.drift_detected]),
        )

        self._drift_history.append(report)
        if len(self._drift_history) > 1000:
            self._drift_history = self._drift_history[-1000:]
        self._last_report = report

        if report.overall_drift:
            logger.warning("Drift detected",
                         type=drift_type, severity=severity,
                         features=len(drifted_features),
                         recommendation=recommendation)
        else:
            logger.info("No drift detected", features=len(feature_results))

        return report

    def get_drift_report(self) -> Dict[str, Any]:
        """Son drift raporunu döndür."""
        if not self._last_report:
            return {"status": "No drift data"}

        r = self._last_report
        return {
            "status": "OK",
            "timestamp": r.timestamp,
            "overall_drift": r.overall_drift,
            "drift_type": r.drift_type,
            "severity": r.severity,
            "affected_features": r.affected_features,
            "recommendation": r.recommendation,
            "agreement_count": r.agreement_count,
            "feature_count": len(r.feature_results),
            "concept_drift": r.concept_drift,
            "history_count": len(self._drift_history),
        }

    # ===================== FEATURE DRIFT =====================

    def _detect_feature_drift(
        self,
        name: str,
        baseline: Dict,
        current: np.ndarray,
        cfg: Any,
    ) -> DriftResult:
        """Tek feature için drift tespit — çoklu yöntem."""
        current = np.asarray(current, dtype=np.float64)
        current = current[np.isfinite(current)]

        if len(current) < 5:
            return DriftResult(
                feature_name=name, drift_detected=False,
                drift_type="INSUFFICIENT_DATA", severity="LOW",
                methods_agreed=0, details={"reason": "Insufficient data"},
            )

        baseline_data = baseline.get("data")
        if baseline_data is None or len(baseline_data) < 5:
            return DriftResult(
                feature_name=name, drift_detected=False,
                drift_type="NO_BASELINE", severity="LOW",
                methods_agreed=0, details={"reason": "No baseline data"},
            )

        drift_signals = []
        details = {}

        # 1. PSI
        psi_result = StatisticalTests.compute_psi(baseline_data, current)
        details["psi"] = {
            "value": psi_result.psi,
            "severity": psi_result.severity,
            "drift": psi_result.drift_detected,
        }
        if psi_result.drift_detected:
            drift_signals.append("PSI")

        # 2. KS Test
        ks_result = StatisticalTests.ks_test(baseline_data, current, alpha=cfg.ks_p_threshold)
        details["ks_test"] = {
            "statistic": ks_result.statistic,
            "p_value": ks_result.p_value,
            "drift": ks_result.drift_detected,
        }
        if ks_result.drift_detected:
            drift_signals.append("KS")

        # 3. Z-score
        zscore_result = StatisticalTests.zscore_test(
            baseline_mean=baseline["mean"],
            baseline_std=baseline["std"],
            current_value=float(np.mean(current)),
            warning_threshold=cfg.zscore_warning,
            critical_threshold=cfg.zscore_critical,
        )
        details["zscore"] = zscore_result
        if zscore_result["drift_detected"]:
            drift_signals.append("ZSCORE")

        # 4. Page-Hinkley
        ph_result = StatisticalTests.page_hinkley_test(
            current, threshold=cfg.ph_threshold, delta=cfg.ph_delta
        )
        details["page_hinkley"] = {
            "drift": ph_result.drift_detected,
            "max_deviation": ph_result.max_deviation,
            "change_point": ph_result.change_point_index,
        }
        if ph_result.drift_detected:
            drift_signals.append("PH")

        # 5. ADWIN
        adwin_result = StatisticalTests.adwin_test(current, delta=cfg.adwin_delta)
        details["adwin"] = {
            "drift": adwin_result.drift_detected,
            "window_size": adwin_result.window_size,
            "p_value": adwin_result.p_value,
        }
        if adwin_result.drift_detected:
            drift_signals.append("ADWIN")

        # Drift kararı: en az 2 yöntem hemfikir
        methods_agreed = len(drift_signals)
        drift_detected = methods_agreed >= 2

        # Drift type sınıflandırma
        drift_type = self._classify_drift_type(psi_result, ks_result, ph_result, adwin_result, zscore_result)

        # Severity
        severity = self._calculate_severity(psi_result, zscore_result, methods_agreed)

        return DriftResult(
            feature_name=name,
            drift_detected=drift_detected,
            drift_type=drift_type,
            severity=severity,
            methods_agreed=methods_agreed,
            details=details,
        )

    def _classify_drift_type(
        self,
        psi: PSIResult,
        ks: KSTestResult,
        ph: PageHinkleyResult,
        adwin: ADWINResult,
        zscore: Dict,
    ) -> str:
        """Drift type sınıflandır."""
        if psi.severity == "CRITICAL":
            return "MAJOR_DATA_DRIFT"
        elif ks.drift_detected and ks.p_value < 0.01:
            return "SIGNIFICANT_DISTRIBUTION_SHIFT"
        elif zscore.get("severity") == "CRITICAL":
            return "EXTREME_OUTLIER"
        elif adwin.drift_detected:
            return "SUDDEN_SHIFT"
        elif ph.drift_detected:
            return "GRADUAL_DRIFT"
        elif psi.drift_detected:
            return "MINOR_DRIFT"
        return "STABLE"

    def _calculate_severity(
        self,
        psi: PSIResult,
        zscore: Dict,
        methods_agreed: int,
    ) -> str:
        """Drift severity hesapla."""
        if psi.severity == "CRITICAL" or zscore.get("severity") == "CRITICAL":
            return "CRITICAL"
        elif methods_agreed >= 3:
            return "HIGH"
        elif methods_agreed >= 2:
            return "MEDIUM"
        elif methods_agreed >= 1:
            return "LOW"
        return "NONE"

    # ===================== CONCEPT DRIFT =====================

    def _detect_concept_drift(
        self,
        current_performance: Optional[Dict[str, float]],
        cfg: Any,
    ) -> Dict[str, Any]:
        """Concept drift tespit — performans bazlı."""
        if not current_performance or len(self._performance_history) < 20:
            return {"concept_drift": False, "reason": "Insufficient performance data"}

        # Son N performans
        recent = self._performance_history[-cfg.concept_drift_window:]
        if len(recent) < 10:
            return {"concept_drift": False, "reason": "Insufficient recent data"}

        # Mevcut performans
        current_sharpe = current_performance.get("sharpe", 0)
        current_winrate = current_performance.get("win_rate", 0)

        # Geçmiş performans
        hist_sharpes = [p.get("sharpe", 0) for p in recent]
        hist_winrates = [p.get("win_rate", 0) for p in recent]

        avg_hist_sharpe = np.mean(hist_sharpes)
        avg_hist_winrate = np.mean(hist_winrates)

        # Concept drift: performans aniden düştü
        sharpe_drop = avg_hist_sharpe - current_sharpe
        winrate_drop = avg_hist_winrate - current_winrate

        concept_drift = bool(
            sharpe_drop > cfg.concept_drift_accuracy_drop * avg_hist_sharpe or
            winrate_drop > cfg.concept_drift_accuracy_drop
        )

        return {
            "concept_drift": concept_drift,
            "current_sharpe": round(current_sharpe, 4),
            "historical_avg_sharpe": round(avg_hist_sharpe, 4),
            "sharpe_drop": round(sharpe_drop, 4),
            "current_winrate": round(current_winrate, 4),
            "historical_avg_winrate": round(avg_hist_winrate, 4),
            "winrate_drop": round(winrate_drop, 4),
        }

    # ===================== RECOMMENDATION =====================

    def _recommend(
        self,
        drift_type: str,
        severity: str,
        affected_count: int,
        concept: Dict,
    ) -> str:
        """Drift durumuna göre öner."""
        if concept.get("concept_drift"):
            return "RETRAIN_IMMEDIATE"
        elif severity == "CRITICAL":
            return "RETRAIN_IMMEDIATE"
        elif severity == "HIGH":
            return "RETRAIN_SCHEDULED"
        elif severity == "MEDIUM":
            return "INVESTIGATE"
        elif affected_count > 0:
            return "MONITOR"
        return "OK"


# Singleton
advanced_drift_detector = AdvancedDriftDetector()
