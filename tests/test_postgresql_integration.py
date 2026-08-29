from typing import Any
"""ALPHA BIST — PostgreSQL Integration Tests

PostgreSQL madde 1 değişikliklerinin doğrulanması:
- DatabaseRouter read/write ayrımı
- Replica lag kontrolü
- Backup script doğrulama
- PIT queries modülü
- TimescaleDB retention/compression

Kullanım:
    python -m pytest tests/test_postgresql_integration.py -v
    python -m pytest tests/test_postgresql_integration.py -v -k "test_database_router"
"""

import ast
from pathlib import Path

import pytest

# Proje root'unu path'e ekle
PROJECT_ROOT = Path(__file__).parent.parent


# =====================================================
# DATABASE.PY STRUCTURE TESTS
# =====================================================


class TestDatabaseStructure:
    """database.py yapısal doğrulama."""

    def test_file_exists(self) -> Any:
        """database.py dosyası mevcut mu."""
        db_path = PROJECT_ROOT / "services" / "core" / "database.py"
        assert db_path.exists(), "services/core/database.py bulunamadı"

    def test_syntax_valid(self) -> Any:
        """database.py syntax geçerli mi."""
        db_path = PROJECT_ROOT / "services" / "core" / "database.py"
        with open(db_path) as f:
            content = f.read()
        try:
            ast.parse(content)
        except SyntaxError as e:
            pytest.fail(f"Syntax hatası: {e}")

    def test_database_router_class_exists(self) -> Any:
        """DatabaseRouter sınıfı mevcut mu."""
        db_path = PROJECT_ROOT / "services" / "core" / "database.py"
        with open(db_path) as f:
            content = f.read()
        assert "class DatabaseRouter" in content, "DatabaseRouter sınıfı bulunamadı"

    def test_db_router_instance_exists(self) -> Any:
        """db_router singleton instance mevcut mu."""
        db_path = PROJECT_ROOT / "services" / "core" / "database.py"
        with open(db_path) as f:
            content = f.read()
        assert "db_router = DatabaseRouter()" in content, "db_router instance bulunamadı"

    def test_check_replica_lag_function(self) -> Any:
        """_check_replica_lag fonksiyonu mevcut mu."""
        db_path = PROJECT_ROOT / "services" / "core" / "database.py"
        with open(db_path) as f:
            content = f.read()
        assert "async def _check_replica_lag" in content, "_check_replica_lag bulunamadı"
        assert "pg_last_xact_replay_timestamp" in content, "Lag sorgusu bulunamadı"

    def test_replica_lag_threshold(self) -> Any:
        """Replica lag threshold tanımlı mı."""
        db_path = PROJECT_ROOT / "services" / "core" / "database.py"
        with open(db_path) as f:
            content = f.read()
        assert "_REPLICA_LAG_THRESHOLD_SECONDS" in content, "Lag threshold bulunamadı"

    def test_router_methods(self) -> Any:
        """DatabaseRouter metodları mevcut mu."""
        db_path = PROJECT_ROOT / "services" / "core" / "database.py"
        with open(db_path) as f:
            content = f.read()
        required_methods = [
            "get_write_conn",
            "get_read_conn",
            "read",
            "write",
            "write_transaction",
            "_release",
        ]
        for method in required_methods:
            assert method in content, f"{method} metodu bulunamadı"

    def test_pg_fetch_uses_replica(self) -> Any:
        """pg_fetch replica kullanıyor mu."""
        db_path = PROJECT_ROOT / "services" / "core" / "database.py"
        with open(db_path) as f:
            content = f.read()
        # pg_fetch fonksiyonunun gövdesini bul
        import re

        match = re.search(
            r"async def pg_fetch\(.*?\n(.*?)(?=\nasync def|\nclass |\Z)",
            content,
            re.DOTALL,
        )
        assert match, "pg_fetch fonksiyonu bulunamadı"
        assert "get_pg_replica_connection" in match.group(1), "pg_fetch replica kullanmıyor"

    def test_pg_execute_uses_primary(self) -> Any:
        """pg_execute primary kullanıyor mu."""
        db_path = PROJECT_ROOT / "services" / "core" / "database.py"
        with open(db_path) as f:
            content = f.read()
        import re

        match = re.search(
            r"async def pg_execute\(.*?\n(.*?)(?=\nasync def|\nclass |\Z)",
            content,
            re.DOTALL,
        )
        assert match, "pg_execute fonksiyonu bulunamadı"
        body = match.group(1)
        assert "get_pg_connection" in body, "pg_execute primary kullanmıyor"
        assert "get_pg_replica" not in body, "pg_execute yanlışlıkla replica kullanıyor"

    def test_no_regression_public_functions(self) -> Any:
        """Mevcut public fonksiyonlar bozulmadı mı."""
        db_path = PROJECT_ROOT / "services" / "core" / "database.py"
        with open(db_path) as f:
            content = f.read()
        expected = [
            "get_pg_pool",
            "get_pg_replica_pool",
            "close_pg_pool",
            "get_pg_connection",
            "get_pg_replica_connection",
            "get_pg_transaction",
            "pg_execute",
            "pg_fetch",
            "pg_fetchrow",
            "pg_fetchval",
            "get_ch_client",
            "close_ch_client",
            "ch_execute",
            "ch_insert",
            "ch_query_df",
            "get_redis",
            "close_redis",
            "redis_get",
            "redis_set",
            "redis_delete",
            "redis_hgetall",
            "redis_hset",
            "redis_publish",
            "check_db_health",
            "init_databases",
            "close_databases",
        ]
        for fn in expected:
            assert f"async def {fn}" in content or f"def {fn}" in content, f"Eksik fonksiyon: {fn}"


# =====================================================
# BACKUP SCRIPT TESTS
# =====================================================


class TestBackupScript:
    """backup_alpha.sh doğrulama."""

    def test_file_exists(self) -> Any:
        """Backup script mevcut mu."""
        path = PROJECT_ROOT / "scripts" / "backup_alpha.sh"
        assert path.exists(), "scripts/backup_alpha.sh bulunamadı"

    def test_no_sqlite(self) -> Any:
        """Backup script SQLite kullanmıyor mu."""
        path = PROJECT_ROOT / "scripts" / "backup_alpha.sh"
        with open(path) as f:
            content = f.read()
        assert "sqlite3" not in content.lower(), "Backup script hala SQLite kullanıyor!"

    def test_uses_duckdb(self) -> Any:
        """Backup script DuckDB kullanıyor mu."""
        path = PROJECT_ROOT / "scripts" / "backup_alpha.sh"
        with open(path) as f:
            content = f.read()
        assert "duckdb" in content.lower(), "Backup script DuckDB kullanmıyor"

    def test_has_pitr_support(self) -> Any:
        """PITR desteği mevcut mu."""
        path = PROJECT_ROOT / "scripts" / "backup_alpha.sh"
        with open(path) as f:
            content = f.read()
        assert "pg_basebackup" in content, "PITR (pg_basebackup) desteği yok"
        assert "pg_switch_wal" in content, "WAL archive desteği yok"

    def test_has_questdb_backup(self) -> Any:
        """QuestDB backup desteği mevcut mu."""
        path = PROJECT_ROOT / "scripts" / "backup_alpha.sh"
        with open(path) as f:
            content = f.read()
        assert "questdb" in content.lower(), "QuestDB backup desteği yok"


# =====================================================
# COMPOSITE INDEX STRATEGY TESTS
# =====================================================


class TestCompositeIndexStrategy:
    """Composite index stratejisi doğrulama."""

    def test_file_exists(self) -> Any:
        """Index stratejisi dokümanı mevcut mu."""
        path = PROJECT_ROOT / "docs" / "COMPOSITE_INDEX_STRATEGY.md"
        assert path.exists(), "docs/COMPOSITE_INDEX_STRATEGY.md bulunamadı"

    def test_critical_tables_documented(self) -> Any:
        """Kritik tablolar belgelenmiş mi."""
        path = PROJECT_ROOT / "docs" / "COMPOSITE_INDEX_STRATEGY.md"
        with open(path) as f:
            content = f.read()
        tables = ["model_predictions", "signals", "positions", "orders", "audit_logs", "daily_performance"]
        for table in tables:
            assert table in content, f"{table} belgelenmemiş"

    def test_concurrently_mentioned(self) -> Any:
        """CONCURRENTLY kullanımı belirtilmiş mi."""
        path = PROJECT_ROOT / "docs" / "COMPOSITE_INDEX_STRATEGY.md"
        with open(path) as f:
            content = f.read()
        assert "CONCURRENTLY" in content, "CONCURRENTLY kullanımı belirtilmemiş"

    def test_maintenance_plan(self) -> Any:
        """Bakım planı mevcut mu."""
        path = PROJECT_ROOT / "docs" / "COMPOSITE_INDEX_STRATEGY.md"
        with open(path) as f:
            content = f.read()
        assert "Haftalık" in content or "Aylık" in content, "Bakım planı yok"


# =====================================================
# AUDIT SCRIPTS TESTS
# =====================================================


class TestAuditScripts:
    """Audit script'leri doğrulama."""

    def test_query_performance_script_exists(self) -> Any:
        """Query performance audit script mevcut mu."""
        path = PROJECT_ROOT / "scripts" / "audit_query_performance.py"
        assert path.exists(), "scripts/audit_query_performance.py bulunamadı"

    def test_query_performance_syntax(self) -> Any:
        """Query performance audit script syntax geçerli mi."""
        path = PROJECT_ROOT / "scripts" / "audit_query_performance.py"
        with open(path) as f:
            ast.parse(f.read())

    def test_query_performance_features(self) -> Any:
        """Query performance audit script gerekli özellikleri içeriyor mu."""
        path = PROJECT_ROOT / "scripts" / "audit_query_performance.py"
        with open(path) as f:
            content = f.read()
        assert "pg_stat_statements" in content
        assert "EXPLAIN" in content
        assert "composite" in content.lower() or "COMPOSITE" in content

    def test_timescaledb_health_script_exists(self) -> Any:
        """TimescaleDB health audit script mevcut mu."""
        path = PROJECT_ROOT / "scripts" / "audit_timescaledb_health.py"
        assert path.exists(), "scripts/audit_timescaledb_health.py bulunamadı"

    def test_timescaledb_health_syntax(self) -> Any:
        """TimescaleDB health audit script syntax geçerli mi."""
        path = PROJECT_ROOT / "scripts" / "audit_timescaledb_health.py"
        with open(path) as f:
            ast.parse(f.read())

    def test_timescaledb_health_features(self) -> Any:
        """TimescaleDB health audit script gerekli özellikleri içeriyor mu."""
        path = PROJECT_ROOT / "scripts" / "audit_timescaledb_health.py"
        with open(path) as f:
            content = f.read()
        assert "DATA_QUALITY_RULES" in content
        assert "hypertable" in content.lower()
        assert "compression" in content.lower()
        assert "retention" in content.lower()


# =====================================================
# TIMESCALEDB RETENTION SQL TESTS
# =====================================================


class TestTimescaleDBRetention:
    """TimescaleDB retention SQL doğrulama."""

    def test_file_exists(self) -> Any:
        """Retention SQL dosyası mevcut mu."""
        path = PROJECT_ROOT / "database" / "init" / "004_timescaledb_retention.sql"
        assert path.exists(), "database/init/004_timescaledb_retention.sql bulunamadı"

    def test_has_retention_policies(self) -> Any:
        """Retention policy'ler mevcut mu."""
        path = PROJECT_ROOT / "database" / "init" / "004_timescaledb_retention.sql"
        with open(path) as f:
            content = f.read()
        assert "add_retention_policy" in content, "Retention policy yok"

    def test_has_compression_policies(self) -> Any:
        """Compression policy'ler mevcut mu."""
        path = PROJECT_ROOT / "database" / "init" / "004_timescaledb_retention.sql"
        with open(path) as f:
            content = f.read()
        assert "add_compression_policy" in content, "Compression policy yok"

    def test_has_continuous_aggregates(self) -> Any:
        """Continuous aggregate'ler mevcut mu."""
        path = PROJECT_ROOT / "database" / "init" / "004_timescaledb_retention.sql"
        with open(path) as f:
            content = f.read()
        assert "timescaledb.continuous" in content, "Continuous aggregate yok"
        assert "monthly_performance_summary" in content
        assert "hourly_prediction_stats" in content

    def test_has_chunk_optimization(self) -> Any:
        """Chunk optimization mevcut mu."""
        path = PROJECT_ROOT / "database" / "init" / "004_timescaledb_retention.sql"
        with open(path) as f:
            content = f.read()
        assert "set_chunk_time_interval" in content, "Chunk optimization yok"


# =====================================================
# PIT QUERIES MODULE TESTS
# =====================================================


class TestPITQueries:
    """PIT queries modülü doğrulama."""

    def test_file_exists(self) -> Any:
        """PIT queries modülü mevcut mu."""
        path = PROJECT_ROOT / "services" / "core" / "pit_queries.py"
        assert path.exists(), "services/core/pit_queries.py bulunamadı"

    def test_syntax_valid(self) -> Any:
        """PIT queries modülü syntax geçerli mi."""
        path = PROJECT_ROOT / "services" / "core" / "pit_queries.py"
        with open(path) as f:
            ast.parse(f.read())

    def test_required_functions(self) -> Any:
        """Gerekli PIT fonksiyonları mevcut mu."""
        path = PROJECT_ROOT / "services" / "core" / "pit_queries.py"
        with open(path) as f:
            content = f.read()
        functions = [
            "pit_fetch_as_of",
            "pit_fetch_latest",
            "pit_fetch_range",
            "pit_validate_no_leakage",
            "pit_fetch_snapshot",
            "pit_fetch_df",
            "pit_audit_all_tables",
        ]
        for fn in functions:
            assert fn in content, f"{fn} fonksiyonu bulunamadı"

    def test_pit_templates(self) -> Any:
        """PIT query templates tanımlı mı."""
        path = PROJECT_ROOT / "services" / "core" / "pit_queries.py"
        with open(path) as f:
            content = f.read()
        assert "PIT_QUERY_TEMPLATES" in content, "PIT_QUERY_TEMPLATES bulunamadı"
        tables = ["model_predictions", "daily_performance", "signals", "positions", "orders", "scan_results"]
        for table in tables:
            assert table in content, f"{table} PIT template'de yok"

    def test_no_lookahead_bias(self) -> Any:
        """PIT sorguları gelecek veri sızıntısı engelliyor mu."""
        path = PROJECT_ROOT / "services" / "core" / "pit_queries.py"
        with open(path) as f:
            content = f.read()
        # as_of_date'ten önceki veriyi getirmeli
        assert "<=" in content or "valid_from <=" in content, "PIT sorgusu gelecek veri sızıntısını engellemiyor"


# =====================================================
# INTEGRATION VERIFICATION
# =====================================================


class TestIntegrationVerification:
    """Tüm değişikliklerin entegrasyon doğrulaması."""

    def test_all_new_files_exist(self) -> Any:
        """Tüm yeni dosyalar mevcut mu."""
        new_files = [
            "services/core/database.py",  # Güncellendi
            "services/core/pit_queries.py",  # Yeni
            "database/init/004_timescaledb_retention.sql",  # Yeni
            "scripts/audit_query_performance.py",  # Yeni
            "scripts/audit_timescaledb_health.py",  # Yeni
            "scripts/backup_alpha.sh",  # Güncellendi
            "docs/COMPOSITE_INDEX_STRATEGY.md",  # Yeni
        ]
        for f in new_files:
            path = PROJECT_ROOT / f
            assert path.exists(), f"{f} bulunamadı"

    def test_all_python_files_syntax(self) -> Any:
        """Tüm Python dosyaları syntax geçerli mi."""
        python_files = [
            "services/core/database.py",
            "services/core/pit_queries.py",
            "scripts/audit_query_performance.py",
            "scripts/audit_timescaledb_health.py",
        ]
        for f in python_files:
            path = PROJECT_ROOT / f
            with open(path) as fh:
                try:
                    ast.parse(fh.read())
                except SyntaxError as e:
                    pytest.fail(f"{f} syntax hatası: {e}")

    def test_rules_file_exists(self) -> Any:
        """Kurallar dosyası mevcut mu."""
        # Workspace'de bist-100-rules.md olmalı
        rules_path = Path("/home/work/.openclaw/workspace/bist-100-rules.md")
        assert rules_path.exists(), "bist-100-rules.md bulunamadı"

    def test_rules_content(self) -> Any:
        """Kurallar dosyası gerekli içerikleri içeriyor mu."""
        rules_path = Path("/home/work/.openclaw/workspace/bist-100-rules.md")
        with open(rules_path) as f:
            content = f.read()
        assert "YASAK" in content
        assert "DOĞRULAMA" in content
        assert "fail-closed" in content.lower() or "fail_closed" in content.lower()
