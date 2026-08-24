-- =====================================================
-- ALPHA BIST — Shard Database Initialization
-- Her shard bağımsız bir PostgreSQL database'i
-- =====================================================

-- Shard 0: A-F tickers
CREATE DATABASE alpha_bist_af;

-- Shard 1: G-M tickers
CREATE DATABASE alpha_bist_gm;

-- Shard 2: N-Z tickers
CREATE DATABASE alpha_bist_nz;

-- Her shard'a temel tabloları kopyala
-- (Bu script sadece database'leri oluşturur,
--  tablolar alembic migration ile gelir)
