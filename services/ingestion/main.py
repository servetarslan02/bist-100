"""ALPHA BIST - Data Ingestion Service (Main Entry Point)"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any
import structlog

from ..core.config import settings
from ..core.database import (
    init_databases, close_databases, get_pg_pool,
    ch_insert, get_ch_client,
)
from ..core.event_schema import CanonicalEvent
from ..core.event_bus import (
    ensure_topics, publish_event, EventType,
    flush_producer, EventConsumer,
)
from ..core.logging import setup_logging
from .bist_universe import bist_universe, get_sector, BIST_INDICES

# Dinamik hisse listesi — otomatik keşif aktif
BIST_STOCKS = bist_universe.BIST_100_TICKERS
BIST_ALL = bist_universe.BIST_ALL_TICKERS
from .providers.yfinance_provider import yfinance_provider
from .providers.kap_provider import kap_provider
from .providers.tcmb_provider import tcmb_provider
from .providers.news_provider import news_provider
from .providers.social_provider import social_provider

logger = structlog.get_logger()


class IngestionService:
    """Main data ingestion service for ALPHA BIST."""

    def __init__(self):
        self._running = False
        self._instrument_map: Dict[str, int] = {}  # ticker -> instrument_id

    async def start(self):
        """Start the ingestion service."""
        setup_logging()
        logger.info("Starting ALPHA BIST Ingestion Service")

        # Otomatik hisse evrenini yenile (başlangıçta)
        await self._refresh_universe()

        await init_databases()
        ensure_topics()

        # Load instrument map from PostgreSQL
        await self._load_instrument_map()

        self._running = True
        logger.info("Ingestion Service started",
                    instruments=len(self._instrument_map),
                    universe_size=len(BIST_ALL))
        
        # Start loops in the background
        self._tasks = [
            asyncio.create_task(self._market_data_loop()),
            asyncio.create_task(self._kap_loop()),
            asyncio.create_task(self._macro_loop()),
            asyncio.create_task(self._news_loop()),
            asyncio.create_task(self._social_loop())
        ]
        
        # Keep the service running
        while self._running:
            await asyncio.sleep(1)

    async def _refresh_universe(self):
        """Hisse evrenini otomatik yenile."""
        global BIST_STOCKS, BIST_ALL
        try:
            logger.info("Refreshing BIST universe...")
            bist_universe.refresh()
            BIST_STOCKS = bist_universe.BIST_100_TICKERS
            BIST_ALL = bist_universe.BIST_ALL_TICKERS
            logger.info("BIST universe refreshed",
                        bist_100=len(BIST_STOCKS),
                        bist_all=len(BIST_ALL))
        except Exception as e:
            logger.warning("Universe refresh failed, using cached/static", error=str(e))

        # Run ingestion loops
        await asyncio.gather(
            self._market_data_loop(),
            self._kap_loop(),
            self._macro_loop(),
            self._news_loop(),
            self._social_loop(),
        )

    async def stop(self):
        """Stop the ingestion service."""
        self._running = False
        flush_producer()
        await close_databases()
        logger.info("Ingestion Service stopped")

    async def _load_instrument_map(self):
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

    async def _seed_instruments(self):
        """Seed initial instrument data into PostgreSQL."""
        from ..core.database import pg_execute

        logger.info("Seeding instruments into PostgreSQL")

        # First, ensure sectors exist
        sectors = set(get_sector(t) for t in BIST_STOCKS)

        for sector_code in sectors:
            await pg_execute("""
                INSERT INTO sectors (code, name)
                VALUES ($1, $1)
                ON CONFLICT (code) DO NOTHING
            """, sector_code)

        # Then, create companies and instruments
        for ticker in BIST_STOCKS:
            sector = get_sector(ticker)

            # Get sector_id
            sector_row = await pg_execute("""
                SELECT id FROM sectors WHERE code = $1
            """, sector)

            # Create company
            await pg_execute("""
                INSERT INTO companies (ticker, name, sector_id, active)
                VALUES ($1, $1, (SELECT id FROM sectors WHERE code = $2), TRUE)
                ON CONFLICT (ticker) DO NOTHING
            """, ticker, sector)

            # Create instrument
            await pg_execute("""
                INSERT INTO instruments (company_id, symbol, instrument_type, exchange, active)
                VALUES (
                    (SELECT id FROM companies WHERE ticker = $1),
                    $1, 'EQUITY', 'BIST', TRUE
                )
                ON CONFLICT (symbol) DO NOTHING
            """, ticker)

        logger.info("Instruments seeded", count=len(BIST_STOCKS))

    # =====================================================
    # Market Data Loop
    # =====================================================

    async def _market_data_loop(self):
        """Periodically fetch market data from yfinance."""
        while self._running:
            try:
                logger.info("Starting market data fetch cycle")

                # Fetch current prices for all stocks
                for ticker in BIST_STOCKS:
                    if not self._running:
                        break

                    try:
                        data = yfinance_provider.fetch_current_price(ticker)
                        if data and data.get("price"):
                            instrument_id = self._instrument_map.get(ticker)
                            if instrument_id:
                                # Publish tick event
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
                        logger.warning("Failed to fetch ticker", ticker=ticker, error=str(e))
                        continue

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
                    except Exception as e:
                        pass  # Intentional: silent error handling

                flush_producer()
                logger.info("Market data fetch cycle completed")

                # Wait before next cycle (5 minutes for delayed data)
                await asyncio.sleep(300)

            except Exception as e:
                logger.error("Market data loop error", error=str(e))
                await asyncio.sleep(60)

    # =====================================================
    # KAP Loop
    # =====================================================

    async def _kap_loop(self):
        """Periodically fetch KAP disclosures."""
        while self._running:
            try:
                logger.info("Starting KAP fetch cycle")

                # Fetch recent disclosures
                from_date = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d")
                to_date = datetime.now().strftime("%Y-%m-%d")

                disclosures = await kap_provider.fetch_disclosures(
                    from_date=from_date,
                    to_date=to_date,
                )

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

                    flush_producer()
                logger.info("KAP fetch cycle completed", count=len(disclosures) if disclosures else 0)

                # Wait 5 minutes
                await asyncio.sleep(300)

            except Exception as e:
                logger.error("KAP loop error", error=str(e))
                await asyncio.sleep(60)

    # =====================================================
    # Macro Loop
    # =====================================================

    async def _macro_loop(self):
        """Periodically fetch macro data."""
        while self._running:
            try:
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

                flush_producer()
                logger.info("Macro data fetch cycle completed")

                # Wait 15 minutes
                await asyncio.sleep(900)

            except Exception as e:
                logger.error("Macro loop error", error=str(e))
                await asyncio.sleep(60)

    # =====================================================
    # News Loop
    # =====================================================

    async def _news_loop(self):
        """Periodically fetch news."""
        while self._running:
            try:
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
                    for article in (official_kap or []):
                        event = CanonicalEvent(
                            event_type=EventType.NEWS_RAW,
                            source="official_kap",
                            data=article,
                        )
                        publish_event(event, key="news_kap")
                except Exception:
                    pass

                flush_producer()
                logger.info("News fetch cycle completed", count=len(rss_articles) if rss_articles else 0)

                # Wait 10 minutes
                await asyncio.sleep(600)

            except Exception as e:
                logger.error("News loop error", error=str(e))
                await asyncio.sleep(60)

    # =====================================================
    # Social Media Loop
    # =====================================================

    async def _social_loop(self):
        """Periodically fetch social media data."""
        while self._running:
            try:
                logger.info("Starting social media fetch cycle")

                # Fetch from X (Twitter)
                if hasattr(settings, 'x_api_key') and settings.x_api_key:
                    social_provider.x_api_key = settings.x_api_key
                    try:
                        mentions = await social_provider.fetch_x_mentions()
                        for mention in (mentions or []):
                            event = CanonicalEvent(
                                event_type=EventType.SOCIAL_EVENT,
                                source="x",
                                data=mention,
                            )
                            publish_event(event, key="social")
                    except Exception:
                        pass

                # Fetch StockTwits for top stocks
                top_tickers = ["THYAO", "ASELS", "AKBNK", "TUPRS", "EREGL"]
                for ticker in top_tickers:
                    try:
                        messages = await social_provider.fetch_stocktwits(ticker)
                        for msg in (messages or []):
                            event = CanonicalEvent(
                                event_type=EventType.SOCIAL_EVENT,
                                source="stocktwits",
                                data={**msg, "ticker": ticker},
                            )
                            publish_event(event, key=f"social_{ticker}")
                    except Exception:
                        pass

                flush_producer()
                logger.info("Social media fetch cycle completed")

                # Wait 15 minutes
                await asyncio.sleep(900)

            except Exception as e:
                logger.error("Social loop error", error=str(e))
                await asyncio.sleep(60)


# =====================================================
# Entry Point
# =====================================================

async def main():
    """Main entry point for the ingestion service."""
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
