"""ALPHA BIST - Data Ingestion Service (Main Entry Point)"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from ..core.config import settings
from ..core.connectivity import connectivity_monitor
from ..core.database import (
    close_databases,
    init_databases,
)
from ..core.event_bus import (
    EventType,
    ensure_topics,
    flush_producer,
    publish_event,
)
from ..core.event_schema import CanonicalEvent
from ..core.logging import setup_logging
from ..core.questdb_client import questdb_client
from .bist_universe import BIST_INDICES, bist_universe, get_sector

# Dinamik hisse listesi — otomatik keşif aktif (tüm 600+ hisse)
BIST_STOCKS = bist_universe.BIST_ALL_TICKERS
BIST_ALL = bist_universe.BIST_ALL_TICKERS
from .providers.investing_provider import investing_provider
from .providers.kap_provider import kap_provider
from .providers.news_provider import news_provider
from .providers.social_provider import social_provider
from .providers.tcmb_provider import tcmb_provider
from .providers.tradingview_provider import tradingview_provider
from .providers.yfinance_provider import yfinance_provider
from .questdb_consumer import questdb_tick_consumer

logger = structlog.get_logger()


def is_bist_session_active() -> bool:
    """BIST seans saatlerini (Hafta içi 09:55 - 18:10 TSİ / UTC+3) kontrol eder."""
    now_utc = datetime.now(UTC)
    if now_utc.weekday() >= 5:  # Cumartesi veya Pazar
        return False
    now_minute = now_utc.hour * 60 + now_utc.minute
    market_open = 6 * 60 + 55  # 06:55 UTC (09:55 TSİ)
    market_close = 15 * 60 + 10  # 15:10 UTC (18:10 TSİ)
    return market_open <= now_minute <= market_close


class IngestionService:
    """Main data ingestion service for ALPHA BIST."""

    def __init__(self):
        """Otomatik eklendi."""
        self._running = False
        self._instrument_map: dict[str, int] = {}  # ticker -> instrument_id

    async def start(self) -> Any:
        """Start the ingestion service."""
        setup_logging()
        logger.info("Starting ALPHA BIST Ingestion Service")

        # Otomatik hisse evrenini yenile (başlangıçta)
        await self._refresh_universe()

        await init_databases()
        ensure_topics()

        # İnternet izleyiciyi başlat (idempotent)
        if not connectivity_monitor._running:
            await connectivity_monitor.start()

        # Load instrument map from PostgreSQL
        await self._load_instrument_map()

        self._running = True
        logger.info("Ingestion Service started", instruments=len(self._instrument_map), universe_size=len(BIST_ALL))

        # QuestDB tick consumer'ı başlat
        await questdb_tick_consumer.start()

        # Start loops in the background
        t_market = asyncio.create_task(self._market_data_loop())
        t_kap = asyncio.create_task(self._kap_loop())
        t_macro = asyncio.create_task(self._macro_loop())
        t_news = asyncio.create_task(self._news_loop())
        t_social = asyncio.create_task(self._social_loop())
        self._tasks = [t_market, t_kap, t_macro, t_news, t_social]

        # Keep the service running
        while self._running:
            await asyncio.sleep(1)

    async def _refresh_universe(self) -> Any:
        """Hisse evrenini otomatik yenile."""
        global BIST_STOCKS, BIST_ALL
        try:
            logger.info("Refreshing BIST universe...")
            bist_universe.refresh()
            BIST_STOCKS = bist_universe.BIST_ALL_TICKERS
            BIST_ALL = bist_universe.BIST_ALL_TICKERS
            logger.info("BIST universe refreshed", total_stocks=len(BIST_STOCKS))
        except Exception as e:
            logger.warning("Universe refresh failed, using cached/static", error=str(e))

    async def stop(self) -> Any:
        """Stop the ingestion service."""
        self._running = False
        await questdb_tick_consumer.stop()
        await connectivity_monitor.stop()
        await flush_producer()
        await close_databases()
        logger.info("Ingestion Service stopped")

    async def _load_instrument_map(self) -> Any:
        """Load instrument ticker -> id mapping from PostgreSQL."""
        from ..core.database import pg_fetch

        rows = await pg_fetch("""
            SELECT i.symbol, i.id
            FROM instruments i
            JOIN companies c ON i.company_id = c.id
            WHERE i.active = TRUE
        """)

        self._instrument_map = {row["symbol"]: row["id"] for row in rows}

        # If no instruments exist, create them
        if not self._instrument_map:
            await self._seed_instruments()
            rows = await pg_fetch("""
                SELECT i.symbol, i.id
                FROM instruments i
                WHERE i.active = TRUE
            """)
            self._instrument_map = {row["symbol"]: row["id"] for row in rows}

    async def _seed_instruments(self) -> Any:
        """Seed initial instrument data into PostgreSQL."""
        from ..core.database import pg_execute

        logger.info("Seeding instruments into PostgreSQL")

        # First, ensure sectors exist
        sectors = set(get_sector(t) for t in BIST_STOCKS)

        for sector_code in sectors:
            await pg_execute(
                """
                INSERT INTO sectors (code, name)
                VALUES ($1, $1)
                ON CONFLICT (code) DO NOTHING
            """,
                sector_code,
            )

        # Then, create companies and instruments
        for ticker in BIST_STOCKS:
            sector = get_sector(ticker)

            # Get sector_id
            await pg_execute(
                """
                SELECT id FROM sectors WHERE code = $1
            """,
                sector,
            )

            # Create company
            await pg_execute(
                """
                INSERT INTO companies (ticker, name, sector_id, active)
                VALUES ($1, $1, (SELECT id FROM sectors WHERE code = $2), TRUE)
                ON CONFLICT (ticker) DO NOTHING
            """,
                ticker,
                sector,
            )

            # Create instrument
            await pg_execute(
                """
                INSERT INTO instruments (company_id, symbol, instrument_type, exchange, active)
                VALUES (
                    (SELECT id FROM companies WHERE ticker = $1),
                    $1, 'EQUITY', 'BIST', TRUE
                )
                ON CONFLICT (symbol) DO NOTHING
            """,
                ticker,
            )

        logger.info("Instruments seeded", count=len(BIST_STOCKS))

    # =====================================================
    # Market Data Loop
    # =====================================================

    async def _market_data_loop(self) -> Any:
        """Periodically fetch market data from yfinance."""
        while self._running:
            try:
                if not is_bist_session_active():
                    logger.debug("Market closed, skipping market data fetch cycle")
                    await asyncio.sleep(300)
                    continue

                # İnternet kontrolü — offline ise bekle
                if not connectivity_monitor.is_online:
                    logger.info("Offline mode, waiting 60s before retry...")
                    await asyncio.sleep(60)
                    continue

                logger.info("Starting market data fetch cycle")

                # 1. PRIMARY: TradingView Scanner API (Tüm BIST tek pakette ~150ms)
                tv_stocks = await tradingview_provider.fetch_all_bist_stocks()
                if tv_stocks:
                    logger.info("TradingView primary market feed active", count=len(tv_stocks))
                    ticks_list: list[dict[str, Any]] = []
                    now_utc = datetime.now(UTC)
                    for ticker, data in tv_stocks.items():
                        if not self._running:
                            break
                        ticks_list.append({
                            "ticker": ticker,
                            "price": float(data["price"]),
                            "volume": int(data.get("volume", 0) or 0),
                            "bid": float(data.get("low", 0.0) or 0.0),
                            "ask": float(data.get("high", 0.0) or 0.0),
                            "timestamp": now_utc,
                        })
                        instrument_id = self._instrument_map.get(ticker)
                        if instrument_id:
                            event = CanonicalEvent(
                                event_type=EventType.MARKET_TICK,
                                source="tradingview",
                                data={
                                    "instrument_id": instrument_id,
                                    "ticker": ticker,
                                    "price": data["price"],
                                    "close": data["close"],
                                    "volume": data.get("volume", 0),
                                    "value_traded": data.get("value_traded", 0),
                                    "open": data.get("open"),
                                    "high": data.get("high"),
                                    "low": data.get("low"),
                                    "change_pct": data.get("change_pct", 0),
                                    "rsi": data.get("rsi"),
                                    "macd": data.get("macd"),
                                    "sma50": data.get("sma50"),
                                    "sma200": data.get("sma200"),
                                    "market_cap": data.get("market_cap"),
                                    "pe_ratio": data.get("pe_ratio"),
                                    "pb_ratio": data.get("pb_ratio"),
                                    "recommendation": data.get("recommendation"),
                                    "source": "tradingview",
                                },
                            )
                            publish_event(event, key=ticker)

                    # Toplu olarak yüksek performanslı QuestDB ILP'ye yaz
                    if ticks_list:
                        try:
                            questdb_client.insert_ticks_batch(ticks_list)
                        except Exception as q_exc:
                            logger.debug("Direct QuestDB batch write notice", error=str(q_exc))
                else:
                    # 2. FALLBACK: yfinance chunked retrieval
                    logger.info("TradingView scan unavailable, running yfinance fallback...")
                    CHUNK_SIZE = 20
                    for i in range(0, len(BIST_STOCKS), CHUNK_SIZE):
                        if not self._running:
                            break
                        chunk = BIST_STOCKS[i : i + CHUNK_SIZE]
                        for ticker in chunk:
                            if not self._running:
                                break
                            try:
                                data = yfinance_provider.fetch_current_price(ticker)
                                if data and data.get("price"):
                                    instrument_id = self._instrument_map.get(ticker)
                                    if instrument_id:
                                        event = CanonicalEvent(
                                            event_type=EventType.MARKET_TICK,
                                            source="yfinance",
                                            data={
                                                "instrument_id": instrument_id,
                                                "ticker": ticker,
                                                "price": data["price"],
                                                "volume": data.get("volume", 0),
                                                "bid": data.get("bid"),
                                                "ask": data.get("ask"),
                                                "source": "yfinance",
                                            },
                                        )
                                        publish_event(event, key=ticker)
                            except Exception as e:
                                logger.warning("Failed to fetch ticker fallback", ticker=ticker, error=str(e))
                                continue
                        await asyncio.sleep(1)

                # Fetch indices
                for index_symbol, index_name in BIST_INDICES.items():
                    try:
                        idx_data = yfinance_provider.fetch_index(index_symbol)
                        if idx_data:
                            event = CanonicalEvent(
                                event_type=EventType.MARKET_TICK,
                                source="yfinance",
                                data={
                                    "ticker": index_symbol,
                                    "name": index_name,
                                    "price": idx_data.get("price", 0),
                                    "change_pct": idx_data.get("change_pct", 0),
                                    "is_index": True,
                                },
                            )
                            publish_event(event, key=index_symbol)
                    except Exception:
                        logger.warning("Caught Exception in _market_data_loop", exc_info=True)

                await flush_producer()
                import gc

                gc.collect()
                logger.info("Market data fetch cycle completed")

                # Optimum bekleme: Seans içi 4 saniye, Seans dışı / Gece 60 saniye
                sleep_interval = 10 if is_bist_session_active() else 120
                await asyncio.sleep(sleep_interval)

            except Exception as e:
                logger.error("Market data loop error", error=str(e))
                await asyncio.sleep(60)

    # =====================================================
    # KAP Loop
    # =====================================================

    async def _kap_loop(self) -> Any:
        """Periodically fetch KAP disclosures."""
        while self._running:
            try:
                # İnternet kontrolü
                if not connectivity_monitor.is_online:
                    await asyncio.sleep(60)
                    continue

                logger.info("Starting KAP fetch cycle")

                # 1. Official KAP RSS feed (En güvenilir ve hızlı)
                disclosures = []
                try:
                    official_disclosures = await news_provider.fetch_official_kap_disclosures()
                    if official_disclosures:
                        for item in official_disclosures:
                            disclosures.append({
                                "kap_id": item.get("id", ""),
                                "ticker": item.get("ticker", ""),
                                "title": item.get("title", ""),
                                "summary": item.get("summary", ""),
                                "category": item.get("category", "Genel"),
                                "sentiment": item.get("sentiment", 0),
                                "importance": 0.5,
                                "is_price_sensitive": False,
                                "publish_date": item.get("publish_date", ""),
                            })
                except Exception:
                    logger.debug("KAP RSS fetch fallback notice")

                # 2. JSON API fallback if needed
                if not disclosures:
                    try:
                        from_date = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%d")
                        to_date = datetime.now(UTC).strftime("%Y-%m-%d")
                        disclosures = await kap_provider.fetch_disclosures(
                            from_date=from_date,
                            to_date=to_date,
                        )
                    except Exception:
                        logger.debug("KAP direct API fetch fallback notice")

                if disclosures:
                    for disc in disclosures:
                        ticker = disc.get("ticker", "")
                        instrument_id = self._instrument_map.get(ticker)

                        event = CanonicalEvent(
                            event_type=EventType.KAP_EVENT,
                            source="kap",
                            data={
                                "kap_id": disc.get("kap_id", ""),
                                "ticker": ticker,
                                "instrument_id": instrument_id,
                                "title": disc.get("title", ""),
                                "summary": disc.get("summary", ""),
                                "category": disc.get("category", ""),
                                "sentiment": disc.get("sentiment", 0),
                                "importance": disc.get("importance", 0),
                                "is_price_sensitive": disc.get("is_price_sensitive", False),
                                "publish_date": disc.get("publish_date", ""),
                            },
                        )
                        publish_event(event, key=ticker or "kap")

                    await flush_producer()
                logger.info("KAP fetch cycle completed", count=len(disclosures) if disclosures else 0)

                # Optimum bekleme: Seans içi 20 saniye, Seans dışı 60 saniye
                sleep_interval = 30 if is_bist_session_active() else 120
                await asyncio.sleep(sleep_interval)

            except Exception as e:
                logger.error("KAP loop error", error=str(e))
                await asyncio.sleep(60)

    # =====================================================
    # Macro Loop
    # =====================================================

    async def _macro_loop(self) -> Any:
        """Periodically fetch macro data."""
        while self._running:
            try:
                # İnternet kontrolü
                if not connectivity_monitor.is_online:
                    await asyncio.sleep(60)
                    continue

                logger.info("Starting macro data fetch cycle")

                # Fetch macro data from TCMB
                if settings.tcmb_evds_api_key:
                    tcmb_provider.api_key = settings.tcmb_evds_api_key
                    macro_data = tcmb_provider.fetch_all_macro()

                    event = CanonicalEvent(
                        event_type=EventType.MACRO_EVENT,
                        source="tcmb",
                        data=macro_data,
                    )
                    publish_event(event, key="macro")

                # Fetch yfinance macro
                macro_yf = yfinance_provider.fetch_macro()

                event = CanonicalEvent(
                    event_type=EventType.MACRO_EVENT,
                    source="yfinance",
                    data=macro_yf,
                )
                publish_event(event, key="macro_yf")

                # Fetch investing / global macro summary
                try:
                    global_macro = await investing_provider.fetch_global_macro_summary()
                    if global_macro:
                        event = CanonicalEvent(
                            event_type=EventType.MACRO_EVENT,
                            source="investing",
                            data=global_macro,
                        )
                        publish_event(event, key="macro_global")
                except Exception:
                    logger.debug("Investing global macro fetch skipped")

                await flush_producer()
                logger.info("Macro data fetch cycle completed")

                # Optimum bekleme: Küresel makro varlıklar için seans içi 30s, seans dışı 60s
                sleep_interval = 60 if is_bist_session_active() else 120
                await asyncio.sleep(sleep_interval)

            except Exception as e:
                logger.error("Macro loop error", error=str(e))
                await asyncio.sleep(60)

    # =====================================================
    # News Loop
    # =====================================================

    async def _news_loop(self) -> Any:
        """Periodically fetch news."""
        while self._running:
            try:
                # İnternet kontrolü
                if not connectivity_monitor.is_online:
                    await asyncio.sleep(60)
                    continue

                logger.info("Starting news fetch cycle")

                # Fetch from RSS
                rss_articles = await news_provider.fetch_financial_news_rss()
                if rss_articles:
                    for article in rss_articles:
                        event = CanonicalEvent(
                            event_type=EventType.NEWS_RAW,
                            source="rss",
                            data=article,
                        )
                        publish_event(event, key="news_rss")

                # Also fetch official KAP and TCMB news feeds
                try:
                    official_kap = await news_provider.fetch_official_kap_disclosures()
                    for article in official_kap or []:
                        event = CanonicalEvent(
                            event_type=EventType.NEWS_RAW,
                            source="official_kap",
                            data=article,
                        )
                        publish_event(event, key="news_kap")
                except Exception:
                    logger.warning("Caught Exception in _news_loop", exc_info=True)

                await flush_producer()
                logger.info("News fetch cycle completed", count=len(rss_articles) if rss_articles else 0)

                # Optimum bekleme: Finansal haberler için seans içi 60s, seans dışı 180s (3 dk)
                sleep_interval = 120 if is_bist_session_active() else 300
                await asyncio.sleep(sleep_interval)

            except Exception as e:
                logger.error("News loop error", error=str(e))
                await asyncio.sleep(60)

    # =====================================================
    # Social Media Loop
    # =====================================================

    async def _social_loop(self) -> Any:
        """Periodically fetch social media data."""
        while self._running:
            try:
                # İnternet kontrolü
                if not connectivity_monitor.is_online:
                    await asyncio.sleep(300)
                    continue

                logger.info("Starting social media fetch cycle")

                # Fetch from X (Twitter)
                if hasattr(settings, "x_api_key") and settings.x_api_key:
                    social_provider.x_api_key = settings.x_api_key
                    try:
                        mentions = await social_provider.fetch_x_mentions()
                        for mention in mentions or []:
                            event = CanonicalEvent(
                                event_type=EventType.SOCIAL_EVENT,
                                source="x",
                                data=mention,
                            )
                            publish_event(event, key="social")
                    except Exception:
                        logger.warning("Caught Exception in _social_loop", exc_info=True)

                await flush_producer()
                logger.info("Social media fetch cycle completed")

                # Optimum bekleme: Sosyal medya NLP için seans içi 60s, seans dışı 180s (3 dk)
                sleep_interval = 120 if is_bist_session_active() else 300
                await asyncio.sleep(sleep_interval)

            except Exception as e:
                logger.debug("Social loop note", error=str(e))
                await asyncio.sleep(300)


# =====================================================
# Health Check HTTP Server
# =====================================================


async def _health_server(port: int = 8080) -> Any:
    """Lightweight health check HTTP server for Docker healthcheck."""
    from aiohttp import web

    async def health_handler(request) -> Any:
        """Otomatik eklendi."""
        return web.json_response({"status": "healthy", "service": "ingestion"})

    app = web.Application()
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Health server started", port=port)


# =====================================================
# Entry Point
# =====================================================


async def main() -> Any:
    """Main entry point for the ingestion service."""
    # Start health server
    await _health_server()

    service = IngestionService()
    try:
        await service.start()
    except KeyboardInterrupt:
        await service.stop()
    except Exception as e:
        logger.error("Ingestion service crashed", error=str(e))
        await service.stop()
        raise


if __name__ == "__main__":
    asyncio.run(main())
