#!/bin/bash
# =====================================================
# ALPHA BIST — Shard Table Initialization
# Her shard database'inde tabloları oluşturur
# =====================================================

set -e

PSQL="psql -v ON_ERROR_STOP=1"

create_tables() {
    local db=$1
    $PSQL -d "$db" <<-EOSQL
        CREATE TABLE IF NOT EXISTS prices (
            id BIGSERIAL PRIMARY KEY,
            ticker VARCHAR(10) NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            open DECIMAL(12,4),
            high DECIMAL(12,4),
            low DECIMAL(12,4),
            close DECIMAL(12,4),
            volume BIGINT,
            source VARCHAR(50),
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_prices_ticker_ts ON prices(ticker, timestamp);

        CREATE TABLE IF NOT EXISTS signals (
            id BIGSERIAL PRIMARY KEY,
            ticker VARCHAR(10) NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            signal_type VARCHAR(50) NOT NULL,
            confidence DECIMAL(5,4),
            metadata JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_signals_ticker_ts ON signals(ticker, timestamp);

        CREATE TABLE IF NOT EXISTS portfolio_positions (
            id BIGSERIAL PRIMARY KEY,
            ticker VARCHAR(10) NOT NULL UNIQUE,
            quantity DECIMAL(15,4) NOT NULL DEFAULT 0,
            avg_price DECIMAL(12,4),
            current_price DECIMAL(12,4),
            pnl DECIMAL(15,4),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
EOSQL
}

echo "Creating shard tables..."
create_tables "alpha_bist_af"
create_tables "alpha_bist_gm"
create_tables "alpha_bist_nz"
echo "Shard tables created successfully."
