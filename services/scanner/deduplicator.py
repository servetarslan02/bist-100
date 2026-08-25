"""
ALPHA BIST — Scan Deduplicator v1.0

Aynı hissenin cooldown süresince tekrar tekrar taranmasını önler.
Event-driven force scan ile cooldown bypass edilebilir.

Gerekçe: 800 hisseyi her taramada tekrar analiz etmek CPU israfı.
Deduplication ile sadece değişen veya önemli hisseler taranır.
"""

import time
from typing import Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class ScanRecord:
    """Tarama kaydı."""
    ticker: str
    last_scan_time: float       # time.time()
    scan_count: int = 0
    last_score: float = 0.0
    last_signal: str = ""
    last_tier: int = 0
    forced: bool = False        # Event-driven force scan


class ScanDeduplicator:
    """Tarama deduplication — aynı hisseyi tekrar tarama.

    Kullanım:
        dedup = ScanDeduplicator(cooldown_seconds=300)

        # Normal tarama — cooldown kontrolü
        if dedup.should_scan("THYAO"):
            result = scan("THYAO")
            dedup.record_scan("THYAO", result)

        # Event-driven — cooldown bypass
        dedup.force_scan("THYAO")  # Bir sonraki should_scan() True döner
    """

    def __init__(
        self,
        cooldown_seconds: int = 300,          # 5 dakika default
        event_cooldown_seconds: int = 10,     # Event-driven: 10 saniye
        max_tracked_tickers: int = 1000,      # Maksimum takip edilen hisse
    ):
        self._cooldown = cooldown_seconds
        self._event_cooldown = event_cooldown_seconds
        self._max_tracked = max_tracked_tickers
        self._records: Dict[str, ScanRecord] = {}
        self._forced_tickers: set = set()  # Force scan bekleyenler

        # İstatistikler
        self._total_checks = 0
        self._total_allowed = 0
        self._total_blocked = 0
        self._total_forced = 0

    def should_scan(self, ticker: str) -> bool:
        """Bu hisse taranmalı mı?

        Args:
            ticker: Hisse kodu

        Returns:
            True: Tarama gerekli, False: Cooldown nedeniyle atla
        """
        self._total_checks += 1

        # Force scan bekliyorsa → her zaman tara
        if ticker in self._forced_tickers:
            self._forced_tickers.discard(ticker)
            self._total_forced += 1
            self._total_allowed += 1
            logger.debug("Force scan", ticker=ticker)
            return True

        # Kayıt yoksa → ilk tarama, izin ver
        record = self._records.get(ticker)
        if record is None:
            self._total_allowed += 1
            return True

        # Cooldown kontrolü
        elapsed = time.time() - record.last_scan_time
        if elapsed < self._cooldown:
            self._total_blocked += 1
            logger.debug("Scan blocked (cooldown)",
                        ticker=ticker,
                        elapsed=f"{elapsed:.0f}s",
                        cooldown=f"{self._cooldown}s")
            return False

        self._total_allowed += 1
        return True

    def record_scan(
        self,
        ticker: str,
        score: float = 0.0,
        signal: str = "",
        tier: int = 0,
        forced: bool = False,
    ):
        """Tarama kaydet.

        Args:
            ticker: Hisse kodu
            score: Fırsat skoru
            signal: Sinyal türü
            tier: Mevcut tier
            forced: Event-driven force scan mıydı?
        """
        now = time.time()

        if ticker in self._records:
            record = self._records[ticker]
            record.last_scan_time = now
            record.scan_count += 1
            record.last_score = score
            record.last_signal = signal
            record.last_tier = tier
            record.forced = forced
        else:
            # Yeni kayıt — limit kontrolü
            if len(self._records) >= self._max_tracked:
                self._evict_oldest()

            self._records[ticker] = ScanRecord(
                ticker=ticker,
                last_scan_time=now,
                scan_count=1,
                last_score=score,
                last_signal=signal,
                last_tier=tier,
                forced=forced,
            )

    def force_scan(self, ticker: str):
        """Zorla tarama (event-driven).

        Bir sonraki should_scan() çağrısında True döner.
        Cooldown'u sıfırlamaz, sadece bir kereliğine bypass eder.

        Args:
            ticker: Hisse kodu
        """
        self._forced_tickers.add(ticker)
        logger.info("Force scan queued", ticker=ticker)

    def force_scan_batch(self, tickers: list):
        """Birden fazla hisse için zorla tarama.

        Args:
            tickers: Hisse kodları listesi
        """
        self._forced_tickers.update(tickers)
        logger.info("Force scan batch queued", count=len(tickers))

    def get_cooldown_remaining(self, ticker: str) -> float:
        """Kalan cooldown süresi (saniye).

        Args:
            ticker: Hisse kodu

        Returns:
            Kalan saniye (0 = cooldown dolmuş)
        """
        record = self._records.get(ticker)
        if record is None:
            return 0.0

        elapsed = time.time() - record.last_scan_time
        remaining = self._cooldown - elapsed
        return max(0.0, remaining)

    def get_last_scan_info(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Son tarama bilgisini al.

        Args:
            ticker: Hisse kodu

        Returns:
            Son tarama bilgisi veya None
        """
        record = self._records.get(ticker)
        if record is None:
            return None

        return {
            "ticker": record.ticker,
            "last_scan_time": datetime.fromtimestamp(
                record.last_scan_time, tz=timezone.utc
            ).isoformat(),
            "scan_count": record.scan_count,
            "last_score": record.last_score,
            "last_signal": record.last_signal,
            "last_tier": record.last_tier,
            "cooldown_remaining": round(self.get_cooldown_remaining(ticker), 1),
        }

    def set_cooldown(self, seconds: int):
        """Cooldown süresini değiştir.

        Args:
            seconds: Yeni cooldown süresi (saniye)
        """
        old = self._cooldown
        self._cooldown = seconds
        logger.info("Cooldown changed", old=f"{old}s", new=f"{seconds}s")

    def get_stats(self) -> Dict[str, Any]:
        """İstatistikler.

        Returns:
            Deduplication istatistikleri
        """
        block_rate = (
            self._total_blocked / self._total_checks * 100
            if self._total_checks > 0 else 0
        )

        return {
            "tracked_tickers": len(self._records),
            "forced_pending": len(self._forced_tickers),
            "cooldown_seconds": self._cooldown,
            "event_cooldown_seconds": self._event_cooldown,
            "total_checks": self._total_checks,
            "total_allowed": self._total_allowed,
            "total_blocked": self._total_blocked,
            "total_forced": self._total_forced,
            "block_rate_pct": round(block_rate, 1),
        }

    def get_all_tracked(self) -> Dict[str, Dict]:
        """Tüm takip edilen hisseleri al.

        Returns:
            ticker → son tarama bilgisi
        """
        return {
            ticker: self.get_last_scan_info(ticker)
            for ticker in self._records
        }

    def clear(self):
        """Tüm kayıtları temizle."""
        self._records.clear()
        self._forced_tickers.clear()
        logger.info("Deduplicator cleared")

    def _evict_oldest(self):
        """En eski kaydı çıkar (limit aşımı)."""
        if not self._records:
            return

        oldest_ticker = min(
            self._records,
            key=lambda t: self._records[t].last_scan_time
        )
        del self._records[oldest_ticker]
        logger.debug("Evicted oldest record", ticker=oldest_ticker)


# Singleton
scan_deduplicator = ScanDeduplicator()
