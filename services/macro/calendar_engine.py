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

import threading
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

    def __repr__(self) -> str:
        """Makro olay kaydının okunabilir string temsili."""
        return (
            f"MacroEvent(id='{self.event_id}', type='{self.event_type}', "
            f"date='{self.date}', status='{self.status}')"
        )


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

    def __init__(self) -> None:
        """Makro takvim motoru başlatıcı.

        Olay listesini ve piyasa beklentilerini ilklendirir, tanımlı makro olayları yükler.
        """
        self._lock = threading.Lock()
        self._events: list[MacroEvent] = []
        self._expectations: dict[str, float] = {}  # event_id → expected
        self._initialize_events()

    def __repr__(self) -> str:
        """Makro takvim motoru okunabilir string temsili."""
        with self._lock:
            return (
                f"MacroCalendarEngine(total_events={len(self._events)}, "
                f"expectations={len(self._expectations)})"
            )

    def _initialize_events(self) -> None:
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
        with self._lock:
            for event in self._events:
                event_date = datetime.strptime(event.date, "%Y-%m-%d")
                if now.date() <= event_date.date() <= cutoff.date():
                    upcoming.append(event)

        return sorted(upcoming, key=lambda e: e.date)

    def register_expectation(self, event_id: str, expected: float) -> None:
        """Beklenti kaydet."""
        with self._lock:
            self._expectations[event_id] = expected

            # Event'i güncelle
            for event in self._events:
                if event.event_id == event_id:
                    event.expected_value = expected
                    break

        logger.info("Expectation registered", event_id=event_id, expected=expected)

    def complete_event(self, event_id: str, actual: float) -> MacroEvent | None:
        """Olay tamamlandı — actual değeri kaydet."""
        with self._lock:
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

    def compute_calendar_proximity_features(self, target_date_str: str | None = None) -> dict[str, float]:
        """TCMB PPK ve FOMC toplantılarına yakınlık metriklerini ve binary risk göstergelerini hesaplar.

        Args:
            target_date_str: Hedef tarih (YYYY-MM-DD), None ise güncel UTC tarihi.

        Returns:
            dict[str, float]: Gün sayıları ve risk bayrakları sözlüğü.
        """
        if target_date_str:
            ref_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        else:
            ref_date = datetime.now(UTC).date()

        days_to_ppk: float = 999.0
        days_to_fomc: float = 999.0

        for d in self.TCMB_PPK_DATES:
            dt = datetime.strptime(d, "%Y-%m-%d").date()
            diff = (dt - ref_date).days
            if diff >= 0 and diff < days_to_ppk:
                days_to_ppk = float(diff)

        for d in self.FOMC_DATES:
            dt = datetime.strptime(d, "%Y-%m-%d").date()
            diff = (dt - ref_date).days
            if diff >= 0 and diff < days_to_fomc:
                days_to_fomc = float(diff)

        high_impact_near = 1.0 if (days_to_ppk <= 3.0 or days_to_fomc <= 2.0) else 0.0

        return {
            "calendar_days_to_ppk": days_to_ppk,
            "calendar_days_to_fomc": days_to_fomc,
            "calendar_high_impact_imminent": high_impact_near,
        }

    def get_pre_event_alert(self, event_id: str) -> dict[str, Any]:
        """Olay öncesi hazırlık uyarısı."""
        with self._lock:
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
        with self._lock:
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
        with self._lock:
            total_events = len(self._events)
            completed = [e for e in self._events if e.status == "COMPLETED"]
            analyzed = [e for e in self._events if e.status == "ANALYZED"]
            exp_len = len(self._expectations)

        return {
            "total_events": total_events,
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
            "expectations_set": exp_len,
        }


# Singleton
macro_calendar_engine = MacroCalendarEngine()

__all__ = [
    "MacroEvent",
    "MacroCalendarEngine",
    "macro_calendar_engine",
]
