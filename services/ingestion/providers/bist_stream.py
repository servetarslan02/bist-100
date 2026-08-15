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
import json
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime, timezone
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class StreamTick:
    """Streaming tick verisi."""
    ticker: str
    price: float
    volume: int
    bid: float = 0.0
    ask: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""


class BISTStreamProvider:
    """
    BIST market data stream provider.
    Birden fazla kaynak destekler.
    """

    def __init__(self):
        self._handlers: List[Callable] = []
        self._running = False
        self._source = "yfinance"  # Varsayılan
        self._tick_count = 0

    def on_tick(self, handler: Callable):
        """Tick handler ata."""
        self._handlers.append(handler)
        return self

    async def start(self, source: str = "yfinance"):
        """Stream'i başlat."""
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

    async def stop(self):
        """Stream'i durdur."""
        self._running = False

    async def _stream_yfinance(self):
        """
        yfinance ile aggressive polling.
        Ücretsiz, 15dk gecikmeli, ama sürekli.
        """
        import yfinance as yf
        from ..bist_universe import bist_universe

        tickers = bist_universe.get_tickers()
        logger.info("Starting yfinance stream", tickers=len(tickers))

        while self._running:
            try:
                # Batch download
                data = yf.download(
                    [f"{t}.IS" for t in tickers[:100]],  # İlk 100
                    period="1d",
                    interval="1m",
                    group_by="ticker",
                    threads=True,
                    progress=False,
                )

                if not data.empty:
                    for ticker in tickers[:100]:
                        try:
                            td = data[f"{ticker}.IS"].dropna()
                            if td.empty:
                                continue

                            last_row = td.iloc[-1]
                            prev_row = td.iloc[-2] if len(td) > 1 else last_row

                            tick = StreamTick(
                                ticker=ticker,
                                price=float(last_row["Close"]),
                                volume=int(last_row["Volume"]),
                                timestamp=datetime.now(timezone.utc),
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
                            pass

                # 60 saniye bekle (ücretsiz API limiti)
                await asyncio.sleep(60)

            except Exception as e:
                logger.error("yfinance stream error", error=str(e))
                await asyncio.sleep(30)

    async def _stream_investing(self):
        """
        Investing.com WebSocket stream.
        Ücretsiz, gecikmeli, ama sürekli.
        """
        try:
            import websockets

            uri = "wss://streaming.forexpros.com/echo/websocket"

            async with websockets.connect(uri) as ws:
                # Subscribe to BIST stocks
                subscribe_msg = json.dumps({
                    "_event": "bulk-subscribe",
                    "message": "pid-list:497,347,1052,..."  # Investing.com BIST IDs
                })
                await ws.send(subscribe_msg)

                while self._running:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        data = json.loads(msg)

                        if "message" in data:
                            parts = data["message"].split("::")
                            if len(parts) >= 2:
                                ticker_data = json.loads(parts[1])
                                tick = StreamTick(
                                    ticker=ticker_data.get("symbol", ""),
                                    price=float(ticker_data.get("last", 0)),
                                    volume=int(ticker_data.get("volume", 0)),
                                    timestamp=datetime.now(timezone.utc),
                                    source="investing",
                                )

                                for handler in self._handlers:
                                    try:
                                        if asyncio.iscoroutinefunction(handler):
                                            await handler(tick)
                                        else:
                                            handler(tick)
                                    except Exception:
                                        pass

                                self._tick_count += 1

                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        logger.warning("Investing stream error", error=str(e))

        except ImportError:
            logger.warning("websockets not installed, falling back to yfinance")
            await self._stream_yfinance()
        except Exception as e:
            logger.error("Investing stream failed", error=str(e))
            await self._stream_yfinance()

    async def _stream_websocket(self):
        """
        Generic WebSocket stream.
        BISTECH veya özel feed bağlanabilir.
        """
        try:
            import websockets

            # BISTECH API endpoint (ücretli)
            uri = "wss://feed.bistech.com.tr/v1/stream"

            async with websockets.connect(uri) as ws:
                # Auth
                auth_msg = json.dumps({
                    "type": "auth",
                    "api_key": "YOUR_API_KEY",
                })
                await ws.send(auth_msg)

                # Subscribe
                subscribe_msg = json.dumps({
                    "type": "subscribe",
                    "symbols": ["THYAO", "ASELS", "AKBNK", "TUPRS", "EREGL"],
                })
                await ws.send(subscribe_msg)

                while self._running:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        data = json.loads(msg)

                        if data.get("type") == "trade":
                            tick = StreamTick(
                                ticker=data.get("symbol", ""),
                                price=float(data.get("price", 0)),
                                volume=int(data.get("volume", 0)),
                                bid=float(data.get("bid", 0)),
                                ask=float(data.get("ask", 0)),
                                timestamp=datetime.now(timezone.utc),
                                source="bistech",
                            )

                            for handler in self._handlers:
                                try:
                                    if asyncio.iscoroutinefunction(handler):
                                        await handler(tick)
                                    else:
                                        handler(tick)
                                except Exception:
                                    pass

                            self._tick_count += 1

                    except asyncio.TimeoutError:
                        continue

        except Exception as e:
            logger.error("WebSocket stream failed", error=str(e))
            await self._stream_yfinance()

    def get_stats(self) -> Dict:
        """İstatistikler."""
        return {
            "source": self._source,
            "tick_count": self._tick_count,
            "running": self._running,
            "handlers": len(self._handlers),
        }


# Singleton
bist_stream = BISTStreamProvider()
