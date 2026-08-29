"""ALPHA BIST — Enhanced Calibration Engine v1.0

Mevcut confidence_calibrator'ı genişletir:
- Out-of-fold prediction generation
- Calibration drift monitoring
- Calibration retraining schedule
- Isotonic regression comparison
- Regime-specific calibration with auto-retrain

Kullanım:
    from services.ml.calibration_enhanced import calibration_enhanced

    # Out-of-fold predictions oluştur
    oof_preds = calibration_enhanced.generate_out_of_fold(model, X, y, cv=5)

    # Calibration drift kontrolü
    drift = calibration_enhanced.check_calibration_drift()

    # Retrain schedule
    should_retrain = calibration_enhanced.should_retrain_calibration()
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class OutOfFoldResult:
    """Out-of-fold prediction sonucu."""

    predictions: np.ndarray
    fold_indices: list[tuple[np.ndarray, np.ndarray]]
    mean_ic: float
    mean_brier: float
    n_folds: int


@dataclass
class CalibrationDriftReport:
    """Calibration drift raporu."""

    current_brier: float
    baseline_brier: float
    brier_change: float
    current_ece: float
    baseline_ece: float
    ece_change: float
    drift_detected: bool
    severity: str  # OK, WARNING, ALERT
    recommendation: str


@dataclass
class RetrainSchedule:
    """Calibration retrain durumu."""

    last_retrain: str
    hours_since_retrain: float
    should_retrain: bool
    reason: str
    next_retrain: str


class CalibrationEnhanced:
    """Gelişmiş calibration motoru.

    Özellikler:
    - Out-of-fold prediction generation (data leakage önleme)
    - Calibration drift monitoring (Brier/ECE trend)
    - Otomatik retrain schedule
    - Isotonic vs Platt karşılaştırma
    """

    def __init__(
        self,
        retrain_interval_hours: float = 24.0,
        drift_threshold: float = 0.05,
        min_samples_for_retrain: int = 100,
    ):
        """Otomatik eklendi."""
        self.retrain_interval_hours = retrain_interval_hours
        self.drift_threshold = drift_threshold
        self.min_samples_for_retrain = min_samples_for_retrain
        self._brier_history: list[tuple[str, float]] = []
        self._ece_history: list[tuple[str, float]] = []
        self._last_retrain: datetime | None = None
        self._baseline_brier: float | None = None
        self._baseline_ece: float | None = None

    def generate_out_of_fold(
        self,
        model: Any,
        X: np.ndarray,
        y: np.ndarray,
        cv: int = 5,
    ) -> OutOfFoldResult:
        """Out-of-fold predictions oluştur.

        Data leakage önleme: Her fold'da model sadece train verisiyle eğitilir,
        validation verisi için tahmin yapılır.

        Args:
            model: sklearn-compatible model (fit/predict veya fit/predict_proba)
            X: Feature matrix
            y: Target array
            cv: Fold sayısı

        Returns:
            OutOfFoldResult
        """
        import copy

        from sklearn.model_selection import TimeSeriesSplit

        kf = TimeSeriesSplit(n_splits=cv)
        oof_predictions = np.zeros(len(y))
        fold_indices: list[tuple[np.ndarray, np.ndarray]] = []
        fold_ics: list[float] = []
        fold_briers: list[float] = []

        for fold_idx, (train_idx, val_idx) in enumerate(kf.split(X)):
            X_train, X_val = X[train_idx], X[val_idx]
            y_train, y_val = y[train_idx], y[val_idx]

            try:
                fold_model = copy.deepcopy(model)
                fold_model.fit(X_train, y_train)

                if hasattr(fold_model, "predict_proba"):
                    preds = fold_model.predict_proba(X_val)[:, 1]
                else:
                    preds = fold_model.predict(X_val)

                oof_predictions[val_idx] = preds
                fold_indices.append((train_idx, val_idx))

                # IC
                try:
                    ic = float(np.corrcoef(preds, y_val)[0, 1])
                    if np.isfinite(ic):
                        fold_ics.append(ic)
                except Exception:
                    logger.error("Exception caught", exc_info=True)

                # Brier
                try:
                    brier = float(np.mean((preds - y_val) ** 2))
                    fold_briers.append(brier)
                except Exception:
                    logger.error("Exception caught", exc_info=True)

            except Exception as e:
                logger.warning("oof_fold_failed", fold=fold_idx, error=str(e))

        return OutOfFoldResult(
            predictions=oof_predictions,
            fold_indices=fold_indices,
            mean_ic=round(float(np.mean(fold_ics)), 4) if fold_ics else 0.0,
            mean_brier=round(float(np.mean(fold_briers)), 4) if fold_briers else 0.0,
            n_folds=cv,
        )

    def record_calibration_metrics(
        self,
        brier_score: float,
        ece: float,
    ) -> None:
        """Calibration metriklerini kaydet.

        Args:
            brier_score: Brier skoru
            ece: Expected Calibration Error
        """
        now = datetime.now(UTC).isoformat()
        self._brier_history.append((now, brier_score))
        self._ece_history.append((now, ece))

        if len(self._brier_history) > 500:
            self._brier_history = self._brier_history[-500:]
            self._ece_history = self._ece_history[-500:]

        # İlk kayıt baseline olarak kullan
        if self._baseline_brier is None:
            self._baseline_brier = brier_score
        if self._baseline_ece is None:
            self._baseline_ece = ece

    def check_calibration_drift(self) -> CalibrationDriftReport:
        """Calibration drift kontrolü.

        Returns:
            CalibrationDriftReport
        """
        if len(self._brier_history) < 2:
            return CalibrationDriftReport(
                current_brier=0.0,
                baseline_brier=0.0,
                brier_change=0.0,
                current_ece=0.0,
                baseline_ece=0.0,
                ece_change=0.0,
                drift_detected=False,
                severity="OK",
                recommendation="Yetersiz veri — drift analizi yapılamaz",
            )

        current_brier = self._brier_history[-1][1]
        current_ece = self._ece_history[-1][1]

        baseline_brier = self._baseline_brier or self._brier_history[0][1]
        baseline_ece = self._baseline_ece or self._ece_history[0][1]

        brier_change = current_brier - baseline_brier
        ece_change = current_ece - baseline_ece

        drift_detected = abs(brier_change) > self.drift_threshold or abs(ece_change) > self.drift_threshold

        if brier_change > 0.10 or ece_change > 0.10:
            severity = "ALERT"
            recommendation = "Calibration ciddi şekilde bozuldu — acil retrain gerekli"
        elif brier_change > 0.05 or ece_change > 0.05:
            severity = "WARNING"
            recommendation = "Calibration drift tespit edildi — retrain önerilir"
        elif drift_detected:
            severity = "WARNING"
            recommendation = "Hafif calibration değişimi — izlemeye devam edin"
        else:
            severity = "OK"
            recommendation = "Calibration stabil"

        return CalibrationDriftReport(
            current_brier=round(current_brier, 4),
            baseline_brier=round(baseline_brier, 4),
            brier_change=round(brier_change, 4),
            current_ece=round(current_ece, 4),
            baseline_ece=round(baseline_ece, 4),
            ece_change=round(ece_change, 4),
            drift_detected=drift_detected,
            severity=severity,
            recommendation=recommendation,
        )

    def should_retrain_calibration(self) -> RetrainSchedule:
        """Calibration retrain gerekli mi?

        Returns:
            RetrainSchedule
        """
        now = datetime.now(UTC)

        if self._last_retrain is None:
            return RetrainSchedule(
                last_retrain="Never",
                hours_since_retrain=float("inf"),
                should_retrain=True,
                reason="İlk calibration — retrain gerekli",
                next_retrain=now.isoformat(),
            )

        hours_since = (now - self._last_retrain).total_seconds() / 3600

        # Zaman bazlı kontrol
        if hours_since >= self.retrain_interval_hours:
            return RetrainSchedule(
                last_retrain=self._last_retrain.isoformat(),
                hours_since_retrain=round(hours_since, 1),
                should_retrain=True,
                reason=f"Son retrain'den bu yana {hours_since:.1f} saat geçti (eşik: {self.retrain_interval_hours}h)",
                next_retrain=now.isoformat(),
            )

        # Drift bazlı kontrol
        drift = self.check_calibration_drift()
        if drift.severity == "ALERT":
            return RetrainSchedule(
                last_retrain=self._last_retrain.isoformat(),
                hours_since_retrain=round(hours_since, 1),
                should_retrain=True,
                reason=f"Calibration drift ALERT: {drift.recommendation}",
                next_retrain=now.isoformat(),
            )

        next_retrain = self._last_retrain + timedelta(hours=self.retrain_interval_hours)

        return RetrainSchedule(
            last_retrain=self._last_retrain.isoformat(),
            hours_since_retrain=round(hours_since, 1),
            should_retrain=False,
            reason="Calibration güncel",
            next_retrain=next_retrain.isoformat(),
        )

    def mark_retrained(self) -> None:
        """Calibration retrain edildi olarak işaretle."""
        self._last_retrain = datetime.now(UTC)
        logger.info("calibration_retrained", timestamp=self._last_retrain.isoformat())

    def compare_calibration_methods(
        self,
        predictions: list[dict],
    ) -> dict[str, Any]:
        """Platt vs Isotonic calibration karşılaştırması.

        Args:
            predictions: [{confidence, outcome}]

        Returns:
            {platt_brier, isotonic_brier, better_method}
        """
        if len(predictions) < 30:
            return {"error": "Yetersiz veri"}

        confidences = np.array([p["confidence"] for p in predictions])
        outcomes = np.array([float(p["outcome"]) for p in predictions])

        results: dict[str, Any] = {}

        # Platt scaling
        try:
            from scipy.optimize import minimize

            n_pos = np.sum(outcomes == 1)
            n_neg = np.sum(outcomes == 0)
            targets = np.where(outcomes == 1, (n_pos + 1) / (n_pos + 2), 1 / (n_neg + 2))

            def platt_loss(params) -> Any:
                """Otomatik eklendi."""
                a, b = params
                f = np.clip(a * confidences + b, -500, 500)
                p = np.clip(1.0 / (1.0 + np.exp(f)), 1e-10, 1 - 1e-10)
                return -np.mean(targets * np.log(p) + (1 - targets) * np.log(1 - p))

            res = minimize(platt_loss, x0=[-1.0, 0.0], method="Nelder-Mead")
            a, b = res.x
            platt_calibrated = 1.0 / (1.0 + np.exp(np.clip(a * confidences + b, -500, 500)))
            platt_brier = float(np.mean((platt_calibrated - outcomes) ** 2))
            results["platt_brier"] = round(platt_brier, 4)
            results["platt_params"] = {"a": round(a, 4), "b": round(b, 4)}
        except Exception as e:
            results["platt_brier"] = None
            results["platt_error"] = str(e)

        # Isotonic regression
        try:
            from sklearn.isotonic import IsotonicRegression

            iso = IsotonicRegression(out_of_bounds="clip")
            iso.fit(confidences, outcomes)
            isotonic_calibrated = iso.predict(confidences)
            isotonic_brier = float(np.mean((isotonic_calibrated - outcomes) ** 2))
            results["isotonic_brier"] = round(isotonic_brier, 4)
        except Exception as e:
            results["isotonic_brier"] = None
            results["isotonic_error"] = str(e)

        # Karşılaştırma
        if results.get("platt_brier") is not None and results.get("isotonic_brier") is not None:
            if results["platt_brier"] < results["isotonic_brier"]:
                results["better_method"] = "platt"
                results["improvement"] = round(results["isotonic_brier"] - results["platt_brier"], 4)
            else:
                results["better_method"] = "isotonic"
                results["improvement"] = round(results["platt_brier"] - results["isotonic_brier"], 4)

        return results

    def get_brier_history(self, limit: int = 50) -> list[tuple[str, float]]:
        """Brier score geçmişi."""
        return self._brier_history[-limit:]

    def get_ece_history(self, limit: int = 50) -> list[tuple[str, float]]:
        """ECE geçmişi."""
        return self._ece_history[-limit:]


# Singleton
calibration_enhanced = CalibrationEnhanced()
