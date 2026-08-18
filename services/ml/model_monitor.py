"""ALPHA BIST — Model Monitor (Nihai).

Performans tracking, prediction drift, model decay detection, auto-retrain trigger.
"""
import numpy as np
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class MonitorReport:
    """Monitoring raporu."""
    model_id: str
    metric_name: str
    current_value: float
    historical_mean: float
    historical_std: float
    z_score: float
    decay_detected: bool
    retrain_recommended: bool
    alert_level: str  # OK, WARNING, CRITICAL


class ModelMonitor:
    """Model performans monitoring."""

    def __init__(
        self,
        decay_z_threshold: float = -2.0,
        retrain_z_threshold: float = -3.0,
        min_history: int = 10,
        window_size: int = 20,
    ):
        self.decay_z_threshold = decay_z_threshold
        self.retrain_z_threshold = retrain_z_threshold
        self.min_history = min_history
        self.window_size = window_size
        self._metric_history: Dict[str, List[float]] = {}  # metric_name → [values]
        self._prediction_history: List[Dict[str, Any]] = []

    def record_metric(self, metric_name: str, value: float):
        """Performans metriği kaydet."""
        if metric_name not in self._metric_history:
            self._metric_history[metric_name] = []
        self._metric_history[metric_name].append(value)

        # Son N tut
        if len(self._metric_history[metric_name]) > self.window_size * 3:
            self._metric_history[metric_name] = self._metric_history[metric_name][-self.window_size * 2:]

    def record_prediction(self, prediction: float, actual: Optional[float] = None, ticker: str = ""):
        """Tahmin kaydet."""
        self._prediction_history.append({
            "prediction": prediction,
            "actual": actual,
            "ticker": ticker,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correct": (prediction > 0.5 and actual > 0) or (prediction <= 0.5 and actual <= 0) if actual is not None else None,
        })

        if len(self._prediction_history) > 1000:
            self._prediction_history = self._prediction_history[-500:]

    def check_decay(self, metric_name: str = "ic") -> MonitorReport:
        """Model decay kontrolü.

        Son periyot performansı vs tarihsel performans.
        """
        history = self._metric_history.get(metric_name, [])

        if len(history) < self.min_history:
            return MonitorReport(
                model_id="",
                metric_name=metric_name,
                current_value=0,
                historical_mean=0,
                historical_std=0,
                z_score=0,
                decay_detected=False,
                retrain_recommended=False,
                alert_level="OK",
            )

        # Son periyot vs tarihsel
        recent = history[-min(self.window_size, len(history) // 2):]
        historical = history[:-len(recent)] if len(recent) < len(history) else history

        current_value = float(np.mean(recent))
        hist_mean = float(np.mean(historical))
        hist_std = float(np.std(historical)) if len(historical) > 1 else 0.01

        z_score = (current_value - hist_mean) / max(hist_std, 0.001)

        # Decay tespiti
        decay_detected = z_score < self.decay_z_threshold
        retrain_recommended = z_score < self.retrain_z_threshold

        # Alert level
        if retrain_recommended:
            alert_level = "CRITICAL"
        elif decay_detected:
            alert_level = "WARNING"
        else:
            alert_level = "OK"

        return MonitorReport(
            model_id="",
            metric_name=metric_name,
            current_value=round(current_value, 4),
            historical_mean=round(hist_mean, 4),
            historical_std=round(hist_std, 4),
            z_score=round(z_score, 4),
            decay_detected=decay_detected,
            retrain_recommended=retrain_recommended,
            alert_level=alert_level,
        )

    def check_prediction_drift(self) -> Dict[str, Any]:
        """Tahmin drift'i kontrolü — tahmin dağılımı değişti mi?"""
        if len(self._prediction_history) < self.min_history * 2:
            return {"drift_detected": False, "reason": "insufficient_data"}

        preds = [p["prediction"] for p in self._prediction_history]
        recent = preds[-self.window_size:]
        historical = preds[:-len(recent)]

        # Distribution comparison
        from scipy import stats
        ks_stat, p_value = stats.ks_2samp(historical, recent)

        return {
            "drift_detected": p_value < 0.05,
            "ks_statistic": round(float(ks_stat), 4),
            "p_value": round(float(p_value), 4),
            "recent_mean": round(float(np.mean(recent)), 4),
            "historical_mean": round(float(np.mean(historical)), 4),
        }

    def get_win_rate(self, window: Optional[int] = None) -> float:
        """Son periyot win rate."""
        predictions = self._prediction_history
        if window:
            predictions = predictions[-window:]

        correct = [p for p in predictions if p.get("correct") is not None]
        if not correct:
            return 0.0

        return round(sum(1 for p in correct if p["correct"]) / len(correct), 4)

    def get_summary(self) -> Dict[str, Any]:
        """Monitoring özeti."""
        summaries = {}
        for metric_name in self._metric_history:
            report = self.check_decay(metric_name)
            summaries[metric_name] = {
                "current": report.current_value,
                "historical_mean": report.historical_mean,
                "z_score": report.z_score,
                "alert": report.alert_level,
            }

        return {
            "metrics": summaries,
            "win_rate": self.get_win_rate(),
            "total_predictions": len(self._prediction_history),
            "prediction_drift": self.check_prediction_drift(),
        }
