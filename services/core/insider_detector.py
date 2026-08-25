"""ALPHA BIST — Insider Trading Detector."""
from typing import Dict, List
from dataclasses import dataclass
import structlog
logger = structlog.get_logger()

@dataclass
class InsiderAlert:
    ticker: str
    alert_type: str  # PRE_KAP_TRADE, UNUSUAL_VOLUME, PRICE_MOVE_BEFORE_KAP
    severity: str
    description: str

class InsiderDetector:
    def detect_pre_kap_trade(self, trades: List[Dict], kap_events: List[Dict]) -> List[InsiderAlert]:
        """KAP açıklaması öncesi olağandışı işlem."""
        alerts = []
        for event in kap_events:
            event_date = event.get("date", "")
            for trade in trades:
                trade_date = trade.get("date", "")
                if trade_date < event_date and trade.get("volume", 0) > trade.get("avg_volume", 1) * 3:
                    alerts.append(InsiderAlert(
                        ticker=trade.get("ticker", ""),
                        alert_type="PRE_KAP_TRADE",
                        severity="HIGH",
                        description=f"KAP öncesi olağandışı hacim: {trade.get('volume', 0)}"
                    ))
        return alerts

insider_detector = InsiderDetector()
