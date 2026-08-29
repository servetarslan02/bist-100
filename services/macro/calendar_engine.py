"""
ALPHA BIST — Macro Calendar Engine v1.0

Makro takvim entegrasyonu — otomatik tetikleme:
- TCMB PPK toplantı tarihleri
- TÜİK veri açıklama tarihleri
- FOMC/ECB toplantı tarihleri
- Olay öncesi hazırlık (beklenti toplama)
- Olay sonrası analiz tetikleme (surprise hesaplama)

KURAL: Olay öncesi beklenti topla, olay sonrası surprise hesapla.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from services.macro.config.macro_config import macro_config

logger = structlog.get_logger()


@dataclass
class MacroEvent:
    """Makro olay."""

    event_id: str
    event_type: str  # TCMB_PPK, CPI, GDP, FOMC, ECB
    date: str
    indicator: str
    description: str
    expected_value: float | None = None
    actual_value: float | None = None
    surprise: float | None = None
    status: str = "UPCOMING"  # UPCOMING, COMPLETED, ANALYZED


class MacroCalendarEngine:
    """Makro takvim motoru."""

    # TCMB PPK toplantı tarihleri 2026
    TCMB_PPK_DATES = [
        "2026-01-23",
        "2026-02-20",
        "2026-03-19",
        "2026-04-16",
        "2026-05-21",
        "2026-06-18",
        "2026-07-23",
        "2026-08-20",
        "2026-09-17",
        "2026-10-22",
        "2026-11-19",
        "2026-12-17",
    ]

    # TÜİK veri açıklama tarihleri (ayın belirli günleri)
    TUIK_SCHEDULE = {
        "CPI": "monthly_10",  # Ayın 10'u
        "PPI": "monthly_10",  # Ayın 10'u
        "GDP": "quarterly_30",  # Çeyreğin son günü
        "UNEMPLOYMENT": "monthly_15",  # Ayın 15'i
        "INDUSTRIAL": "monthly_12",  # Ayın 12'si
    }

    # FOMC toplantı tarihleri 2026
    FOMC_DATES = [
        "2026-01-28",
        "2026-03-18",
        "2026-05-06",
        "2026-06-17",
        "2026-07-29",
        "2026-09-16",
        "2026-10-28",
        "2026-12-16",
    ]

    def __init__(self):
        """Otomatik eklendi."""
        self._events: list[MacroEvent] = []
        self._expectations: dict[str, float] = {}  # event_id → expected
        self._initialize_events()

    def _initialize_events(self) -> Any:
        """Takvim olaylarını başlat."""
        year = datetime.now(UTC).year

        # TCMB PPK
        for date_str in self.TCMB_PPK_DATES:
            if date_str.startswith(str(year)):
                self._events.append(
                    MacroEvent(
                        event_id=f"TCMB_PPK_{date_str}",
                        event_type="TCMB_PPK",
                        date=date_str,
                        indicator="POLICY_RATE",
                        description="TCMB Para Politikası Kurulu Toplantısı",
                    )
                )

        # FOMC
        for date_str in self.FOMC_DATES:
            if date_str.startswith(str(year)):
                self._events.append(
                    MacroEvent(
                        event_id=f"FOMC_{date_str}",
                        event_type="FOMC",
                        date=date_str,
                        indicator="FED_RATE",
                        description="ABD Federal Açık Piyasa Komitesi Toplantısı",
                    )
                )

    def get_upcoming_events(self, days: int = 7) -> list[MacroEvent]:
        """Yaklaşan makro olayları getir."""
        now = datetime.now(UTC)
        cutoff = now + timedelta(days=days)

        upcoming = []
        for event in self._events:
            event_date = datetime.strptime(event.date, "%Y-%m-%d")
            if now.date() <= event_date.date() <= cutoff.date():
                upcoming.append(event)

        return sorted(upcoming, key=lambda e: e.date)

    def register_expectation(self, event_id: str, expected: float) -> Any:
        """Beklenti kaydet."""
        self._expectations[event_id] = expected

        # Event'i güncelle
        for event in self._events:
            if event.event_id == event_id:
                event.expected_value = expected
                break

        logger.info("Expectation registered", event_id=event_id, expected=expected)

    def complete_event(self, event_id: str, actual: float) -> MacroEvent | None:
        """Olay tamamlandı — actual değeri kaydet."""
        for event in self._events:
            if event.event_id == event_id:
                event.actual_value = actual
                event.status = "COMPLETED"

                # Surprise hesapla
                if event.expected_value is not None:
                    event.surprise = actual - event.expected_value
                    event.status = "ANALYZED"

                    logger.warning(
                        "Macro event completed with surprise",
                        event_id=event_id,
                        expected=event.expected_value,
                        actual=actual,
                        surprise=event.surprise,
                    )
                else:
                    logger.info("Macro event completed (no expectation)", event_id=event_id, actual=actual)

                return event

        return None

    def get_pre_event_alert(self, event_id: str) -> dict[str, Any]:
        """Olay öncesi hazırlık uyarısı."""
        event = next((e for e in self._events if e.event_id == event_id), None)
        if not event:
            return {"error": "Event not found"}

        now = datetime.now(UTC)
        event_date = datetime.strptime(event.date, "%Y-%m-%d")
        days_until = (event_date.date() - now.date()).days

        return {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "indicator": event.indicator,
            "description": event.description,
            "date": event.date,
            "days_until": days_until,
            "expected_value": event.expected_value,
            "has_expectation": event.expected_value is not None,
            "preparation_needed": days_until <= macro_config.calendar.pre_event_alert_days,
        }

    def get_post_event_analysis(self, event_id: str) -> dict[str, Any]:
        """Olay sonrası analiz."""
        event = next((e for e in self._events if e.event_id == event_id), None)
        if not event or event.status != "ANALYZED":
            return {"error": "Event not analyzed"}

        return {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "indicator": event.indicator,
            "expected": event.expected_value,
            "actual": event.actual_value,
            "surprise": event.surprise,
            "surprise_pct": event.surprise / abs(event.expected_value) if event.expected_value else 0,
            "direction": "HIGHER" if event.surprise > 0 else ("LOWER" if event.surprise < 0 else "IN_LINE"),
        }

    def get_calendar_report(self) -> dict[str, Any]:
        """Takvim raporu."""
        now = datetime.now(UTC)

        upcoming = self.get_upcoming_events(days=30)
        completed = [e for e in self._events if e.status == "COMPLETED"]
        analyzed = [e for e in self._events if e.status == "ANALYZED"]

        return {
            "total_events": len(self._events),
            "upcoming_30d": len(upcoming),
            "completed": len(completed),
            "analyzed": len(analyzed),
            "next_event": {
                "id": upcoming[0].event_id,
                "type": upcoming[0].event_type,
                "date": upcoming[0].date,
                "days_until": (datetime.strptime(upcoming[0].date, "%Y-%m-%d").date() - now.date()).days,
            }
            if upcoming
            else None,
            "expectations_set": len(self._expectations),
        }


# Singleton
macro_calendar_engine = MacroCalendarEngine()
