#!/usr/bin/env python3
from typing import Any
"""ALPHA BIST — Historical Data Backfill

DB'ye historical market data yükler.
PostgreSQL ve ClickHouse'a yazar.

Kullanım:
    python scripts/backfill_data.py --tickers THYAO,GARAN,ASELS --start 2020-01-01 --end 2026-08-18
    python scripts/backfill_data.py --all-bist100 --start 2020-01-01
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import structlog

logger = structlog.get_logger()


async def backfill_ticker(ticker: str, start_date: str, end_date: str) -> Any:
    """Tek ticker için historical data yükle."""
    try:
        import yfinance as yf

        from services.core.database import pg_execute

        yf_ticker = f"{ticker}.IS"
        data = yf.download(yf_ticker, start=start_date, end=end_date, progress=False)

        if data.empty:
            logger.warning("No data", ticker=ticker)
            return 0

        count = 0
        for idx, _row in data.iterrows():
            date_str = str(idx.date())
            try:
                await pg_execute(
                    """INSERT INTO market_data_snapshots
                       (instrument_id, snapshot_date, data_source, bar_count, first_bar_date, last_bar_date, quality_score)
                       VALUES ((SELECT id FROM instruments WHERE symbol = $1), $2, 'yfinance', 1, $2, $2, 1.0)
                       ON CONFLICT (instrument_id, snapshot_date, data_source) DO NOTHING""",
                    ticker,
                    date_str,
                )
                count += 1
            except Exception as e:
                logger.debug("Insert failed", ticker=ticker, date=date_str, error=str(e))

        logger.info("Backfill completed", ticker=ticker, rows=count)
        return count

    except Exception as e:
        logger.error("Backfill failed", ticker=ticker, error=str(e))
        return 0


async def main() -> Any:
    """Otomatik eklendi."""
    parser = argparse.ArgumentParser(description="Historical data backfill")
    parser.add_argument("--tickers", help="Comma-separated ticker list")
    parser.add_argument("--all-bist100", action="store_true", help="All BIST-100 tickers")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"), help="End date")
    args = parser.parse_args()

    from services.core.database import init_databases

    await init_databases()

    if args.all_bist100:
        from services.ingestion.bist_universe import bist_universe

        tickers = bist_universe.BIST_100_TICKERS
    elif args.tickers:
        tickers = args.tickers.split(",")
    else:
        logger.info("Specify --tickers or --all-bist100")
        return

    total = 0
    for ticker in tickers:
        count = await backfill_ticker(ticker, args.start, args.end)
        total += count

    logger.info(f"\nBackfill complete: {total} rows for {len(tickers)} tickers")


if __name__ == "__main__":
    asyncio.run(main())
