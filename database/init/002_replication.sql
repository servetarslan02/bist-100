-- PostgreSQL Replication User Setup
-- Primary'de çalıştırılır, replica bu kullanıcı ile bağlanır

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'replicator') THEN
        CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'alpha_secure_pass_123';
    END IF;
END
$$;

-- Replication slot (veri kaybını önler)
SELECT pg_create_physical_replication_slot('replica1_slot', true);
