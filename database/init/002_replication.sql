-- PostgreSQL Replication User Setup
-- NOT: Replication devre dışı (max_wal_senders=0, hot_standby=off)
-- Bu script sadece ileride replication aktif edilirse kullanılır.

-- Replication slot oluşturma devre dışı bırakıldı:
-- SELECT pg_create_physical_replication_slot('replica1_slot', true);

-- Replication aktif edilmek istenirse aşağıdaki komutları çalıştırın:
-- DO $$
-- BEGIN
--     IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'replicator') THEN
--         CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'CHANGE_ME_SECURE_PASSWORD';
--     END IF;
-- END
-- $$;
