"""
ALPHA BIST — Incremental Fetcher v1.0

Sadece yeni veriyi çek — tam çekme yerine delta.
Bandwidth ve API limit tasarrufu.

Her ticker için son çekme zamanını takip eder.
Belirli bir aralık geçmeden tekrar çekmez.

Kullanım:
    fetcher = IncrementalFetcher()
    if fetcher.should_fetch("THYAO", min_interval=60):
        data = await fetch("THYAO")
        fetcher.mark_fetched("THYAO")
"""

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog

logger = structlog.get_logger()


@dataclass
class FetchState:
    """Ticker çekme durumu."""
    ticker: str
    last_fetch_time: float          # Epoch time
    last_fetch_timestamp: datetime | None = None
    fetch_count: int = 0
    last_error: str | None = None
    last_success: bool = True


@dataclass
class IncrementalStats:
    """İstatistikler."""
    total_checks: int = 0
    total_fetches: int = 0
    total_skipped: int = 0
    total_errors: int = 0


class IncrementalFetcher:
    """
    Incremental veri çekme.

    Her ticker için son çekme zamanını takip eder.
    Belirli bir aralık geçmeden tekrar çekmez.
    """

    def __init__(self, default_lookback_hours: int = 1):
        self._states: dict[str, FetchState] = {}
        self._default_lookback_hours = default_lookback_hours
        self._stats = IncrementalStats()

    def should_fetch(
        self,
        ticker: str,
        min_interval_seconds: int = 60,
    ) -> bool:
        """
        Bu ticker'ı şimdi çekmeli mi?

        Args:
            ticker: Hisse kodu
            min_interval_seconds: Minimum çekme aralığı (saniye)

        Returns:
            True: Çekilmeli, False: Atlanmalı
        """
        self._stats.total_checks += 1

        state = self._states.get(ticker)
        if state is None:
            return True

        elapsed = time.time() - state.last_fetch_time
        if elapsed >= min_interval_seconds:
            return True

        self._stats.total_skipped += 1
        return False

    def mark_fetched(
        self,
        ticker: str,
        success: bool = True,
        error: str | None = None,
    ):
        """Çekme zamanını güncelle."""
        now = time.time()
        state = self._states.get(ticker)

        if state is None:
            state = FetchState(
                ticker=ticker,
                last_fetch_time=now,
                last_fetch_timestamp=datetime.now(UTC),
            )
            self._states[ticker] = state

        state.last_fetch_time = now
        state.last_fetch_timestamp = datetime.now(UTC)
        state.fetch_count += 1
        state.last_success = success
        state.last_error = error

        if success:
            self._stats.total_fetches += 1
        else:
            self._stats.total_errors += 1

    def get_since(self, ticker: str) -> datetime:
        """
        Bu ticker için son çekme zamanını döndür.

        Hiç çekilmediyse, default_lookback_hours geriye dön.
        """
        state = self._states.get(ticker)
        if state and state.last_fetch_timestamp:
            return state.last_fetch_timestamp

        return datetime.now(UTC) - timedelta(
            hours=self._default_lookback_hours
        )

    def get_fetch_count(self, ticker: str) -> int:
        """Bu ticker'ın kaç kez çekildiği."""
        state = self._states.get(ticker)
        return state.fetch_count if state else 0

    def get_all_states(self) -> dict[str, dict]:
        """Tüm ticker durumları."""
        return {
            ticker: {
                "ticker": ticker,
                "last_fetch_time": state.last_fetch_timestamp.isoformat() if state.last_fetch_timestamp else None,
                "fetch_count": state.fetch_count,
                "last_success": state.last_success,
                "last_error": state.last_error,
                "seconds_since_fetch": round(
                    time.time() - state.last_fetch_time, 1
                ) if state.last_fetch_time else None,
            }
            for ticker, state in self._states.items()
        }

    def get_stats(self) -> dict:
        """İstatistikler."""
        return {
            "total_checks": self._stats.total_checks,
            "total_fetches": self._stats.total_fetches,
            "total_skipped": self._stats.total_skipped,
            "total_errors": self._stats.total_errors,
            "skip_rate": round(
                self._stats.total_skipped / max(self._stats.total_checks, 1) * 100, 1
            ),
            "tracked_tickers": len(self._states),
        }

    def get_stale_tickers(
        self,
        max_age_seconds: int = 3600,
    ) -> list[str]:
        """
        Belirli süredir çekilmemiş ticker'ları döndür.

        Args:
            max_age_seconds: Maksimum yaş (saniye)

        Returns:
            Eski ticker listesi
        """
        cutoff = time.time() - max_age_seconds
        stale = []

        for ticker, state in self._states.items():
            if state.last_fetch_time < cutoff:
                stale.append(ticker)

        return stale

    def reset(self, ticker: str | None = None):
        """Sıfırla."""
        if ticker:
            self._states.pop(ticker, None)
        else:
            self._states.clear()
            self._stats = IncrementalStats()


# Singleton
incremental_fetcher = IncrementalFetcher()
