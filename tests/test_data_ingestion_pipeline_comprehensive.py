"""ALPHA BIST — Tarihsel Veri Alım Hattı (Ingestion Pipeline) Kapsamlı Test Paketi.

services/data/ingestion_pipeline.py modülünün temel analiz alımı (ingest_fundamentals),
KAP bildirimleri ve haber entegrasyonu, olaylardan katalist türetme (derive_catalysts_from_events),
Polars özet dönüşümleri ve DuckDB alım denetim izi işlevlerini test eder.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import duckdb
import orjson
import polars as pl
import pytest

from services.data.historical_contracts import (
    EventSnapshot,
    FundamentalSnapshot,
    InMemoryHistoricalRepository,
)
from services.data.historical_fundamental_provider import HistoricalFundamentalProvider
from services.data.ingestion_pipeline import (
    DEFAULT_CHECKPOINT_SIZE,
    DEFAULT_DAYS_BACK,
    DEFAULT_MAX_PERIODS,
    DEFAULT_MIN_HOURS_INTERVAL,
    DEFAULT_WAL_SIZE,
    HistoricalIngestionPipeline,
    clear_ingestion_audit_duckdb,
    configure_duckdb_wal,
    export_ingestion_run_to_duckdb,
    export_ingestion_summary_to_polars,
    read_ingestion_audit_from_duckdb,
    to_orjson_bytes,
)


class TestIngestionPipelineBasics:
    """Sabitler, serileştirme ve Polars özet testleri."""

    def test_constants(self) -> None:
        """Sabitlerin beklenen değerlerini kontrol eder."""
        assert DEFAULT_CHECKPOINT_SIZE == "4MB"
        assert DEFAULT_WAL_SIZE == "2MB"
        assert DEFAULT_DAYS_BACK == 365
        assert DEFAULT_MAX_PERIODS == 8
        assert DEFAULT_MIN_HOURS_INTERVAL == 1.0

    def test_configure_duckdb_wal(self) -> None:
        """DuckDB bağlantısında WAL optimizasyonunu doğrular."""
        conn = duckdb.connect(":memory:")
        configure_duckdb_wal(conn)
        conn.close()

    def test_to_orjson_bytes_helper(self) -> None:
        """to_orjson_bytes serileştirme yardımcısını test eder."""
        payload = {"islem": "alim", "durum": "tamam"}
        raw = to_orjson_bytes(payload)
        assert isinstance(raw, bytes)
        assert orjson.loads(raw) == payload

    def test_export_ingestion_summary_to_polars(self) -> None:
        """Alım özetinin Polars DataFrame formatına dönüştürülmesi testi."""
        results = {"THYAO": 4, "GARAN": 3, "EREGL": "hata_olustu"}
        df = export_ingestion_summary_to_polars(results, stage="fundamental")

        assert isinstance(df, pl.DataFrame)
        assert df.height == 3
        assert "ticker" in df.columns
        assert "status" in df.columns
        assert df.filter(pl.col("ticker") == "THYAO")["count"][0] == 4
        assert df.filter(pl.col("ticker") == "EREGL")["status"][0] == "hata_olustu"

        # Boş sözlük testi
        df_empty = export_ingestion_summary_to_polars({}, stage="fundamental")
        assert df_empty.height == 0


class TestIngestionPipelineFlow:
    """HistoricalIngestionPipeline sınıfı iş akışı testleri."""

    @pytest.fixture
    def pipeline_fixture(self):
        """InMemory repo ve mock fundamental provider fixture'ı."""
        repo = InMemoryHistoricalRepository()
        mock_provider = MagicMock(spec=HistoricalFundamentalProvider)
        pipeline = HistoricalIngestionPipeline(
            repository=repo,
            fundamental_provider=mock_provider,
        )
        return pipeline, repo, mock_provider

    def test_pipeline_init_and_repr(self, pipeline_fixture) -> None:
        """Bileşen başlatma, durum metotları ve orjson dönüşümünü doğrular."""
        pipeline, _, _ = pipeline_fixture
        assert "HistoricalIngestionPipeline" in repr(pipeline)

        as_dict = pipeline.to_dict()
        assert as_dict["repository"] == "InMemoryHistoricalRepository"

        raw_bytes = pipeline.to_orjson_bytes()
        assert isinstance(raw_bytes, bytes)

    def test_ingest_fundamentals(self, pipeline_fixture) -> None:
        """Temel analiz verilerinin çekilip repoya kaydedilmesi akışı."""
        pipeline, repo, mock_provider = pipeline_fixture

        # Mock temel analiz snapshot'ları
        mock_provider.fetch_historical_fundamentals.return_value = [
            FundamentalSnapshot(
                ticker="THYAO",
                period_end="2024-12-31",
                available_at="2025-03-01",
                values={"fk": 4.5},
            ),
            FundamentalSnapshot(
                ticker="THYAO",
                period_end="2025-03-31",
                available_at="2025-05-10",
                values={"fk": 4.8},
            ),
        ]

        res = pipeline.ingest_fundamentals(["THYAO"], force=True)
        assert res["THYAO"] == 2

        # Depodan doğrula
        snaps = repo.get_fundamental_snapshots("THYAO", "2025-06-01")
        assert len(snaps) == 2
        assert snaps[0].period_end == "2025-03-31"

    def test_category_to_catalyst_type(self) -> None:
        """KAP kategorisinin katalist türüne dönüştürülmesi testi."""
        assert HistoricalIngestionPipeline._category_to_catalyst_type("FINANCIAL_REPORT") == "EARNINGS"
        assert HistoricalIngestionPipeline._category_to_catalyst_type("DIVIDEND") == "DIVIDEND_DATE"
        assert HistoricalIngestionPipeline._category_to_catalyst_type("CONTRACT") == "CONTRACT_EXPIRY"
        assert HistoricalIngestionPipeline._category_to_catalyst_type("UNKNOWN_CAT") is None

    def test_derive_catalysts_from_events(self, pipeline_fixture) -> None:
        """Repodaki KAP olaylarından şirket katalisti türetilmesi testi."""
        pipeline, repo, _ = pipeline_fixture

        # Repoya KAP olayı ekle
        repo.add_event_snapshot(
            EventSnapshot(
                event_id="EVT-KAP-01",
                ticker="GARAN",
                published_at="2025-03-15T10:00:00",
                event_type="DIVIDEND",
                title="Kar Payı Dağıtım Kararı",
                sentiment=0.7,
                importance=0.85,
                source="kap",
            )
        )

        res = pipeline.derive_catalysts_from_events(["GARAN"])
        assert res["GARAN"] == 1

        # Türetilen katalisti depodan doğrula
        cats = repo.get_catalyst_snapshots("GARAN", "2025-04-01")
        assert len(cats) == 1
        assert cats[0].event_id == "CAT-EVT-KAP-01"
        assert cats[0].catalyst_type == "DIVIDEND_DATE"
        assert cats[0].importance == 0.85


class TestIngestionAuditDuckDB:
    """export_ingestion_run_to_duckdb, read_ingestion_audit_from_duckdb ve temizleme testleri."""

    def test_export_and_read_audit_flow(self) -> None:
        """DuckDB alım denetim tablosuna kayıt, sorgulama ve temizleme döngüsü."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = str(Path(tmpdir) / "test_ingestion_audit.duckdb")

            # Kayıt oluştur
            results = {"THYAO": 4, "GARAN": 2}
            res = export_ingestion_run_to_duckdb(
                stage="fundamental",
                tickers=["THYAO", "GARAN"],
                results=results,
                db_path=test_db,
            )
            assert res == 1

            # Polars Okuma
            df = read_ingestion_audit_from_duckdb(db_path=test_db, stage="fundamental")
            assert isinstance(df, pl.DataFrame)
            assert df.height == 1
            assert df["stage"][0] == "fundamental"
            assert df["total_tickers"][0] == 2
            assert df["success_count"][0] == 2

            # Temizleme
            clear_ingestion_audit_duckdb(db_path=test_db)
            df_after = read_ingestion_audit_from_duckdb(db_path=test_db)
            assert df_after.height == 0
