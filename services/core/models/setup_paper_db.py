import asyncio
from services.core.database import init_databases, pg_execute

async def setup_tables():
    await init_databases()
    
    query = """
    CREATE TABLE IF NOT EXISTS paper_trade_portfolio (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        target_date DATE NOT NULL,
        tickers JSONB NOT NULL,
        is_cash_regime BOOLEAN DEFAULT FALSE,
        is_rebalance BOOLEAN DEFAULT FALSE
    );
    
    CREATE TABLE IF NOT EXISTS paper_trade_ledger (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        period_start DATE NOT NULL,
        period_end DATE NOT NULL,
        portfolio_value NUMERIC NOT NULL,
        cash_ratio NUMERIC NOT NULL,
        cagr NUMERIC
    );
    """
    
    await pg_execute(query)
    print('Paper trade tables created successfully.')

if __name__ == '__main__':
    asyncio.run(setup_tables())
