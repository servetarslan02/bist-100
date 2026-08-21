-- =====================================================
-- ALPHA BIST - PostgreSQL Schema v1.0
-- Operational / Transactional Database
-- =====================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

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
