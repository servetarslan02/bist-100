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
from ..core.event_bus import (
from ..core.event_schema import CanonicalEvent
    ensure_topics, publish_event, EventType,
    flush_producer, EventConsumer,
)
from ..core.logging import setup_logging
from .bist_universe import BIST_STOCKS, get_sector, BIST_INDICES
from .providers.yfinance_provider import yfinance_provider
from .providers.kap_provider import kap_provider
from .providers.tcmb_provider import tcmb_provider
from .providers.news_provider import news_provider

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

        await init_databases()
        ensure_topics()

        # Load instrument map from PostgreSQL
        await self._load_instrument_map()

        self._running = True
        logger.info("Ingestion Service started", instruments=len(self._instrument_map))

        # Run ingestion loops
        await asyncio.gather(
            self._market_data_loop(),
            self._kap_loop(),
            self._macro_loop(),
            self._news_loop(),
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
                    except Exception:
                        pass

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

                disclosures = kap_provider.fetch_disclosures(
                    from_date=from_date,
                    to_date=to_date,
                )

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
                logger.info("KAP fetch cycle completed", count=len(disclosures))

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

                # Fetch from NewsAPI
                if settings.news_api_key:
                    news_provider.news_api_key = settings.news_api_key
                    articles = news_provider.fetch_newsapi()

                    for article in articles:
                        event = CanonicalEvent(
                            event_type=EventType.NEWS_RAW,
                            source="newsapi",
                            data=article,
                        )
                        publish_event(event, key="news")

                # Fetch from RSS
                rss_articles = news_provider.fetch_financial_news_rss()
                for article in rss_articles:
                    event = CanonicalEvent(
                        event_type=EventType.NEWS_RAW,
                        source="rss",
                        data=article,
                    )
                    publish_event(event, key="news_rss")

                flush_producer()
                logger.info("News fetch cycle completed")

                # Wait 10 minutes
                await asyncio.sleep(600)

            except Exception as e:
                logger.error("News loop error", error=str(e))
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
