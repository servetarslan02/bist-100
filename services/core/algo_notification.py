"""
ALPHA BIST — Algo Trading Notification (SPK) v2.0 (Enterprise-Grade)

Kurumsal Standartlar:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. İZLENEBİLİRLİK: OTel span (SPK bildirim üretimi)
2. GÜVENLİK: structlog.__name__, kesin type hints
3. KALİTE: %100 docstring kapsama
"""

from __future__ import annotations

from typing import Any

import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.algo_notification")


def generate_algo_notification(strategy: dict[str, Any]) -> dict[str, Any]:
    """SPK algoritmik trading bildirimi oluştur.

    Args:
        strategy: Algoritma strateji bilgileri (isim, tip vb.)

    Returns:
        SPK standartlarına uygun bildirim sözlüğü.
    """
    with tracer.start_as_current_span("algo_notification.generate") as span:
        strategy_name = strategy.get("name", "UNKNOWN")
        span.set_attribute("strategy.name", strategy_name)
        span.set_attribute("strategy.type", strategy.get("type", "UNKNOWN"))

        notification = {
            "notification_type": "ALGO_TRADING",
            "strategy_name": strategy_name,
            "strategy_type": strategy.get("type", ""),
            "description": strategy.get("description", ""),
            "risk_level": strategy.get("risk_level", "MEDIUM"),
            "auto_generated": True,
        }
        logger.debug("SPK algoritma bildirimi oluşturuldu", strategy_name=strategy_name)
        return notification
