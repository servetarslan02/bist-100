import structlog
logger = structlog.get_logger(__name__)
from typing import Any
import asyncio

from services.core.database import init_databases, pg_execute


async def run() -> Any:
    """Otomatik eklendi."""
    await init_databases()
    await pg_execute("DROP TABLE IF EXISTS paper_trade_portfolio")
    await pg_execute("""CREATE TABLE IF NOT EXISTS paper_trade_portfolio (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        target_date DATE NOT NULL,
        tickers JSONB NOT NULL,
        is_cash_regime BOOLEAN DEFAULT FALSE,
        is_rebalance BOOLEAN DEFAULT FALSE
    );""")
    logger.info("Recreated table!")


if __name__ == "__main__":
    asyncio.run(run())
