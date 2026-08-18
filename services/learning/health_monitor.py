"""
ALPHA BIST — Health Monitor v1.0

Learning system sağlık izleme:
- Modül bazlı health check
- Otomatik alerting
- Self-healing tetikleme
- Cascade failure prevention

KURAL: Bir modül çökse diğerleri çalışmaya devam etmeli.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

from services.learning.config.learning_config import learning_settings

logger = structlog.get_logger()


@dataclass
class ModuleHealth:
    """Modül sağlık durumu."""
    module: str
    status: str  # HEALTHY, WARNING, CRITICAL, DEGRADED, RESTARTING
    last_check: str
    error_count: int
    last_error: Optional[str]
    uptime_hours: float


@dataclass
class HealthReport:
    """Kapsamlı sağlık raporu."""
    timestamp: str
    overall_status: str
    modules: Dict[str, ModuleHealth]
    critical_modules: List[str]
    warning_modules: List[str]
    recommendations: List[str]


class LearningHealthMonitor:
    """Learning system sağlık izleme."""

    def __init__(self):
        self._module_status: Dict[str, ModuleHealth] = {}
        self._error_history: List[Dict] = []
        self._restart_requests: List[str] = []
        self._start_time = datetime.now(timezone.utc)

    def check_health(self) -> HealthReport:
        """Tüm modüllerin sağlık durumunu kontrol et."""
        modules = {}
        critical = []
        warnings = []
        recommendations = []

        # Her modül için health check
        checks = {
            "prediction_tracking": self._check_prediction_tracking(),
            "outcome_tracking": self._check_outcome_tracking(),
            "calibration": self._check_calibration(),
            "drift_detection": self._check_drift_detection(),
            "model_performance": self._check_model_performance(),
            "feature_pipeline": self._check_feature_pipeline(),
        }

        for module, health in checks.items():
            modules[module] = health
            if health.status == "CRITICAL":
                critical.append(module)
                recommendations.append(f"Immediate attention required: {module}")
            elif health.status == "WARNING":
                warnings.append(module)

        overall = "CRITICAL" if critical else ("WARNING" if warnings else "HEALTHY")

        report = HealthReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            overall_status=overall,
            modules=modules,
            critical_modules=critical,
            warning_modules=warnings,
            recommendations=recommendations,
        )

        if critical:
            logger.warning("Health check: CRITICAL modules detected", modules=critical)

        return report

    def request_restart(self, module: str):
        """Modül restart isteği."""
        if module not in self._restart_requests:
            self._restart_requests.append(module)
            logger.info("Restart requested", module=module)

    def get_restart_requests(self) -> List[str]:
        """Restart isteklerini al ve temizle."""
        requests = self._restart_requests.copy()
        self._restart_requests.clear()
        return requests

    def record_error(self, module: str, error: str):
        """Hata kaydet."""
        self._error_history.append({
            "module": module,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Modül status güncelle
        if module in self._module_status:
            self._module_status[module].error_count += 1
            self._module_status[module].last_error = error

    def get_report(self) -> Dict[str, Any]:
        """Rapor."""
        uptime = (datetime.now(timezone.utc) - self._start_time).total_seconds() / 3600
        return {
            "status": "OK",
            "uptime_hours": round(uptime, 1),
            "module_count": len(self._module_status),
            "error_count": len(self._error_history),
            "pending_restarts": len(self._restart_requests),
        }

    # ===================== HEALTH CHECKS =====================

    def _check_prediction_tracking(self) -> ModuleHealth:
        """Prediction tracking sağlık kontrolü."""
        try:
            from services.learning.integrated_learning import learning_system
            stats = learning_system.get_stats()
            if stats.get("total_predictions", 0) > 0:
                status = "HEALTHY"
            else:
                status = "WARNING"
        except Exception as e:
            status = "CRITICAL"
            self.record_error("prediction_tracking", str(e))
            stats = {}

        return ModuleHealth(
            module="prediction_tracking",
            status=status,
            last_check=datetime.now(timezone.utc).isoformat(),
            error_count=sum(1 for e in self._error_history if e["module"] == "prediction_tracking"),
            last_error=next((e["error"] for e in reversed(self._error_history) if e["module"] == "prediction_tracking"), None),
            uptime_hours=(datetime.now(timezone.utc) - self._start_time).total_seconds() / 3600,
        )

    def _check_outcome_tracking(self) -> ModuleHealth:
        """Outcome tracking sağlık kontrolü."""
        try:
            from services.learning.outcome_tracker import outcome_tracker
            stats = outcome_tracker.get_stats()
            status = "HEALTHY"
        except Exception as e:
            status = "CRITICAL"
            self.record_error("outcome_tracking", str(e))

        return ModuleHealth(
            module="outcome_tracking",
            status=status,
            last_check=datetime.now(timezone.utc).isoformat(),
            error_count=sum(1 for e in self._error_history if e["module"] == "outcome_tracking"),
            last_error=next((e["error"] for e in reversed(self._error_history) if e["module"] == "outcome_tracking"), None),
            uptime_hours=0,
        )

    def _check_calibration(self) -> ModuleHealth:
        """Calibration sağlık kontrolü."""
        try:
            from services.learning.calibration import confidence_calibrator
            report = confidence_calibrator.get_calibration_report()
            status = "HEALTHY" if report.get("status") == "OK" else "WARNING"
        except Exception as e:
            status = "CRITICAL"
            self.record_error("calibration", str(e))

        return ModuleHealth(
            module="calibration",
            status=status,
            last_check=datetime.now(timezone.utc).isoformat(),
            error_count=sum(1 for e in self._error_history if e["module"] == "calibration"),
            last_error=next((e["error"] for e in reversed(self._error_history) if e["module"] == "calibration"), None),
            uptime_hours=0,
        )

    def _check_drift_detection(self) -> ModuleHealth:
        """Drift detection sağlık kontrolü."""
        try:
            from services.learning.drift_detector import advanced_drift_detector
            report = advanced_drift_detector.get_drift_report()
            if report.get("overall_drift"):
                status = "WARNING"
            else:
                status = "HEALTHY"
        except Exception as e:
            status = "CRITICAL"
            self.record_error("drift_detection", str(e))

        return ModuleHealth(
            module="drift_detection",
            status=status,
            last_check=datetime.now(timezone.utc).isoformat(),
            error_count=sum(1 for e in self._error_history if e["module"] == "drift_detection"),
            last_error=next((e["error"] for e in reversed(self._error_history) if e["module"] == "drift_detection"), None),
            uptime_hours=0,
        )

    def _check_model_performance(self) -> ModuleHealth:
        """Model performans sağlık kontrolü."""
        try:
            from services.learning.learning_loop import learning_loop
            state = learning_loop.get_state()
            if state.get("retrain_needed"):
                status = "WARNING"
            elif state.get("recent_accuracy", 0) < 0.45:
                status = "CRITICAL"
            else:
                status = "HEALTHY"
        except Exception as e:
            status = "CRITICAL"
            self.record_error("model_performance", str(e))

        return ModuleHealth(
            module="model_performance",
            status=status,
            last_check=datetime.now(timezone.utc).isoformat(),
            error_count=sum(1 for e in self._error_history if e["module"] == "model_performance"),
            last_error=next((e["error"] for e in reversed(self._error_history) if e["module"] == "model_performance"), None),
            uptime_hours=0,
        )

    def _check_feature_pipeline(self) -> ModuleHealth:
        """Feature pipeline sağlık kontrolü."""
        # Basit: feature_tracker'a bak
        try:
            from services.learning.feature_tracker import feature_importance_tracker
            report = feature_importance_tracker.get_report()
            status = "HEALTHY" if report.get("total_records", 0) > 0 else "WARNING"
        except Exception as e:
            status = "CRITICAL"
            self.record_error("feature_pipeline", str(e))

        return ModuleHealth(
            module="feature_pipeline",
            status=status,
            last_check=datetime.now(timezone.utc).isoformat(),
            error_count=sum(1 for e in self._error_history if e["module"] == "feature_pipeline"),
            last_error=next((e["error"] for e in reversed(self._error_history) if e["module"] == "feature_pipeline"), None),
            uptime_hours=0,
        )


# Singleton
learning_health_monitor = LearningHealthMonitor()
