-- =====================================================
-- ALPHA BIST — TimescaleDB Retention & Maintenance Policies
-- Oluşturulma: 2026-08-28
-- Amaç: Eski veriyi otomatik temizle, depolama optimizasyonu
-- =====================================================

-- =====================================================
-- RETENTION POLICIES (Otomatik veri temizleme)
-- =====================================================

-- Scan results: 2 yıldan eski veriyi sil (çok hacimli)
SELECT add_retention_policy('scan_results', INTERVAL '730 days', if_not_exists => TRUE);

-- Alerts: 1 yıldan eski alarmları sil
SELECT add_retention_policy('alerts', INTERVAL '365 days', if_not_exists => TRUE);

-- Audit logs: 2 yıldan eski logları sil (compliance gereği uzun tutulabilir)
SELECT add_retention_policy('audit_logs', INTERVAL '730 days', if_not_exists => TRUE);

-- System events: 1 yıldan eski olayları sil
SELECT add_retention_policy('system_events', INTERVAL '365 days', if_not_exists => TRUE);

-- Paper trades: 1 yıldan eski kağıt işlemleri sil
SELECT add_retention_policy('paper_trades', INTERVAL '365 days', if_not_exists => TRUE);

-- Backtest runs: 6 aydan eski backtest sonuçlarını sil
SELECT add_retention_policy('backtest_runs', INTERVAL '180 days', if_not_exists => TRUE);

-- Equity snapshots: 1 yıldan eski anlık görüntüleri sil
SELECT add_retention_policy('equity_snapshots', INTERVAL '365 days', if_not_exists => TRUE);

-- Daily P&L: 5 yıldan eski günlük P&L'yi sil (uzun vadeli analiz için tutulabilir)
-- NOT: Bu politika opsiyonel, iş gereksinimlerine göre ayarlanmalı
-- SELECT add_retention_policy('daily_pnl', INTERVAL '1825 days', if_not_exists => TRUE);

-- =====================================================
-- COMPRESSION POLICIES (Mevcut olanları doğrula + eksikleri ekle)
-- =====================================================

-- Model predictions: 30 gün sonra sıkıştır (zaten mevcut)
-- SELECT add_compression_policy('model_predictions', INTERVAL '30 days', if_not_exists => TRUE);

-- Daily performance: 90 gün sonra sıkıştır (zaten mevcut)
-- SELECT add_compression_policy('daily_performance', INTERVAL '90 days', if_not_exists => TRUE);

-- Scan results: 7 gün sonra sıkıştır (zaten mevcut)
-- SELECT add_compression_policy('scan_results', INTERVAL '7 days', if_not_exists => TRUE);

-- Alerts: 30 gün sonra sıkıştır (zaten mevcut)
-- SELECT add_compression_policy('alerts', INTERVAL '30 days', if_not_exists => TRUE);

-- Audit logs: 30 gün sonra sıkıştır (zaten mevcut)
-- SELECT add_compression_policy('audit_logs', INTERVAL '30 days', if_not_exists => TRUE);

-- Equity curve: 90 gün sonra sıkıştır
ALTER TABLE equity_curve SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'date DESC'
);
SELECT add_compression_policy('equity_curve', INTERVAL '90 days', if_not_exists => TRUE);

-- Daily P&L: 90 gün sonra sıkıştır
ALTER TABLE daily_pnl SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'pnl_date DESC'
);
SELECT add_compression_policy('daily_pnl', INTERVAL '90 days', if_not_exists => TRUE);

-- Equity snapshots: 30 gün sonra sıkıştır
ALTER TABLE equity_snapshots SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'ticker',
    timescaledb.compress_orderby = 'snapshot_date DESC'
);
SELECT add_compression_policy('equity_snapshots', INTERVAL '30 days', if_not_exists => TRUE);

-- System events: 30 gün sonra sıkıştır
ALTER TABLE system_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'event_type',
    timescaledb.compress_orderby = 'created_at DESC'
);
SELECT add_compression_policy('system_events', INTERVAL '30 days', if_not_exists => TRUE);

-- Paper trades: 30 gün sonra sıkıştır
ALTER TABLE paper_trades SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'ticker',
    timescaledb.compress_orderby = 'created_at DESC'
);
SELECT add_compression_policy('paper_trades', INTERVAL '30 days', if_not_exists => TRUE);

-- Backtest runs: 30 gün sonra sıkıştır
ALTER TABLE backtest_runs SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'created_at DESC'
);
SELECT add_compression_policy('backtest_runs', INTERVAL '30 days', if_not_exists => TRUE);

-- =====================================================
-- CONTINUOUS AGGREGATES REFRESH POLICIES
-- =====================================================

-- Mevcut continuous aggregate'ler için refresh policy ekle
SELECT add_continuous_aggregate_policy('daily_perf_summary',
    start_offset => INTERVAL '3 months',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

SELECT add_continuous_aggregate_policy('weekly_scan_summary',
    start_offset => INTERVAL '6 months',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '6 hours',
    if_not_exists => TRUE
);

-- =====================================================
-- YENİ CONTINUOUS AGGREGATES
-- =====================================================

-- Aylık performans özeti (uzun vadeli analiz için)
CREATE MATERIALIZED VIEW IF NOT EXISTS monthly_performance_summary
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 month', date) AS month,
    strategy_id,
    AVG(total_return) AS avg_return,
    STDDEV(total_return) AS volatility,
    MAX(drawdown) AS max_drawdown,
    SUM(total_pnl) AS total_pnl,
    COUNT(*) AS trading_days
FROM daily_performance
GROUP BY time_bucket('1 month', date), strategy_id
WITH NO DATA;

-- Aylık refresh policy
SELECT add_continuous_aggregate_policy('monthly_performance_summary',
    start_offset => INTERVAL '12 months',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- Saatlik model prediction istatistikleri
CREATE MATERIALIZED VIEW IF NOT EXISTS hourly_prediction_stats
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', prediction_date) AS hour,
    instrument_id,
    AVG(confidence) AS avg_confidence,
    AVG(predicted_return) AS avg_predicted_return,
    COUNT(*) AS prediction_count
FROM model_predictions
GROUP BY time_bucket('1 hour', prediction_date), instrument_id
WITH NO DATA;

-- Saatlik refresh policy
SELECT add_continuous_aggregate_policy('hourly_prediction_stats',
    start_offset => INTERVAL '7 days',
    end_offset => INTERVAL '10 minutes',
    schedule_interval => INTERVAL '30 minutes',
    if_not_exists => TRUE
);

-- =====================================================
-- CHUNK TIME INTERVAL OPTIMIZATION
-- =====================================================

-- Büyük tablolar için chunk boyutunu ayarla
-- (Varsayılan 7 gün, yüksek hacimli tablolar için daha küçük)
SELECT set_chunk_time_interval('scan_results', INTERVAL '1 day');
SELECT set_chunk_time_interval('alerts', INTERVAL '7 days');
SELECT set_chunk_time_interval('audit_logs', INTERVAL '7 days');
SELECT set_chunk_time_interval('system_events', INTERVAL '7 days');

-- =====================================================
-- DOĞRULAMA SORGULARI
-- =====================================================

-- Retention policy'leri kontrol et
-- SELECT * FROM timescaledb_information.jobs WHERE proc_name = 'policy_retention';

-- Compression policy'leri kontrol et
-- SELECT * FROM timescaledb_information.jobs WHERE proc_name = 'policy_compression';

-- Continuous aggregate refresh policy'leri kontrol et
-- SELECT * FROM timescaledb_information.jobs WHERE proc_name = 'policy_refresh_continuous_aggregate';

-- Chunk bilgileri
-- SELECT hypertable_name, chunk_name, range_start, range_end, is_compressed
-- FROM timescaledb_information.chunks
-- ORDER BY range_start DESC;
