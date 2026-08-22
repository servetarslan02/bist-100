"""ALPHA BIST — Model Monitor (Nihai —⭐⭐⭐⭐⭐).

Performans tracking, prediction drift, model decay detection,
auto-retrain trigger, dashboard data, alerting system.
"""
import numpy as np
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
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
    trend: str = ""  # improving, degrading, stable


@dataclass
class Alert:
    """Alert kaydı."""
    timestamp: str
    model_id: str
    alert_type: str  # DECAY, DRIFT, RETRAIN, PERFORMANCE
    severity: str  # WARNING, CRITICAL
    message: str
    metric_name: str
    current_value: float
    threshold: float


class ModelMonitor:
    """Model performans monitoring —⭐⭐⭐⭐⭐ seviye.

    Özellikler:
    - Performance tracking (IC, Sharpe, win rate zaman içinde)
    - Prediction drift detection (KS test)
    - Model decay detection (z-score based)
    - Auto-retrain trigger (decay eşiği aşıldığında)
    - Monitoring dashboard data (grafik için)
    - Alerting system (WARNING/CRITICAL)
    - Multi-metric monitoring
    - Performance trend analysis
    - Rolling window statistics
    - Model health score
    """

    def __init__(
        self,
        decay_z_threshold: float = -2.0,
        retrain_z_threshold: float = -3.0,
        min_history: int = 10,
        window_size: int = 20,
        alert_cooldown_minutes: int = 60,
    ):
        self.decay_z_threshold = decay_z_threshold
        self.retrain_z_threshold = retrain_z_threshold
        self.min_history = min_history
        self.window_size = window_size
        self.alert_cooldown_minutes = alert_cooldown_minutes
        self._metric_history: Dict[str, List[Tuple[str, float]]] = {}  # metric → [(timestamp, value)]
        self._prediction_history: List[Dict[str, Any]] = []
        self._alerts: List[Alert] = []
        self._last_alert: Dict[str, datetime] = {}
        self._retrain_callbacks: List[Any] = []

    def record_metric(self, metric_name: str, value: float, model_id: str = ""):
        """Performans metriği kaydet."""
        if metric_name not in self._metric_history:
            self._metric_history[metric_name] = []
        self._metric_history[metric_name].append((
            datetime.now(timezone.utc).isoformat(),
            value,
        ))

        # Son N tut
        if len(self._metric_history[metric_name]) > self.window_size * 3:
            self._metric_history[metric_name] = self._metric_history[metric_name][-self.window_size * 2:]

        # Decay check
        report = self.check_decay(metric_name, model_id)
        if report.alert_level in ("WARNING", "CRITICAL"):
            self._emit_alert(report, model_id)

    def record_prediction(self, prediction: float, actual: Optional[float] = None, ticker: str = ""):
        """Tahmin kaydet."""
        self._prediction_history.append({
            "prediction": prediction,
            "actual": actual,
            "ticker": ticker,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correct": (prediction > 0.5 and actual > 0) or (prediction <= 0.5 and actual <= 0) if actual is not None else None,
        })
        if len(self._prediction_history) > 5000:
            self._prediction_history = self._prediction_history[-5000:]

        if len(self._prediction_history) > 1000:
            self._prediction_history = self._prediction_history[-500:]

    def check_decay(self, metric_name: str = "ic", model_id: str = "") -> MonitorReport:
        """Model decay kontrolü."""
        history = self._metric_history.get(metric_name, [])
        values = [v for _, v in history]

        if len(values) < self.min_history:
            return MonitorReport(
                model_id=model_id,
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
        recent = values[-min(self.window_size, len(values) // 2):]
        historical = values[:-len(recent)] if len(recent) < len(values) else values

        current_value = float(np.mean(recent))
        hist_mean = float(np.mean(historical))
        hist_std = float(np.std(historical)) if len(historical) > 1 else 0.01

        z_score = (current_value - hist_mean) / max(hist_std, 0.001)

        # Trend
        trend = self._compute_trend(values)

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
            model_id=model_id,
            metric_name=metric_name,
            current_value=round(current_value, 4),
            historical_mean=round(hist_mean, 4),
            historical_std=round(hist_std, 4),
            z_score=round(z_score, 4),
            decay_detected=decay_detected,
            retrain_recommended=retrain_recommended,
            alert_level=alert_level,
            trend=trend,
        )

    def check_prediction_drift(self) -> Dict[str, Any]:
        """Tahmin drift'i kontrolü."""
        if len(self._prediction_history) < self.min_history * 2:
            return {"drift_detected": False, "reason": "insufficient_data"}

        preds = [p["prediction"] for p in self._prediction_history]
        recent = preds[-self.window_size:]
        historical = preds[:-len(recent)]

        from scipy import stats
        ks_stat, p_value = stats.ks_2samp(historical, recent)

        return {
            "drift_detected": p_value < 0.05,
            "ks_statistic": round(float(ks_stat), 4),
            "p_value": round(float(p_value), 4),
            "recent_mean": round(float(np.mean(recent)), 4),
            "historical_mean": round(float(np.mean(historical)), 4),
            "recent_std": round(float(np.std(recent)), 4),
            "historical_std": round(float(np.std(historical)), 4),
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

    def get_health_score(self, model_id: str = "") -> Dict[str, Any]:
        """Model sağlık skoru (0-100)."""
        scores = []
        details = {}

        # Metric health
        for metric_name in self._metric_history:
            report = self.check_decay(metric_name, model_id)
            if report.alert_level == "OK":
                metric_score = 100
            elif report.alert_level == "WARNING":
                metric_score = 50
            else:
                metric_score = 10
            scores.append(metric_score)
            details[metric_name] = {
                "score": metric_score,
                "z_score": report.z_score,
                "trend": report.trend,
            }

        # Prediction drift
        drift = self.check_prediction_drift()
        if drift.get("drift_detected"):
            scores.append(30)
            details["prediction_drift"] = "DRIFT_DETECTED"
        else:
            scores.append(90)
            details["prediction_drift"] = "OK"

        # Win rate
        win_rate = self.get_win_rate()
        if win_rate > 0.55:
            scores.append(90)
        elif win_rate > 0.5:
            scores.append(70)
        elif win_rate > 0.45:
            scores.append(50)
        else:
            scores.append(20)
        details["win_rate"] = win_rate

        overall = int(np.mean(scores)) if scores else 0

        return {
            "overall_score": overall,
            "grade": "A" if overall >= 80 else "B" if overall >= 60 else "C" if overall >= 40 else "D",
            "details": details,
            "n_metrics": len(self._metric_history),
            "n_predictions": len(self._prediction_history),
        }

    def get_dashboard_data(self, model_id: str = "") -> Dict[str, Any]:
        """Dashboard için veri hazırla."""
        # Metric time series
        metric_series = {}
        for metric_name, history in self._metric_history.items():
            timestamps = [h[0] for h in history[-50:]]
            values = [h[1] for h in history[-50:]]
            metric_series[metric_name] = {
                "timestamps": timestamps,
                "values": [round(v, 4) for v in values],
                "current": round(values[-1], 4) if values else 0,
                "mean": round(float(np.mean(values)), 4) if values else 0,
            }

        # Alerts
        recent_alerts = [
            {
                "timestamp": a.timestamp,
                "type": a.alert_type,
                "severity": a.severity,
                "message": a.message,
            }
            for a in self._alerts[-10:]
        ]

        # Health
        health = self.get_health_score(model_id)

        return {
            "model_id": model_id,
            "health": health,
            "metric_series": metric_series,
            "recent_alerts": recent_alerts,
            "prediction_drift": self.check_prediction_drift(),
            "win_rate": self.get_win_rate(),
            "summary": self.get_summary(),
        }

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
                "trend": report.trend,
            }

        return {
            "metrics": summaries,
            "win_rate": self.get_win_rate(),
            "total_predictions": len(self._prediction_history),
            "prediction_drift": self.check_prediction_drift(),
            "n_alerts": len(self._alerts),
            "health_score": self.get_health_score().get("overall_score", 0),
        }

    def get_alerts(self, severity: Optional[str] = None) -> List[Dict[str, Any]]:
        """Alert listesi."""
        alerts = self._alerts
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        return [
            {
                "timestamp": a.timestamp,
                "model_id": a.model_id,
                "type": a.alert_type,
                "severity": a.severity,
                "message": a.message,
            }
            for a in alerts[-50:]
        ]

    def register_retrain_callback(self, callback: Any):
        """Auto-retrain callback kaydet."""
        self._retrain_callbacks.append(callback)
        if len(self._retrain_callbacks) > 100:
            self._retrain_callbacks = self._retrain_callbacks[-100:]

    def _compute_trend(self, values: List[float]) -> str:
        """Performans trendi."""
        if len(values) < 5:
            return "stable"

        recent = np.mean(values[-5:])
        older = np.mean(values[:-5])

        change = (recent - older) / max(abs(older), 1e-8)

        if change > 0.05:
            return "improving"
        elif change < -0.05:
            return "degrading"
        else:
            return "stable"

    def _emit_alert(self, report: MonitorReport, model_id: str):
        """Alert oluştur."""
        # Cooldown check
        alert_key = f"{model_id}_{report.metric_name}"
        now = datetime.now(timezone.utc)
        last = self._last_alert.get(alert_key)
        if last and (now - last).total_seconds() < self.alert_cooldown_minutes * 60:
            return

        alert = Alert(
            timestamp=now.isoformat(),
            model_id=model_id,
            alert_type="DECAY" if report.decay_detected else "PERFORMANCE",
            severity=report.alert_level,
            message=f"{report.metric_name}: {report.current_value} (z={report.z_score}, trend={report.trend})",
            metric_name=report.metric_name,
            current_value=report.current_value,
            threshold=self.decay_z_threshold,
        )

        self._alerts.append(alert)
        if len(self._alerts) > 500:
            self._alerts = self._alerts[-500:]
        self._last_alert[alert_key] = now

        logger.warning("model_alert", **{"model_id": model_id, "severity": report.alert_level, "metric": report.metric_name, "z_score": report.z_score})

        # Auto-retrain callback
        if report.retrain_recommended and self._retrain_callbacks:
            for callback in self._retrain_callbacks:
                try:
                    callback(model_id, report)
                except Exception as e:
                    logger.error("retrain_callback_failed", error=str(e))
