"""ALPHA BIST — Macro Calendar."""
from typing import Dict, Any, List
from datetime import datetime
import structlog
logger = structlog.get_logger()

# Önemli makro olaylar takvimi
MACRO_EVENTS = {
    "TCMB_PPK": {"frequency": "monthly", "importance": "HIGH"},
    "CPI_RELEASE": {"frequency": "monthly", "importance": "HIGH"},
    "GDP_RELEASE": {"frequency": "quarterly", "importance": "MEDIUM"},
    "UNEMPLOYMENT": {"frequency": "monthly", "importance": "MEDIUM"},
    "CURRENT_ACCOUNT": {"frequency": "monthly", "importance": "MEDIUM"},
    "BUDGET_BALANCE": {"frequency": "monthly", "importance": "LOW"},
}

def get_macro_events(date: str = "") -> List[Dict[str, Any]]:
    """Belirli bir tarihteki makro olayları getir."""
    events = []
    for event_type, info in MACRO_EVENTS.items():
        events.append({"type": event_type, "frequency": info["frequency"], "importance": info["importance"]})
    return events

def get_upcoming_events(days: int = 7) -> List[Dict[str, Any]]:
    """Yaklaşan makro olaylar."""
    return get_macro_events()
