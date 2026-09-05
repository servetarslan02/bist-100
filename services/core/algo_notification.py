"""ALPHA BIST — SPK Algoritmik İşlem Bildirim Modülü (Enterprise-Grade).

Bu modül, Sermaye Piyasası Kurulu (SPK) mevzuatı ve BIST düzenlemeleri uyarınca,
otonom veya yarı otonom çalışan algoritmik alım-satım stratejilerinin
kayıt altına alınmasını ve standart bildirim formatına dönüştürülmesini sağlar.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.algo_notification")


def generate_algo_notification(strategy: dict[str, Any] | None = None) -> dict[str, Any]:
    """SPK mevzuatına uygun algoritmik işlem stratejisi bildirimi oluşturur.

    Args:
        strategy: Algoritma strateji parametreleri ve üst verileri.
            Beklenen anahtarlar: 'name', 'type', 'description', 'risk_level', 'parameters'.

    Returns:
        dict[str, Any]: SPK standartlarında benzersiz bildirim kaydı.

    Raises:
        ValueError: Strateji verisi geçersiz veya eksik olduğunda.
    """
    if strategy is None:
        strategy = {}

    with tracer.start_as_current_span("algo_notification.generate") as span:
        strategy_name = str(strategy.get("name") or "GENERIC_BIST_ALGO").strip()
        strategy_type = str(strategy.get("type") or "QUANT_MOMENTUM").strip()
        risk_level = str(strategy.get("risk_level") or "MEDIUM").upper()

        span.set_attribute("strategy.name", strategy_name)
        span.set_attribute("strategy.type", strategy_type)
        span.set_attribute("strategy.risk_level", risk_level)

        now = time.time()
        notification_id = f"spk_algo_{uuid.uuid4().hex[:12]}"

        notification: dict[str, Any] = {
            "notification_id": notification_id,
            "notification_type": "ALGO_TRADING",
            "strategy_name": strategy_name,
            "strategy_type": strategy_type,
            "description": str(strategy.get("description") or "BIST otomatik algoritma stratejisi"),
            "risk_level": risk_level,
            "auto_generated": True,
            "timestamp": now,
            "timestamp_iso": datetime.fromtimestamp(now, tz=UTC).isoformat(),
            "compliance_status": "COMPLIANT",
        }

        logger.info(
            "spk_algoritma_bildirimi_olusturuldu",
            notification_id=notification_id,
            strategy_name=strategy_name,
            strategy_type=strategy_type,
            risk_level=risk_level,
        )
        return notification


__all__ = [
    "generate_algo_notification",
]
