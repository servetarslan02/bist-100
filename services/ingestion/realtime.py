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
from datetime import UTC, datetime
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
    """

    def __init__(self):
        self._running = False
        self._handlers: list[Callable] = []
        self._last_prices: dict[str, float] = {}
        self._last_update: dict[str, datetime] = {}
        self._poll_interval = 300  # 5 dakika (yfinance delayed)
        self._provider = "yfinance"  # Default

    def on_tick(self, handler: Callable):
        """Tick handler kaydet."""
        self._handlers.append(handler)
        if len(self._handlers) > 100:
            self._handlers = self._handlers[-100:]

    async def start(self, tickers: list[str], provider: str = "yfinance"):
        """Veri akışını başlat."""
        self._running = True
        self._provider = provider

        logger.info("Realtime data provider starting", provider=provider, tickers=len(tickers))

        if provider == "yfinance":
            await self._yfinance_polling(tickers)
        elif provider == "matriks":
            await self._matriks_streaming(tickers)
        else:
            logger.error("Unknown provider", provider=provider)

    async def _yfinance_polling(self, tickers: list[str]):
        """yfinance ile polling (5 dakika aralıkla)."""

        while self._running:
            try:
                start = time.time()

                # Chunked download
                for i in range(0, len(tickers), 50):
                    chunk = tickers[i : i + 50]
                    tickers_yf = [f"{t}.IS" for t in chunk]
                    data = yf.download(tickers_yf, period="1d", group_by="ticker", threads=True, progress=False)

                    for ticker in chunk:
                        try:
                            # yf returns a DataFrame where columns might be a MultiIndex if multiple tickers
                            td = data.dropna() if len(chunk) == 1 else data[f"{ticker}.IS"].dropna()

                            if len(td) > 0:
                                latest = td.iloc[-1]
                                price = float(latest["Close"])
                                volume = int(latest.get("Volume", 0))

                                # Değişim hesapla
                                prev = self._last_prices.get(ticker, price)
                                change_pct = (price / prev - 1) * 100 if prev > 0 else 0

                                # Güncelle
                                self._last_prices[ticker] = price
                                from datetime import timedelta

                                self._last_update[ticker] = datetime.now(UTC) - timedelta(minutes=15)

                                # Handler'ları çağır
                                for handler in self._handlers:
                                    try:
                                        if asyncio.iscoroutinefunction(handler):
                                            await handler(ticker, price, volume, change_pct)
                                        else:
                                            handler(ticker, price, volume, change_pct)
                                    except Exception as e:
                                        logger.warning("Handler error", ticker=ticker, error=str(e))
                        except Exception as e:
                            logger.debug("Handled exception", error=str(e), ticker=ticker)

                    # Rate limit protection between chunks
                    await asyncio.sleep(1)

                elapsed = time.time() - start
                logger.info("yfinance poll completed", tickers=len(tickers), elapsed=f"{elapsed:.1f}s")

                # Sonraki poll'e kadar bekle
                await asyncio.sleep(self._poll_interval)

            except Exception as e:
                logger.error("yfinance polling error", error=str(e))
                await asyncio.sleep(60)

    async def _matriks_streaming(self, tickers: list[str]):
        """Matriks streaming (WebSocket)."""
        # Matriks API entegrasyonu
        logger.info("Matriks streaming not yet implemented, falling back to yfinance")
        await self._yfinance_polling(tickers)

    def get_last_price(self, ticker: str) -> float | None:
        """Son fiyat."""
        return self._last_prices.get(ticker)

    def get_all_prices(self) -> dict[str, float]:
        """Tüm son fiyatlar."""
        return dict(self._last_prices)

    def get_stats(self) -> dict[str, Any]:
        """İstatistikler."""
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

    async def stop(self):
        """Veri akışını durdur."""
        self._running = False
        logger.info("Realtime data provider stopped")


# Singleton
realtime_provider = RealtimeDataProvider()
