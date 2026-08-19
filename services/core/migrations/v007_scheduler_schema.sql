-- ALPHA BIST — Scheduler Schema
-- Version: 007
-- Description: system_jobs tablosu + scheduler config

-- migrate:split
CREATE TABLE IF NOT EXISTS system_jobs (
    id              BIGSERIAL PRIMARY KEY,
    job_type        VARCHAR(100) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    priority        INTEGER DEFAULT 5,
    payload         JSONB DEFAULT '{}',
    result          JSONB,
    error_message   TEXT,
    max_retries     INTEGER DEFAULT 3,
    retry_count     INTEGER DEFAULT 0,
    duration_ms     DOUBLE PRECISION,
    idempotency_key VARCHAR(64),
    triggered_by    VARCHAR(20) DEFAULT 'scheduler',
    worker_id       VARCHAR(50),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- İndeks: job_type + status sorguları için
CREATE INDEX IF NOT EXISTS idx_system_jobs_type_status
    ON system_jobs (job_type, status);

-- İndeks: completed_at sorguları için (failure stats)
CREATE INDEX IF NOT EXISTS idx_system_jobs_completed_at
    ON system_jobs (completed_at DESC);

-- İndeks: idempotency_key tekil kontrolü
CREATE UNIQUE INDEX IF NOT EXISTS idx_system_jobs_idempotency
    ON system_jobs (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- migrate:split
CREATE TABLE IF NOT EXISTS scheduler_config (
    id              BIGSERIAL PRIMARY KEY,
    job_type        VARCHAR(100) UNIQUE NOT NULL,
    interval_seconds INTEGER NOT NULL DEFAULT 300,
    priority        INTEGER DEFAULT 5,
    enabled         BOOLEAN DEFAULT TRUE,
    trading_only    BOOLEAN DEFAULT TRUE,
    max_retries     INTEGER DEFAULT 3,
    timeout_seconds INTEGER DEFAULT 300,
    description     TEXT,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Varsayılan job konfigürasyonlarını doldur
INSERT INTO scheduler_config (job_type, interval_seconds, priority, enabled, trading_only, description)
VALUES
    ('market_data_update', 120, 1, TRUE, FALSE, 'Piyasa verisi güncelleme'),
    ('feature_calculation', 300, 1, TRUE, FALSE, 'Feature hesaplama'),
    ('universe_refresh', 86400, 8, TRUE, FALSE, 'Universe yenileme'),
    ('live_scanning', 0, 2, TRUE, TRUE, 'Canlı tarama'),
    ('batch_scan', 3600, 3, TRUE, TRUE, 'Batch tarama'),
    ('signal_generation', 600, 3, TRUE, TRUE, 'Sinyal üretimi'),
    ('risk_monitoring', 120, 2, TRUE, TRUE, 'Risk izleme'),
    ('health_check', 60, 9, TRUE, FALSE, 'Sistem sağlık kontrolü'),
    ('persistence', 900, 5, TRUE, FALSE, 'Veri saklama'),
    ('daily_report', 86400, 7, TRUE, FALSE, 'Günlük rapor'),
    ('performance_attribution', 86400, 7, TRUE, FALSE, 'Performans atıf analizi'),
    ('learning_cycle', 86400, 6, TRUE, FALSE, 'Öğrenme döngüsü'),
    ('model_drift_detection', 86400, 6, TRUE, FALSE, 'Model drift tespiti'),
    ('model_retrain', 604800, 7, TRUE, FALSE, 'Model yeniden eğitim'),
    ('backtest', 604800, 8, TRUE, FALSE, 'Backtest'),
    ('calibration_update', 2592000, 9, TRUE, FALSE, 'Calibration güncelleme'),
    ('backup', 86400, 10, TRUE, FALSE, 'Veritabanı yedekleme')
ON CONFLICT (job_type) DO NOTHING;
