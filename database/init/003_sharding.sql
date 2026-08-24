-- =====================================================
-- ALPHA BIST — Shard Database Creation
-- Her shard bağımsız bir PostgreSQL database'i
-- Ticker-based sharding: A-F, G-M, N-Z
-- =====================================================

-- Shard 0: A-F tickers
CREATE DATABASE alpha_bist_af;

-- Shard 1: G-M tickers
CREATE DATABASE alpha_bist_gm;

-- Shard 2: N-Z tickers
CREATE DATABASE alpha_bist_nz;
