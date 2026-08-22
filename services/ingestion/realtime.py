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
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timezone

import yfinance as yf
import structlog

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
        self._handlers: List[Callable] = []
        self._last_prices: Dict[str, float] = {}
        self._last_update: Dict[str, datetime] = {}
        self._poll_interval = 300  # 5 dakika (yfinance delayed)
        self._provider = "yfinance"  # Default

    def on_tick(self, handler: Callable):
        """Tick handler kaydet."""
        self._handlers.append(handler)
        if len(self._handlers) > 100:
            self._handlers = self._handlers[-100:]

    async def start(self, tickers: List[str], provider: str = "yfinance"):
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

    async def _yfinance_polling(self, tickers: List[str]):
        """yfinance ile polling (5 dakika aralıkla)."""

        while self._running:
            try:
                start = time.time()

                # Batch download
                tickers_yf = [f"{t}.IS" for t in tickers[:50]]
                data = yf.download(tickers_yf, period="1d", group_by="ticker",
                                  threads=True, progress=False)

                for ticker in tickers[:50]:
                    try:
                        td = data[f"{ticker}.IS"].dropna()
                        if len(td) > 0:
                            latest = td.iloc[-1]
                            price = float(latest["Close"])
                            volume = int(latest.get("Volume", 0))

                            # Değişim hesapla
                            prev = self._last_prices.get(ticker, price)
                            change_pct = (price / prev - 1) * 100 if prev > 0 else 0

                            # Güncelle
                            self._last_prices[ticker] = price
                            self._last_update[ticker] = datetime.now(timezone.utc)

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
                        logger.debug("Handled exception", error=str(e), context="realtime.py:94")
                        pass

                elapsed = time.time() - start
                logger.info("yfinance poll completed", tickers=len(tickers), elapsed=f"{elapsed:.1f}s")

                # Sonraki poll'e kadar bekle
                await asyncio.sleep(self._poll_interval)

            except Exception as e:
                logger.error("yfinance polling error", error=str(e))
                await asyncio.sleep(60)

    async def _matriks_streaming(self, tickers: List[str]):
        """Matriks streaming (WebSocket)."""
        # Matriks API entegrasyonu
        logger.info("Matriks streaming not yet implemented, falling back to yfinance")
        await self._yfinance_polling(tickers)

    def get_last_price(self, ticker: str) -> Optional[float]:
        """Son fiyat."""
        return self._last_prices.get(ticker)

    def get_all_prices(self) -> Dict[str, float]:
        """Tüm son fiyatlar."""
        return dict(self._last_prices)

    def get_stats(self) -> Dict[str, Any]:
        """İstatistikler."""
        return {
            "provider": self._provider,
            "tickers_tracked": len(self._last_prices),
            "last_updates": {
                t: u.isoformat() for t, u in sorted(
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
