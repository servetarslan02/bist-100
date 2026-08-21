-- ALPHA BIST — Positions entry_commission field
-- Version: 003
-- Description: Add entry_commission to positions table for v2.0 accounting
-- Idempotent: runner catches "duplicate column" error and continues

ALTER TABLE positions ADD COLUMN entry_commission REAL DEFAULT 0;

-- migrate:down
-- SQLite doesn't support DROP COLUMN (before 3.35.0).
-- For SQLite: recreate table without the column.
-- For PostgreSQL: ALTER TABLE positions DROP COLUMN entry_commission;
-- Since we target compatibility, we leave the column (harmless default 0).
-- Manual intervention required for full rollback on SQLite < 3.35.
