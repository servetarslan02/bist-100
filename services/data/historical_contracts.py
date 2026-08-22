"""
ALPHA BIST — Historical Data Contracts

PIT-safe historical veri sözleşmeleri.

Backtest'te kullanılan tüm historical veriler bu contract'lar üzerinden geçer.

KURAL: publication_date <= current_date olmayan veri KULLANILAMAZ.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class FundamentalSnapshot:
    """Historical fundamental veri snapshot'ı.

    PIT kuralı: available_at <= backtest_date
    """
    ticker: str
    period_end: str            # Dönem sonu (YYYY-MM-DD) — örn: 2025-06-30
    available_at: str          # Açıklanma tarihi (YYYY-MM-DD) — örn: 2025-08-14
    values: Dict[str, Any]     # Fundamental değerler
    source: str = "unknown"
    status: str = "FRESH"      # FRESH / STALE / MISSING / UNKNOWN


@dataclass
class EventSnapshot:
    """Historical KAP/News event snapshot'ı.

    PIT kuralı: published_at <= backtest_date
    """
    event_id: str
    ticker: str
    published_at: str          # Yayın tarihi (ISO-8601)
    event_type: str            # KAP category / news type
    title: str = ""
    sentiment: float = 0.0
    importance: float = 0.5
    source: str = "unknown"    # kap / news / rss
    content: str = ""


@dataclass
class CatalystSnapshot:
    """Historical catalyst snapshot'ı.

    PIT kuralı: announcement_date <= backtest_date
    Event'in kendisi gelecekte olabilir ama announcement bilgisi bilinmeli.
    """
    event_id: str
    ticker: str
    announcement_date: str     # Açıklandığı tarih
    event_date: str            # Gerçekleşeceği/gerçekleştiği tarih
    catalyst_type: str         # EARNINGS, DIVIDEND, etc.
    importance: float = 0.5
    source: str = "unknown"


class HistoricalDataRepository:
    """Historical veri repository interface.

    Bu interface'i implement eden sınıflar:
    - InMemoryHistoricalRepository (test için)
    - DatabaseHistoricalRepository (production için)
    - FileHistoricalRepository (dosya tabanlı)

    Production'da gerçek historical veri sağlanmalıdır.
    """

    def get_fundamental_snapshots(
        self,
        ticker: str,
        as_of_date: str,
    ) -> List[FundamentalSnapshot]:
        """Belirli tarihte bilinen fundamental snapshot'ları döndür.

        Args:
            ticker: Hisse kodu
            as_of_date: Backtest tarihi (YYYY-MM-DD)

        Returns:
            available_at <= as_of_date olan snapshot'lar (en yeniden eskiye)
        """
        raise NotImplementedError

    def get_event_snapshots(
        self,
        ticker: str,
        as_of_date: str,
        event_types: Optional[List[str]] = None,
    ) -> List[EventSnapshot]:
        """Belirli tarihte bilinen KAP/News event'lerini döndür.

        Args:
            ticker: Hisse kodu
            as_of_date: Backtest tarihi (YYYY-MM-DD)
            event_types: Filtrelenecek event tipleri (None = hepsi)

        Returns:
            published_at <= as_of_date olan event'ler
        """
        raise NotImplementedError

    def get_catalyst_snapshots(
        self,
        ticker: str,
        as_of_date: str,
    ) -> List[CatalystSnapshot]:
        """Belirli tarihte bilinen catalyst'leri döndür.

        Args:
            ticker: Hisse kodu
            as_of_date: Backtest tarihi (YYYY-MM-DD)

        Returns:
            announcement_date <= as_of_date olan catalyst'ler
        """
        raise NotImplementedError

    def add_fundamental_snapshot(self, snapshot: FundamentalSnapshot):
        """Fundamental snapshot ekle."""
        raise NotImplementedError

    def add_event_snapshot(self, snapshot: EventSnapshot):
        """Event snapshot ekle."""
        raise NotImplementedError

    def add_catalyst_snapshot(self, snapshot: CatalystSnapshot):
        """Catalyst snapshot ekle."""
        raise NotImplementedError


class InMemoryHistoricalRepository(HistoricalDataRepository):
    """In-memory historical repository (test ve fixture için)."""

    def __init__(self):
        self._fundamentals: List[FundamentalSnapshot] = []
        self._events: List[EventSnapshot] = []
        self._catalysts: List[CatalystSnapshot] = []

    def get_fundamental_snapshots(
        self, ticker: str, as_of_date: str,
    ) -> List[FundamentalSnapshot]:
        return sorted(
            [s for s in self._fundamentals
             if s.ticker == ticker and s.available_at <= as_of_date],
            key=lambda s: s.available_at,
            reverse=True,
        )

    def get_event_snapshots(
        self, ticker: str, as_of_date: str,
        event_types: Optional[List[str]] = None,
    ) -> List[EventSnapshot]:
        events = [
            s for s in self._events
            if s.ticker == ticker and s.published_at[:10] <= as_of_date
        ]
        if event_types:
            events = [e for e in events if e.event_type in event_types]
        return sorted(events, key=lambda s: s.published_at, reverse=True)

    def get_catalyst_snapshots(
        self, ticker: str, as_of_date: str,
    ) -> List[CatalystSnapshot]:
        return sorted(
            [s for s in self._catalysts
             if s.ticker == ticker and s.announcement_date <= as_of_date],
            key=lambda s: s.announcement_date,
            reverse=True,
        )

    def add_fundamental_snapshot(self, snapshot: FundamentalSnapshot):
        self._fundamentals.append(snapshot)
        if len(self._fundamentals) > 500:
            self._fundamentals = self._fundamentals[-500:]

    def add_event_snapshot(self, snapshot: EventSnapshot):
        self._events.append(snapshot)
        if len(self._events) > 500:
            self._events = self._events[-500:]

    def add_catalyst_snapshot(self, snapshot: CatalystSnapshot):
        self._catalysts.append(snapshot)
        if len(self._catalysts) > 500:
            self._catalysts = self._catalysts[-500:]

    def clear(self):
        self._fundamentals.clear()
        self._events.clear()
        self._catalysts.clear()
