import asyncio
from services.core.database import init_databases, pg_execute

async def run():
    await init_databases()
    await pg_execute("TRUNCATE TABLE paper_trade_portfolio")
    print("Truncated paper_trade_portfolio")

if __name__ == "__main__":
    asyncio.run(run())
