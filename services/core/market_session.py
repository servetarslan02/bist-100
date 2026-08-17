"""ALPHA BIST — Market Session Manager

BIST piyasa saatleri ve durum yönetimi.
Europe/Istanbul timezone. UTC/local karışımı yok.
"""

from datetime import datetime, time, timezone, timedelta
from enum import Enum
from typing import Optional
import structlog

logger = structlog.get_logger()

# Europe/Istanbul = UTC+3
_TZ_ISTANBUL = timezone(timedelta(hours=3))

# BIST tatil günleri (2026 — örnek, production'da dinamik çekilmeli)
_BIST_HOLIDAYS_2026 = {
    "2026-01-01", "2026-04-23", "2026-05-01", "2026-05-19",
    "2026-07-15", "2026-08-30", "2026-10-29", "2026-12-25",
    # Ramazan/Kurban Bayramı — production'da API'den çekilmeli
}


class MarketPhase(Enum):
    CLOSED = "closed"               # Piyasa kapalı (hafta sonu, tatil, gece)
    PRE_MARKET = "pre_market"       # 09:50 — 10:00
    ACTIVE = "active"               # 10:00 — 18:00
    POST_MARKET = "post_market"     # 18:00 — 18:30
    AFTER_HOURS = "after_hours"     # 18:30 — 23:59


class MarketSessionManager:
    """BIST piyasa session yönetimi.

    Tüm zaman hesaplamaları Europe/Istanbul timezone'da.
    """

    # BIST çalışma saatleri (Istanbul time)
    PRE_MARKET_START = time(9, 50)
    MARKET_OPEN = time(10, 0)
    MARKET_CLOSE = time(18, 0)
    POST_MARKET_END = time(18, 30)

    def __init__(self, holidays: Optional[set] = None):
        self._holidays = holidays or _BIST_HOLIDAYS_2026

    def now_istanbul(self) -> datetime:
        """Şu anki Istanbul zamanı."""
        return datetime.now(_TZ_ISTANBUL)

    def current_phase(self) -> MarketPhase:
        """Piyasanın şu anki durumu."""
        now = self.now_istanbul()

        # Hafta sonu
        if now.weekday() >= 5:
            return MarketPhase.CLOSED

        # Tatil
        date_str = now.strftime("%Y-%m-%d")
        if date_str in self._holidays:
            return MarketPhase.CLOSED

        t = now.time()

        if t < self.PRE_MARKET_START:
            return MarketPhase.CLOSED
        elif t < self.MARKET_OPEN:
            return MarketPhase.PRE_MARKET
        elif t < self.MARKET_CLOSE:
            return MarketPhase.ACTIVE
        elif t < self.POST_MARKET_END:
            return MarketPhase.POST_MARKET
        else:
            return MarketPhase.AFTER_HOURS

    def is_trading_hours(self) -> bool:
        """Piyasa açık mı? (ACTIVE phase)"""
        return self.current_phase() == MarketPhase.ACTIVE

    def is_pre_market(self) -> bool:
        return self.current_phase() == MarketPhase.PRE_MARKET

    def is_post_market(self) -> bool:
        return self.current_phase() == MarketPhase.POST_MARKET

    def is_closed(self) -> bool:
        return self.current_phase() == MarketPhase.CLOSED

    def next_phase_change(self) -> Optional[datetime]:
        """Bir sonraki phase değişikliği zamanı."""
        now = self.now_istanbul()
        phase = self.current_phase()
        t = now.time()

        if phase == MarketPhase.CLOSED:
            if now.weekday() >= 5:
                # Pazartesi 09:50
                days_until_monday = 7 - now.weekday()
                next_day = now + timedelta(days=days_until_monday)
                return next_day.replace(hour=9, minute=50, second=0, microsecond=0)
            elif t < self.PRE_MARKET_START:
                return now.replace(hour=9, minute=50, second=0, microsecond=0)
            else:
                # Ertesi gün 09:50
                next_day = now + timedelta(days=1)
                if next_day.weekday() >= 5:
                    next_day += timedelta(days=7 - next_day.weekday())
                return next_day.replace(hour=9, minute=50, second=0, microsecond=0)

        elif phase == MarketPhase.PRE_MARKET:
            return now.replace(hour=10, minute=0, second=0, microsecond=0)
        elif phase == MarketPhase.ACTIVE:
            return now.replace(hour=18, minute=0, second=0, microsecond=0)
        elif phase == MarketPhase.POST_MARKET:
            return now.replace(hour=18, minute=30, second=0, microsecond=0)
        else:
            return None

    def seconds_until_next_phase(self) -> int:
        """Bir sonraki phase'e kaç saniye kaldı."""
        next_change = self.next_phase_change()
        if next_change is None:
            return 0
        now = self.now_istanbul()
        delta = (next_change - now).total_seconds()
        return max(0, int(delta))

    def should_run_trading_job(self) -> bool:
        """Trading job çalıştırılmalı mı?"""
        phase = self.current_phase()
        return phase in (MarketPhase.ACTIVE, MarketPhase.PRE_MARKET)

    def get_status(self) -> dict:
        """Durum bilgisi."""
        now = self.now_istanbul()
        phase = self.current_phase()
        return {
            "phase": phase.value,
            "istanbul_time": now.isoformat(),
            "weekday": now.strftime("%A"),
            "is_trading_day": now.weekday() < 5 and now.strftime("%Y-%m-%d") not in self._holidays,
            "next_phase_change": self.next_phase_change().isoformat() if self.next_phase_change() else None,
            "seconds_until_next": self.seconds_until_next_phase(),
        }


# Singleton
market_session = MarketSessionManager()
