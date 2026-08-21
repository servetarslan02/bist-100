"""ALPHA BIST — Manipulation Detector (SPK Uyumlu)."""
from typing import Dict, Any, List
from dataclasses import dataclass
import structlog
logger = structlog.get_logger()

@dataclass
class ManipulationAlert:
    alert_type: str   # WASH_TRADING, SPOOFING, LAYERING, VOLUME_MANIP
    severity: str     # LOW, MEDIUM, HIGH, CRITICAL
    description: str
    details: Dict[str, Any] = None
    def __post_init__(self):
        if self.details is None: self.details = {}

class ManipulationDetector:
    def detect_wash_trading(self, trades: List[Dict]) -> List[ManipulationAlert]:
        """Wash trading tespiti — aynı fiyat/hacim tekrarları."""
        alerts = []
        for i in range(1, len(trades)):
            if (trades[i].get("price") == trades[i-1].get("price") and
                trades[i].get("volume") == trades[i-1].get("volume") and
                trades[i].get("buyer") == trades[i-1].get("seller")):
                alerts.append(ManipulationAlert("WASH_TRADING", "HIGH", "Olası wash trading"))
        return alerts

    def detect_spoofing(self, orders: List[Dict]) -> List[ManipulationAlert]:
        """Spoofing tespiti — büyük emir + hızlı iptal."""
        alerts = []
        cancel_count = 0
        for order in orders:
            if order.get("action") == "CANCEL":
                cancel_count += 1
            if cancel_count > 5:
                alerts.append(ManipulationAlert("SPOOFING", "MEDIUM", "Yüksek iptal oranı"))
                cancel_count = 0
        return alerts

    def detect_volume_manipulation(self, volumes: List[float], avg_volume: float) -> List[ManipulationAlert]:
        """Hacim manipülasyonu tespiti."""
        alerts = []
        if volumes and avg_volume > 0:
            if volumes[-1] > avg_volume * 5:
                alerts.append(ManipulationAlert("VOLUME_MANIP", "HIGH",
                    f"Anormal hacim: {volumes[-1]:.0f} vs ortalama {avg_volume:.0f}"))
        return alerts

manipulation_detector = ManipulationDetector()
