"""
ALPHA BIST — Health Check Worker

Sistem sağlık kontrolü worker'ı.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import structlog

logger = structlog.get_logger()
_TZ_ISTANBUL = timezone(timedelta(hours=3))


class HealthCheckWorker:
    """Sistem sağlık kontrolü worker'ı."""

    def __init__(self):
        self._last_check: Optional[str] = None
        self._alerts: List[Dict[str, Any]] = []

    def run_full_check(self) -> Dict[str, Any]:
        """Tüm sistem sağlık kontrollerini çalıştır."""
        result = {
            "timestamp": datetime.now(_TZ_ISTANBUL).isoformat(),
            "checks": {},
            "alerts": [],
            "overall": "healthy",
        }

        # Market durumu
        try:
            from services.core.market_session_fsm import bist_session_fsm
            result["checks"]["market"] = {"status": "ok", **bist_session_fsm.get_status()}
        except Exception as e:
            result["checks"]["market"] = {"status": "warning", "warning": str(e)}

        # Model durumu
        import os
        model_dir = "ml/saved_models"
        if os.path.exists(model_dir):
            models = [f for f in os.listdir(model_dir) if f.endswith(('.pkl', '.json'))]
            result["checks"]["models"] = {"status": "ok" if models else "warning", "count": len(models)}
        else:
            result["checks"]["models"] = {"status": "warning", "warning": "No model directory"}

        # Disk
        try:
            import psutil
            disk = psutil.disk_usage('/')
            result["checks"]["disk"] = {"status": "ok", "percent": disk.percent}
        except ImportError:
            result["checks"]["disk"] = {"status": "ok", "message": "psutil not available"}

        # Alert üretimi
        for service, check in result["checks"].items():
            if check.get("status") == "error":
                result["alerts"].append({"level": "critical", "service": service})
                result["overall"] = "degraded"

        self._last_check = result["timestamp"]
        self._alerts = result["alerts"]
        return result

    def get_status(self) -> Dict[str, Any]:
        return {"last_check": self._last_check, "alert_count": len(self._alerts)}


health_check_worker = HealthCheckWorker()
