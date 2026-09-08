"""ALPHA BIST — Tarihsel Veri Adaptörü ve Öznitelik Köprüsü Kapsamlı Test Paketi.

services/data/historical_adapter.py modülünün temel analiz öznitelik türetimi (FCF yield,
kalite skoru, değerleme skoru), KAP/haber olayları ve duygu (sentiment) analizleri,
katalist zaman aşımı (time-decay) hesaplamaları, Polars DataFrame aktarımı ve
DuckDB denetim tablosu kayıt işlevlerini tam kapsamla test eder.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb
import orjson
import polars as pl
import pytest

from services.data.historical_adapter import (
    DEFAULT_CHECKPOINT_SIZE,
    DEFAULT_HALF_LIFE_DAYS,
    DEFAULT_WAL_SIZE,
    HistoricalDataAdapter,
    clear_historical_audit_duckdb,
    configure_duckdb_wal,
    export_features_to_duckdb,
    export_features_to_polars,
    read_historical_audit_from_duckdb,
    to_orjson_bytes,
)
from services.data.historical_contracts import (
    CatalystSnapshot,
    EventSnapshot,
    FundamentalSnapshot,
    InMemoryHistoricalRepository,
)


class TestHistoricalAdapterBasics:
    """Sabitler, serileştirme ve DuckDB WAL testleri."""

    def test_constants(self) -> None:
        """Sabitlerin doğruluğunu test eder."""
        assert DEFAULT_CHECKPOINT_SIZE == "4MB"
        assert DEFAULT_WAL_SIZE == "2MB"
        assert DEFAULT_HALF_LIFE_DAYS == 30.0

    def test_configure_duckdb_wal(self) -> None:
        """DuckDB bağlantısında WAL optimizasyonunu test eder."""
        conn = duckdb.connect(":memory:")
        configure_duckdb_wal(conn)
        conn.close()

    def test_to_orjson_bytes_helper(self) -> None:
        """to_orjson_bytes fonksiyonunun doğruluğunu kontrol eder."""
        data = {"score": 88.5, "ticker": "THYAO"}
        raw = to_orjson_bytes(data)
        assert isinstance(raw, bytes)
        assert orjson.loads(raw) == data


class TestHistoricalAdapterFeatureEngineering:
    """HistoricalDataAdapter temel analiz, duygu ve katalist öznitelik testleri."""

    @pytest.fixture
    def mock_repo(self):
        """Test snapshot'ları içeren InMemoryHistoricalRepository fixture'ı."""
        repo = InMemoryHistoricalRepository()

        # Temel Analiz Snapshot
        repo.add_fundamental_snapshot(
            FundamentalSnapshot(
                ticker="THYAO",
                period_end="2024-12-31",
                available_at="2025-03-01",
                values={
                    "free_cash_flow": 1000000000.0,
                    "market_cap": 20000000000.0,
                    "debt_to_equity": 0.25,
                    "current_ratio": 1.8,
                    "pe_ratio": 8.5,
                    "pb_ratio": 1.2,
                    "fcf_yield": 0.05,
                    "roe": 0.18,
                    "profit_margin": 0.15,
                },
            )
        )

        # KAP Olayı
        repo.add_event_snapshot(
            EventSnapshot(
                event_id="EVT-01",
                ticker="THYAO",
                published_at="2025-03-10T12:00:00",
                event_type="KAP_ACIKLAMA",
                title="Yeni Uçak Alımı",
                sentiment=0.8,
                importance=0.9,
                source="kap",
            )
        )

        # Haber Olayı
        repo.add_event_snapshot(
            EventSnapshot(
                event_id="EVT-02",
                ticker="THYAO",
                published_at="2025-03-12T09:30:00",
                event_type="HABER",
                title="Turizm Sezonu Beklentileri",
                sentiment=0.6,
                importance=0.7,
                source="news",
            )
        )

        # Katalist Olayı (2025-03-15 tarihinden 15 gün sonrası için)
        repo.add_catalyst_snapshot(
            CatalystSnapshot(
                event_id="CAT-01",
                ticker="THYAO",
                announcement_date="2025-03-05",
                event_date="2025-03-30",
                catalyst_type="TEMETTU",
                importance=0.8,
                source="kap",
            )
        )

        return repo

    def test_adapter_initialization_and_repr(self, mock_repo) -> None:
        """Adaptör başlatma, __repr__, to_dict ve to_orjson_bytes testleri."""
        adapter = HistoricalDataAdapter(repository=mock_repo)
        assert "HistoricalDataAdapter" in repr(adapter)

        as_dict = adapter.to_dict()
        assert as_dict["repository"] == "InMemoryHistoricalRepository"

        raw_bytes = adapter.to_orjson_bytes()
        assert isinstance(raw_bytes, bytes)

    def test_get_fundamental_features_calculation(self, mock_repo) -> None:
        """Temel analiz özniteliklerinin (FCF verimi, kalite skoru, değerleme skoru) hesaplanması."""
        adapter = HistoricalDataAdapter(repository=mock_repo)

        features = adapter.get_fundamental_features("THYAO", "2025-03-15")
        assert features
        assert "fcf_yield_pct" in features
        assert features["fcf_yield_pct"] == 5.0  # 1 milyar / 20 milyar * 100
        assert "balance_sheet_quality" in features
        assert features["balance_sheet_quality"] > 50.0  # borç/özkaynak düşük olduğu için ödüllendirilmeli
        assert "value_score" in features
        assert features["value_score"] > 0.0
        assert "quality_score" in features

        # Veri olmayan tarih için boş sözlük dönmeli
        empty_features = adapter.get_fundamental_features("THYAO", "2024-01-01")
        assert empty_features == {}

    def test_get_kap_and_news_events(self, mock_repo) -> None:
        """KAP ve haber olaylarının filtrelenerek listelenmesi testi."""
        adapter = HistoricalDataAdapter(repository=mock_repo)

        kap_events = adapter.get_kap_events("THYAO", "2025-03-15")
        assert len(kap_events) >= 1
        assert kap_events[0]["ticker"] == "THYAO"

        news_events = adapter.get_news_events("THYAO", "2025-03-15")
        assert len(news_events) == 1
        assert news_events[0]["source"] == "news"

    def test_compute_sentiment(self, mock_repo) -> None:
        """KAP ve haber duygu skorlarının ağırlıklandırılarak birleştirilmesi testi."""
        adapter = HistoricalDataAdapter(repository=mock_repo)

        kap_events = adapter.get_kap_events("THYAO", "2025-03-15")
        news_events = adapter.get_news_events("THYAO", "2025-03-15")

        sent_features = adapter.compute_sentiment(kap_events, news_events)
        assert "kap_sentiment_weighted" in sent_features
        assert "news_sentiment_weighted" in sent_features
        assert "combined_sentiment" in sent_features
        assert sent_features["combined_sentiment"] > 0.5

    def test_get_catalyst_events_and_decay(self, mock_repo) -> None:
        """Katalist gün farkı ve zaman aşımı ağırlıklı etki skoru testi."""
        adapter = HistoricalDataAdapter(repository=mock_repo)

        cat_events = adapter.get_catalyst_events("THYAO", "2025-03-15")
        assert len(cat_events) == 1
        assert cat_events[0]["days_until"] == 15  # 2025-03-30 - 2025-03-15 = 15 gün

        decay_features = adapter.compute_catalyst_features(cat_events)
        assert decay_features["catalyst_count"] == 1
        assert decay_features["catalyst_days_nearest"] == 15
        assert decay_features["catalyst_time_decay_score"] > 0.0

        # Boş katalist listesi testi
        empty_decay = adapter.compute_catalyst_features([])
        assert empty_decay["catalyst_count"] == 0
        assert empty_decay["catalyst_days_nearest"] == 999


class TestHistoricalAdapterExportAndDuckDB:
    """Polars DataFrame ve DuckDB denetim tablosu kayıt testleri."""

    def test_export_features_to_polars(self) -> None:
        """Özniteliklerin Polars DataFrame'e aktarılması testi."""
        features = {"kalite_skor": 85.0, "degerleme_skor": 75.0}
        df = export_features_to_polars(features)
        assert isinstance(df, pl.DataFrame)
        assert df.height == 1
        assert df["kalite_skor"][0] == 85.0

        df_empty = export_features_to_polars({})
        assert df_empty.height == 0

    def test_export_and_read_historical_audit(self) -> None:
        """DuckDB audit tablosuna yazma, okuma ve temizleme akışı."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = str(Path(tmpdir) / "test_hist_audit.duckdb")
            features = {"fcf_yield": 4.5, "kalite": 80.0}

            res = export_features_to_duckdb(
                ticker="GARAN",
                current_date="2025-03-15",
                features=features,
                db_path=test_db,
            )
            assert res == 1

            df = read_historical_audit_from_duckdb(db_path=test_db, limit=10)
            assert isinstance(df, pl.DataFrame)
            assert df.height == 1
            assert df["ticker"][0] == "GARAN"
            assert df["current_date"][0] == "2025-03-15"

            clear_historical_audit_duckdb(db_path=test_db)
            df_after = read_historical_audit_from_duckdb(db_path=test_db)
            assert df_after.height == 0
