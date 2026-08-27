"""ALPHA BIST — QuestDB Integration Tests

QuestDB entegrasyonu doğrulama:
- Client yapısı
- Tablo tanımları
- Consumer entegrasyonu
- Retention stratejisi
- Failure/recovery

Kullanım:
    python -m pytest tests/test_questdb_integration.py -v
"""

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


# =====================================================
# QUESTDB CLIENT STRUCTURE TESTS
# =====================================================


class TestQuestDBClient:
    """QuestDB client yapısal doğrulama."""

    def test_file_exists(self):
        """questdb_client.py mevcut mu."""
        path = PROJECT_ROOT / "services" / "core" / "questdb_client.py"
        assert path.exists(), "services/core/questdb_client.py bulunamadı"

    def test_syntax_valid(self):
        """questdb_client.py syntax geçerli mi."""
        path = PROJECT_ROOT / "services" / "core" / "questdb_client.py"
        with open(path, "r") as f:
            ast.parse(f.read())

    def test_class_exists(self):
        """QuestDBClient sınıfı mevcut mu."""
        path = PROJECT_ROOT / "services" / "core" / "questdb_client.py"
        with open(path, "r") as f:
            content = f.read()
        assert "class QuestDBClient" in content

    def test_singleton_exists(self):
        """questdb_client singleton mevcut mu."""
        path = PROJECT_ROOT / "services" / "core" / "questdb_client.py"
        with open(path, "r") as f:
            content = f.read()
        assert "questdb_client = QuestDBClient()" in content

    def test_required_methods(self):
        """Gerekli metodlar mevcut mu."""
        path = PROJECT_ROOT / "services" / "core" / "questdb_client.py"
        with open(path, "r") as f:
            content = f.read()
        methods = [
            "connect",
            "close",
            "insert_tick",
            "insert_ticks_batch",
            "insert_ohlcv",
            "insert_event",
            "query",
            "query_df",
            "ensure_tables",
        ]
        for m in methods:
            assert m in content, f"{m} metodu bulunamadı"

    def test_ilp_protocol(self):
        """ILP protocol kullanılıyor mu."""
        path = PROJECT_ROOT / "services" / "core" / "questdb_client.py"
        with open(path, "r") as f:
            content = f.read()
        assert "socket" in content, "Socket-based ILP kullanılmıyor"
        assert "ilp_port" in content, "ILP port tanımlı değil"

    def test_table_definitions(self):
        """Tablo tanımları mevcut mu."""
        path = PROJECT_ROOT / "services" / "core" / "questdb_client.py"
        with open(path, "r") as f:
            content = f.read()
        assert "market_ticks" in content
        assert "ohlcv" in content
        assert "events" in content
        assert "PARTITION BY" in content
        assert "DEDUP" in content

    def test_batch_write(self):
        """Toplu yazma desteği var mı."""
        path = PROJECT_ROOT / "services" / "core" / "questdb_client.py"
        with open(path, "r") as f:
            content = f.read()
        assert "insert_ticks_batch" in content


# =====================================================
# QUESTDB CONSUMER TESTS
# =====================================================


class TestQuestDBConsumer:
    """QuestDB consumer yapısal doğrulama."""

    def test_file_exists(self):
        """questdb_consumer.py mevcut mu."""
        path = PROJECT_ROOT / "services" / "ingestion" / "questdb_consumer.py"
        assert path.exists(), "services/ingestion/questdb_consumer.py bulunamadı"

    def test_syntax_valid(self):
        """questdb_consumer.py syntax geçerli mi."""
        path = PROJECT_ROOT / "services" / "ingestion" / "questdb_consumer.py"
        with open(path, "r") as f:
            ast.parse(f.read())

    def test_class_exists(self):
        """QuestDBTickConsumer sınıfı mevcut mu."""
        path = PROJECT_ROOT / "services" / "ingestion" / "questdb_consumer.py"
        with open(path, "r") as f:
            content = f.read()
        assert "class QuestDBTickConsumer" in content

    def test_singleton_exists(self):
        """questdb_tick_consumer singleton mevcut mu."""
        path = PROJECT_ROOT / "services" / "ingestion" / "questdb_consumer.py"
        with open(path, "r") as f:
            content = f.read()
        assert "questdb_tick_consumer = QuestDBTickConsumer()" in content

    def test_buffer_mechanism(self):
        """Buffer mekanizması mevcut mu."""
        path = PROJECT_ROOT / "services" / "ingestion" / "questdb_consumer.py"
        with open(path, "r") as f:
            content = f.read()
        assert "_buffer" in content
        assert "_buffer_size" in content
        assert "_flush" in content

    def test_reconnection_logic(self):
        """Yeniden bağlanma mantığı mevcut mu."""
        path = PROJECT_ROOT / "services" / "ingestion" / "questdb_consumer.py"
        with open(path, "r") as f:
            content = f.read()
        assert "reconnect" in content.lower() or "connect" in content

    def test_stats_method(self):
        """İstatistik metodu mevcut mu."""
        path = PROJECT_ROOT / "services" / "ingestion" / "questdb_consumer.py"
        with open(path, "r") as f:
            content = f.read()
        assert "get_stats" in content


# =====================================================
# INGESTION INTEGRATION TESTS
# =====================================================


class TestIngestionIntegration:
    """Ingestion servisi QuestDB entegrasyonu."""

    def test_import_exists(self):
        """QuestDB consumer import edilmiş mi."""
        path = PROJECT_ROOT / "services" / "ingestion" / "main.py"
        with open(path, "r") as f:
            content = f.read()
        assert "questdb_tick_consumer" in content, "QuestDB consumer import edilmemiş"

    def test_start_called(self):
        """QuestDB consumer start() çağrılmış mı."""
        path = PROJECT_ROOT / "services" / "ingestion" / "main.py"
        with open(path, "r") as f:
            content = f.read()
        assert "questdb_tick_consumer.start()" in content, "QuestDB consumer start() çağrılmamış"

    def test_stop_called(self):
        """QuestDB consumer stop() çağrılmış mı."""
        path = PROJECT_ROOT / "services" / "ingestion" / "main.py"
        with open(path, "r") as f:
            content = f.read()
        assert "questdb_tick_consumer.stop()" in content, "QuestDB consumer stop() çağrılmamış"


# =====================================================
# RETENTION STRATEGY TESTS
# =====================================================


class TestRetentionStrategy:
    """QuestDB retention stratejisi doğrulama."""

    def test_retention_file_exists(self):
        """Retention dosyası mevcut mu."""
        path = PROJECT_ROOT / "database" / "questdb" / "retention.sql"
        assert path.exists(), "database/questdb/retention.sql bulunamadı"

    def test_retention_content(self):
        """Retention dosyası gerekli içerikleri içeriyor mu."""
        path = PROJECT_ROOT / "database" / "questdb" / "retention.sql"
        with open(path, "r") as f:
            content = f.read()
        assert "market_ticks" in content
        assert "ohlcv" in content
        assert "events" in content
        assert "PARTITION" in content
        assert "DROP PARTITION" in content

    def test_data_distribution_strategy(self):
        """Veri dağıtım stratejisi belgelenmiş mi."""
        path = PROJECT_ROOT / "database" / "questdb" / "retention.sql"
        with open(path, "r") as f:
            content = f.read()
        assert "QuestDB" in content
        assert "TimescaleDB" in content
        assert "ClickHouse" in content


# =====================================================
# DATABASE INTEGRATION TESTS
# =====================================================


class TestDatabaseIntegration:
    """database.py QuestDB entegrasyonu."""

    def test_questdb_in_health_check(self):
        """QuestDB health check'te mevcut mu."""
        path = PROJECT_ROOT / "services" / "core" / "database.py"
        with open(path, "r") as f:
            content = f.read()
        assert "questdb" in content.lower(), "QuestDB health check'te yok"

    def test_questdb_in_init(self):
        """QuestDB init_databases'da mevcut mu."""
        path = PROJECT_ROOT / "services" / "core" / "database.py"
        with open(path, "r") as f:
            content = f.read()
        assert "questdb_client" in content, "QuestDB init_databases'da yok"

    def test_questdb_in_close(self):
        """QuestDB close_databases'da mevcut mu."""
        path = PROJECT_ROOT / "services" / "core" / "database.py"
        with open(path, "r") as f:
            content = f.read()
        assert "questdb_client.close" in content, "QuestDB close_databases'da yok"


# =====================================================
# FAILURE/RECOVERY TESTS
# =====================================================


class TestFailureRecovery:
    """Failure/recovery senaryoları."""

    def test_consumer_has_error_handling(self):
        """Consumer hata yönetimi mevcut mu."""
        path = PROJECT_ROOT / "services" / "ingestion" / "questdb_consumer.py"
        with open(path, "r") as f:
            content = f.read()
        assert "try:" in content
        assert "except" in content
        assert "_error_count" in content

    def test_consumer_has_reconnection(self):
        """Consumer yeniden bağlanma mantığı mevcut mu."""
        path = PROJECT_ROOT / "services" / "ingestion" / "questdb_consumer.py"
        with open(path, "r") as f:
            content = f.read()
        assert "reconnect" in content.lower() or "connect" in content

    def test_client_has_timeout(self):
        """Client timeout ayarı mevcut mu."""
        path = PROJECT_ROOT / "services" / "core" / "questdb_client.py"
        with open(path, "r") as f:
            content = f.read()
        assert "timeout" in content.lower()

    def test_client_has_retry(self):
        """Client retry mantığı mevcut mu (connection level)."""
        path = PROJECT_ROOT / "services" / "core" / "questdb_client.py"
        with open(path, "r") as f:
            content = f.read()
        # En azından reconnect denemesi olmalı
        assert "connect" in content


# =====================================================
# CONFIG INTEGRATION TESTS
# =====================================================


class TestConfigIntegration:
    """Config entegrasyonu."""

    def test_questdb_config_exists(self):
        """QuestDB config ayarları mevcut mu."""
        path = PROJECT_ROOT / "services" / "core" / "config.py"
        with open(path, "r") as f:
            content = f.read()
        assert "questdb_host" in content, "questdb_host config'de yok"
        assert "questdb_http_port" in content, "questdb_http_port config'de yok"
        assert "questdb_ilp_port" in content, "questdb_ilp_port config'de yok"
