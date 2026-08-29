import structlog
logger = structlog.get_logger(__name__)
from typing import Any
import asyncio

from services.core.database import init_databases, pg_execute


async def run() -> Any:
    """Otomatik eklendi."""
    await init_databases()
    await pg_execute("TRUNCATE TABLE paper_trade_portfolio")
    logger.info("Truncated paper_trade_portfolio")


if __name__ == "__main__":
    asyncio.run(run())
