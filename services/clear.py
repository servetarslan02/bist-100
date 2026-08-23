import asyncio
from services.core.database import init_databases, pg_execute

async def run():
    await init_databases()
    # Tum kisisel portfoy ve gecmis tablolari temizleniyor
    await pg_execute("TRUNCATE TABLE paper_trade_portfolio")
    await pg_execute("TRUNCATE TABLE position_history")
    await pg_execute("TRUNCATE TABLE daily_pnl")
    await pg_execute("TRUNCATE TABLE equity_snapshots")
    await pg_execute("TRUNCATE TABLE cash_ledger")
    await pg_execute("TRUNCATE TABLE positions")
    print("Tum DB temizlendi")

if __name__ == "__main__":
    asyncio.run(run())
