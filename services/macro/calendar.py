"""
ALPHA BIST — Macro Calendar v2.0

Makro olay takvimi:
- MACRO_EVENTS: Sabit olay listesi
- get_macro_events(): Tüm olayları getir
- get_upcoming_events(): Yaklaşan olayları getir
- get_event_impact(): Olay etkisi
"""

from typing import Dict, List, Any
from datetime import datetime, timedelta
import structlog

logger = structlog.get_logger()


# Önemli makro olaylar
MACRO_EVENTS = {
    "TCMB_PPK": {
        "description": "TCMB Para Politikası Kurulu Toplantısı",
        "impact": "HIGH",
        "indicator": "POLICY_RATE",
        "frequency": "monthly",
    },
    "CPI_RELEASE": {
        "description": "TÜİK Tüketici Fiyat Endeksi Açıklaması",
        "impact": "HIGH",
        "indicator": "CPI",
        "frequency": "monthly",
    },
    "PPI_RELEASE": {
        "description": "TÜİK Üretici Fiyat Endeksi Açıklaması",
        "impact": "MEDIUM",
        "indicator": "PPI",
        "frequency": "monthly",
    },
    "GDP_RELEASE": {
        "description": "TÜİK GSYH Açıklaması",
        "impact": "HIGH",
        "indicator": "GDP",
        "frequency": "quarterly",
    },
    "UNEMPLOYMENT": {
        "description": "TÜİK İstihdam Verisi",
        "impact": "MEDIUM",
        "indicator": "UNEMPLOYMENT",
        "frequency": "monthly",
    },
    "INDUSTRIAL": {
        "description": "TÜİK Sanayi Üretimi",
        "impact": "MEDIUM",
        "indicator": "INDUSTRIAL_PRODUCTION",
        "frequency": "monthly",
    },
    "TRADE_BALANCE": {
        "description": "TÜİK Dış Ticaret Dengesi",
        "impact": "MEDIUM",
        "indicator": "TRADE_BALANCE",
        "frequency": "monthly",
    },
    "FOMC": {
        "description": "ABD Federal Açık Piyasa Komitesi Toplantısı",
        "impact": "HIGH",
        "indicator": "FED_RATE",
        "frequency": "8_per_year",
    },
    "ECB": {
        "description": "Avrupa Merkez Bankası Toplantısı",
        "impact": "MEDIUM",
        "indicator": "ECB_RATE",
        "frequency": "8_per_year",
    },
    "US_CPI": {
        "description": "ABD Tüketici Fiyat Endeksi",
        "impact": "MEDIUM",
        "indicator": "US_CPI",
        "frequency": "monthly",
    },
}


def get_macro_events() -> Dict[str, Dict]:
    """Tüm makro olayları getir."""
    return MACRO_EVENTS


def get_upcoming_events(days: int = 7) -> List[Dict[str, Any]]:
    """Yaklaşan makro olayları getir.

    Args:
        days: kaç gün sonrası

    Returns:
        Yaklaşan olaylar listesi
    """
    now = datetime.now()
    upcoming = []

    # TCMB PPK - ayın belirli günleri
    tcmb_dates = _get_tcmb_dates(year=now.year)
    for date in tcmb_dates:
        if now.date() <= date.date() <= (now + timedelta(days=days)).date():
            upcoming.append({
                "event_type": "TCMB_PPK",
                "date": date.strftime("%Y-%m-%d"),
                "description": MACRO_EVENTS["TCMB_PPK"]["description"],
                "impact": MACRO_EVENTS["TCMB_PPK"]["impact"],
                "days_until": (date.date() - now.date()).days,
            })

    # TÜİK CPI - ayın 10'u
    for month in range(now.month, now.month + 2):
        try:
            cpi_date = datetime(now.year, month, 10)
            if now.date() <= cpi_date.date() <= (now + timedelta(days=days)).date():
                upcoming.append({
                    "event_type": "CPI_RELEASE",
                    "date": cpi_date.strftime("%Y-%m-%d"),
                    "description": MACRO_EVENTS["CPI_RELEASE"]["description"],
                    "impact": MACRO_EVENTS["CPI_RELEASE"]["impact"],
                    "days_until": (cpi_date.date() - now.date()).days,
                })
        except ValueError:
            logger.warning("Data error in get_upcoming_events: ValueError", exc_info=True)

    return sorted(upcoming, key=lambda x: x["days_until"])


def get_event_impact(event_type: str) -> Dict[str, Any]:
    """Olay etkisini getir."""
    event = MACRO_EVENTS.get(event_type)
    if not event:
        return {"error": f"Unknown event type: {event_type}"}

    sector_impacts = {
        "HIGH": {"BANK": 0.8, "AVIATION": 0.3, "ENERGY": 0.4, "TECH": 0.5},
        "MEDIUM": {"BANK": 0.4, "AVIATION": 0.2, "ENERGY": 0.3, "TECH": 0.3},
        "LOW": {"BANK": 0.2, "AVIATION": 0.1, "ENERGY": 0.1, "TECH": 0.1},
    }

    return {
        "event_type": event_type,
        "description": event["description"],
        "impact": event["impact"],
        "indicator": event["indicator"],
        "sector_impacts": sector_impacts.get(event["impact"], {}),
    }


def _get_tcmb_dates(year: int) -> List[datetime]:
    """TCMB PPK toplantı tarihleri."""
    # Yaklaşık tarihler (her ayın 3. veya 4. haftası)
    dates = []
    for month in range(1, 13):
        # Her ayın 3. Perşembesi (yaklaşık)
        for day in range(15, 29):
            try:
                d = datetime(year, month, day)
                if d.weekday() == 3:  # Perşembe
                    dates.append(d)
                    break
            except ValueError:
                continue
    return dates
