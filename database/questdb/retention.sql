-- =====================================================
-- ALPHA BIST — QuestDB Retention & Maintenance
-- Oluşturulma: 2026-08-28
-- Amaç: QuestDB tabloları için veri yaşam döngüsü
-- =====================================================

-- =====================================================
-- TABLO YAPILARI (Doğrulama)
-- =====================================================

-- market_ticks: Yüksek frekanslı tick verisi (saniyelik/dakikalık)
-- PARTITION BY DAY → günlük partition'lar
-- DEDUP UPSERT KEYS(timestamp, ticker) → duplike kayıtları önler
-- WAL → Write-Ahead Logging (crash recovery)

-- ohlcv: OHLCV verisi (günlük/haftalık)
-- PARTITION BY DAY → günlük partition'lar
-- DEDUP UPSERT KEYS(timestamp, ticker, timeframe) → duplike kayıtları önler

-- events: Olay verisi (KAP, haber, makro)
-- PARTITION BY MONTH → aylık partition'lar (daha az sıklık)

-- =====================================================
-- RETENTION POLICIES (QuestDB native)
-- =====================================================

-- QuestDB'de retention için partition-based strateji kullanılır.
-- Eski partition'lar manuel veya otomatik olarak silinir.

-- market_ticks: 30 günden eski tick verisini sil
-- (Yüksek hacimli, 30 gün yeterli)
-- QuestDB'de: ALTER TABLE market_ticks DROP PARTITION WHERE timestamp < dateadd('d', -30, now())

-- ohlcv: 1 yıldan eski OHLCV verisini sil
-- (Daha düşük hacimli, uzun süreli analiz için)
-- QuestDB'de: ALTER TABLE ohlcv DROP PARTITION WHERE timestamp < dateadd('y', -1, now())

-- events: 6 aydan eski olay verisini sil
-- QuestDB'de: ALTER TABLE events DROP PARTITION WHERE timestamp < dateadd('m', -6, now())

-- =====================================================
-- COMPRESSION (QuestDB native)
-- =====================================================

-- QuestDB, WAL tablolarında otomatik sıkıştırma kullanır.
-- Partition-based storage sayesinde eski veriler otomatik olarak optimize edilir.

-- =====================================================
-- PERFORMANS OPTİMİZASYONU
-- =====================================================

-- 1. Batch writes: Tek tek yazmak yerine toplu yazma (100+ tick/batch)
-- 2. ILP protocol: HTTP API'den daha hızlı (socket-based)
-- 3. WAL mode: Crash recovery + concurrent reads
-- 4. Partition pruning: Zaman bazlı sorgularda sadece ilgili partition'lar okunur

-- =====================================================
-- BAKIM SORGULARI (Periyodik çalıştırılacak)
-- =====================================================

-- Partition durumu kontrolü
-- SELECT partition, numRows, diskSize FROM table_partitions('market_ticks')

-- Tablo boyutu kontrolü
-- SELECT table, numRows, diskSize FROM tables()

-- Eski partition'ları temizle (30 gün)
-- ALTER TABLE market_ticks DROP PARTITION WHERE timestamp < dateadd('d', -30, now())

-- =====================================================
-- VERİ DAĞITIM STRATEJİSİ
-- =====================================================

-- QuestDB:    Tick verisi (saniyelik/dakikalık) — ILP ile ultra hızlı yazma
-- TimescaleDB: OHLCV (günlük/haftalık) — SQL + hypertable
-- ClickHouse:  30 yıllık tarihsel veri — OLAP analitik sorgular
-- DuckDB:      Local state + offline research — embedded
-- PostgreSQL:  İşlemsel veri, metadata, modeller — ACID

-- NOT: Aynı veriyi üç farklı DB'de gereksiz yere tutmayın!
