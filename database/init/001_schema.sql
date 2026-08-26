-- =====================================================
-- ALPHA BIST - PostgreSQL Schema v1.0
-- Operational / Transactional Database
-- =====================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";       -- pgvector: vektör araması
CREATE EXTENSION IF NOT EXISTS "timescaledb";   -- TimescaleDB: zaman serisi optimizasyonu

-- =====================================================
-- REFERENCE DATA
-- =====================================================

CREATE TABLE sectors (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    name_en VARCHAR(100),
    parent_id INTEGER REFERENCES sectors(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE companies (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    sector_id INTEGER REFERENCES sectors(id),
    market_cap BIGINT,
    free_float_ratio DECIMAL(5,4),
    isin VARCHAR(20),
    founded_year INTEGER,
    employee_count INTEGER,
    website VARCHAR(200),
    description TEXT,
    kap_id VARCHAR(50),
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE instruments (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id),
    symbol VARCHAR(20) UNIQUE NOT NULL,
    isin VARCHAR(20),
    instrument_type VARCHAR(20) DEFAULT 'EQUITY',
    exchange VARCHAR(20) DEFAULT 'BIST',
    lot_size INTEGER DEFAULT 1,
    tick_size DECIMAL(10,6),
    trading_hours_start TIME DEFAULT '10:00',
    trading_hours_end TIME DEFAULT '18:00',
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE indices (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    index_type VARCHAR(50),
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE index_components (
    id SERIAL PRIMARY KEY,
    index_id INTEGER REFERENCES indices(id),
    instrument_id INTEGER REFERENCES instruments(id),
    weight DECIMAL(8,4),
    added_date DATE,
    removed_date DATE,
    UNIQUE(index_id, instrument_id)
);

-- =====================================================
-- PORTFOLIO & TRADING
-- =====================================================

CREATE TABLE portfolios (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    initial_capital DECIMAL(15,2) NOT NULL DEFAULT 100000,
    current_capital DECIMAL(15,2) NOT NULL DEFAULT 100000,
    cash_balance DECIMAL(15,2) NOT NULL DEFAULT 100000,
    invested_value DECIMAL(15,2) DEFAULT 0,
    total_pnl DECIMAL(15,2) DEFAULT 0,
    total_return_pct DECIMAL(8,4) DEFAULT 0,
    peak_equity DECIMAL(15,2) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'ACTIVE',
    is_paper BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE positions (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolios(id),
    instrument_id INTEGER REFERENCES instruments(id),
    quantity INTEGER NOT NULL DEFAULT 0,
    avg_cost DECIMAL(12,4) NOT NULL,
    entry_commission DECIMAL(12,4) DEFAULT 0,
    current_price DECIMAL(12,4),
    market_value DECIMAL(15,2),
    unrealized_pnl DECIMAL(15,2) DEFAULT 0,
    unrealized_pnl_pct DECIMAL(8,4) DEFAULT 0,
    weight_pct DECIMAL(5,2),
    entry_date TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'OPEN',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(portfolio_id, instrument_id)
);

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolios(id),
    instrument_id INTEGER REFERENCES instruments(id),
    order_type VARCHAR(20) NOT NULL,
    side VARCHAR(4) NOT NULL,
    quantity INTEGER NOT NULL,
    price DECIMAL(12,4),
    stop_price DECIMAL(12,4),
    filled_quantity INTEGER DEFAULT 0,
    avg_fill_price DECIMAL(12,4),
    status VARCHAR(20) DEFAULT 'PENDING',
    time_in_force VARCHAR(10) DEFAULT 'DAY',
    source VARCHAR(20) DEFAULT 'MANUAL',
    signal_id INTEGER,
    strategy_id INTEGER,
    notes TEXT,
    placed_at TIMESTAMPTZ DEFAULT NOW(),
    filled_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE fills (
    id SERIAL PRIMARY KEY,
    order_id INTEGER REFERENCES orders(id),
    instrument_id INTEGER REFERENCES instruments(id),
    side VARCHAR(4) NOT NULL,
    quantity INTEGER NOT NULL,
    price DECIMAL(12,4) NOT NULL,
    commission DECIMAL(10,4) DEFAULT 0,
    slippage DECIMAL(10,4) DEFAULT 0,
    filled_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =====================================================
-- STRATEGIES & SIGNALS
-- =====================================================

CREATE TABLE strategies (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    strategy_type VARCHAR(50),
    parameters JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE signals (
    id SERIAL PRIMARY KEY,
    instrument_id INTEGER REFERENCES instruments(id),
    strategy_id INTEGER REFERENCES strategies(id),
    signal_type VARCHAR(20) NOT NULL,
    direction VARCHAR(10),
    score DECIMAL(5,2),
    confidence DECIMAL(5,4),
    risk_level VARCHAR(20),
    horizon VARCHAR(10),
    expected_return_pct DECIMAL(8,4),
    expected_volatility_pct DECIMAL(8,4),
    edge_decomposition JSONB DEFAULT '{}',
    reasoning TEXT,
    model_version VARCHAR(50),
    status VARCHAR(20) DEFAULT 'ACTIVE',
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =====================================================
-- MODELS
-- =====================================================

CREATE TABLE models (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    model_type VARCHAR(50),
    framework VARCHAR(50),
    target_variable VARCHAR(100),
    features JSONB DEFAULT '[]',
    hyperparameters JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'DRAFT',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE model_versions (
    id SERIAL PRIMARY KEY,
    model_id INTEGER REFERENCES models(id),
    version VARCHAR(20) NOT NULL,
    training_data_start DATE,
    training_data_end DATE,
    validation_data_start DATE,
    validation_data_end DATE,
    metrics JSONB DEFAULT '{}',
    backtest_metrics JSONB DEFAULT '{}',
    walk_forward_metrics JSONB DEFAULT '{}',
    artifact_path VARCHAR(500),
    status VARCHAR(20) DEFAULT 'CANDIDATE',
    champion_since TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(model_id, version)
);

CREATE TABLE model_predictions (
    id SERIAL PRIMARY KEY,
    model_version_id INTEGER REFERENCES model_versions(id),
    instrument_id INTEGER REFERENCES instruments(id),
    prediction_date DATE NOT NULL,
    horizon_days INTEGER,
    predicted_direction VARCHAR(10),
    predicted_return_pct DECIMAL(8,4),
    probability_positive DECIMAL(5,4),
    predicted_volatility_pct DECIMAL(8,4),
    confidence DECIMAL(5,4),
    features_used JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE model_outcomes (
    id SERIAL PRIMARY KEY,
    prediction_id INTEGER REFERENCES model_predictions(id),
    actual_return_pct DECIMAL(8,4),
    actual_direction VARCHAR(10),
    actual_volatility_pct DECIMAL(8,4),
    prediction_error DECIMAL(8,4),
    is_correct BOOLEAN,
    outcome_date DATE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =====================================================
-- KNOWLEDGE GRAPH
-- =====================================================

CREATE TABLE knowledge_entities (
    id SERIAL PRIMARY KEY,
    entity_type VARCHAR(50) NOT NULL,
    name VARCHAR(200) NOT NULL,
    aliases JSONB DEFAULT '[]',
    properties JSONB DEFAULT '{}',
    embedding vector(1024),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE knowledge_relations (
    id SERIAL PRIMARY KEY,
    source_entity_id INTEGER REFERENCES knowledge_entities(id),
    target_entity_id INTEGER REFERENCES knowledge_entities(id),
    relation_type VARCHAR(50) NOT NULL,
    strength DECIMAL(5,4) DEFAULT 1.0,
    properties JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_entity_id, target_entity_id, relation_type)
);

-- =====================================================
-- ALERTS & AUDIT
-- =====================================================

CREATE TABLE alerts (
    id SERIAL PRIMARY KEY,
    alert_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    title VARCHAR(200) NOT NULL,
    message TEXT,
    instrument_id INTEGER REFERENCES instruments(id),
    data JSONB DEFAULT '{}',
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    action VARCHAR(50) NOT NULL,
    entity_type VARCHAR(50),
    entity_id INTEGER,
    actor VARCHAR(50) DEFAULT 'SYSTEM',
    details JSONB DEFAULT '{}',
    ip_address INET,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE system_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) DEFAULT 'INFO',
    source VARCHAR(50),
    message TEXT,
    data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =====================================================
-- CONFIGURATION
-- =====================================================

CREATE TABLE system_config (
    id SERIAL PRIMARY KEY,
    config_key VARCHAR(100) UNIQUE NOT NULL,
    config_value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    updated_by VARCHAR(50) DEFAULT 'SYSTEM'
);

-- =====================================================
-- SIMULATIONS
-- =====================================================

CREATE TABLE simulations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200),
    simulation_type VARCHAR(50),
    parameters JSONB DEFAULT '{}',
    results JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'PENDING',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE scenarios (
    id SERIAL PRIMARY KEY,
    simulation_id INTEGER REFERENCES simulations(id),
    scenario_name VARCHAR(100),
    market_change_pct DECIMAL(8,4),
    portfolio_impact JSONB DEFAULT '{}',
    probability DECIMAL(5,4),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =====================================================
-- INDEXES
-- =====================================================

CREATE INDEX idx_companies_ticker ON companies(ticker);
CREATE INDEX idx_companies_sector ON companies(sector_id);
CREATE INDEX idx_instruments_symbol ON instruments(symbol);
CREATE INDEX idx_instruments_company ON instruments(company_id);
CREATE INDEX idx_positions_portfolio ON positions(portfolio_id);
CREATE INDEX idx_orders_portfolio ON orders(portfolio_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_signals_instrument ON signals(instrument_id);
CREATE INDEX idx_signals_strategy ON signals(strategy_id);
CREATE INDEX idx_signals_status ON signals(status);
CREATE INDEX idx_model_predictions_instrument ON model_predictions(instrument_id);
CREATE INDEX idx_model_predictions_date ON model_predictions(prediction_date);
CREATE INDEX idx_alerts_type ON alerts(alert_type);
CREATE INDEX idx_alerts_severity ON alerts(severity);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);
CREATE INDEX idx_audit_logs_entity ON audit_logs(entity_type, entity_id);
CREATE INDEX idx_knowledge_entities_type ON knowledge_entities(entity_type);
CREATE INDEX idx_knowledge_relations_source ON knowledge_relations(source_entity_id);
CREATE INDEX idx_knowledge_relations_target ON knowledge_relations(target_entity_id);

-- =====================================================
-- SYSTEM JOBS (Background task queue)
-- =====================================================

CREATE TABLE IF NOT EXISTS system_jobs (
    id SERIAL PRIMARY KEY,
    job_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
    priority INTEGER DEFAULT 0,
    payload_json TEXT DEFAULT '{}',
    result_json TEXT DEFAULT '{}',
    error_message TEXT,
    idempotency_key VARCHAR(100) UNIQUE,
    scheduled_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_system_jobs_status ON system_jobs(status);
CREATE INDEX idx_system_jobs_type ON system_jobs(job_type);
CREATE INDEX idx_system_jobs_idempotency ON system_jobs(idempotency_key);
CREATE INDEX idx_system_jobs_scheduled ON system_jobs(scheduled_at);

-- =====================================================
-- STATE SNAPSHOTS (Market/asset state recovery)
-- =====================================================

CREATE TABLE IF NOT EXISTS state_snapshots (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    state_data JSONB NOT NULL,
    snapshot_time TIMESTAMPTZ DEFAULT NOW(),
    snapshot_type VARCHAR(50) DEFAULT 'ASSET',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_state_snapshots_ticker ON state_snapshots(ticker);
CREATE INDEX idx_state_snapshots_time ON state_snapshots(snapshot_time DESC);

-- =====================================================
-- POSITION HISTORY (Trade/position audit trail)
-- =====================================================

CREATE TABLE IF NOT EXISTS position_history (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolios(id),
    reference_id VARCHAR(50),
    ticker VARCHAR(20) NOT NULL,
    action VARCHAR(20) NOT NULL CHECK (action IN ('OPEN', 'CLOSE', 'REDUCE', 'ADD')),
    direction VARCHAR(10) DEFAULT 'LONG',
    quantity INTEGER NOT NULL,
    price DECIMAL(12, 4) NOT NULL,
    commission DECIMAL(12, 4) DEFAULT 0,
    avg_cost_before DECIMAL(12, 4) DEFAULT 0,
    avg_cost_after DECIMAL(12, 4) DEFAULT 0,
    quantity_before INTEGER DEFAULT 0,
    quantity_after INTEGER DEFAULT 0,
    realized_pnl DECIMAL(12, 4) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_position_history_portfolio ON position_history(portfolio_id);
CREATE INDEX idx_position_history_ticker ON position_history(ticker);
CREATE INDEX idx_position_history_action ON position_history(action);

-- =====================================================
-- SCAN RESULTS (Scanner output persistence)
-- =====================================================

CREATE TABLE IF NOT EXISTS scan_results (
    id SERIAL PRIMARY KEY,
    scan_id VARCHAR(50) NOT NULL,
    scan_type VARCHAR(50) NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    score DECIMAL(5, 2),
    signal VARCHAR(20),
    direction VARCHAR(10),
    confidence DECIMAL(5, 4),
    tier INTEGER,
    regime VARCHAR(30),
    price DECIMAL(12, 4),
    volume BIGINT,
    features_json JSONB DEFAULT '{}',
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_scan_results_scan ON scan_results(scan_id);
CREATE INDEX idx_scan_results_ticker ON scan_results(ticker);
CREATE INDEX idx_scan_results_score ON scan_results(score DESC);

-- =====================================================
-- DAILY PERFORMANCE (Paper trading daily stats)
-- =====================================================

CREATE TABLE IF NOT EXISTS daily_performance (
    date DATE PRIMARY KEY,
    portfolio_value DECIMAL(15, 4) NOT NULL,
    cash DECIMAL(15, 4) NOT NULL,
    daily_return_pct DECIMAL(8, 4) NOT NULL,
    cumulative_return_pct DECIMAL(8, 4) NOT NULL,
    max_drawdown_pct DECIMAL(8, 4) NOT NULL,
    benchmark_return_pct DECIMAL(8, 4) DEFAULT 0,
    alpha_pct DECIMAL(8, 4) DEFAULT 0,
    turnover DECIMAL(8, 4) DEFAULT 0,
    transaction_cost DECIMAL(12, 4) DEFAULT 0,
    num_positions INTEGER DEFAULT 0,
    num_trades INTEGER DEFAULT 0,
    json_data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =====================================================
-- EQUITY CURVE (Portfolio equity over time)
-- =====================================================

CREATE TABLE IF NOT EXISTS equity_curve (
    date DATE PRIMARY KEY,
    equity DECIMAL(15, 4) NOT NULL,
    cash DECIMAL(15, 4) NOT NULL,
    market_value DECIMAL(15, 4) NOT NULL,
    positions INTEGER DEFAULT 0,
    drawdown DECIMAL(8, 4) DEFAULT 0,
    daily_return DECIMAL(8, 4) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =====================================================
-- PORTFOLIO STATE (Paper trading current state)
-- =====================================================

CREATE TABLE IF NOT EXISTS portfolio_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    date DATE NOT NULL,
    cash DECIMAL(15, 4) NOT NULL,
    initial_capital DECIMAL(15, 4) NOT NULL,
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    json_data JSONB DEFAULT '{}'
);

-- =====================================================
-- PAPER TRADES (Paper trading trade log)
-- =====================================================

CREATE TABLE IF NOT EXISTS paper_trades (
    trade_id VARCHAR(50) PRIMARY KEY,
    date DATE NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    quantity INTEGER NOT NULL,
    entry_price DECIMAL(12, 4) NOT NULL,
    exit_price DECIMAL(12, 4) NOT NULL,
    realized_pnl DECIMAL(12, 4) NOT NULL,
    commission DECIMAL(12, 4) DEFAULT 0,
    reason TEXT,
    json_data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_paper_trades_ticker ON paper_trades(ticker);
CREATE INDEX idx_paper_trades_date ON paper_trades(date);

-- =====================================================
-- PAPER AUDIT LOG (Paper trading audit trail)
-- =====================================================

CREATE TABLE IF NOT EXISTS paper_audit_log (
    entry_id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    date DATE NOT NULL,
    entry_type VARCHAR(50) NOT NULL,
    ticker VARCHAR(20),
    json_data JSONB NOT NULL,
    entry_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_paper_audit_log_date ON paper_audit_log(date);
CREATE INDEX idx_paper_audit_log_type ON paper_audit_log(entry_type);

-- =====================================================
-- BACKTEST RUNS (Backtest persistence)
-- =====================================================

CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id VARCHAR(50) PRIMARY KEY,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    initial_capital DECIMAL(15, 4),
    final_equity DECIMAL(15, 4),
    total_return_pct DECIMAL(8, 4),
    sharpe_ratio DECIMAL(8, 4),
    max_drawdown_pct DECIMAL(8, 4),
    total_trades INTEGER,
    config_json JSONB DEFAULT '{}',
    metrics_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS backtest_trades (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(50) REFERENCES backtest_runs(run_id),
    trade_id INTEGER,
    ticker VARCHAR(20),
    side VARCHAR(10),
    date DATE,
    quantity INTEGER,
    price DECIMAL(12, 4),
    commission DECIMAL(12, 4),
    slippage DECIMAL(12, 4),
    pnl DECIMAL(12, 4),
    pnl_pct DECIMAL(8, 4),
    holding_days INTEGER
);

CREATE TABLE IF NOT EXISTS backtest_equity (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(50) REFERENCES backtest_runs(run_id),
    date DATE NOT NULL,
    equity DECIMAL(15, 4),
    cash DECIMAL(15, 4),
    market_value DECIMAL(15, 4),
    positions INTEGER,
    drawdown DECIMAL(8, 4),
    daily_return DECIMAL(8, 4)
);

CREATE INDEX idx_backtest_trades_run ON backtest_trades(run_id);
CREATE INDEX idx_backtest_equity_run ON backtest_equity(run_id);
CREATE INDEX idx_backtest_equity_date ON backtest_equity(run_id, date);

-- =====================================================
-- CASH LEDGER (Cash movement audit trail)
-- =====================================================

CREATE TABLE IF NOT EXISTS cash_ledger (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolios(id),
    amount DECIMAL(15, 4) NOT NULL,
    balance_after DECIMAL(15, 4) NOT NULL,
    entry_type VARCHAR(20) NOT NULL,
    description TEXT,
    ticker VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_cash_ledger_portfolio ON cash_ledger(portfolio_id);
CREATE INDEX idx_cash_ledger_type ON cash_ledger(entry_type);

-- =====================================================
-- EQUITY SNAPSHOTS (Daily portfolio equity)
-- =====================================================

CREATE TABLE IF NOT EXISTS equity_snapshots (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolios(id),
    snapshot_date DATE NOT NULL,
    total_equity DECIMAL(15, 4) NOT NULL,
    cash DECIMAL(15, 4) NOT NULL,
    invested DECIMAL(15, 4) DEFAULT 0,
    unrealized_pnl DECIMAL(15, 4) DEFAULT 0,
    realized_pnl_today DECIMAL(15, 4) DEFAULT 0,
    commission_today DECIMAL(15, 4) DEFAULT 0,
    positions_count INTEGER DEFAULT 0,
    high_water_mark DECIMAL(15, 4) DEFAULT 0,
    drawdown_from_hwm DECIMAL(8, 4) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_equity_snapshots_portfolio ON equity_snapshots(portfolio_id);
CREATE INDEX idx_equity_snapshots_date ON equity_snapshots(snapshot_date DESC);

-- =====================================================
-- DAILY P&L (Daily performance tracking)
-- =====================================================

CREATE TABLE IF NOT EXISTS daily_pnl (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolios(id),
    pnl_date DATE NOT NULL,
    realized_pnl DECIMAL(15, 4) DEFAULT 0,
    unrealized_pnl DECIMAL(15, 4) DEFAULT 0,
    commission DECIMAL(15, 4) DEFAULT 0,
    net_pnl DECIMAL(15, 4) DEFAULT 0,
    equity_start DECIMAL(15, 4) DEFAULT 0,
    equity_end DECIMAL(15, 4) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(portfolio_id, pnl_date)
);

CREATE INDEX idx_daily_pnl_portfolio ON daily_pnl(portfolio_id);
CREATE INDEX idx_daily_pnl_date ON daily_pnl(pnl_date DESC);

-- =====================================================
-- EVENT LEDGER (Event bus idempotency)
-- =====================================================

CREATE TABLE IF NOT EXISTS event_ledger (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(100) UNIQUE NOT NULL,
    event_type VARCHAR(50),
    payload TEXT,
    published_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_event_ledger_id ON event_ledger(event_id);
CREATE INDEX idx_event_ledger_type ON event_ledger(event_type);

-- =====================================================
-- DEFAULT DATA
-- =====================================================

INSERT INTO sectors (code, name) VALUES
    ('BANK', 'Bankacılık'),
    ('INDUST', 'Sanayi'),
    ('TECH', 'Teknoloji'),
    ('ENERGY', 'Enerji'),
    ('RETAIL', 'Perakende'),
    ('CONSTR', 'İnşaat'),
    ('FOOD', 'Gıda'),
    ('CHEM', 'Kimya'),
    ('METAL', 'Metal'),
    ('TELECOM', 'Telekomünikasyon'),
    ('HEALTH', 'Sağlık'),
    ('REAL', 'Gayrimenkul'),
    ('AUTO', 'Otomotiv'),
    ('TEXTIL', 'Tekstil'),
    ('MEDIA', 'Medya'),
    ('MINING', 'Madencilik'),
    ('AVIATION', 'Havacılık'),
    ('TOURISM', 'Turizm'),
    ('HOLDING', 'Holding'),
    ('OTHER', 'Diğer');

INSERT INTO strategies (name, description, strategy_type) VALUES
    ('Momentum', 'Kısa-orta vadeli momentum sinyalleri', 'MOMENTUM'),
    ('Breakout', 'Fiyat sıkışması sonrası kırılım', 'BREAKOUT'),
    ('Mean Reversion', 'Ortalama dönüş stratejisi', 'MEAN_REVERSION'),
    ('Event Driven', 'KAP/haber bazlı strateji', 'EVENT_DRIVEN'),
    ('SPEC', 'Olağandışı hareket tespiti', 'SPEC'),
    ('Value', 'Fundamental değer odaklı', 'VALUE'),
    ('Defensive', 'Korunma odaklı strateji', 'DEFENSIVE');

INSERT INTO system_config (config_key, config_value, description) VALUES
    ('market.open_hour', '"10:00"', 'Piyasa açılış saati'),
    ('market.close_hour', '"18:00"', 'Piyasa kapanış saati'),
    ('risk.max_position_pct', '10', 'Maksimum pozisyon büyüklüğü (%)'),
    ('risk.max_sector_pct', '30', 'Maksimum sektör konsantrasyonu (%)'),
    ('risk.max_drawdown_pct', '15', 'Maksimum drawdown (%)'),
    ('risk.daily_loss_limit_pct', '5', 'Günlük zarar limiti (%)'),
    ('ml.retrain_interval_hours', '168', 'Yeniden eğitim aralığı (saat)'),
    ('llm.context_size', '8192', 'LLM context boyutu');

-- =====================================================
-- TIMESCALEDB HYPERTABLES (Zaman serisi optimizasyonu)
-- =====================================================

-- Model predictions → hypertable
SELECT create_hypertable('model_predictions', 'prediction_date',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- Daily performance → hypertable
SELECT create_hypertable('daily_performance', 'date',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- Equity curve → hypertable
SELECT create_hypertable('equity_curve', 'date',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- Daily P&L → hypertable
SELECT create_hypertable('daily_pnl', 'pnl_date',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- Equity snapshots → hypertable
SELECT create_hypertable('equity_snapshots', 'snapshot_date',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- Scan results → hypertable
SELECT create_hypertable('scan_results', 'timestamp',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- Alerts → hypertable
SELECT create_hypertable('alerts', 'created_at',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- Audit logs → hypertable
SELECT create_hypertable('audit_logs', 'created_at',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- System events → hypertable
SELECT create_hypertable('system_events', 'created_at',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- Paper trades → hypertable
SELECT create_hypertable('paper_trades', 'created_at',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- Backtest runs → hypertable
SELECT create_hypertable('backtest_runs', 'created_at',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- =====================================================
-- TIMESCALEDB COMPRESSION (Otomatik sıkıştırma)
-- =====================================================

ALTER TABLE model_predictions SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'instrument_id',
    timescaledb.compress_orderby = 'prediction_date DESC'
);
SELECT add_compression_policy('model_predictions', INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE daily_performance SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'date DESC'
);
SELECT add_compression_policy('daily_performance', INTERVAL '90 days', if_not_exists => TRUE);

ALTER TABLE scan_results SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'ticker',
    timescaledb.compress_orderby = 'timestamp DESC'
);
SELECT add_compression_policy('scan_results', INTERVAL '7 days', if_not_exists => TRUE);

ALTER TABLE alerts SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'alert_type',
    timescaledb.compress_orderby = 'created_at DESC'
);
SELECT add_compression_policy('alerts', INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE audit_logs SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'action',
    timescaledb.compress_orderby = 'created_at DESC'
);
SELECT add_compression_policy('audit_logs', INTERVAL '30 days', if_not_exists => TRUE);

-- =====================================================
-- TIMESCALEDB CONTINUOUS AGGREGATES (Otomatik聚合)
-- =====================================================

-- Günlük performans özeti
CREATE MATERIALIZED VIEW IF NOT EXISTS daily_perf_summary
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', pnl_date) AS day,
    portfolio_id,
    AVG(net_pnl) AS avg_daily_pnl,
    SUM(net_pnl) AS total_pnl,
    COUNT(*) AS trade_count
FROM daily_pnl
GROUP BY time_bucket('1 day', pnl_date), portfolio_id
WITH NO DATA;

-- Haftalık scan sonuçları
CREATE MATERIALIZED VIEW IF NOT EXISTS weekly_scan_summary
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('7 days', timestamp) AS week,
    ticker,
    AVG(score) AS avg_score,
    MAX(score) AS max_score,
    COUNT(*) AS scan_count
FROM scan_results
GROUP BY time_bucket('7 days', timestamp), ticker
WITH NO DATA;

-- =====================================================
-- PGVECTOR HNSW INDEX (Vektör araması — 10x hızlı)
-- =====================================================

-- knowledge_entities.embedding için HNSW index
-- cosine distance: benzerlik araması için
CREATE INDEX IF NOT EXISTS idx_knowledge_entities_embedding_hnsw
ON knowledge_entities
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 200);

-- IVFFlat index (fallback, daha az bellek)
-- CREATE INDEX IF NOT EXISTS idx_knowledge_entities_embedding_ivfflat
-- ON knowledge_entities
-- USING ivfflat (embedding vector_cosine_ops)
-- WITH (lists = 100);

-- =====================================================
-- PERFORMANS İYİLEŞTİRMELERİ v2.0
-- =====================================================

-- =====================================================
-- COMPOSITE INDEXES (Sorgu performansı için kritik)
-- =====================================================

-- Portföy sorguları için composite index
CREATE INDEX IF NOT EXISTS idx_positions_portfolio_status ON positions(portfolio_id, status);
CREATE INDEX IF NOT EXISTS idx_positions_portfolio_instrument ON positions(portfolio_id, instrument_id);

-- Sinyal sorguları için composite index
CREATE INDEX IF NOT EXISTS idx_signals_instrument_status ON signals(instrument_id, status);
CREATE INDEX IF NOT EXISTS idx_signals_strategy_status ON signals(strategy_id, status);
CREATE INDEX IF NOT EXISTS idx_signals_created_status ON signals(created_at DESC, status);

-- Emir sorguları için composite index
CREATE INDEX IF NOT EXISTS idx_orders_portfolio_status ON orders(portfolio_id, status);
CREATE INDEX IF NOT EXISTS idx_orders_instrument_status ON orders(instrument_id, status);
CREATE INDEX IF NOT EXISTS idx_orders_placed_status ON orders(placed_at DESC, status);

-- Model tahmin sorguları için composite index
CREATE INDEX IF NOT EXISTS idx_predictions_instrument_date ON model_predictions(instrument_id, prediction_date DESC);
CREATE INDEX IF NOT EXISTS idx_predictions_model_date ON model_predictions(model_version_id, prediction_date DESC);

-- Alert sorguları için composite index
CREATE INDEX IF NOT EXISTS idx_alerts_type_severity ON alerts(alert_type, severity);
CREATE INDEX IF NOT EXISTS idx_alerts_created_ack ON alerts(created_at DESC, acknowledged);

-- Audit log sorguları için composite index
CREATE INDEX IF NOT EXISTS idx_audit_entity_action ON audit_logs(entity_type, entity_id, action);
CREATE INDEX IF NOT EXISTS idx_audit_created_action ON audit_logs(created_at DESC, action);

-- Scan results için composite index
CREATE INDEX IF NOT EXISTS idx_scan_ticker_score ON scan_results(ticker, score DESC);
CREATE INDEX IF NOT EXISTS idx_scan_type_signal ON scan_results(scan_type, signal);

-- Paper trades için composite index
CREATE INDEX IF NOT EXISTS idx_paper_ticker_date ON paper_trades(ticker, date DESC);

-- Position history için composite index
CREATE INDEX IF NOT EXISTS idx_poshist_portfolio_ticker ON position_history(portfolio_id, ticker);
CREATE INDEX IF NOT EXISTS idx_poshist_action_date ON position_history(action, created_at DESC);

-- Daily P&L için composite index
CREATE INDEX IF NOT EXISTS idx_dailypnl_portfolio_date ON daily_pnl(portfolio_id, pnl_date DESC);

-- Equity snapshots için composite index
CREATE INDEX IF NOT EXISTS idx_eqsnap_portfolio_date ON equity_snapshots(portfolio_id, snapshot_date DESC);

-- Knowledge graph için composite index
CREATE INDEX IF NOT EXISTS idx_knowledge_entity_type ON knowledge_entities(entity_type, name);

-- =====================================================
-- PARTITIONING (Büyük tablolar için)
-- =====================================================

-- Model predictions tablosu zaten TimescaleDB hypertable
-- Scan results tablosu zaten TimescaleDB hypertable

-- =====================================================
-- VACUUM & ANALYZE AYARLARI (Otomatik bakım)
-- =====================================================

-- Autovacuum ayarlarını tablo bazında optimize et
ALTER TABLE positions SET (autovacuum_vacuum_scale_factor = 0.05);
ALTER TABLE orders SET (autovacuum_vacuum_scale_factor = 0.05);
ALTER TABLE signals SET (autovacuum_vacuum_scale_factor = 0.05);
ALTER TABLE alerts SET (autovacuum_vacuum_scale_factor = 0.1);
ALTER TABLE audit_logs SET (autovacuum_vacuum_scale_factor = 0.1);
ALTER TABLE scan_results SET (autovacuum_vacuum_scale_factor = 0.05);
ALTER TABLE model_predictions SET (autovacuum_vacuum_scale_factor = 0.05);

-- =====================================================
-- MATERIALIZED VIEW'lar (Önceden hesaplanmış聚合)
-- =====================================================

-- Son 30 günlük performans özeti
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_recent_performance AS
SELECT
    dp.portfolio_id,
    dp.pnl_date,
    dp.net_pnl,
    dp.equity_end,
    dp.commission,
    LAG(dp.equity_end) OVER (PARTITION BY dp.portfolio_id ORDER BY dp.pnl_date) as prev_equity,
    CASE
        WHEN LAG(dp.equity_end) OVER (PARTITION BY dp.portfolio_id ORDER BY dp.pnl_date) > 0
        THEN (dp.equity_end - LAG(dp.equity_end) OVER (PARTITION BY dp.portfolio_id ORDER BY dp.pnl_date))
             / LAG(dp.equity_end) OVER (PARTITION BY dp.portfolio_id ORDER BY dp.pnl_date) * 100
        ELSE 0
    END as daily_return_pct
FROM daily_pnl dp
WHERE dp.pnl_date >= CURRENT_DATE - INTERVAL '30 days'
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_recent_perf ON mv_recent_performance(portfolio_id, pnl_date);

-- Aktif pozisyonlar özeti
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_active_positions AS
SELECT
    p.portfolio_id,
    p.instrument_id,
    i.symbol as ticker,
    p.quantity,
    p.avg_cost,
    p.current_price,
    p.market_value,
    p.unrealized_pnl,
    p.unrealized_pnl_pct,
    p.weight_pct,
    p.entry_date,
    c.name as company_name,
    s.name as sector_name
FROM positions p
JOIN instruments i ON p.instrument_id = i.id
JOIN companies c ON i.company_id = c.id
LEFT JOIN sectors s ON c.sector_id = s.id
WHERE p.status = 'OPEN'
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_active_pos ON mv_active_positions(portfolio_id, instrument_id);

-- Sektör bazlı pozisyon dağılımı
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_sector_allocation AS
SELECT
    p.portfolio_id,
    s.name as sector_name,
    COUNT(*) as position_count,
    SUM(p.market_value) as total_value,
    SUM(p.weight_pct) as total_weight,
    AVG(p.unrealized_pnl_pct) as avg_pnl_pct
FROM positions p
JOIN instruments i ON p.instrument_id = i.id
JOIN companies c ON i.company_id = c.id
LEFT JOIN sectors s ON c.sector_id = s.id
WHERE p.status = 'OPEN'
GROUP BY p.portfolio_id, s.name
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_sector_alloc ON mv_sector_allocation(portfolio_id, sector_name);

-- =====================================================
-- FONKSİYONLAR (Yardımcı hesaplamalar)
-- =====================================================

-- Sharpe Ratio hesaplama fonksiyonu
CREATE OR REPLACE FUNCTION calculate_sharpe_ratio(
    p_portfolio_id INTEGER,
    p_days INTEGER DEFAULT 30,
    p_risk_free_rate DECIMAL DEFAULT 0.15
) RETURNS DECIMAL AS $$
DECLARE
    v_avg_return DECIMAL;
    v_std_return DECIMAL;
    v_annualized_sharpe DECIMAL;
BEGIN
    SELECT
        AVG(daily_return_pct),
        STDDEV(daily_return_pct)
    INTO v_avg_return, v_std_return
    FROM (
        SELECT
            CASE
                WHEN LAG(equity_end) OVER (ORDER BY pnl_date) > 0
                THEN (equity_end - LAG(equity_end) OVER (ORDER BY pnl_date))
                     / LAG(equity_end) OVER (ORDER BY pnl_date) * 100
                ELSE 0
            END as daily_return_pct
        FROM daily_pnl
        WHERE portfolio_id = p_portfolio_id
          AND pnl_date >= CURRENT_DATE - INTERVAL '1 day' * p_days
    ) sub;

    IF v_std_return IS NULL OR v_std_return = 0 THEN
        RETURN 0;
    END IF;

    -- Yıllık Sharpe (252 işlem günü)
    v_annualized_sharpe := (v_avg_return - p_risk_free_rate / 252) / v_std_return * SQRT(252);

    RETURN ROUND(v_annualized_sharpe, 4);
END;
$$ LANGUAGE plpgsql;

-- Maximum Drawdown hesaplama fonksiyonu
CREATE OR REPLACE FUNCTION calculate_max_drawdown(
    p_portfolio_id INTEGER,
    p_days INTEGER DEFAULT 30
) RETURNS DECIMAL AS $$
DECLARE
    v_max_drawdown DECIMAL := 0;
    v_peak DECIMAL := 0;
    v_current DECIMAL;
    rec RECORD;
BEGIN
    FOR rec IN
        SELECT equity_end
        FROM daily_pnl
        WHERE portfolio_id = p_portfolio_id
          AND pnl_date >= CURRENT_DATE - INTERVAL '1 day' * p_days
        ORDER BY pnl_date
    LOOP
        v_current := rec.equity_end;
        IF v_current > v_peak THEN
            v_peak := v_current;
        END IF;
        IF v_peak > 0 AND (v_peak - v_current) / v_peak * 100 > v_max_drawdown THEN
            v_max_drawdown := (v_peak - v_current) / v_peak * 100;
        END IF;
    END LOOP;

    RETURN ROUND(v_max_drawdown, 4);
END;
$$ LANGUAGE plpgsql;

-- Win Rate hesaplama fonksiyonu
CREATE OR REPLACE FUNCTION calculate_win_rate(
    p_portfolio_id INTEGER,
    p_days INTEGER DEFAULT 30
) RETURNS DECIMAL AS $$
DECLARE
    v_total_trades INTEGER;
    v_winning_trades INTEGER;
BEGIN
    SELECT
        COUNT(*),
        COUNT(CASE WHEN realized_pnl > 0 THEN 1 END)
    INTO v_total_trades, v_winning_trades
    FROM position_history
    WHERE portfolio_id = p_portfolio_id
      AND action = 'CLOSE'
      AND created_at >= CURRENT_DATE - INTERVAL '1 day' * p_days;

    IF v_total_trades = 0 THEN
        RETURN 0;
    END IF;

    RETURN ROUND(v_winning_trades::DECIMAL / v_total_trades * 100, 2);
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- PG_STAT_STATEMENTS VIEW (Sorgu performans analizi)
-- =====================================================

CREATE OR REPLACE VIEW v_slow_queries AS
SELECT
    query,
    calls,
    total_exec_time as total_time,
    mean_exec_time as mean_time,
    stddev_exec_time as stddev_time,
    rows,
    100.0 * shared_blks_hit / nullif(shared_blks_hit + shared_blks_read, 0) AS hit_percent
FROM pg_stat_statements
WHERE calls > 5
ORDER BY mean_exec_time DESC
LIMIT 50;

-- =====================================================
-- TABLO BOYUTLARI VIEW
-- =====================================================

CREATE OR REPLACE VIEW v_table_sizes AS
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as total_size,
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) as table_size,
    pg_size_pretty(pg_indexes_size(schemaname||'.'||tablename)) as index_size,
    n_live_tup as row_count,
    n_dead_tup as dead_rows,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- =====================================================
-- INDEX KULLANIM VIEW
-- =====================================================

CREATE OR REPLACE VIEW v_index_usage AS
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan as index_scans,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched,
    pg_size_pretty(pg_relation_size(indexrelid)) as index_size
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;

-- =====================================================
-- BAŞLANGIÇ VERİLERİ (Refresh fonksiyonu)
-- =====================================================

-- Materialized view'ları yenileme fonksiyonu
CREATE OR REPLACE FUNCTION refresh_materialized_views()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_recent_performance;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_active_positions;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_sector_allocation;
END;
$$ LANGUAGE plpgsql;

-- pg_cron ile otomatik yenileme (eğer pg_cron kuruluysa)
-- SELECT cron.schedule('refresh-mviews', '*/5 * * * *', 'SELECT refresh_materialized_views()');
