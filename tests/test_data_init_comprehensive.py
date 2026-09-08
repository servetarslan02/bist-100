"""ALPHA BIST — Veri Katmanı Paket Başlatıcı (__init__.py) Kapsamlı Test Paketi.

services/data/__init__.py modülünün dışa aktardığı tüm sınıfların, singleton örneklerinin,
geriye dönük uyumluluk takma adlarının ve __all__ sembollerinin eksiksizliğini doğrular.
"""

from __future__ import annotations

import services.data as data_pkg
from services.data import (
    CatalystSnapshot,
    DataSource,
    DataSourceManager,
    EventSnapshot,
    EvidentlyDataMonitor,
    FundamentalSnapshot,
    HistoricalAdapter,
    HistoricalDataAdapter,
    HistoricalDataWarehouse,
    HistoricalFundamentalProvider,
    HistoricalIngestionPipeline,
    IngestionPipeline,
    PersistentHistoricalRepository,
    PersistentRepository,
    data_monitor,
    data_source,
    historical_adapter,
    historical_fundamental_provider,
    historical_warehouse,
    persistent_repository,
)


class TestDataInitComprehensive:
    """services/data paket seviyesi dışa aktarım testleri."""

    def test_all_symbols_exported(self) -> None:
        """__all__ listesinde yer alan tüm sembollerin pakette tanımlı olduğunu doğrular."""
        assert hasattr(data_pkg, "__all__")
        all_symbols = data_pkg.__all__
        assert len(all_symbols) == 23

        for sym in all_symbols:
            assert hasattr(data_pkg, sym), f"{sym} sembolü services.data paketinde bulunamadı!"

    def test_class_and_alias_equivalences(self) -> None:
        """Takma adların ana sınıflarla birebir aynı nesne olduğunu doğrular."""
        assert DataSource is DataSourceManager
        assert HistoricalAdapter is HistoricalDataAdapter
        assert PersistentRepository is PersistentHistoricalRepository
        assert IngestionPipeline is HistoricalIngestionPipeline

    def test_singleton_instances(self) -> None:
        """Singleton örneklerin doğru sınıf tiplerinde olduğunu ve başlatıldığını doğrular."""
        assert isinstance(data_source, DataSourceManager)
        assert isinstance(data_monitor, EvidentlyDataMonitor)
        assert isinstance(historical_adapter, HistoricalDataAdapter)
        assert isinstance(historical_fundamental_provider, HistoricalFundamentalProvider)
        assert isinstance(historical_warehouse, HistoricalDataWarehouse)
        assert isinstance(persistent_repository, PersistentHistoricalRepository)

    def test_models_importable(self) -> None:
        """Veri sözleşme modellerinin paketten sorunsuz içe aktarıldığını doğrular."""
        snap = FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-03-31",
            available_at="2025-05-10",
            values={},
        )
        assert snap.ticker == "THYAO"

        event = EventSnapshot(
            event_id="E-1",
            ticker="GARAN",
            published_at="2025-03-10",
            event_type="KAP",
        )
        assert event.event_id == "E-1"

        cat = CatalystSnapshot(
            event_id="C-1",
            ticker="GARAN",
            announcement_date="2025-03-10",
            event_date="2025-04-10",
            catalyst_type="TEMETTU",
        )
        assert cat.catalyst_type == "TEMETTU"
