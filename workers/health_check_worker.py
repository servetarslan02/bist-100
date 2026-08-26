"""
ALPHA BIST — Health Check Worker

Sistem sağlık kontrolü worker'ı.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
import structlog

logger = structlog.get_logger()
_TZ_ISTANBUL = timezone(timedelta(hours=3))


class HealthCheckWorker:
    """Sistem sağlık kontrolü worker'ı."""

    def __init__(self):
        self._last_check: Optional[str] = None

    def run_full_check(self) -> Dict[str, Any]:
        """Tüm sistem sağlık kontrollerini çalıştır."""
        result = {
            "timestamp": datetime.now(_TZ_ISTANBUL).isoformat(),
            "checks": {},
            "overall": "healthy",
        }

        try:
            from services.core.market_session_fsm import bist_session_fsm
            result["checks"]["market"] = {"status": "ok", **bist_session_fsm.get_status()}
        except Exception as e:
            result["checks"]["market"] = {"status": "warning", "warning": str(e)}

        import os
        model_dir = "ml/saved_models"
        if os.path.exists(model_dir):
            models = [f for f in os.listdir(model_dir) if f.endswith(('.pkl', '.json'))]
            result["checks"]["models"] = {"status": "ok" if models else "warning", "count": len(models)}

        self._last_check = result["timestamp"]
        return result

    def get_status(self) -> Dict[str, Any]:
        return {"last_check": self._last_check}


health_check_worker = HealthCheckWorker()
