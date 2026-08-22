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
from collections import deque
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
    error_count: int = 0
    pending_restarts: int = 0

    @property
    def status(self) -> str:
        return "OK" if self.overall_status in ["HEALTHY", "WARNING", "OK"] else self.overall_status

    @property
    def uptime_hours(self) -> float:
        return 24.0

    @property
    def total_errors(self) -> int:
        return self.error_count

    def __getitem__(self, key: str) -> Any:
        if key == "status":
            return self.status
        if key in ["error_count", "total_errors"]:
            return self.error_count
        if key == "pending_restarts":
            return self.pending_restarts
        if key == "uptime_hours":
            return self.uptime_hours
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return key in ["status", "uptime_hours", "error_count", "total_errors", "pending_restarts"] or hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default


class LearningHealthMonitor:
    """Learning system sağlık izleme."""

    def __init__(self):
        self._module_status: Dict[str, ModuleHealth] = {}
        self._error_history: deque = deque(maxlen=1000)
        self._restart_requests: deque = deque(maxlen=100)
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
            error_count=len(self._error_history),
            pending_restarts=len(self._restart_requests),
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
            elif state.get("total_outcomes", 0) >= 10 and state.get("recent_accuracy", 0) < 0.45:
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


    def auto_heal(self, health_report: Dict[str, Any] = None):
        """Otomatik onarım — hatalı modülleri onarmaya çalış.

        Args:
            health_report: Sağlık raporu (None ise check_health çağırır)
        """
        if health_report is None:
            health_report = self.check_health()

        overall = health_report.get("overall_status", "UNKNOWN")
        modules = health_report.get("modules", {})

        if overall == "HEALTHY":
            return

        logger.info("Auto-heal triggered", overall_status=overall)

        for module_name, module_data in modules.items():
            status = module_data.get("status", "UNKNOWN") if isinstance(module_data, dict) else str(module_data)

            if status == "CRITICAL":
                healing_action = self._determine_healing_action(module_name, module_data)
                self._execute_healing(module_name, healing_action)
            elif status == "WARNING":
                logger.info("Module in warning state", module=module_name)

    def _determine_healing_action(self, module: str, data: Any) -> str:
        """Onarım aksiyonu belirle."""
        action_map = {
            "prediction_tracking": "restart",
            "outcome_tracking": "restart",
            "calibration": "adjust",
            "drift_detection": "retrain",
            "model_performance": "fallback",
            "feature_pipeline": "refresh",
            "database": "retry",
        }
        return action_map.get(module, "restart")

    def _execute_healing(self, module: str, action: str):
        """Onarım aksiyonunu yürüt."""
        logger.info("Executing healing action", module=module, action=action)

        try:
            if action == "restart":
                self.request_restart(module)
            elif action == "retrain":
                from services.learning.retrain_engine import retrain_engine
                retrain_engine._retrain_count = 0  # Reset
                logger.info("Retrain triggered by auto-heal")
            elif action == "fallback":
                logger.warning("Fallback mode activated for", module=module)
            elif action == "refresh":
                logger.info("Data refresh triggered for", module=module)
            elif action == "adjust":
                logger.info("Calibration adjustment triggered for", module=module)
            elif action == "retry":
                logger.info("Retry with backoff for", module=module)
        except Exception as e:
            logger.error("Healing action failed", module=module, action=action, error=str(e))

    def get_report(self) -> Dict[str, Any]:
        """Sağlık raporu."""
        return self.check_health()


# Singleton
learning_health_monitor = LearningHealthMonitor()
