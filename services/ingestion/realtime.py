"""
ALPHA BIST — Real-time Data Provider v1.0

Gerçek zamanlı veri akışı:
- BIST canlı fiyat (WebSocket/streaming)
- Fallback: yfinance polling (5 dakika)
- Event-driven updates

FAZ 1: Real-time data
"""

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
import yfinance as yf

logger = structlog.get_logger()


class RealtimeDataProvider:
    """Gerçek zamanlı veri sağlayıcı.

    Öncelik sırası:
    1. BIST WebSocket (varsa)
    2. Matriks streaming (varsa)
    3. yfinance polling (fallback)

    Args:
        tickers: İzlenecek hisse listesi.
        provider: Veri kaynağı ("yfinance" veya "matriks").
    """

    def __init__(self) -> None:
        """RealtimeDataProvider örneği oluşturur."""
        self._running = False
        self._handlers: list[Callable[..., Any]] = []
        self._last_prices: dict[str, float] = {}
        self._last_update: dict[str, datetime] = {}
        self._poll_interval: int = 300
        self._provider: str = "yfinance"

    def on_tick(self, handler: Callable[..., Any]) -> None:
        """Tick handler kaydeder.

        Maksimum 100 handler tutulur (eski olanlar silinir).

        Args:
            handler: (ticker, price, volume, change_pct) alan fonksiyon.
        """
        self._handlers.append(handler)
        if len(self._handlers) > 100:
            self._handlers = self._handlers[-100:]

    async def start(self, tickers: list[str], provider: str = "yfinance") -> None:
        """Veri akışını başlatır.

        Args:
            tickers: İzlenecek hisse listesi.
            provider: Veri kaynağı ("yfinance" veya "matriks").
        """
        self._running = True
        self._provider = provider

        logger.info("Realtime data provider starting", provider=provider, tickers=len(tickers))

        if provider == "yfinance":
            await self._yfinance_polling(tickers)
        elif provider == "matriks":
            await self._matriks_streaming(tickers)
        else:
            logger.error("Unknown provider", provider=provider)

    async def _yfinance_polling(self, tickers: list[str]) -> None:
        """yfinance ile periyodik polling yapar.

        50'lik chunk'lar halinde veri çeker, her chunk arasında 1 saniye bekler.

        Args:
            tickers: İzlenecek hisse listesi.
        """
        while self._running:
            try:
                start = time.time()

                for i in range(0, len(tickers), 50):
                    chunk = tickers[i : i + 50]
                    tickers_yf = [f"{t}.IS" for t in chunk]
                    data = yf.download(tickers_yf, period="1d", group_by="ticker", threads=True, progress=False)

                    for ticker in chunk:
                        try:
                            td = data.dropna() if len(chunk) == 1 else data[f"{ticker}.IS"].dropna()

                            if len(td) > 0:
                                latest = td.iloc[-1]
                                price = float(latest["Close"])
                                volume = int(latest.get("Volume", 0))

                                prev = self._last_prices.get(ticker, price)
                                change_pct = (price / prev - 1) * 100 if prev > 0 else 0

                                self._last_prices[ticker] = price
                                self._last_update[ticker] = datetime.now(UTC) - timedelta(minutes=15)

                                for handler in self._handlers:
                                    try:
                                        if asyncio.iscoroutinefunction(handler):
                                            await handler(ticker, price, volume, change_pct)
                                        else:
                                            handler(ticker, price, volume, change_pct)
                                    except Exception as exc:
                                        logger.warning("Handler error", ticker=ticker, error=str(exc))
                        except Exception as exc:
                            logger.debug("Ticker processing skipped", error=str(exc), ticker=ticker)

                    await asyncio.sleep(1)

                elapsed = time.time() - start
                logger.info("yfinance poll completed", tickers=len(tickers), elapsed=f"{elapsed:.1f}s")

                await asyncio.sleep(self._poll_interval)

            except Exception as exc:
                logger.error("yfinance polling error", error=str(exc))
                await asyncio.sleep(60)

    async def _matriks_streaming(self, tickers: list[str]) -> None:
        """Matriks streaming (WebSocket) ile veri akışı.

        Henüz implementasyon tamamlanmadı — yfinance polling'e düşer.

        Args:
            tickers: İzlenecek hisse listesi.
        """
        logger.info("Matriks streaming not yet implemented, falling back to yfinance")
        await self._yfinance_polling(tickers)

    def get_last_price(self, ticker: str) -> float | None:
        """Son bilinen fiyatı döndürür.

        Args:
            ticker: Hisse sembolü.

        Returns:
            Son fiyat veya None (hiç veri yoksa).
        """
        return self._last_prices.get(ticker)

    def get_all_prices(self) -> dict[str, float]:
        """Tüm son fiyatları döndürür.

        Returns:
            {ticker: fiyat} sözlüğü.
        """
        return dict(self._last_prices)

    def get_stats(self) -> dict[str, Any]:
        """İstatistikleri döndürür.

        Returns:
            Provider istatistik sözlüğü.
        """
        return {
            "provider": self._provider,
            "tickers_tracked": len(self._last_prices),
            "last_updates": {
                t: u.isoformat()
                for t, u in sorted(
                    self._last_update.items(),
                    key=lambda x: x[1],
                    reverse=True,
                )[:10]
            },
        }

    async def stop(self) -> None:
        """Veri akışını durdurur."""
        self._running = False
        logger.info("Realtime data provider stopped")


# Singleton
realtime_provider = RealtimeDataProvider()


__all__ = [
    "RealtimeDataProvider",
    "realtime_provider",
]
