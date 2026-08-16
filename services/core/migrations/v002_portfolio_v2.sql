-- ALPHA BIST — Portfolio v2.0 Tables
-- Version: 002
-- Description: Cash ledger, position history, equity snapshots, daily P&L

-- migrate:split
CREATE TABLE IF NOT EXISTS cash_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER REFERENCES portfolios(id),
    amount REAL NOT NULL,
    balance_after REAL NOT NULL,
    entry_type TEXT NOT NULL,
    description TEXT,
    ticker TEXT,
    reference_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- migrate:split
CREATE TABLE IF NOT EXISTS position_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER REFERENCES portfolios(id),
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    direction TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    commission REAL DEFAULT 0,
    avg_cost_before REAL DEFAULT 0,
    avg_cost_after REAL DEFAULT 0,
    quantity_before INTEGER DEFAULT 0,
    quantity_after INTEGER DEFAULT 0,
    realized_pnl REAL DEFAULT 0,
    reference_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- migrate:split
CREATE TABLE IF NOT EXISTS equity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER REFERENCES portfolios(id),
    snapshot_date TEXT NOT NULL,
    total_equity REAL NOT NULL,
    cash REAL NOT NULL,
    invested REAL NOT NULL,
    unrealized_pnl REAL DEFAULT 0,
    realized_pnl_today REAL DEFAULT 0,
    commission_today REAL DEFAULT 0,
    positions_count INTEGER DEFAULT 0,
    high_water_mark REAL DEFAULT 0,
    drawdown_from_hwm REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- migrate:split
CREATE TABLE IF NOT EXISTS daily_pnl (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER REFERENCES portfolios(id),
    pnl_date TEXT NOT NULL,
    realized_pnl REAL DEFAULT 0,
    unrealized_pnl REAL DEFAULT 0,
    commission REAL DEFAULT 0,
    net_pnl REAL DEFAULT 0,
    equity_start REAL DEFAULT 0,
    equity_end REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(portfolio_id, pnl_date)
);

-- migrate:down
DROP TABLE IF EXISTS daily_pnl;
DROP TABLE IF EXISTS equity_snapshots;
DROP TABLE IF EXISTS position_history;
DROP TABLE IF EXISTS cash_ledger;
