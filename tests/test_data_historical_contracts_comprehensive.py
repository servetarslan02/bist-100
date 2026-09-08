"""ALPHA BIST — Tarihsel Veri Sözleşmeleri Kapsamlı Test Paketi.

services/data/historical_contracts.py modülünün tüm modelleri, soyut sınıfları,
InMemoryHistoricalRepository işlevleri, DuckDB WAL ve denetim kayıt fonksiyonlarını doğrular.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb
import orjson
import polars as pl

from services.data.historical_contracts import (
    DEFAULT_CHECKPOINT_SIZE,
    DEFAULT_MAX_IN_MEMORY_ITEMS,
    DEFAULT_WAL_SIZE,
    CatalystSnapshot,
    EventSnapshot,
    FundamentalSnapshot,
    InMemoryHistoricalRepository,
    clear_contract_audit_duckdb,
    configure_duckdb_wal,
    export_snapshot_to_duckdb,
    read_contract_audit_from_duckdb,
    to_orjson_bytes,
)


class TestHistoricalContractsBasics:
    """Modül sabitleri ve orjson / DuckDB yardımcıları testleri."""

    def test_constants_values(self) -> None:
        """Sabit değerlerin beklenen aralıklarda olduğunu doğrular."""
        assert DEFAULT_CHECKPOINT_SIZE == "4MB"
        assert DEFAULT_WAL_SIZE == "2MB"
        assert DEFAULT_MAX_IN_MEMORY_ITEMS == 500

    def test_to_orjson_bytes_with_primitive_and_dict(self) -> None:
        """to_orjson_bytes fonksiyonunun ilkel ve sözlük verileri doğru serileştirdiğini doğrular."""
        data = {"anahtar": "değer", "sayi": 42}
        res = to_orjson_bytes(data)
        assert isinstance(res, bytes)
        assert orjson.loads(res) == data

    def test_configure_duckdb_wal(self) -> None:
        """DuckDB bağlantısına PRAGMA ayarlarının başarıyla uygulandığını doğrular."""
        conn = duckdb.connect(":memory:")
        configure_duckdb_wal(conn)
        conn.close()


class TestDataContractModels:
    """FundamentalSnapshot, EventSnapshot ve CatalystSnapshot sözleşme modelleri testleri."""

    def test_fundamental_snapshot_creation_and_serialization(self) -> None:
        """FundamentalSnapshot oluşturma, sözlük ve orjson dönüşümlerini doğrular."""
        snap = FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-06-30",
            available_at="2025-08-15",
            values={"fk": 4.5, "pd_dd": 1.2, "net_kar": 15000000000},
            source="fintables",
            status="FRESH",
        )
        assert snap.ticker == "THYAO"
        assert snap.status == "FRESH"
        assert "THYAO" in repr(snap)

        as_dict = snap.to_dict()
        assert as_dict["type"] == "fundamental"
        assert as_dict["ticker"] == "THYAO"
        assert as_dict["values"]["fk"] == 4.5

        raw_bytes = snap.to_orjson_bytes()
        assert isinstance(raw_bytes, bytes)
        decoded = orjson.loads(raw_bytes)
        assert decoded["ticker"] == "THYAO"

    def test_event_snapshot_creation_and_serialization(self) -> None:
        """EventSnapshot oluşturma ve duygu/önem katsayısı doğrulaması."""
        event = EventSnapshot(
            event_id="EVT-001",
            ticker="GARAN",
            published_at="2025-08-10T14:30:00Z",
            event_type="KAP_ACIKLAMA",
            title="Bedelsiz Sermaye Artırımı",
            sentiment=0.75,
            importance=0.9,
            source="kap",
            content="Şirketimiz %100 bedelsiz kararı almıştır.",
        )
        assert event.event_id == "EVT-001"
        assert event.sentiment == 0.75
        assert "GARAN" in repr(event)

        as_dict = event.to_dict()
        assert as_dict["type"] == "event"
        assert as_dict["event_id"] == "EVT-001"
        assert as_dict["importance"] == 0.9

        raw_bytes = event.to_orjson_bytes()
        decoded = orjson.loads(raw_bytes)
        assert decoded["event_type"] == "KAP_ACIKLAMA"

    def test_catalyst_snapshot_creation_and_serialization(self) -> None:
        """CatalystSnapshot oluşturma ve duyuru/olay tarihleri doğrulaması."""
        cat = CatalystSnapshot(
            event_id="CAT-001",
            ticker="ASELS",
            announcement_date="2025-07-01",
            event_date="2025-07-20",
            catalyst_type="DIVIDEND",
            importance=0.8,
            source="kap",
        )
        assert cat.event_id == "CAT-001"
        assert cat.catalyst_type == "DIVIDEND"
        assert "ASELS" in repr(cat)

        as_dict = cat.to_dict()
        assert as_dict["type"] == "catalyst"
        assert as_dict["announcement_date"] == "2025-07-01"

        raw_bytes = cat.to_orjson_bytes()
        decoded = orjson.loads(raw_bytes)
        assert decoded["event_date"] == "2025-07-20"


class TestInMemoryHistoricalRepository:
    """InMemoryHistoricalRepository sınıfının işlevsel testleri."""

    def test_repo_initialization_and_repr(self) -> None:
        """Depo başlatma ve durum metotlarını doğrular."""
        repo = InMemoryHistoricalRepository(max_items=50)
        assert "InMemoryHistoricalRepository" in repr(repo)

        status_dict = repo.to_dict()
        assert status_dict["max_items"] == 50
        assert status_dict["fundamental_count"] == 0

        raw_bytes = repo.to_orjson_bytes()
        assert isinstance(raw_bytes, bytes)

    def test_fundamental_snapshot_filtering_and_sorting(self) -> None:
        """Point-In-Time (available_at <= as_of_date) kuralı ve sembol temizliği doğrulaması."""
        repo = InMemoryHistoricalRepository()

        # 3 farklı çeyrek snapshot'ı ekle
        repo.add_fundamental_snapshot(
            FundamentalSnapshot(
                ticker="THYAO.IS",
                period_end="2024-12-31",
                available_at="2025-03-10",
                values={"net_kar": 100},
            )
        )
        repo.add_fundamental_snapshot(
            FundamentalSnapshot(
                ticker="THYAO",
                period_end="2025-03-31",
                available_at="2025-05-15",
                values={"net_kar": 150},
            )
        )
        repo.add_fundamental_snapshot(
            FundamentalSnapshot(
                ticker="THYAO",
                period_end="2025-06-30",
                available_at="2025-08-20",
                values={"net_kar": 200},
            )
        )

        # 2025-06-01 anında sorgulama (son çeyrek henüz açıklanmamış olmalı!)
        res = repo.get_fundamental_snapshots("THYAO", "2025-06-01")
        assert len(res) == 2
        # Azalan tarih sıralı olmalı (en güncel açıklanan en başta)
        assert res[0].available_at == "2025-05-15"
        assert res[1].available_at == "2025-03-10"

        # Tümünü içeren bir tarihte sorgulama
        res_all = repo.get_fundamental_snapshots("thyao.is", "2025-09-01")
        assert len(res_all) == 3
        assert res_all[0].available_at == "2025-08-20"

    def test_event_snapshot_filtering_and_types(self) -> None:
        """Olay snapshot'larının tip ve tarih filtrelerini test eder."""
        repo = InMemoryHistoricalRepository()

        repo.add_event_snapshot(
            EventSnapshot(
                event_id="E1",
                ticker="EREGL",
                published_at="2025-04-10T10:00:00",
                event_type="KAP_ACIKLAMA",
                sentiment=0.4,
            )
        )
        repo.add_event_snapshot(
            EventSnapshot(
                event_id="E2",
                ticker="EREGL",
                published_at="2025-05-12T11:00:00",
                event_type="HABER",
                sentiment=-0.2,
            )
        )

        # Tarih ve tip filtresi
        events = repo.get_event_snapshots("EREGL", "2025-05-01")
        assert len(events) == 1
        assert events[0].event_id == "E1"

        events_type = repo.get_event_snapshots("EREGL", "2025-06-01", event_types=["HABER"])
        assert len(events_type) == 1
        assert events_type[0].event_id == "E2"

    def test_catalyst_snapshot_filtering(self) -> None:
        """Katalist snapshot'larının duyuru tarihine göre filtrelendiğini test eder."""
        repo = InMemoryHistoricalRepository()

        repo.add_catalyst_snapshot(
            CatalystSnapshot(
                event_id="C1",
                ticker="TUPRS",
                announcement_date="2025-03-01",
                event_date="2025-04-01",
                catalyst_type="TEMETTU",
            )
        )
        repo.add_catalyst_snapshot(
            CatalystSnapshot(
                event_id="C2",
                ticker="TUPRS",
                announcement_date="2025-06-01",
                event_date="2025-07-01",
                catalyst_type="GENEL_KURUL",
            )
        )

        res = repo.get_catalyst_snapshots("TUPRS", "2025-05-01")
        assert len(res) == 1
        assert res[0].event_id == "C1"

    def test_max_items_limit_and_clear(self) -> None:
        """Maksimum eleman kısıtlaması ve clear metodunu doğrular."""
        repo = InMemoryHistoricalRepository(max_items=10)
        for i in range(15):
            repo.add_fundamental_snapshot(
                FundamentalSnapshot(
                    ticker="KCHOL",
                    period_end=f"2024-0{i+1}-01",
                    available_at=f"2024-0{i+1}-15",
                    values={},
                )
            )
        status = repo.to_dict()
        assert status["fundamental_count"] == 10

        repo.clear()
        assert repo.to_dict()["fundamental_count"] == 0


class TestDuckDBAuditFunctions:
    """export_snapshot_to_duckdb, read_contract_audit_from_duckdb ve clear fonksiyonları."""

    def test_export_and_read_audit_flow(self) -> None:
        """Snapshot'ın DuckDB denetim tablosuna yazılması ve Polars DataFrame olarak okunması."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = str(Path(tmpdir) / "test_audit.duckdb")

            snap = FundamentalSnapshot(
                ticker="SISE",
                period_end="2025-03-31",
                available_at="2025-05-10",
                values={"fk": 6.8},
            )

            # Yazma
            res = export_snapshot_to_duckdb(snap, db_path=test_db)
            assert res == 1

            # Okuma (Polars DataFrame)
            df = read_contract_audit_from_duckdb(db_path=test_db, limit=10)
            assert isinstance(df, pl.DataFrame)
            assert df.height == 1
            assert "ticker" in df.columns
            assert df["ticker"][0] == "SISE"
            assert df["snapshot_type"][0] == "fundamental"

            # Temizleme
            clear_contract_audit_duckdb(db_path=test_db)
            df_after = read_contract_audit_from_duckdb(db_path=test_db)
            assert df_after.height == 0
