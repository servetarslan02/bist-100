"""
ALPHA BIST — BIST Market Data Stream v1.0

5. Gerçek BIST streaming market data provider.
Ücretsiz seçenekler:
- BISTECH API (ücretli ama en doğru)
- Investing.com WebSocket (ücretsiz, gecikmeli)
- TradingView WebSocket (ücretsiz, gecikmeli)
- Yahoo Finance WebSocket (ücretsiz, gecikmeli)
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import orjson
import structlog
import yfinance as yf

logger = structlog.get_logger()

# Varsayılan sabitler
DEFAULT_MAX_HANDLERS: int = 100
DEFAULT_STREAM_POLL_SECONDS: int = 60
DEFAULT_STREAM_ERROR_BACKOFF: int = 30
DEFAULT_WS_TIMEOUT: float = 5.0


@dataclass
class StreamTick:
    """Streaming tick verisi."""

    ticker: str
    price: float
    volume: int
    bid: float = 0.0
    ask: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    source: str = ""

    def __repr__(self) -> str:
        """StreamTick string temsili.

        Returns:
            İnsan tarafından okunabilir temsil.
        """
        return (
            f"StreamTick(ticker={self.ticker!r}, "
            f"price={self.price}, volume={self.volume}, "
            f"source={self.source!r})"
        )


class BISTStreamProvider:
    """
    BIST market data stream provider.
    Birden fazla kaynak destekler.
    """

    def __init__(self) -> None:
        """BISTStreamProvider örneği oluşturur."""
        self._handlers: list[Callable] = []
        self._running = False
        self._source = "yfinance"
        self._tick_count = 0

    def __repr__(self) -> str:
        """BISTStreamProvider string temsili.

        Returns:
            İnsan tarafından okunabilir temsil.
        """
        return (
            f"BISTStreamProvider(source={self._source!r}, "
            f"running={self._running}, ticks={self._tick_count})"
        )

    def on_tick(self, handler: Callable) -> "BISTStreamProvider":
        """Tick handler kaydeder.

        Maksimum 100 handler tutulur.

        Args:
            handler: StreamTick alan fonksiyon.

        Returns:
            Kendisi (chain için).
        """
        self._handlers.append(handler)
        if len(self._handlers) > DEFAULT_MAX_HANDLERS:
            self._handlers = self._handlers[-DEFAULT_MAX_HANDLERS:]
        return self

    async def start(self, source: str = "yfinance") -> None:
        """Stream'i başlatır.

        Args:
            source: Veri kaynağı ("yfinance", "investing", "websocket").
        """
        self._source = source
        self._running = True

        if source == "yfinance":
            await self._stream_yfinance()
        elif source == "investing":
            await self._stream_investing()
        elif source == "websocket":
            await self._stream_websocket()
        else:
            logger.error("Unknown stream source", source=source)

    async def stop(self) -> None:
        """Stream'i durdurur."""
        self._running = False
        logger.info("BIST stream stopped", source=self._source, ticks=self._tick_count)

    async def _stream_yfinance(self) -> None:
        """yfinance ile aggressive polling yapar.

        Ücretsiz, 15dk gecikmeli, ama sürekli.
        Blokluyor yf.download() asyncio.to_thread ile sarılır.
        """
        from ..bist_universe import bist_universe

        tickers = bist_universe.get_tickers()
        logger.info("Starting yfinance stream", tickers=len(tickers))

        while self._running:
            try:
                # Batch download for all universe tickers
                data = await asyncio.to_thread(
                    yf.download,
                    [f"{t}.IS" for t in tickers],
                    period="1d",
                    interval="1m",
                    group_by="ticker",
                    threads=True,
                    progress=False,
                )

                if not data.empty:
                    for ticker in tickers:
                        try:
                            td = data[f"{ticker}.IS"].dropna()
                            if td.empty:
                                continue

                            last_row = td.iloc[-1]

                            tick = StreamTick(
                                ticker=ticker,
                                price=float(last_row["Close"]),
                                volume=int(last_row["Volume"]),
                                timestamp=datetime.now(UTC),
                                source="yfinance",
                            )

                            # Handler'lara gönder
                            for handler in self._handlers:
                                try:
                                    if asyncio.iscoroutinefunction(handler):
                                        await handler(tick)
                                    else:
                                        handler(tick)
                                except Exception as e:
                                    logger.warning("Tick handler error", error=str(e))

                            self._tick_count += 1

                        except Exception:
                            logger.warning("Caught Exception in _stream_yfinance", exc_info=True)

                # 60 saniye bekle (ücretsiz API limiti)
                await asyncio.sleep(DEFAULT_STREAM_POLL_SECONDS)

            except Exception as e:
                logger.error("yfinance stream error", error=str(e))
                await asyncio.sleep(DEFAULT_STREAM_ERROR_BACKOFF)

    async def _stream_investing(self) -> None:
        """Investing.com WebSocket stream.

        Ücretsiz, gecikmeli, ama sürekli.
        """
        try:
            import websockets

            uri = "wss://streaming.forexpros.com/echo/websocket"

            async with websockets.connect(uri) as ws:
                # Subscribe to BIST stocks
                subscribe_msg = orjson.dumps(
                    {
                        "_event": "bulk-subscribe",
                        "message": "pid-list:497,347,1052,...",  # Investing.com BIST IDs
                    }
                ).decode()
                await ws.send(subscribe_msg)

                while self._running:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=DEFAULT_WS_TIMEOUT)
                        data = orjson.loads(msg)

                        if "message" in data:
                            parts = data["message"].split("::")
                            if len(parts) >= 2:
                                ticker_data = orjson.loads(parts[1])
                                tick = StreamTick(
                                    ticker=ticker_data.get("symbol", ""),
                                    price=float(ticker_data.get("last", 0)),
                                    volume=int(ticker_data.get("volume", 0)),
                                    timestamp=datetime.now(UTC),
                                    source="investing",
                                )

                                for handler in self._handlers:
                                    try:
                                        if asyncio.iscoroutinefunction(handler):
                                            await handler(tick)
                                        else:
                                            handler(tick)
                                    except Exception as e:
                                        logger.warning("Investing tick handler error", error=str(e))

                                self._tick_count += 1

                    except TimeoutError:
                        continue
                    except Exception as e:
                        logger.warning("Investing stream error", error=str(e))

        except ImportError:
            logger.warning("websockets not installed, falling back to yfinance")
            await self._stream_yfinance()
        except Exception as e:
            logger.error("Investing stream failed", error=str(e))
            await self._stream_yfinance()

    async def _stream_websocket(self) -> None:
        """Generic WebSocket stream.

        BISTECH veya özel feed bağlanabilir.
        API key ortam değişkeninden okunmalıdır.
        """
        import os

        api_key = os.getenv("BISTECH_API_KEY", "")
        if not api_key:
            logger.error("BISTECH_API_KEY ortam değişkeni tanımlı değil")
            await self._stream_yfinance()
            return

        try:
            import websockets

            uri = "wss://feed.bistech.com.tr/v1/stream"

            async with websockets.connect(uri) as ws:
                # Auth
                auth_msg = orjson.dumps(
                    {
                        "type": "auth",
                        "api_key": api_key,
                    }
                ).decode()
                await ws.send(auth_msg)

                from ..bist_universe import bist_universe
                sub_tickers = bist_universe.get_tickers()

                # Subscribe
                subscribe_msg = orjson.dumps(
                    {
                        "type": "subscribe",
                        "symbols": sub_tickers,
                    }
                ).decode()
                await ws.send(subscribe_msg)

                while self._running:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=DEFAULT_WS_TIMEOUT)
                        data = orjson.loads(msg)

                        if data.get("type") == "trade":
                            tick = StreamTick(
                                ticker=data.get("symbol", ""),
                                price=float(data.get("price", 0)),
                                volume=int(data.get("volume", 0)),
                                bid=float(data.get("bid", 0)),
                                ask=float(data.get("ask", 0)),
                                timestamp=datetime.now(UTC),
                                source="bistech",
                            )

                            for handler in self._handlers:
                                try:
                                    if asyncio.iscoroutinefunction(handler):
                                        await handler(tick)
                                    else:
                                        handler(tick)
                                except Exception as e:
                                    logger.warning("Bistech tick handler error", error=str(e))

                            self._tick_count += 1

                    except TimeoutError:
                        continue

        except Exception as e:
            logger.error("WebSocket stream failed", error=str(e))
            await self._stream_yfinance()

    def get_stats(self) -> dict[str, Any]:
        """İstatistikleri döndürür.

        Returns:
            Provider istatistik sözlüğü.
        """
        return {
            "source": self._source,
            "tick_count": self._tick_count,
            "running": self._running,
            "handlers": len(self._handlers),
        }


# Singleton
bist_stream = BISTStreamProvider()


__all__ = ["StreamTick", "BISTStreamProvider", "bist_stream"]
