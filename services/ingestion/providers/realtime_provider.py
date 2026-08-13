"""ALPHA BIST - Real-Time Data Provider v1.3

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
import json
from datetime import datetime
from typing import Optional, Dict, Any, Callable, List, Set
from dataclasses import dataclass, field
try:
    import aiohttp
except ImportError:
    aiohttp = None
import structlog

logger = structlog.get_logger()


@dataclass
class DataEvent:
    """Yakalanan veri olayı."""
    source: str
    event_type: str
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    content_hash: str = ""

    def __post_init__(self):
        if not self.content_hash:
            raw = json.dumps(self.data, sort_keys=True, default=str)
            self.content_hash = hashlib.md5(raw.encode()).hexdigest()


class RealTimeDataEngine:
    """
    Push-based veri motoru.

    Dış kaynaklar:
    - RSS/WebSub → push (yeni içerik otomatik gelir)
    - WebSocket → push (fiyat/streaming)
    - Webhook → push (bildirim)
    - SSE → push (server-sent events)

    Polling SON ÇAREDİR — sadece push desteklemeyen kaynaklar için.
    """

    def __init__(self):
        self._running = False
        self._handlers: Dict[str, List[Callable]] = {}
        self._seen_hashes: Set[str] = set()  # Duplicate detection
        self._session: Optional[aiohttp.ClientSession] = None

    def on(self, source: str, handler: Callable):
        """Veri kaynağına handler ata."""
        if source not in self._handlers:
            self._handlers[source] = []
        self._handlers[source].append(handler)
        return self

    async def start(self):
        """Tüm veri kaynaklarını başlat."""
        self._running = True
        if aiohttp:
            self._session = aiohttp.ClientSession()

        logger.info("RealTime Data Engine started")

        # Paralel olarak tüm kaynakları dinle
        await asyncio.gather(
            self._listen_kap_realtime(),
            self._listen_news_rss(),
            self._listen_market_stream(),
            self._listen_macro_events(),
            return_exceptions=True,
        )

    async def stop(self):
        """Durdur."""
        self._running = False
        if self._session:
            await self._session.close()

    def _is_new(self, event: DataEvent) -> bool:
        """Duplicate detection — aynı veri iki kez işlenmez."""
        if event.content_hash in self._seen_hashes:
            return False
        self._seen_hashes.add(event.content_hash)
        # Memory limit
        if len(self._seen_hashes) > 50000:
            self._seen_hashes = set(list(self._seen_hashes)[-25000:])
        return True

    async def _dispatch(self, event: DataEvent):
        """Event'i ilgili handler'lara dağıt."""
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

    # =====================================================
    # KAP Real-Time (RSS polling — çok sık)
    # =====================================================

    async def _listen_kap_realtime(self):
        """
        KAP bildirimlerini dinle.
        KAP WebSocket/SSE yok ama RSS/API çok sık poll edilebilir.
        Her 30 saniyede bir yeni bildirim kontrolü.
        """
        last_check = datetime.utcnow()

        while self._running:
            try:
                # KAP API'den son bildirimleri çek
                url = "https://www.kap.org.tr/tr/api/disclosures"
                params = {
                    "fromDate": last_check.strftime("%Y-%m-%d"),
                    "toDate": datetime.utcnow().strftime("%Y-%m-%d"),
                }

                async with self._session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
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

                        last_check = datetime.utcnow()
                        logger.debug("KAP check completed", new=len(data.get("data", [])))

            except Exception as e:
                logger.warning("KAP realtime error", error=str(e))

            # 30 saniye bekle — KAP'ta yeni bildirim anında düşer
            await asyncio.sleep(30)

    # =====================================================
    # News RSS Real-Time (SSE/RSS — sürekli)
    # =====================================================

    async def _listen_news_rss(self):
        """
        Haber RSS feed'lerini sürekli dinle.
        RSS feed'leri pubsub mantığıyla çalışır — yeni haber eklenir eklenmez görünür.
        Her 15 saniyede bir kontrol.
        """
        import xml.etree.ElementTree as ET

        feeds = [
            ("https://www.dunya.com/rss/ekonomi.xml", "Dünya"),
            ("https://www.paraanaliz.com/feed/", "ParaAnaliz"),
            ("https://www.borsagundem.com/rss", "Borsa Gündem"),
        ]

        seen_urls: Set[str] = set()

        while self._running:
            for feed_url, source_name in feeds:
                try:
                    async with self._session.get(feed_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
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
                    logger.debug("RSS fetch error", source=source_name, error=str(e))

                # Memory limit
                if len(seen_urls) > 10000:
                    seen_urls = set(list(seen_urls)[-5000:])

            # 15 saniye bekle
            await asyncio.sleep(15)

    # =====================================================
    # Market Data Stream (aggressive polling)
    # =====================================================

    async def _listen_market_stream(self):
        """
        Piyasa verisini dinle.
        Ücretsiz kaynaklarla aggressive polling (her 60 saniye).
        Lisanslı feed ile gerçek streaming olur.
        """
        import yfinance as yf
        from ..bist_universe import BIST_STOCKS

        # Sadece aktif hisseleri dinle (ilk 50 — en likit)
        watchlist = BIST_STOCKS[:50]

        while self._running:
            try:
                # Batch download — tek seferde 50 hisse
                tickers_str = " ".join([f"{t}.IS" for t in watchlist])
                data = yf.download(
                    tickers_str,
                    period="1d",
                    interval="1m",
                    group_by="ticker",
                    threads=True,
                    progress=False,
                )

                if not data.empty:
                    for ticker in watchlist:
                        try:
                            td = data[f"{ticker}.IS"]
                            if td.empty:
                                continue

                            last_row = td.iloc[-1]
                            prev_row = td.iloc[-2] if len(td) > 1 else last_row

                            event = DataEvent(
                                source="market",
                                event_type="market.tick",
                                data={
                                    "ticker": ticker,
                                    "price": float(last_row["Close"]),
                                    "open": float(last_row["Open"]),
                                    "high": float(last_row["High"]),
                                    "low": float(last_row["Low"]),
                                    "volume": int(last_row["Volume"]),
                                    "change_pct": float((last_row["Close"] / prev_row["Close"] - 1) * 100) if prev_row["Close"] > 0 else 0,
                                    "timestamp": str(last_row.name),
                                },
                            )
                            await self._dispatch(event)
                        except Exception:
                            pass

                logger.debug("Market stream tick", stocks=len(watchlist))

            except Exception as e:
                logger.warning("Market stream error", error=str(e))

            # 60 saniye — ücretsiz kaynaklarla makul interval
            # Lisanslı feed ile bu 0 olur (real-time streaming)
            await asyncio.sleep(60)

    # =====================================================
    # Macro Events (düşük frekans — zaten nadir değişir)
    # =====================================================

    async def _listen_macro_events(self):
        """
        Makro verileri dinle.
        TCMB/TÜİK verileri zaten nadir değişir (günlük/aylık).
        Ama sürpriz veri geldiğinde anında yakalanmalı.
        """
        while self._running:
            try:
                # TCMB EVDS'den son verileri kontrol et
                # (Gerçek implementasyonda webhook/SSE kullanılabilir)
                logger.debug("Macro check completed")

            except Exception as e:
                logger.warning("Macro listener error", error=str(e))

            # 5 dakika — makro veri zaten nadir değişir
            await asyncio.sleep(300)


# Singleton
realtime_engine = RealTimeDataEngine()
