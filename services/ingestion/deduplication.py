"""
ALPHA BIST — Event Deduplication v1.0

Aynı verinin iki kez işlenmesini önler.
24 saatlik pencere içinde aynı event tekrar gelirse filtrelenir.

Hash: event_type + source + ticker + price + timestamp → MD5

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
    """Deduplication istatistikleri."""

    total_checked: int = 0
    total_duplicates: int = 0
    total_unique: int = 0
    window_cleanups: int = 0


class EventDeduplicator:
    """
    Event deduplication — aynı veri iki kez işlenmesin.

    24 saatlik sliding window içinde aynı event hash'i
    tekrar gelirse duplicate olarak işaretlenir.
    """

    def __init__(self, window_hours: int = 24):
        """Otomatik eklendi."""
        self._seen: dict[str, float] = {}  # hash → timestamp (epoch)
        self._window_seconds = window_hours * 3600
        self._stats = DedupStats()

    def _compute_hash(self, event_data: dict[str, Any]) -> str:
        """Event hash'i oluştur."""
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
        return hashlib.md5(key.encode("utf-8")).hexdigest()

    def is_duplicate(self, event_data: dict[str, Any]) -> bool:
        """
        Bu event daha önce işlendi mi?

        Args:
            event_data: Event verisi (CanonicalEvent.data veya dict)

        Returns:
            True: Duplicate, False: Unique
        """
        self._stats.total_checked += 1
        self._cleanup_if_needed()

        event_hash = self._compute_hash(event_data)

        if event_hash in self._seen:
            self._stats.total_duplicates += 1
            logger.debug("Duplicate event detected", event_hash=event_hash[:8], event_type=event_data.get("event_type"))
            return True

        return False

    def mark_seen(self, event_data: dict[str, Any]) -> Any:
        """Event'i işlenmiş olarak işaretle."""
        event_hash = self._compute_hash(event_data)
        self._seen[event_hash] = time.time()
        self._stats.total_unique += 1

    def check_and_mark(self, event_data: dict[str, Any]) -> bool:
        """
        Kontrol et ve işaretle (tek adımda).

        Returns:
            True: Duplicate (işlenmemeli)
            False: Unique (işlenmeli, işaretlendi)
        """
        if self.is_duplicate(event_data):
            return True
        self.mark_seen(event_data)
        return False

    def _cleanup_if_needed(self) -> Any:
        """Eski hash'leri temizle (periyodik)."""
        # Her 100 kontrolde bir temizle
        if self._stats.total_checked % 100 != 0:
            return

        cutoff = time.time() - self._window_seconds
        old_count = len(self._seen)
        self._seen = {h: ts for h, ts in self._seen.items() if ts > cutoff}
        cleaned = old_count - len(self._seen)
        if cleaned > 0:
            self._stats.window_cleanups += 1
            logger.debug("Dedup cleanup", cleaned=cleaned, remaining=len(self._seen))

    def cleanup(self) -> Any:
        """Manuel temizleme."""
        cutoff = time.time() - self._window_seconds
        old_count = len(self._seen)
        self._seen = {h: ts for h, ts in self._seen.items() if ts > cutoff}
        cleaned = old_count - len(self._seen)
        logger.info("Manual dedup cleanup", cleaned=cleaned, remaining=len(self._seen))

    def get_stats(self) -> dict:
        """İstatistikler."""
        return {
            "total_checked": self._stats.total_checked,
            "total_duplicates": self._stats.total_duplicates,
            "total_unique": self._stats.total_unique,
            "duplicate_rate": round(self._stats.total_duplicates / max(self._stats.total_checked, 1) * 100, 1),
            "window_size_hours": self._window_seconds / 3600,
            "current_entries": len(self._seen),
            "window_cleanups": self._stats.window_cleanups,
        }

    def reset(self) -> Any:
        """Sıfırla."""
        self._seen.clear()
        self._stats = DedupStats()


# Singleton
event_deduplicator = EventDeduplicator()
