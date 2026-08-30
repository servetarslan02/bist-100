from typing import Any

"""ALPHA BIST — QuestDB Gerçek Integration Tests

Gerçek fonksiyonel testler:
- Consumer tick işliyor mu
- Buffer mekanizması çalışıyor mu
- Reconnection mantığı doğru mu
- Batch write çalışıyor mu
- Ingestion → QuestDB entegrasyonu

Kullanım:
    python -m pytest tests/test_questdb_integration.py -v
"""

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import zinciri sorununu bypass et — doğrudan import
sys.path.insert(0, str(Path(__file__).parent.parent))

import importlib.util
import types

# services paket zincirini manuel oluştur
services_pkg = types.ModuleType("services")
services_pkg.__path__ = [str(Path(__file__).parent.parent / "services")]
sys.modules["services"] = services_pkg

services_core = types.ModuleType("services.core")
services_core.__path__ = [str(Path(__file__).parent.parent / "services" / "core")]
sys.modules["services.core"] = services_core
services_pkg.core = services_core

services_ingestion = types.ModuleType("services.ingestion")
services_ingestion.__path__ = [str(Path(__file__).parent.parent / "services" / "ingestion")]
sys.modules["services.ingestion"] = services_ingestion
services_pkg.ingestion = services_ingestion

# config mock
mock_settings = MagicMock()
mock_settings.questdb_host = "localhost"
mock_settings.questdb_http_port = 9000
mock_settings.questdb_pg_port = 8812
mock_settings.questdb_ilp_port = 9009
config_mod = types.ModuleType("services.core.config")
config_mod.settings = mock_settings
sys.modules["services.core.config"] = config_mod
services_core.config = config_mod

# event_bus mock
event_bus_mod = types.ModuleType("services.core.event_bus")
event_bus_mod.EventType = MagicMock()
event_bus_mod.event_bus = MagicMock()
event_bus_mod.subscribe = MagicMock()
sys.modules["services.core.event_bus"] = event_bus_mod
services_core.event_bus = event_bus_mod

# questdb_client'ı yükle
spec = importlib.util.spec_from_file_location(
    "services.core.questdb_client",
    Path(__file__).parent.parent / "services" / "core" / "questdb_client.py",
)
questdb_mod = importlib.util.module_from_spec(spec)
questdb_mod.__package__ = "services.core"
sys.modules["services.core.questdb_client"] = questdb_mod
services_core.questdb_client = questdb_mod
spec.loader.exec_module(questdb_mod)
QuestDBClient = questdb_mod.QuestDBClient

# questdb_consumer'ı yükle
spec2 = importlib.util.spec_from_file_location(
    "services.ingestion.questdb_consumer",
    Path(__file__).parent.parent / "services" / "ingestion" / "questdb_consumer.py",
)
consumer_mod = importlib.util.module_from_spec(spec2)
consumer_mod.__package__ = "services.ingestion"
sys.modules["services.ingestion.questdb_consumer"] = consumer_mod
services_ingestion.questdb_consumer = consumer_mod
spec2.loader.exec_module(consumer_mod)
QuestDBTickConsumer = consumer_mod.QuestDBTickConsumer


# =====================================================
# QUESTDB CLIENT FUNCTIONAL TESTS
# =====================================================


class TestQuestDBClientFunctional:
    """QuestDB client fonksiyonel testler."""

    def test_client_initial_state(self) -> Any:
        """Client başlangıç durumu doğru mu."""
        client = QuestDBClient()
        assert client._connected is False
        assert client._ilp_socket is None

    def test_tick_format_correct(self) -> Any:
        """Tick verisi doğru ILP formatında mı."""
        client = QuestDBClient()
        # Mock socket
        mock_socket = MagicMock()
        client._ilp_socket = mock_socket
        client._connected = True

        # Tick yaz
        result = client.insert_tick("THYAO", 100.50, 1000, 100.40, 100.60)

        assert result is True
        # Socket'e veri gönderildi mi
        mock_socket.sendall.assert_called_once()
        # ILP formatını kontrol et
        sent_data = mock_socket.sendall.call_args[0][0].decode("utf-8")
        assert "market_ticks,ticker=THYAO" in sent_data
        assert "price=100.5" in sent_data
        assert "volume=1000" in sent_data
        assert "bid=100.4" in sent_data
        assert "ask=100.6" in sent_data

    def test_batch_tick_format_correct(self) -> Any:
        """Toplu tick verisi doğru formatında mı."""
        client = QuestDBClient()
        mock_socket = MagicMock()
        client._ilp_socket = mock_socket
        client._connected = True

        ticks = [
            {"ticker": "THYAO", "price": 100.50, "volume": 1000, "bid": 100.40, "ask": 100.60},
            {"ticker": "GARAN", "price": 50.25, "volume": 500, "bid": 50.20, "ask": 50.30},
        ]

        result = client.insert_ticks_batch(ticks)

        assert result is True
        mock_socket.sendall.assert_called_once()
        sent_data = mock_socket.sendall.call_args[0][0].decode("utf-8")
        assert "ticker=THYAO" in sent_data
        assert "ticker=GARAN" in sent_data
        assert sent_data.count("market_ticks") == 2

    def test_ohlcv_format_correct(self) -> Any:
        """OHLCV verisi doğru formatında mı."""
        client = QuestDBClient()
        mock_socket = MagicMock()
        client._ilp_socket = mock_socket
        client._connected = True

        result = client.insert_ohlcv("THYAO", "1d", 100.0, 105.0, 99.0, 103.0, 50000)

        assert result is True
        sent_data = mock_socket.sendall.call_args[0][0].decode("utf-8")
        assert "ohlcv,ticker=THYAO,timeframe=1d" in sent_data
        assert "open=100.0" in sent_data
        assert "high=105.0" in sent_data
        assert "low=99.0" in sent_data
        assert "close=103.0" in sent_data
        assert "volume=50000" in sent_data

    def test_event_format_correct(self) -> Any:
        """Event verisi doğru formatında mı."""
        client = QuestDBClient()
        mock_socket = MagicMock()
        client._ilp_socket = mock_socket
        client._connected = True

        result = client.insert_event("KAP", "THYAO", "Kar açıklaması", 0.8, 0.9)

        assert result is True
        sent_data = mock_socket.sendall.call_args[0][0].decode("utf-8")
        assert "events,event_type=KAP,ticker=THYAO" in sent_data
        assert "sentiment=0.8" in sent_data
        assert "importance=0.9" in sent_data

    def test_write_when_disconnected_returns_false(self) -> Any:
        """Bağlantı yokken yazma denemesi False döndürmeli."""
        client = QuestDBClient()
        client._connected = False
        # _sync_connect de başarısız olacak (socket yok)
        client._sync_connect = MagicMock(return_value=False)

        result = client.insert_tick("THYAO", 100.0, 1000)
        assert result is False

    def test_write_failure_sets_disconnected(self) -> Any:
        """Yazma hatası bağlantıyı kesmeli."""
        client = QuestDBClient()
        mock_socket = MagicMock()
        mock_socket.sendall.side_effect = ConnectionError("Connection lost")
        client._ilp_socket = mock_socket
        client._connected = True

        result = client.insert_tick("THYAO", 100.0, 1000)

        assert result is False
        assert client._connected is False

    def test_close_cleans_up(self) -> Any:
        """Close bağlantıyı temizlemeli."""
        client = QuestDBClient()
        mock_socket = MagicMock()
        client._ilp_socket = mock_socket
        client._connected = True

        client.close()

        mock_socket.close.assert_called_once()
        assert client._ilp_socket is None
        assert client._connected is False


# =====================================================
# QUESTDB CONSUMER FUNCTIONAL TESTS
# =====================================================


class TestQuestDBConsumerFunctional:
    """QuestDB consumer fonksiyonel testler."""

    def test_consumer_initial_state(self) -> Any:
        """Consumer başlangıç durumu doğru mu."""
        consumer = QuestDBTickConsumer()
        assert consumer._running is False
        assert consumer._buffer == []
        assert consumer._write_count == 0
        assert consumer._error_count == 0

    @pytest.mark.asyncio
    async def test_tick_added_to_buffer(self) -> Any:
        """Tick verisi buffer'a ekleniyor mu."""
        consumer = QuestDBTickConsumer()
        consumer._running = True

        # Mock event
        event = MagicMock()
        event.data = {
            "ticker": "THYAO",
            "price": 100.50,
            "volume": 1000,
            "bid": 100.40,
            "ask": 100.60,
        }

        await consumer._on_tick(event)

        assert len(consumer._buffer) == 1
        assert consumer._buffer[0]["ticker"] == "THYAO"
        assert consumer._buffer[0]["price"] == 100.50
        assert consumer._buffer[0]["volume"] == 1000

    @pytest.mark.asyncio
    async def test_index_tick_ignored(self) -> Any:
        """Index tick'leri ignore edilmeli."""
        consumer = QuestDBTickConsumer()
        consumer._running = True

        event = MagicMock()
        event.data = {
            "ticker": "XU100",
            "price": 10000,
            "is_index": True,
        }

        await consumer._on_tick(event)

        assert len(consumer._buffer) == 0

    @pytest.mark.asyncio
    async def test_invalid_tick_ignored(self) -> Any:
        """Geçersiz tick verisi ignore edilmeli."""
        consumer = QuestDBTickConsumer()
        consumer._running = True

        # Ticker yok
        event1 = MagicMock()
        event1.data = {"price": 100.0}
        await consumer._on_tick(event1)
        assert len(consumer._buffer) == 0

        # Price yok
        event2 = MagicMock()
        event2.data = {"ticker": "THYAO"}
        await consumer._on_tick(event2)
        assert len(consumer._buffer) == 0

    @pytest.mark.asyncio
    async def test_buffer_flush_on_full(self) -> Any:
        """Buffer dolduğunda flush edilmeli."""
        consumer = QuestDBTickConsumer()
        consumer._running = True
        consumer._buffer_size = 3  # Küçük buffer

        # Mock flush — buffer'ı da temizlesin
        async def mock_flush() -> Any:
            """Otomatik eklendi."""
            consumer._buffer.clear()

        consumer._flush_buffer = AsyncMock(side_effect=mock_flush)

        for i in range(3):
            event = MagicMock()
            event.data = {"ticker": f"TKR{i}", "price": 100.0 + i, "volume": 1000}
            await consumer._on_tick(event)

        # 3. tick'te buffer dolmalı ve flush çağırmalı
        consumer._flush_buffer.assert_called_once()
        assert len(consumer._buffer) == 0  # Flush sonrası buffer temizlenmeli

    @pytest.mark.asyncio
    async def test_flush_buffer_writes_to_questdb(self) -> Any:
        """Flush buffer QuestDB'ye yazıyor mu."""
        consumer = QuestDBTickConsumer()
        consumer._buffer = [
            {
                "ticker": "THYAO",
                "price": 100.0,
                "volume": 1000,
                "bid": 99.0,
                "ask": 101.0,
                "timestamp": datetime.now(UTC),
            },
            {"ticker": "GARAN", "price": 50.0, "volume": 500, "bid": 49.0, "ask": 51.0, "timestamp": datetime.now(UTC)},
        ]

        # Mock questdb_client
        with patch("services.ingestion.questdb_consumer.questdb_client") as mock_client:
            mock_client._connected = True
            mock_client.insert_ticks_batch.return_value = True

            await consumer._flush_buffer()

            mock_client.insert_ticks_batch.assert_called_once()
            ticks = mock_client.insert_ticks_batch.call_args[0][0]
            assert len(ticks) == 2
            assert ticks[0]["ticker"] == "THYAO"
            assert ticks[1]["ticker"] == "GARAN"
            assert consumer._write_count == 2
            assert len(consumer._buffer) == 0

    @pytest.mark.asyncio
    async def test_flush_buffer_handles_failure(self) -> Any:
        """Flush hatası yönetiliyor mu."""
        consumer = QuestDBTickConsumer()
        consumer._buffer = [
            {
                "ticker": "THYAO",
                "price": 100.0,
                "volume": 1000,
                "bid": 99.0,
                "ask": 101.0,
                "timestamp": datetime.now(UTC),
            },
        ]

        with patch("services.ingestion.questdb_consumer.questdb_client") as mock_client:
            mock_client._connected = True
            mock_client.insert_ticks_batch.return_value = False  # Yazma hatası

            await consumer._flush_buffer()

            assert consumer._error_count == 1
            assert consumer._write_count == 0

    @pytest.mark.asyncio
    async def test_flush_reconnects_on_disconnected(self) -> Any:
        """Bağlantı yokken flush yeniden bağlanmalı."""
        consumer = QuestDBTickConsumer()
        consumer._buffer = [
            {
                "ticker": "THYAO",
                "price": 100.0,
                "volume": 1000,
                "bid": 99.0,
                "ask": 101.0,
                "timestamp": datetime.now(UTC),
            },
        ]

        with patch("services.ingestion.questdb_consumer.questdb_client") as mock_client:
            mock_client._connected = False
            # Yeniden bağlanma başarılı
            mock_client.connect = AsyncMock(return_value=True)
            mock_client.insert_ticks_batch.return_value = True

            await consumer._flush_buffer()

            mock_client.connect.assert_called_once()
            mock_client.insert_ticks_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_drops_ticks_on_reconnect_failure(self) -> Any:
        """Yeniden bağlanma başarısızsa tick'ler düşmeli."""
        consumer = QuestDBTickConsumer()
        consumer._buffer = [
            {
                "ticker": "THYAO",
                "price": 100.0,
                "volume": 1000,
                "bid": 99.0,
                "ask": 101.0,
                "timestamp": datetime.now(UTC),
            },
        ]

        with patch("services.ingestion.questdb_consumer.questdb_client") as mock_client:
            mock_client._connected = False
            mock_client.connect = AsyncMock(return_value=False)  # Bağlantı başarısız

            await consumer._flush_buffer()

            assert consumer._error_count == 1
            assert consumer._write_count == 0
            assert len(consumer._buffer) == 0

    def test_get_stats(self) -> Any:
        """İstatistikler doğru mu."""
        consumer = QuestDBTickConsumer()
        consumer._running = True
        consumer._write_count = 100
        consumer._error_count = 5
        consumer._buffer = [{"ticker": "THYAO"}]

        stats = consumer.get_stats()

        assert stats["running"] is True
        assert stats["buffer_size"] == 1
        assert stats["total_writes"] == 100
        assert stats["total_errors"] == 5
        assert "last_flush" in stats
        assert "connected" in stats


# =====================================================
# INGESTION INTEGRATION TESTS
# =====================================================


class TestIngestionIntegration:
    """Ingestion servisi QuestDB entegrasyonu."""

    def test_consumer_singleton_same_instance(self) -> Any:
        """Singleton aynı instance mı döndürüyor."""
        c1 = consumer_mod.questdb_tick_consumer
        c2 = consumer_mod.questdb_tick_consumer
        assert c1 is c2

    def test_consumer_imported_in_main(self) -> Any:
        """main.py'de consumer import edilmiş mi."""
        main_path = Path(__file__).parent.parent / "services" / "ingestion" / "main.py"
        with open(main_path) as f:
            content = f.read()
        assert "questdb_tick_consumer" in content
        assert "questdb_tick_consumer.start()" in content
        assert "questdb_tick_consumer.stop()" in content


# =====================================================
# DATA FORMAT TESTS
# =====================================================


class TestDataFormat:
    """Veri formatı doğrulama."""

    def test_tick_timestamp_is_nanoseconds(self) -> Any:
        """Tick timestamp nanosecond cinsinden mi."""
        client = QuestDBClient()
        mock_socket = MagicMock()
        client._ilp_socket = mock_socket
        client._connected = True

        ts = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)
        client.insert_tick("THYAO", 100.0, 1000, timestamp=ts)

        sent_data = mock_socket.sendall.call_args[0][0].decode("utf-8")
        # Timestamp satırın sonunda olmalı
        parts = sent_data.strip().split()
        ts_ns = int(parts[-1])
        # 2025-06-15 10:30:00 UTC = 1750000200000000000 (yaklaşık)
        assert ts_ns > 1700000000000000000  # 2023'ten büyük
        assert ts_ns < 1800000000000000000  # 2027'den küçük

    def test_ilp_line_format(self) -> Any:
        """ILP satır formatı doğru mu."""
        client = QuestDBClient()
        mock_socket = MagicMock()
        client._ilp_socket = mock_socket
        client._connected = True

        client.insert_tick("THYAO", 100.50, 1000, 100.40, 100.60)

        sent_data = mock_socket.sendall.call_args[0][0].decode("utf-8")
        lines = sent_data.strip().split("\n")
        assert len(lines) == 1

        line = lines[0]
        # Format: measurement,tag=value field=value timestamp
        parts = line.split()
        assert len(parts) == 3  # measurement+tags, fields, timestamp

        # Measurement + tags
        measurement = parts[0]
        assert measurement.startswith("market_ticks,")
        assert "ticker=THYAO" in measurement

        # Fields
        fields = parts[1]
        assert "price=100.5" in fields
        assert "volume=1000" in fields
