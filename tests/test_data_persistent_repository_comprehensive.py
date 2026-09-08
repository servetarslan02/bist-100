"""ALPHA BIST — Kalıcı Tarihsel Veri Deposu Kapsamlı Test Paketi.

services/data/persistent_repository.py modülünün DuckDB bağlantı yönetimi,
temel analiz, olay ve katalist snapshot saklama/sorgulama (PIT ve deduplication),
istatistikler, Polars DataFrame sorgulama ve temizleme işlevlerini test eder.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb
import orjson
import polars as pl
import pytest

from services.data.historical_contracts import (
    CatalystSnapshot,
    EventSnapshot,
    FundamentalSnapshot,
)
from services.data.persistent_repository import (
    DEFAULT_CHECKPOINT_SIZE,
    DEFAULT_WAL_SIZE,
    PersistentHistoricalRepository,
    clear_persistent_repository_duckdb,
    configure_duckdb_wal,
    read_persistent_catalysts_from_duckdb,
    read_persistent_events_from_duckdb,
    read_persistent_fundamentals_from_duckdb,
    to_orjson_bytes,
)


class TestPersistentRepositoryBasics:
    """Sabitler ve serileştirme testleri."""

    def test_constants_and_wal(self) -> None:
        """Sabitler ve WAL yapılandırma fonksiyonu testi."""
        assert DEFAULT_CHECKPOINT_SIZE == "4MB"
        assert DEFAULT_WAL_SIZE == "2MB"

        conn = duckdb.connect(":memory:")
        configure_duckdb_wal(conn)
        conn.close()

    def test_to_orjson_bytes_helper(self) -> None:
        """to_orjson_bytes serileştirme doğrulaması."""
        payload = {"durum": "aktif", "kayitlar": [1, 2, 3]}
        raw = to_orjson_bytes(payload)
        assert isinstance(raw, bytes)
        assert orjson.loads(raw) == payload


class TestPersistentHistoricalRepositoryOperations:
    """PersistentHistoricalRepository CRUD ve PIT uyumlu sorgulama testleri."""

    @pytest.fixture
    def repo_fixture(self):
        """Geçici test veri tabanı ile repository fixture'ı."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = str(Path(tmpdir) / "test_repo.duckdb")
            repo = PersistentHistoricalRepository(db_path=test_db)
            yield repo, test_db

    def test_repo_init_and_repr(self, repo_fixture) -> None:
        """Repo başlatma, __repr__, to_dict ve to_orjson_bytes testleri."""
        repo, db_path = repo_fixture
        assert "PersistentHistoricalRepository" in repr(repo)

        as_dict = repo.to_dict()
        assert as_dict["db_path"] == db_path
        assert as_dict["is_connected"] is True

        raw_bytes = repo.to_orjson_bytes()
        assert isinstance(raw_bytes, bytes)

    def test_fundamental_snapshot_crud_and_pit(self, repo_fixture) -> None:
        """Temel analiz snapshot'ı ekleme, deduplication (upsert) ve PIT sorgulama testi."""
        repo, _ = repo_fixture

        snap1 = FundamentalSnapshot(
            ticker="THYAO",
            period_end="2024-12-31",
            available_at="2025-03-01",
            values={"fk": 4.2, "net_kar": 12000000000},
            source="fintables",
        )
        snap2 = FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-03-31",
            available_at="2025-05-10",
            values={"fk": 4.5, "net_kar": 15000000000},
            source="fintables",
        )

        assert repo.add_fundamental_snapshot(snap1) is True
        assert repo.add_fundamental_snapshot(snap2) is True

        # Upsert testi (aynı periyot ve available_at ile güncelleme)
        snap2_updated = FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-03-31",
            available_at="2025-05-10",
            values={"fk": 4.6, "net_kar": 15500000000},
            source="fintables_revize",
        )
        assert repo.add_fundamental_snapshot(snap2_updated) is True

        # PIT Filtreleme: 2025-04-01 tarihinde yalnızca ilk çeyrek biliniyor olmalı
        pit_snapshots = repo.get_fundamental_snapshots("THYAO.IS", "2025-04-01")
        assert len(pit_snapshots) == 1
        assert pit_snapshots[0].period_end == "2024-12-31"

        # 2025-06-01 tarihinde güncel revize değer okunabilmeli
        all_snapshots = repo.get_fundamental_snapshots("thyao", "2025-06-01")
        assert len(all_snapshots) == 2
        assert all_snapshots[0].period_end == "2025-03-31"
        assert all_snapshots[0].values["fk"] == 4.6
        assert all_snapshots[0].source == "fintables_revize"

    def test_event_snapshot_crud_and_deduplication(self, repo_fixture) -> None:
        """Olay snapshot'ı ekleme, event_id bazında tekilleştirme ve filtreleme testi."""
        repo, _ = repo_fixture

        ev1 = EventSnapshot(
            event_id="EVT-101",
            ticker="GARAN",
            published_at="2025-02-15T10:00:00",
            event_type="KAP_BILDIRIM",
            title="Genel Kurul Kararı",
            sentiment=0.3,
            importance=0.7,
        )
        ev2 = EventSnapshot(
            event_id="EVT-102",
            ticker="GARAN",
            published_at="2025-03-20T14:00:00",
            event_type="FINANSAL_HABER",
            title="Kredi Notu Artışı",
            sentiment=0.8,
            importance=0.9,
        )

        assert repo.add_event_snapshot(ev1) is True
        assert repo.add_event_snapshot(ev2) is True

        # Aynı event_id tekrar eklendiğinde DO NOTHING işletilmeli ve başarılı dönmeli
        assert repo.add_event_snapshot(ev1) is True

        # PIT Filtreleme
        events_before = repo.get_event_snapshots("GARAN", "2025-03-01")
        assert len(events_before) == 1
        assert events_before[0].event_id == "EVT-101"

        # Tip filtreleme
        haber_events = repo.get_event_snapshots("GARAN", "2025-04-01", event_types=["FINANSAL_HABER"])
        assert len(haber_events) == 1
        assert haber_events[0].event_id == "EVT-102"

    def test_catalyst_snapshot_crud(self, repo_fixture) -> None:
        """Katalist snapshot'ı ekleme ve duyuru tarihine göre sorgulama testi."""
        repo, _ = repo_fixture

        cat1 = CatalystSnapshot(
            event_id="CAT-201",
            ticker="ASELS",
            announcement_date="2025-01-10",
            event_date="2025-02-01",
            catalyst_type="SOZLESME",
            importance=0.85,
        )
        assert repo.add_catalyst_snapshot(cat1) is True

        cats = repo.get_catalyst_snapshots("ASELS", "2025-02-01")
        assert len(cats) == 1
        assert cats[0].event_id == "CAT-201"
        assert cats[0].catalyst_type == "SOZLESME"

    def test_get_stats_and_clear(self, repo_fixture) -> None:
        """Depo istatistikleri ve clear metodunun tüm verileri temizlediğini doğrular."""
        repo, _ = repo_fixture

        repo.add_fundamental_snapshot(
            FundamentalSnapshot(
                ticker="BIMAS",
                period_end="2024-12-31",
                available_at="2025-03-01",
                values={},
            )
        )
        repo.add_event_snapshot(
            EventSnapshot(
                event_id="EVT-301",
                ticker="BIMAS",
                published_at="2025-03-05",
                event_type="KAP",
            )
        )
        repo.add_catalyst_snapshot(
            CatalystSnapshot(
                event_id="CAT-301",
                ticker="BIMAS",
                announcement_date="2025-03-06",
                event_date="2025-03-20",
                catalyst_type="TEMETTU",
            )
        )

        stats = repo.get_stats()
        assert stats["fundamental_snapshots"] == 1
        assert stats["event_snapshots"] == 1
        assert stats["catalyst_snapshots"] == 1

        repo.clear()
        stats_cleared = repo.get_stats()
        assert stats_cleared["fundamental_snapshots"] == 0
        assert stats_cleared["event_snapshots"] == 0
        assert stats_cleared["catalyst_snapshots"] == 0


class TestPersistentRepositoryPolarsReaders:
    """read_persistent_*_from_duckdb yardımcılarının Polars dönüşümü testleri."""

    def test_read_helpers_and_clear_standalone(self) -> None:
        """read_persistent_* ve clear_persistent_repository_duckdb testleri."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = str(Path(tmpdir) / "test_polars.duckdb")
            repo = PersistentHistoricalRepository(db_path=test_db)

            repo.add_fundamental_snapshot(
                FundamentalSnapshot(
                    ticker="KCHOL",
                    period_end="2024-12-31",
                    available_at="2025-03-01",
                    values={"fk": 5.0},
                )
            )
            repo.add_event_snapshot(
                EventSnapshot(
                    event_id="EVT-401",
                    ticker="KCHOL",
                    published_at="2025-03-02",
                    event_type="KAP",
                )
            )
            repo.add_catalyst_snapshot(
                CatalystSnapshot(
                    event_id="CAT-401",
                    ticker="KCHOL",
                    announcement_date="2025-03-03",
                    event_date="2025-03-25",
                    catalyst_type="GENEL_KURUL",
                )
            )

            # Polars Okuyucuları Testi
            df_funds = read_persistent_fundamentals_from_duckdb(db_path=test_db, ticker="KCHOL")
            assert isinstance(df_funds, pl.DataFrame)
            assert df_funds.height == 1
            assert df_funds["ticker"][0] == "KCHOL"

            df_events = read_persistent_events_from_duckdb(db_path=test_db, ticker="KCHOL")
            assert isinstance(df_events, pl.DataFrame)
            assert df_events.height == 1

            df_cats = read_persistent_catalysts_from_duckdb(db_path=test_db, ticker="KCHOL")
            assert isinstance(df_cats, pl.DataFrame)
            assert df_cats.height == 1

            # Harici temizleme
            clear_persistent_repository_duckdb(db_path=test_db)
            df_empty = read_persistent_fundamentals_from_duckdb(db_path=test_db)
            assert df_empty.height == 0
