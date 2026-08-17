-- ALPHA BIST — Migration v005
-- FAZ 4 model metadata + system jobs + indexes
-- migrate:up

-- FAZ 4 model metadata fields
ALTER TABLE model_versions ADD COLUMN IF NOT EXISTS target_horizon INTEGER DEFAULT 5;
ALTER TABLE model_versions ADD COLUMN IF NOT EXISTS feature_names JSONB DEFAULT '[]';
ALTER TABLE model_versions ADD COLUMN IF NOT EXISTS cs_features JSONB DEFAULT '[]';
ALTER TABLE model_versions ADD COLUMN IF NOT EXISTS confidence_score DECIMAL(5,4) DEFAULT 0;
ALTER TABLE model_versions ADD COLUMN IF NOT EXISTS confidence_details JSONB DEFAULT '{}';
ALTER TABLE model_versions ADD COLUMN IF NOT EXISTS purge_gap_days INTEGER DEFAULT 5;
ALTER TABLE model_versions ADD COLUMN IF NOT EXISTS scaler_mean JSONB DEFAULT '[]';
ALTER TABLE model_versions ADD COLUMN IF NOT EXISTS scaler_std JSONB DEFAULT '[]';
ALTER TABLE model_versions ADD COLUMN IF NOT EXISTS impute_values JSONB DEFAULT '{}';
ALTER TABLE model_versions ADD COLUMN IF NOT EXISTS feature_importance JSONB DEFAULT '{}';

-- System jobs table (scheduler persistence)
CREATE TABLE IF NOT EXISTS system_jobs (
    id SERIAL PRIMARY KEY,
    job_type VARCHAR(50) NOT NULL,
    idempotency_key VARCHAR(64) NOT NULL,
    status VARCHAR(20) DEFAULT 'PENDING',
    priority INTEGER DEFAULT 0,
    payload JSONB DEFAULT '{}',
    result JSONB DEFAULT '{}',
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Market data cache metadata
CREATE TABLE IF NOT EXISTS market_data_snapshots (
    id SERIAL PRIMARY KEY,
    instrument_id INTEGER REFERENCES instruments(id),
    snapshot_date DATE NOT NULL,
    data_source VARCHAR(50),
    bar_count INTEGER,
    first_bar_date DATE,
    last_bar_date DATE,
    quality_score DECIMAL(5,4),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(instrument_id, snapshot_date, data_source)
);

-- Feature snapshot metadata
CREATE TABLE IF NOT EXISTS feature_snapshots (
    id SERIAL PRIMARY KEY,
    instrument_id INTEGER REFERENCES instruments(id),
    feature_date DATE NOT NULL,
    feature_count INTEGER,
    nan_count INTEGER DEFAULT 0,
    inf_count INTEGER DEFAULT 0,
    quality_score DECIMAL(5,4),
    features_hash VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(instrument_id, feature_date)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_signals_instrument_date ON signals(instrument_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status) WHERE status = 'ACTIVE';
CREATE INDEX IF NOT EXISTS idx_model_predictions_date ON model_predictions(prediction_date DESC);
CREATE INDEX IF NOT EXISTS idx_model_predictions_horizon ON model_predictions(horizon_days);
CREATE INDEX IF NOT EXISTS idx_orders_portfolio ON orders(portfolio_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status) WHERE status IN ('PENDING', 'PARTIAL');
CREATE INDEX IF NOT EXISTS idx_fills_order ON fills(order_id);
CREATE INDEX IF NOT EXISTS idx_system_jobs_status ON system_jobs(status) WHERE status IN ('PENDING', 'RUNNING');
CREATE INDEX IF NOT EXISTS idx_system_jobs_type ON system_jobs(job_type, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_system_jobs_idempotency ON system_jobs(idempotency_key) WHERE status IN ('PENDING', 'RUNNING');
CREATE INDEX IF NOT EXISTS idx_market_data_snapshots_date ON market_data_snapshots(instrument_id, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_feature_snapshots_date ON feature_snapshots(instrument_id, feature_date DESC);
CREATE INDEX IF NOT EXISTS idx_model_versions_status ON model_versions(status) WHERE status = 'CHAMPION';
CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at DESC);

-- migrate:down
DROP INDEX IF EXISTS idx_audit_logs_created;
DROP INDEX IF EXISTS idx_model_versions_status;
DROP INDEX IF EXISTS idx_feature_snapshots_date;
DROP INDEX IF EXISTS idx_market_data_snapshots_date;
DROP INDEX IF EXISTS idx_system_jobs_idempotency;
DROP INDEX IF EXISTS idx_system_jobs_type;
DROP INDEX IF EXISTS idx_system_jobs_status;
DROP INDEX IF EXISTS idx_fills_order;
DROP INDEX IF EXISTS idx_orders_status;
DROP INDEX IF EXISTS idx_orders_portfolio;
DROP INDEX IF EXISTS idx_model_predictions_horizon;
DROP INDEX IF EXISTS idx_model_predictions_date;
DROP INDEX IF EXISTS idx_signals_status;
DROP INDEX IF EXISTS idx_signals_instrument_date;
DROP TABLE IF EXISTS feature_snapshots;
DROP TABLE IF EXISTS market_data_snapshots;
DROP TABLE IF EXISTS system_jobs;
ALTER TABLE model_versions DROP COLUMN IF EXISTS feature_importance;
ALTER TABLE model_versions DROP COLUMN IF EXISTS impute_values;
ALTER TABLE model_versions DROP COLUMN IF EXISTS scaler_std;
ALTER TABLE model_versions DROP COLUMN IF EXISTS scaler_mean;
ALTER TABLE model_versions DROP COLUMN IF EXISTS purge_gap_days;
ALTER TABLE model_versions DROP COLUMN IF EXISTS confidence_details;
ALTER TABLE model_versions DROP COLUMN IF EXISTS confidence_score;
ALTER TABLE model_versions DROP COLUMN IF EXISTS cs_features;
ALTER TABLE model_versions DROP COLUMN IF EXISTS feature_names;
ALTER TABLE model_versions DROP COLUMN IF EXISTS target_horizon;
