"""ALPHA BIST — Model Calibration v2.0 (Production-Hardened)

Confidence calibration — Brier score, calibration curve,
Platt scaling, isotonic regression, regime-specific calibration,
overconfidence detection, calibration monitoring.

Geliştirmeler (v2.0):
- Platt vs Isotonic karşılaştırma (hangisi daha iyi?)
- Bootstrap confidence intervals (Brier, ECE için)
- Adaptive online calibration (yeni veriyle güncelleme)
- Brier Skill Score (baseline'a göre)
- Calibration alerting (drift eşiği aşıldığında)
- Calibration reliability diagram data (görselleştirme için)
- Train/val split ile Platt scaling (data leakage yok)
- Net Reclassification Index (NRI)
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class CalibrationResult:
    """Kalibrasyon sonucu."""

    is_calibrated: bool
    brier_score: float
    calibration_curve: list[dict[str, float]]
    miscalibration: float
    overconfident: bool
    recommendation: str
    # Detay
    expected_calibration_error: float = 0.0
    maximum_calibration_error: float = 0.0
    log_loss: float = 0.0
    # v2.0 ekleri
    brier_skill_score: float = 0.0
    brier_baseline: float = 0.0
    ece_ci_lower: float = 0.0
    ece_ci_upper: float = 0.0
    brier_ci_lower: float = 0.0
    brier_ci_upper: float = 0.0
    platt_ece: float = 0.0
    isotonic_ece: float = 0.0
    best_calibrator: str = "none"
    nri: float = 0.0


@dataclass
class RegimeCalibrationResult:
    """Regime-specific kalibrasyon sonucu."""

    regime: str
    result: CalibrationResult
    n_samples: int


@dataclass
class CalibrationAlert:
    """Kalibrasyon alarmı."""

    timestamp: str
    alert_type: str  # DRIFT, DEGRADATION, OVERCONFIDENCE
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    message: str
    metric: str
    value: float
    threshold: float


class ModelCalibration:
    """Model confidence kalibrasyonu v2.0.

    Özellikler:
    - Calibration curve (beklenen vs gerçek doğruluk)
    - Brier score + Brier Skill Score (baseline'a göre)
    - Expected Calibration Error (ECE) + bootstrap CI
    - Maximum Calibration Error (MCE)
    - Platt scaling (sigmoid calibration) — train/val split ile
    - Isotonic regression calibration — train/val split ile
    - Platt vs Isotonic karşılaştırma
    - Overconfidence detection
    - Regime-specific calibration
    - Calibration monitoring (zaman içinde değişimi)
    - Adaptive calibration (online güncelleme)
    - Calibration alerting (drift eşiği aşıldığında)
    - Net Reclassification Index (NRI)
    - Reliability diagram data (görselleştirme için)
    """

    def __init__(
        self,
        n_bins: int = 10,
        overconfidence_threshold: float = 0.15,
        ece_threshold: float = 0.05,
        drift_threshold: float = 0.05,
        bootstrap_n: int = 100,
    ):
        self.n_bins = n_bins
        self.overconfidence_threshold = overconfidence_threshold
        self.ece_threshold = ece_threshold
        self.drift_threshold = drift_threshold
        self.bootstrap_n = bootstrap_n
        self._calibration_history: list[dict[str, Any]] = []
        self._regime_calibrators: dict[str, Any] = {}
        self._alerts: list[CalibrationAlert] = []
        self._platt_calibrator: Any = None
        self._isotonic_calibrator: Any = None
        self._adaptive_buffer: list[tuple[float, float]] = []  # (confidence, outcome)
        self._adaptive_window: int = 500

    def check_calibration(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
    ) -> CalibrationResult:
        """Kapsamlı kalibrasyon kontrolü — v2.0.

        Platt ve Isotonic'i karşılaştırır, bootstrap CI hesaplar.
        """
        from sklearn.calibration import calibration_curve
        from sklearn.metrics import brier_score_loss, log_loss

        # Brier score
        try:
            brier = float(brier_score_loss(y_true, y_prob))
        except Exception:
            brier = 1.0

        # Brier Skill Score (baseline = her zaman 0.5 tahmin et)
        baseline_prob = np.full_like(y_prob, 0.5)
        try:
            brier_baseline = float(brier_score_loss(y_true, baseline_prob))
        except Exception:
            brier_baseline = 0.25
        brier_skill_score = 1.0 - (brier / max(brier_baseline, 1e-10))

        # Log loss
        try:
            ll = float(log_loss(y_true, y_prob))
        except Exception:
            ll = 1.0

        # Calibration curve
        try:
            fraction_pos, mean_predicted = calibration_curve(y_true, y_prob, n_bins=self.n_bins, strategy="uniform")
            curve = []
            for frac, mean_pred in zip(fraction_pos, mean_predicted, strict=False):
                curve.append(
                    {
                        "mean_predicted": round(float(mean_pred), 4),
                        "fraction_positive": round(float(frac), 4),
                        "gap": round(abs(float(mean_pred) - float(frac)), 4),
                    }
                )
        except Exception:
            curve = []

        # ECE (Expected Calibration Error)
        ece = self._compute_ece(y_true, y_prob)

        # MCE (Maximum Calibration Error)
        mce = max([c["gap"] for c in curve]) if curve else 0.0

        # Miscalibration
        miscalibration = float(np.mean([c["gap"] for c in curve])) if curve else 0.0

        # Bootstrap confidence intervals
        ece_ci = self._bootstrap_ece_ci(y_true, y_prob)
        brier_ci = self._bootstrap_brier_ci(y_true, y_prob)

        # Platt vs Isotonic karşılaştırma
        platt_ece, isotonic_ece, best_calibrator = self._compare_calibrators(y_true, y_prob)

        # Net Reclassification Index
        nri = self._compute_nri(y_true, y_prob)

        # Overconfidence check
        overconfident = miscalibration > self.overconfidence_threshold or ece > self.ece_threshold

        # Recommendation
        if brier < 0.1 and ece < 0.03:
            recommendation = "EXCELLENT"
        elif brier < 0.2 and ece < 0.05:
            recommendation = "GOOD"
        elif brier < 0.3 and ece < 0.1:
            recommendation = "NEEDS_CALIBRATION"
        else:
            recommendation = "POOR"

        result = CalibrationResult(
            is_calibrated=miscalibration < self.overconfidence_threshold and ece < self.ece_threshold,
            brier_score=round(brier, 4),
            calibration_curve=curve,
            miscalibration=round(miscalibration, 4),
            overconfident=overconfident,
            recommendation=recommendation,
            expected_calibration_error=round(ece, 4),
            maximum_calibration_error=round(mce, 4),
            log_loss=round(ll, 4),
            brier_skill_score=round(brier_skill_score, 4),
            brier_baseline=round(brier_baseline, 4),
            ece_ci_lower=round(ece_ci[0], 4),
            ece_ci_upper=round(ece_ci[1], 4),
            brier_ci_lower=round(brier_ci[0], 4),
            brier_ci_upper=round(brier_ci[1], 4),
            platt_ece=round(platt_ece, 4),
            isotonic_ece=round(isotonic_ece, 4),
            best_calibrator=best_calibrator,
            nri=round(nri, 4),
        )

        # History
        self._calibration_history.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "brier_score": brier,
                "ece": ece,
                "miscalibration": miscalibration,
                "n_samples": len(y_true),
                "brier_skill_score": brier_skill_score,
            }
        )
        if len(self._calibration_history) > 1000:
            self._calibration_history = self._calibration_history[-1000:]

        # Alerting
        self._check_alerts(result, len(y_true))

        return result

    def calibrate_platt(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        y_prob_val: np.ndarray | None = None,
        y_true_train: np.ndarray | None = None,
    ) -> tuple[Any, np.ndarray]:
        """Platt scaling (sigmoid calibration) — train/val split ile.

        Args:
            y_true: Tüm gerçek etiketler (veya train etiketleri)
            y_prob: Tüm olasılıklar (veya train olasılıkları)
            y_prob_val: Validation olasılıkları (None ise train üzerinde predict)
            y_true_train: Train etiketleri (y_prob_val varsa, calibrator train üzerinde eğitilir)
        """
        from sklearn.linear_model import LogisticRegression

        # Validation varsa, sadece train üzerinde eğit
        train_y = y_true_train if y_true_train is not None and y_prob_val is not None else y_true
        train_prob = y_prob if y_prob_val is not None else y_prob

        calibrator = LogisticRegression(max_iter=1000)
        calibrator.fit(train_prob.reshape(-1, 1), train_y)

        self._platt_calibrator = calibrator

        if y_prob_val is not None:
            calibrated = calibrator.predict_proba(y_prob_val.reshape(-1, 1))[:, 1]
        else:
            calibrated = calibrator.predict_proba(y_prob.reshape(-1, 1))[:, 1]

        return calibrator, calibrated

    def calibrate_isotonic(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        y_prob_val: np.ndarray | None = None,
    ) -> tuple[Any, np.ndarray]:
        """Isotonic regression calibration — train/val split ile."""
        from sklearn.isotonic import IsotonicRegression

        calibrator = IsotonicRegression(out_of_bounds="clip")
        calibrator.fit(y_prob, y_true)

        self._isotonic_calibrator = calibrator

        calibrated = calibrator.predict(y_prob_val) if y_prob_val is not None else calibrator.predict(y_prob)

        return calibrator, calibrated

    def calibrate_regime_specific(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        regimes: np.ndarray,
        method: str = "isotonic",
    ) -> dict[str, Any]:
        """Her rejim için ayrı kalibrasyon.

        Returns:
            {regime: calibrator}
        """
        unique_regimes = np.unique(regimes)

        for regime in unique_regimes:
            mask = regimes == regime
            if np.sum(mask) < 20:
                continue

            try:
                if method == "platt":
                    calibrator, _ = self.calibrate_platt(y_true[mask], y_prob[mask])
                else:
                    calibrator, _ = self.calibrate_isotonic(y_true[mask], y_prob[mask])

                self._regime_calibrators[regime] = calibrator
                logger.info("regime_calibration_fitted", regime=regime, n_samples=int(np.sum(mask)))
            except Exception as e:
                logger.warning("regime_calibration_failed", regime=regime, error=str(e))

        return self._regime_calibrators

    def apply_calibration(
        self,
        y_prob: np.ndarray,
        regime: str | None = None,
    ) -> np.ndarray:
        """Kalibrasyon uygula.

        Args:
            y_prob: Ham olasılık tahminleri
            regime: Mevcut rejim (regime-specific calibrator kullanır)

        Returns:
            Kalibre edilmiş olasılıklar
        """
        if regime and regime in self._regime_calibrators:
            calibrator = self._regime_calibrators[regime]
            try:
                return calibrator.predict(y_prob)
            except Exception as e:
                logger.debug("Handled exception", error=str(e), context="calibration.py:236")

        return y_prob

    def adaptive_update(self, confidence: float, outcome: float) -> None:
        """Online adaptive calibration — yeni veriyle güncelle.

        Her yeni prediction sonucu geldiğinde buffer'a ekler.
        Buffer dolduğunda kalibrasyonu yeniden fit eder.

        Args:
            confidence: Model confidence'ı [0, 1]
            outcome: Gerçek sonuç (0 veya 1)
        """
        self._adaptive_buffer.append((max(0.0, min(1.0, confidence)), float(outcome)))

        if len(self._adaptive_buffer) >= self._adaptive_window:
            self._refit_adaptive()

    def _refit_adaptive(self) -> None:
        """Adaptive buffer'dan kalibrasyonu yeniden fit et."""
        if len(self._adaptive_buffer) < 30:
            return

        confidences = np.array([c for c, _ in self._adaptive_buffer])
        outcomes = np.array([o for _, o in self._adaptive_buffer])

        # Platt scaling yeniden fit
        try:
            self.calibrate_platt(outcomes, confidences)
            logger.info("Adaptive Platt refit", samples=len(self._adaptive_buffer))
        except Exception as e:
            logger.warning("Adaptive Platt refit failed", error=str(e))

        # Isotonic yeniden fit
        try:
            self.calibrate_isotonic(outcomes, confidences)
            logger.info("Adaptive Isotonic refit", samples=len(self._adaptive_buffer))
        except Exception as e:
            logger.warning("Adaptive Isotonic refit failed", error=str(e))

        # Buffer'ı temizle (son %20'sini tut — drift detection için)
        keep = len(self._adaptive_buffer) // 5
        self._adaptive_buffer = self._adaptive_buffer[-keep:]

    def check_overconfidence(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        confidence_threshold: float = 0.8,
    ) -> dict[str, Any]:
        """Overconfidence analizi — yüksek confidence'lı tahminlerin doğruluğu.

        Args:
            y_true: Gerçek etiketler
            y_prob: Model olasılıkları
            confidence_threshold: Yüksek confidence eşiği

        Returns:
            Overconfidence raporu
        """
        # Yüksek confidence'lı tahminler
        high_conf_mask = (y_prob > confidence_threshold) | (y_prob < (1 - confidence_threshold))
        n_high_conf = int(np.sum(high_conf_mask))

        if n_high_conf == 0:
            return {
                "overconfident": False,
                "n_high_confidence": 0,
                "reason": "no_high_confidence_predictions",
            }

        # Yüksek confidence'lı tahminlerin doğruluğu
        high_conf_preds = (y_prob[high_conf_mask] > 0.5).astype(int)
        high_conf_true = y_true[high_conf_mask]
        high_conf_accuracy = float(np.mean(high_conf_preds == high_conf_true))

        # Düşük confidence'lı tahminlerin doğruluğu
        low_conf_mask = ~high_conf_mask
        if np.sum(low_conf_mask) > 0:
            low_conf_preds = (y_prob[low_conf_mask] > 0.5).astype(int)
            low_conf_true = y_true[low_conf_mask]
            low_conf_accuracy = float(np.mean(low_conf_preds == low_conf_true))
        else:
            low_conf_accuracy = 0.0

        # Overconfidence gap
        expected_accuracy = float(np.mean(y_prob[high_conf_mask]))
        overconfidence_gap = expected_accuracy - high_conf_accuracy

        return {
            "overconfident": overconfidence_gap > self.overconfidence_threshold,
            "n_high_confidence": n_high_conf,
            "high_confidence_accuracy": round(high_conf_accuracy, 4),
            "expected_accuracy": round(expected_accuracy, 4),
            "overconfidence_gap": round(overconfidence_gap, 4),
            "low_confidence_accuracy": round(low_conf_accuracy, 4),
            "n_total": len(y_true),
        }

    def get_calibration_history(self) -> list[dict[str, Any]]:
        """Kalibrasyon geçmişi."""
        return self._calibration_history

    def get_calibration_drift(self) -> dict[str, Any]:
        """Kalibrasyon drift analizi — zaman içinde kalibrasyon değişti mi?"""
        if len(self._calibration_history) < 3:
            return {"drift_detected": False, "reason": "insufficient_history"}

        recent = self._calibration_history[-3:]
        older = self._calibration_history[:-3] if len(self._calibration_history) > 3 else recent

        recent_ece = np.mean([h["ece"] for h in recent])
        older_ece = np.mean([h["ece"] for h in older])

        drift = abs(recent_ece - older_ece) > self.drift_threshold

        return {
            "drift_detected": drift,
            "recent_ece": round(float(recent_ece), 4),
            "historical_ece": round(float(older_ece), 4),
            "ece_change": round(float(recent_ece - older_ece), 4),
        }

    def get_alerts(self) -> list[CalibrationAlert]:
        """Kalibrasyon alarmları."""
        return self._alerts

    def get_reliability_diagram_data(self, y_true: np.ndarray, y_prob: np.ndarray) -> dict[str, Any]:
        """Reliability diagram verisi (görselleştirme için).

        Returns:
            {bins: [{lower, upper, avg_pred, avg_actual, count}], perfect_line: [...]}
        """
        bin_edges = np.linspace(0, 1, self.n_bins + 1)
        bins = []

        for i in range(self.n_bins):
            lower = bin_edges[i]
            upper = bin_edges[i + 1]
            if i == self.n_bins - 1:
                mask = (y_prob >= lower) & (y_prob <= upper)
            else:
                mask = (y_prob >= lower) & (y_prob < upper)

            count = int(np.sum(mask))
            if count == 0:
                continue

            avg_pred = float(np.mean(y_prob[mask]))
            avg_actual = float(np.mean(y_true[mask]))

            bins.append({
                "lower": round(lower, 2),
                "upper": round(upper, 2),
                "avg_predicted": round(avg_pred, 4),
                "avg_actual": round(avg_actual, 4),
                "count": count,
                "gap": round(abs(avg_pred - avg_actual), 4),
            })

        # Perfect calibration line
        perfect = [{"x": round(b["avg_predicted"], 4), "y": round(b["avg_predicted"], 4)} for b in bins]

        return {
            "bins": bins,
            "perfect_line": perfect,
            "n_samples": len(y_true),
        }

    # ===================== INTERNAL =====================

    def _compare_calibrators(
        self, y_true: np.ndarray, y_prob: np.ndarray
    ) -> tuple[float, float, str]:
        """Platt ve Isotonic'i karşılaştır — hangisi daha iyi?

        Returns:
            (platt_ece, isotonic_ece, best_calibrator)
        """
        from sklearn.isotonic import IsotonicRegression
        from sklearn.linear_model import LogisticRegression

        # Train/val split (zaman bazlı — son %30 val)
        n = len(y_true)
        split_idx = int(n * 0.7)
        if split_idx < 20 or n - split_idx < 10:
            return 0.0, 0.0, "insufficient_data"

        y_train, y_val = y_true[:split_idx], y_true[split_idx:]
        p_train, p_val = y_prob[:split_idx], y_prob[split_idx:]

        # Platt
        try:
            lr = LogisticRegression(max_iter=1000)
            lr.fit(p_train.reshape(-1, 1), y_train)
            platt_cal = lr.predict_proba(p_val.reshape(-1, 1))[:, 1]
            platt_ece = self._compute_ece(y_val, platt_cal)
        except Exception:
            platt_ece = 999.0

        # Isotonic
        try:
            iso = IsotonicRegression(out_of_bounds="clip")
            iso.fit(p_train, y_train)
            isotonic_cal = iso.predict(p_val)
            isotonic_ece = self._compute_ece(y_val, isotonic_cal)
        except Exception:
            isotonic_ece = 999.0

        if platt_ece < isotonic_ece:
            best = "platt"
        elif isotonic_ece < platt_ece:
            best = "isotonic"
        else:
            best = "equal"

        return platt_ece, isotonic_ece, best

    def _compute_nri(self, y_true: np.ndarray, y_prob: np.ndarray, threshold: float = 0.5) -> float:
        """Net Reclassification Index (NRI).

        Modelin doğru/yanlış sınıflandırdığı örnekleri
        yeniden sınıflandırma kalitesini ölçer.

        Basitleştirilmiş versiyon: doğru sınıflandırma oranı - yanlış sınıflandırma oranı.
        """
        preds = (y_prob > threshold).astype(int)
        correct = float(np.sum(preds == y_true))
        incorrect = float(np.sum(preds != y_true))
        total = len(y_true)

        if total == 0:
            return 0.0

        return (correct - incorrect) / total

    def _bootstrap_ece_ci(
        self, y_true: np.ndarray, y_prob: np.ndarray, confidence: float = 0.95
    ) -> tuple[float, float]:
        """Bootstrap ile ECE confidence interval hesapla."""
        n = len(y_true)
        if n < 30:
            ece = self._compute_ece(y_true, y_prob)
            return (ece, ece)

        ece_samples = []
        for _ in range(self.bootstrap_n):
            indices = np.random.choice(n, n, replace=True)
            ece_samples.append(self._compute_ece(y_true[indices], y_prob[indices]))

        alpha = (1 - confidence) / 2
        lower = float(np.percentile(ece_samples, alpha * 100))
        upper = float(np.percentile(ece_samples, (1 - alpha) * 100))
        return (lower, upper)

    def _bootstrap_brier_ci(
        self, y_true: np.ndarray, y_prob: np.ndarray, confidence: float = 0.95
    ) -> tuple[float, float]:
        """Bootstrap ile Brier score confidence interval hesapla."""
        from sklearn.metrics import brier_score_loss

        n = len(y_true)
        if n < 30:
            brier = float(brier_score_loss(y_true, y_prob))
            return (brier, brier)

        brier_samples = []
        for _ in range(self.bootstrap_n):
            indices = np.random.choice(n, n, replace=True)
            try:
                brier_samples.append(float(brier_score_loss(y_true[indices], y_prob[indices])))
            except Exception:
                continue

        if not brier_samples:
            return (0.0, 1.0)

        alpha = (1 - confidence) / 2
        lower = float(np.percentile(brier_samples, alpha * 100))
        upper = float(np.percentile(brier_samples, (1 - alpha) * 100))
        return (lower, upper)

    def _check_alerts(self, result: CalibrationResult, n_samples: int) -> None:
        """Kalibrasyon alarmlarını kontrol et."""
        now = datetime.now(UTC).isoformat()

        # ECE drift alarmı
        if len(self._calibration_history) >= 3:
            recent_ece = np.mean([h["ece"] for h in self._calibration_history[-3:]])
            if recent_ece > self.ece_threshold * 2:
                self._alerts.append(CalibrationAlert(
                    timestamp=now,
                    alert_type="DEGRADATION",
                    severity="HIGH",
                    message=f"ECE {recent_ece:.4f} — kalibrasyon bozuluyor",
                    metric="ece",
                    value=recent_ece,
                    threshold=self.ece_threshold,
                ))

        # Overconfidence alarmı
        if result.overconfident:
            self._alerts.append(CalibrationAlert(
                timestamp=now,
                alert_type="OVERCONFIDENCE",
                severity="MEDIUM",
                message=f"Model overconfident — ECE={result.expected_calibration_error:.4f}",
                metric="ece",
                value=result.expected_calibration_error,
                threshold=self.overconfidence_threshold,
            ))

        # Brier Skill Score negatifse (baseline'dan kötü)
        if result.brier_skill_score < 0:
            self._alerts.append(CalibrationAlert(
                timestamp=now,
                alert_type="DEGRADATION",
                severity="CRITICAL",
                message=f"Brier Skill Score negatif ({result.brier_skill_score:.4f}) — baseline'dan kötü",
                metric="brier_skill_score",
                value=result.brier_skill_score,
                threshold=0.0,
            ))

        # Alert history sınırla
        if len(self._alerts) > 100:
            self._alerts = self._alerts[-100:]

    def _compute_ece(self, y_true: np.ndarray, y_prob: np.ndarray) -> float:
        """Expected Calibration Error hesapla."""
        try:
            bin_edges = np.linspace(0, 1, self.n_bins + 1)
            ece = 0.0

            for i in range(self.n_bins):
                mask = (y_prob >= bin_edges[i]) & (y_prob < bin_edges[i + 1])
                if np.sum(mask) == 0:
                    continue

                bin_accuracy = float(np.mean(y_true[mask]))
                bin_confidence = float(np.mean(y_prob[mask]))
                bin_size = float(np.sum(mask)) / len(y_true)

                ece += bin_size * abs(bin_accuracy - bin_confidence)

            return ece
        except Exception:
            return 0.0
