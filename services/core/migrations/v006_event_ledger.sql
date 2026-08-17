-- Event Ledger — Durable event storage for idempotency and replay
-- migrate:up
CREATE TABLE IF NOT EXISTS event_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT,
    payload TEXT,
    published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_event_ledger_event_id ON event_ledger(event_id);
CREATE INDEX IF NOT EXISTS idx_event_ledger_type ON event_ledger(event_type);
-- migrate:down
DROP TABLE IF EXISTS event_ledger;
