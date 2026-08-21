-- ALPHA BIST — Initial Schema
-- Version: 001
-- Description: Core tables

-- migrate:split
CREATE TABLE IF NOT EXISTS sectors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- migrate:split
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    sector_id INTEGER REFERENCES sectors(id),
    active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- migrate:split
CREATE TABLE IF NOT EXISTS instruments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id),
    symbol TEXT UNIQUE NOT NULL,
    instrument_type TEXT DEFAULT 'EQUITY',
    exchange TEXT DEFAULT 'BIST',
    active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- migrate:split
CREATE TABLE IF NOT EXISTS portfolios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    initial_capital REAL NOT NULL DEFAULT 100000,
    current_capital REAL NOT NULL DEFAULT 100000,
    cash_balance REAL NOT NULL DEFAULT 100000,
    invested_value REAL DEFAULT 0,
    total_pnl REAL DEFAULT 0,
    total_return_pct REAL DEFAULT 0,
    status TEXT DEFAULT 'ACTIVE',
    is_paper INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- migrate:split
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER REFERENCES portfolios(id),
    instrument_id INTEGER REFERENCES instruments(id),
    quantity INTEGER NOT NULL DEFAULT 0,
    avg_cost REAL NOT NULL,
    current_price REAL,
    market_value REAL,
    unrealized_pnl REAL DEFAULT 0,
    unrealized_pnl_pct REAL DEFAULT 0,
    weight_pct REAL,
    entry_date TIMESTAMP,
    status TEXT DEFAULT 'OPEN',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(portfolio_id, instrument_id)
);

-- migrate:split
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER REFERENCES portfolios(id),
    instrument_id INTEGER REFERENCES instruments(id),
    order_type TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL,
    filled_quantity INTEGER DEFAULT 0,
    avg_fill_price REAL,
    status TEXT DEFAULT 'PENDING',
    source TEXT DEFAULT 'MANUAL',
    signal_id INTEGER,
    placed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    filled_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- migrate:split
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER REFERENCES orders(id),
    instrument_id INTEGER REFERENCES instruments(id),
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    commission REAL DEFAULT 0,
    filled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- migrate:split
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id INTEGER REFERENCES instruments(id),
    signal_type TEXT NOT NULL,
    direction TEXT,
    score REAL,
    confidence REAL,
    risk_level TEXT,
    horizon TEXT,
    expected_return_pct REAL,
    reasoning TEXT,
    model_version TEXT,
    status TEXT DEFAULT 'ACTIVE',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- migrate:split
CREATE TABLE IF NOT EXISTS system_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_key TEXT UNIQUE NOT NULL,
    config_value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- migrate:split
CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    strategy_type TEXT,
    status TEXT DEFAULT 'ACTIVE',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- migrate:split
CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    model_type TEXT,
    status TEXT DEFAULT 'DRAFT',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- migrate:split
CREATE TABLE IF NOT EXISTS model_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id INTEGER REFERENCES models(id),
    version TEXT NOT NULL,
    metrics TEXT DEFAULT '{}',
    status TEXT DEFAULT 'CANDIDATE',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(model_id, version)
);

-- migrate:split
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT,
    instrument_id INTEGER,
    data TEXT DEFAULT '{}',
    acknowledged INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- migrate:split
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    actor TEXT DEFAULT 'SYSTEM',
    details TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- migrate:down
DROP TABLE IF EXISTS audit_logs;
DROP TABLE IF EXISTS alerts;
DROP TABLE IF EXISTS model_versions;
DROP TABLE IF EXISTS models;
DROP TABLE IF EXISTS strategies;
DROP TABLE IF EXISTS system_config;
DROP TABLE IF EXISTS signals;
DROP TABLE IF EXISTS fills;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS positions;
DROP TABLE IF EXISTS portfolios;
DROP TABLE IF EXISTS instruments;
DROP TABLE IF EXISTS companies;
DROP TABLE IF EXISTS sectors;
