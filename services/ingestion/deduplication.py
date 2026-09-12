"""
ALPHA BIST — Event Deduplication v1.0

Aynı verinin iki kez işlenmesini önler.
24 saatlik pencere içinde aynı event tekrar gelirse filtrelenir.

Hash: event_type + source + ticker + price + timestamp → SHA-256

Kullanım:
    dedup = EventDeduplicator()
    if not dedup.is_duplicate(event):
        process(event)
        dedup.mark_seen(event)
"""

import hashlib
import time
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class DedupStats:
    """Deduplication istatistikleri.

    Attributes:
        total_checked: Kontrol edilen toplam event sayısı.
        total_duplicates: Bulunan tekrar sayısı.
        total_unique: Benzersiz event sayısı.
        window_cleanups: Pencere temizleme sayısı.
    """

    total_checked: int = 0
    total_duplicates: int = 0
    total_unique: int = 0
    window_cleanups: int = 0

    def __repr__(self) -> str:
        return (
            f"DedupStats(checked={self.total_checked}, "
            f"duplicates={self.total_duplicates}, "
            f"unique={self.total_unique})"
        )


class EventDeduplicator:
    """Event deduplication — aynı veri iki kez işlenmesin.

    24 saatlik sliding window içinde aynı event hash'i
    tekrar gelirse duplicate olarak işaretlenir.

    Args:
        window_hours: Deduplikasyon penceresi (saat).
    """

    def __init__(self, window_hours: int = 24) -> None:
        """EventDeduplicator örneği oluşturur.

        Args:
            window_hours: Deduplikasyon penceresi (saat cinsinden).
        """
        self._seen: dict[str, float] = {}
        self._window_seconds = window_hours * 3600
        self._stats = DedupStats()

    def _compute_hash(self, event_data: dict[str, Any]) -> str:
        """Event verisinden benzersiz hash oluşturur.

        Args:
            event_data: Event verisi (CanonicalEvent.data veya dict).

        Returns:
            SHA-256 hex digest.
        """
        price_val = event_data.get("price")
        try:
            price_str = str(round(float(price_val), 2)) if price_val is not None and price_val != "" else "0.0"
        except (ValueError, TypeError):
            price_str = "0.0"

        key_parts = [
            str(event_data.get("event_type", "")),
            str(event_data.get("source", "")),
            str(event_data.get("ticker", "")),
            price_str,
            str(event_data.get("timestamp", "")),
            str(event_data.get("kap_id", "")),
            str(event_data.get("social_id", "")),
        ]
        key = "|".join(key_parts)
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def is_duplicate(self, event_data: dict[str, Any]) -> bool:
        """Bu event daha önce işlendi mi kontrol eder.

        Args:
            event_data: Event verisi (CanonicalEvent.data veya dict).

        Returns:
            True: Duplicate (işlenmemeli), False: Unique.
        """
        self._stats.total_checked += 1
        self._cleanup_if_needed()

        event_hash = self._compute_hash(event_data)

        if event_hash in self._seen:
            self._stats.total_duplicates += 1
            logger.debug("Duplicate event detected", event_hash=event_hash[:8], event_type=event_data.get("event_type"))
            return True

        return False

    def mark_seen(self, event_data: dict[str, Any]) -> None:
        """Event'i işlenmiş olarak işaretler.

        Args:
            event_data: Event verisi.
        """
        event_hash = self._compute_hash(event_data)
        self._seen[event_hash] = time.time()
        self._stats.total_unique += 1

    def check_and_mark(self, event_data: dict[str, Any]) -> bool:
        """Kontrol eder ve işaretler (tek adımda).

        Args:
            event_data: Event verisi.

        Returns:
            True: Duplicate (işlenmemeli), False: Unique (işlenmeli, işaretlendi).
        """
        if self.is_duplicate(event_data):
            return True
        self.mark_seen(event_data)
        return False

    def _cleanup_if_needed(self) -> None:
        """Eski hash'leri periyodik olarak temizler.

        Her 100 kontrolde bir, pencere dışındaki kayıtları siler.
        """
        if self._stats.total_checked % 100 != 0:
            return

        cutoff = time.time() - self._window_seconds
        old_count = len(self._seen)
        self._seen = {h: ts for h, ts in self._seen.items() if ts > cutoff}
        cleaned = old_count - len(self._seen)
        if cleaned > 0:
            self._stats.window_cleanups += 1
            logger.debug("Dedup cleanup", cleaned=cleaned, remaining=len(self._seen))

    def cleanup(self) -> None:
        """Manuel temizleme — pencere dışındaki kayıtları siler."""
        cutoff = time.time() - self._window_seconds
        old_count = len(self._seen)
        self._seen = {h: ts for h, ts in self._seen.items() if ts > cutoff}
        cleaned = old_count - len(self._seen)
        logger.info("Manual dedup cleanup", cleaned=cleaned, remaining=len(self._seen))

    def get_stats(self) -> dict[str, Any]:
        """İstatistikleri döndürür.

        Returns:
            Deduplikasyon istatistik sözlüğü.
        """
        return {
            "total_checked": self._stats.total_checked,
            "total_duplicates": self._stats.total_duplicates,
            "total_unique": self._stats.total_unique,
            "duplicate_rate": round(self._stats.total_duplicates / max(self._stats.total_checked, 1) * 100, 1),
            "window_size_hours": self._window_seconds / 3600,
            "current_entries": len(self._seen),
            "window_cleanups": self._stats.window_cleanups,
        }

    def reset(self) -> None:
        """Tüm durumu sıfırlar."""
        self._seen.clear()
        self._stats = DedupStats()


# Singleton
event_deduplicator = EventDeduplicator()


__all__ = [
    "DedupStats",
    "EventDeduplicator",
    "event_deduplicator",
]
