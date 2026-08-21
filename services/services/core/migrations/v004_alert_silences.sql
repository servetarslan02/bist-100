-- ALPHA BIST — Alert Silences Table
-- Version: 004
-- Description: DB-backed silence management for alerting

-- migrate:split
CREATE TABLE IF NOT EXISTS alert_silences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type TEXT,
    fingerprint TEXT,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    reason TEXT,
    created_by TEXT DEFAULT 'system',
    created_at REAL,
    UNIQUE(fingerprint, alert_type)
);

-- migrate:split
CREATE INDEX IF NOT EXISTS idx_alert_silences_active
ON alert_silences(end_time);

-- migrate:split
CREATE INDEX IF NOT EXISTS idx_alert_silences_type
ON alert_silences(alert_type);

-- migrate:down
DROP INDEX IF EXISTS idx_alert_silences_type;
DROP INDEX IF EXISTS idx_alert_silences_active;
DROP TABLE IF EXISTS alert_silences;
