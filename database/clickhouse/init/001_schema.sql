-- =====================================================
-- ALPHA BIST - ClickHouse Schema v1.0
-- Analytical / Time-Series Database
-- =====================================================

CREATE DATABASE IF NOT EXISTS alpha_bist;

-- =====================================================
-- MARKET DATA (High-volume time-series)
-- =====================================================

CREATE TABLE IF NOT EXISTS alpha_bist.market_ticks (
    instrument_id UInt32,
    timestamp DateTime64(3, 'Europe/Istanbul'),
    price Decimal(12, 4),
    volume UInt64,
    bid Decimal(12, 4),
    ask Decimal(12, 4),
    trade_count UInt32 DEFAULT 0,
    source LowCardinality(String),
    quality Float32 DEFAULT 1.0
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (instrument_id, timestamp)
TTL timestamp + INTERVAL 5 YEAR
SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS alpha_bist.market_trades (
    instrument_id UInt32,
    timestamp DateTime64(3, 'Europe/Istanbul'),
    price Decimal(12, 4),
    quantity UInt64,
    side Enum8('BUY' = 1, 'SELL' = 2),
    trade_id String,
    source LowCardinality(String)
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (instrument_id, timestamp)
TTL timestamp + INTERVAL 5 YEAR;

CREATE TABLE IF NOT EXISTS alpha_bist.orderbook_snapshots (
    instrument_id UInt32,
    timestamp DateTime64(3, 'Europe/Istanbul'),
    bid_prices Array(Decimal(12, 4)),
    bid_volumes Array(UInt64),
    ask_prices Array(Decimal(12, 4)),
    ask_volumes Array(UInt64),
    spread Decimal(12, 4),
    mid_price Decimal(12, 4),
    source LowCardinality(String)
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (instrument_id, timestamp)
TTL timestamp + INTERVAL 1 YEAR;

-- =====================================================
-- OHLCV (Aggregated candles)
-- =====================================================

CREATE TABLE IF NOT EXISTS alpha_bist.ohlcv (
    instrument_id UInt32,
    timestamp DateTime('Europe/Istanbul'),
    timeframe Enum8('1m' = 1, '5m' = 5, '15m' = 15, '1h' = 60, '1d' = 1440),
    open Decimal(12, 4),
    high Decimal(12, 4),
    low Decimal(12, 4),
    close Decimal(12, 4),
    volume UInt64,
    trade_count UInt32 DEFAULT 0,
    vwap Decimal(12, 4)
) ENGINE = ReplacingMergeTree()
PARTITION BY (toYYYYMMDD(timestamp), timeframe)
ORDER BY (instrument_id, timeframe, timestamp)
TTL timestamp + INTERVAL 5 YEAR;

-- =====================================================
-- FEATURES (Computed features per instrument)
-- =====================================================

CREATE TABLE IF NOT EXISTS alpha_bist.features (
    instrument_id UInt32,
    timestamp DateTime64(3, 'Europe/Istanbul'),
    feature_name LowCardinality(String),
    feature_value Float64,
    feature_version UInt32 DEFAULT 1,
    source LowCardinality(String)
) ENGINE = ReplacingMergeTree(feature_version)
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (instrument_id, feature_name, timestamp)
TTL timestamp + INTERVAL 3 YEAR;

-- =====================================================
-- ASSET STATES (Current state per instrument)
-- =====================================================

CREATE TABLE IF NOT EXISTS alpha_bist.asset_states (
    instrument_id UInt32,
    timestamp DateTime64(3, 'Europe/Istanbul'),
    state_name LowCardinality(String),
    state_value Float64,
    state_string String DEFAULT '',
    confidence Float32 DEFAULT 1.0,
    updated_by LowCardinality(String) DEFAULT 'SYSTEM'
) ENGINE = ReplacingMergeTree(updated_by)
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (instrument_id, state_name, timestamp);

-- =====================================================
-- MARKET STATES (Overall market regime)
-- =====================================================

CREATE TABLE IF NOT EXISTS alpha_bist.market_states (
    timestamp DateTime64(3, 'Europe/Istanbul'),
    regime LowCardinality(String),
    regime_confidence Float32,
    trend_score Float32,
    breadth_pct Float32,
    volatility_regime LowCardinality(String),
    liquidity_level LowCardinality(String),
    risk_appetite Float32,
    details JSON
) ENGINE = ReplacingMergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY timestamp;

-- =====================================================
-- WORLD STATES (Global macro state)
-- =====================================================

CREATE TABLE IF NOT EXISTS alpha_bist.world_states (
    timestamp DateTime64(3, 'Europe/Istanbul'),
    geopolitical_risk Float32,
    global_risk_appetite Float32,
    usd_strength Float32,
    us_rate_pressure Float32,
    commodity_pressure Float32,
    oil_pressure Float32,
    turkey_macro_risk Float32,
    vix_level Float32,
    news_shock Float32,
    details JSON
) ENGINE = ReplacingMergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY timestamp;

-- =====================================================
-- EVENTS (News, KAP, Social, Macro)
-- =====================================================

CREATE TABLE IF NOT EXISTS alpha_bist.events (
    event_id String,
    timestamp DateTime64(3, 'Europe/Istanbul'),
    event_type LowCardinality(String),
    source LowCardinality(String),
    title String,
    body String DEFAULT '',
    entities Array(UInt32) DEFAULT [],
    instrument_ids Array(UInt32) DEFAULT [],
    sentiment Float32 DEFAULT 0,
    importance Float32 DEFAULT 0,
    credibility Float32 DEFAULT 1.0,
    novelty Float32 DEFAULT 0,
    event_category LowCardinality(String) DEFAULT 'OTHER',
    raw_data String DEFAULT '',
    processed Boolean DEFAULT false
) ENGINE = ReplacingMergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (event_type, timestamp)
TTL timestamp + INTERVAL 3 YEAR;

CREATE TABLE IF NOT EXISTS alpha_bist.kap_events (
    kap_id String,
    timestamp DateTime64(3, 'Europe/Istanbul'),
    company_id UInt32,
    ticker LowCardinality(String),
    announcement_type LowCardinality(String),
    title String,
    summary String DEFAULT '',
    sentiment Float32 DEFAULT 0,
    importance Float32 DEFAULT 0,
    is_price_sensitive Boolean DEFAULT false,
    raw_html String DEFAULT '',
    processed Boolean DEFAULT false
) ENGINE = ReplacingMergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (company_id, timestamp)
TTL timestamp + INTERVAL 5 YEAR;

CREATE TABLE IF NOT EXISTS alpha_bist.news_events (
    news_id String,
    timestamp DateTime64(3, 'Europe/Istanbul'),
    source LowCardinality(String),
    title String,
    body String DEFAULT '',
    url String DEFAULT '',
    language LowCardinality(String) DEFAULT 'tr',
    entities Array(String) DEFAULT [],
    instrument_ids Array(UInt32) DEFAULT [],
    sentiment Float32 DEFAULT 0,
    importance Float32 DEFAULT 0,
    event_type LowCardinality(String) DEFAULT 'NEWS',
    processed Boolean DEFAULT false
) ENGINE = ReplacingMergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (source, timestamp)
TTL timestamp + INTERVAL 2 YEAR;

CREATE TABLE IF NOT EXISTS alpha_bist.social_events (
    social_id String,
    timestamp DateTime64(3, 'Europe/Istanbul'),
    platform LowCardinality(String),
    author String DEFAULT '',
    content String DEFAULT '',
    entities Array(String) DEFAULT [],
    instrument_ids Array(UInt32) DEFAULT [],
    sentiment Float32 DEFAULT 0,
    engagement_score Float32 DEFAULT 0,
    is_influencer Boolean DEFAULT false,
    processed Boolean DEFAULT false
) ENGINE = ReplacingMergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (platform, timestamp)
TTL timestamp + INTERVAL 1 YEAR;

CREATE TABLE IF NOT EXISTS alpha_bist.macro_events (
    macro_id String,
    timestamp DateTime64(3, 'Europe/Istanbul'),
    event_type LowCardinality(String),
    country LowCardinality(String) DEFAULT 'TR',
    indicator_name String,
    actual_value Float64,
    expected_value Float64,
    previous_value Float64,
    surprise Float64,
    importance Float32,
    source LowCardinality(String) DEFAULT 'TCMB',
    processed Boolean DEFAULT false
) ENGINE = ReplacingMergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (event_type, timestamp);

-- =====================================================
-- SIGNALS (Generated trading signals)
-- =====================================================

CREATE TABLE IF NOT EXISTS alpha_bist.signals_history (
    signal_id UInt64,
    instrument_id UInt32,
    timestamp DateTime64(3, 'Europe/Istanbul'),
    signal_type LowCardinality(String),
    direction Enum8('LONG' = 1, 'SHORT' = 2, 'NEUTRAL' = 3),
    score Float32,
    confidence Float32,
    risk_level LowCardinality(String),
    horizon LowCardinality(String),
    expected_return_pct Float32,
    expected_volatility_pct Float32,
    edge_decomposition JSON DEFAULT '{}',
    model_version LowCardinality(String) DEFAULT '',
    strategy_id UInt32 DEFAULT 0,
    status LowCardinality(String) DEFAULT 'ACTIVE'
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (instrument_id, timestamp);

-- =====================================================
-- MODEL PREDICTIONS & OUTCOMES
-- =====================================================

CREATE TABLE IF NOT EXISTS alpha_bist.model_predictions (
    prediction_id UInt64,
    model_version_id UInt32,
    instrument_id UInt32,
    prediction_date Date,
    horizon_days UInt16,
    predicted_direction Enum8('UP' = 1, 'DOWN' = 2, 'NEUTRAL' = 3),
    predicted_return_pct Float32,
    probability_positive Float32,
    predicted_volatility_pct Float32,
    confidence Float32,
    features_used JSON DEFAULT '{}',
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(prediction_date)
ORDER BY (instrument_id, prediction_date, horizon_days);

CREATE TABLE IF NOT EXISTS alpha_bist.model_outcomes (
    prediction_id UInt64,
    actual_return_pct Float32,
    actual_direction Enum8('UP' = 1, 'DOWN' = 2, 'NEUTRAL' = 3),
    actual_volatility_pct Float32,
    prediction_error Float32,
    is_correct UInt8,
    outcome_date Date,
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(outcome_date)
ORDER BY (prediction_id, outcome_date);

-- =====================================================
-- ANOMALY DETECTION LOG
-- =====================================================

CREATE TABLE IF NOT EXISTS alpha_bist.anomalies (
    anomaly_id UInt64,
    instrument_id UInt32,
    timestamp DateTime64(3, 'Europe/Istanbul'),
    anomaly_type LowCardinality(String),
    severity Enum8('LOW' = 1, 'MEDIUM' = 2, 'HIGH' = 3, 'CRITICAL' = 4),
    score Float32,
    sigma Float32,
    description String,
    evidence JSON DEFAULT '{}',
    resolved Boolean DEFAULT false,
    resolved_at Nullable(DateTime64(3, 'Europe/Istanbul'))
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (instrument_id, timestamp);

-- =====================================================
-- REGIME HISTORY
-- =====================================================

CREATE TABLE IF NOT EXISTS alpha_bist.regime_history (
    timestamp DateTime64(3, 'Europe/Istanbul'),
    previous_regime LowCardinality(String),
    new_regime LowCardinality(String),
    confidence Float32,
    trigger String,
    duration_hours Float32,
    details JSON DEFAULT '{}'
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY timestamp;

-- =====================================================
-- DATA QUALITY LOG
-- =====================================================

CREATE TABLE IF NOT EXISTS alpha_bist.data_quality_log (
    timestamp DateTime64(3, 'Europe/Istanbul'),
    source LowCardinality(String),
    data_type LowCardinality(String),
    quality_score Float32,
    latency_ms UInt32,
    completeness_pct Float32,
    error_count UInt32 DEFAULT 0,
    missing_count UInt32 DEFAULT 0,
    duplicate_count UInt32 DEFAULT 0,
    details String DEFAULT ''
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (source, data_type, timestamp)
TTL timestamp + INTERVAL 6 MONTH;

-- =====================================================
-- MATERIALIZED VIEWS (Auto-aggregations)
-- =====================================================

-- Daily OHLCV aggregation
CREATE MATERIALIZED VIEW IF NOT EXISTS alpha_bist.ohlcv_daily_mv
TO alpha_bist.ohlcv
AS SELECT
    instrument_id,
    toStartOfDay(timestamp) AS timestamp,
    '1d' AS timeframe,
    argMin(open, timestamp) AS open,
    max(high) AS high,
    min(low) AS low,
    argMax(close, timestamp) AS close,
    sum(volume) AS volume,
    count() AS trade_count,
    sum(price * volume) / sum(volume) AS vwap
FROM alpha_bist.market_ticks
GROUP BY instrument_id, toStartOfDay(timestamp);

-- Hourly volume anomaly detection
CREATE MATERIALIZED VIEW IF NOT EXISTS alpha_bist.volume_hourly_mv
ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMMDD(hour)
ORDER BY (instrument_id, hour)
AS SELECT
    instrument_id,
    toStartOfHour(timestamp) AS hour,
    sum(volume) AS total_volume,
    count() AS tick_count,
    avg(price) AS avg_price,
    max(price) - min(price) AS price_range
FROM alpha_bist.market_ticks
GROUP BY instrument_id, toStartOfHour(timestamp);
