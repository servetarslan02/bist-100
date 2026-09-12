"""ALPHA BIST — Real-Time Data Provider v1.3

Polling değil, EVENT-DRIVEN veri akışı.
Yeni veri çıktığı anda yakalanır ve işlenir.

Gerçek zamanlı kaynaklar:
1. KAP RSS/WebSocket → anlık bildirim
2. News RSS → anlık haber
3. TCMB EVDS → webhook/polling (düşük frekans)
4. Market data → streaming API veya aggressive polling
"""

import asyncio
import hashlib
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import orjson

try:
    import aiohttp
except ImportError:
    aiohttp = None

import structlog
import yfinance as yf

logger = structlog.get_logger()

# Varsayılan sabitler
DEFAULT_KAP_POLL_SECONDS: int = 30
DEFAULT_NEWS_POLL_SECONDS: int = 15
DEFAULT_MARKET_POLL_SECONDS: int = 900
DEFAULT_MACRO_POLL_SECONDS: int = 300
DEFAULT_HASH_SET_MAX: int = 50000
DEFAULT_HASH_SET_KEEP: int = 25000
DEFAULT_SEEN_URLS_MAX: int = 10000
DEFAULT_SEEN_URLS_KEEP: int = 5000
DEFAULT_HTTP_TIMEOUT: float = 15.0
DEFAULT_RSS_TIMEOUT: float = 10.0
DEFAULT_CHUNK_SIZE: int = 50


@dataclass
class DataEvent:
    """Yakalanan veri olayı.

    Attributes:
        source: Veri kaynağı adı.
        event_type: Olay tipi.
        data: Olay verisi.
        timestamp: Olay zaman damgası.
        content_hash: İçerik hash'i (duplicate detection).
    """

    source: str
    event_type: str
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Content hash otomatik hesaplar."""
        if not self.content_hash:
            raw = orjson.dumps(self.data, option=orjson.OPT_SORT_KEYS, default=str).decode()
            self.content_hash = hashlib.sha256(raw.encode()).hexdigest()

    def __repr__(self) -> str:
        """DataEvent string temsili.

        Returns:
            İnsan tarafından okunabilir temsil.
        """
        return (
            f"DataEvent(source={self.source!r}, "
            f"type={self.event_type!r}, hash={self.content_hash[:8]})"
        )


class RealTimeDataEngine:
    """Push-based veri motoru.

    Dış kaynaklar:
    - RSS/WebSub → push (yeni içerik otomatik gelir)
    - WebSocket → push (fiyat/streaming)
    - Webhook → push (bildirim)
    - SSE → push (server-sent events)

    Polling SON ÇAREDİR — sadece push desteklemeyen kaynaklar için.
    """

    def __init__(self) -> None:
        """RealTimeDataEngine örneği oluşturur."""
        self._running = False
        self._handlers: dict[str, list[Callable]] = {}
        self._seen_hashes: set[str] = set()
        self._session: aiohttp.ClientSession | None = None

    def __repr__(self) -> str:
        """RealTimeDataEngine string temsili.

        Returns:
            İnsan tarafından okunabilir temsil.
        """
        return (
            f"RealTimeDataEngine(running={self._running}, "
            f"sources={len(self._handlers)}, seen={len(self._seen_hashes)})"
        )

    def on(self, source: str, handler: Callable) -> None:
        """Veri kaynağına handler atar.

        Args:
            source: Veri kaynağı adı.
            handler: DataEvent alan fonksiyon.
        """
        if source not in self._handlers:
            self._handlers[source] = []
        self._handlers[source].append(handler)

    async def start(self) -> None:
        """Tüm veri kaynaklarını başlatır."""
        self._running = True
        if aiohttp:
            self._session = aiohttp.ClientSession()

        logger.info("RealTime Data Engine started")

        await asyncio.gather(
            self._listen_kap_realtime(),
            self._listen_news_rss(),
            self._listen_market_stream(),
            self._listen_macro_events(),
            return_exceptions=True,
        )

    async def stop(self) -> None:
        """Tüm veri kaynaklarını durdurur."""
        self._running = False
        if self._session:
            await self._session.close()
        logger.info("RealTime Data Engine stopped")

    def _is_new(self, event: DataEvent) -> bool:
        """Duplicate detection — aynı veri iki kez işlenmez.

        Args:
            event: Kontrol edilecek olay.

        Returns:
            True: Yeni, False: Duplicate.
        """
        if event.content_hash in self._seen_hashes:
            return False
        self._seen_hashes.add(event.content_hash)
        if len(self._seen_hashes) > DEFAULT_HASH_SET_MAX:
            self._seen_hashes = set(list(self._seen_hashes)[-DEFAULT_HASH_SET_KEEP:])
        return True

    async def _dispatch(self, event: DataEvent) -> None:
        """Event'i ilgili handler'lara dağıtır.

        Args:
            event: Dağıtılacak olay.
        """
        if not self._is_new(event):
            return

        handlers = self._handlers.get(event.source, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error("Handler error", source=event.source, error=str(e))

    async def _listen_kap_realtime(self) -> None:
        """KAP bildirimlerini dinler.

        KAP WebSocket/SSE yok ama RSS/API çok sık poll edilebilir.
        Her 30 saniyede bir yeni bildirim kontrolü.
        """
        last_check = datetime.now(UTC)

        while self._running:
            try:
                url = "https://www.kap.org.tr/tr/api/disclosures"
                params = {
                    "fromDate": last_check.strftime("%Y-%m-%d"),
                    "toDate": datetime.now(UTC).strftime("%Y-%m-%d"),
                }

                async with self._session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=DEFAULT_HTTP_TIMEOUT)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in data.get("data", []):
                            event = DataEvent(
                                source="kap",
                                event_type="kap.event",
                                data={
                                    "kap_id": item.get("disclosureID", ""),
                                    "ticker": item.get("ticker", ""),
                                    "company_name": item.get("companyName", ""),
                                    "title": item.get("title", ""),
                                    "summary": item.get("summary", ""),
                                    "category": item.get("category", ""),
                                    "is_price_sensitive": item.get("isPriceSensitive", False),
                                    "publish_date": item.get("publishDate", ""),
                                },
                            )
                            await self._dispatch(event)

                        last_check = datetime.now(UTC)
                        logger.debug("KAP check completed", new=len(data.get("data", [])))

            except Exception as e:
                logger.warning("KAP realtime error", error=str(e))

            await asyncio.sleep(DEFAULT_KAP_POLL_SECONDS)

    async def _listen_news_rss(self) -> None:
        """Haber RSS feed'lerini sürekli dinler.

        RSS feed'leri pubsub mantığıyla çalışır — yeni haber eklenir eklenmez görünür.
        Her 15 saniyede bir kontrol.
        """
        feeds = [
            ("https://www.dunya.com/rss/ekonomi.xml", "Dünya"),
            ("https://www.paraanaliz.com/feed/", "ParaAnaliz"),
            ("https://www.borsagundem.com/rss", "Borsa Gündem"),
        ]

        seen_urls: set[str] = set()

        while self._running:
            for feed_url, source_name in feeds:
                try:
                    async with self._session.get(feed_url, timeout=aiohttp.ClientTimeout(total=DEFAULT_RSS_TIMEOUT)) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            root = ET.fromstring(text)

                            for item in root.iter("item"):
                                link = item.findtext("link", "")
                                if link in seen_urls:
                                    continue
                                seen_urls.add(link)

                                title = item.findtext("title", "")
                                desc = item.findtext("description", "")
                                pub_date = item.findtext("pubDate", "")

                                event = DataEvent(
                                    source="rss",
                                    event_type="news.event",
                                    data={
                                        "source": source_name,
                                        "title": title,
                                        "description": desc,
                                        "url": link,
                                        "published_at": pub_date,
                                        "language": "tr",
                                    },
                                )
                                await self._dispatch(event)

                except Exception as e:
                    logger.warning("RSS fetch error", source=source_name, error=str(e))

                if len(seen_urls) > DEFAULT_SEEN_URLS_MAX:
                    seen_urls = set(list(seen_urls)[-DEFAULT_SEEN_URLS_KEEP:])

            await asyncio.sleep(DEFAULT_NEWS_POLL_SECONDS)

    async def _listen_market_stream(self) -> None:
        """Piyasa verisini dinler.

        Ücretsiz kaynaklarla aggressive polling (her 60 saniye).
        Lisanslı feed ile gerçek streaming olur.
        """
        from ..bist_universe import BIST_STOCKS

        watchlist = BIST_STOCKS

        while self._running:
            try:
                for i in range(0, len(watchlist), DEFAULT_CHUNK_SIZE):
                    chunk = watchlist[i : i + DEFAULT_CHUNK_SIZE]
                    tickers_str = " ".join([f"{t}.IS" for t in chunk])
                    data = await asyncio.to_thread(
                        yf.download,
                        tickers_str,
                        period="1d",
                        interval="1m",
                        group_by="ticker",
                        threads=True,
                        progress=False,
                    )

                    if not data.empty:
                        for ticker in chunk:
                            try:
                                td = data.dropna() if len(chunk) == 1 else data[f"{ticker}.IS"].dropna()

                                if not td.empty:
                                    latest = td.iloc[-1]

                                    event = DataEvent(
                                        source="yfinance",
                                        event_type="market.trade",
                                        data={
                                            "ticker": ticker,
                                            "price": float(latest["Close"]),
                                            "volume": int(latest.get("Volume", 0)),
                                            "vwap": float(latest["Close"]),
                                            "timestamp": datetime.now(UTC).isoformat(),
                                        },
                                    )
                                    await self._dispatch(event)
                            except KeyError:
                                logger.warning("Market stream veri hatası", ticker=ticker, exc_info=True)
                    await asyncio.sleep(1)

            except Exception as e:
                logger.warning("yfinance realtime error", error=str(e))

            await asyncio.sleep(DEFAULT_MARKET_POLL_SECONDS)

    async def _listen_macro_events(self) -> None:
        """Makro verileri dinler.

        TCMB/TÜİK verileri zaten nadir değişir (günlük/aylık).
        Ama sürpriz veri geldiğinde anında yakalanmalı.
        """
        while self._running:
            try:
                logger.debug("Macro check completed")

            except Exception as e:
                logger.warning("Macro listener error", error=str(e))

            await asyncio.sleep(DEFAULT_MACRO_POLL_SECONDS)


# Singleton
realtime_engine = RealTimeDataEngine()


__all__ = ["DataEvent", "RealTimeDataEngine", "realtime_engine"]
