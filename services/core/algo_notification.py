"""ALPHA BIST — Algo Trading Notification (SPK)."""
from typing import Any

import structlog

logger = structlog.get_logger()

def generate_algo_notification(strategy: dict[str, Any]) -> dict[str, Any]:
    """SPK algoritmik trading bildirimi oluştur."""
    return {
        "notification_type": "ALGO_TRADING",
        "strategy_name": strategy.get("name", ""),
        "strategy_type": strategy.get("type", ""),
        "description": strategy.get("description", ""),
        "risk_level": strategy.get("risk_level", "MEDIUM"),
        "auto_generated": True,
    }
