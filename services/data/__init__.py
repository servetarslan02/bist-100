"""ALPHA BIST — Data Service (Veri Katmanı).

BIST Pay Piyasası için çok kaynaklı veri toplama, tarihsel uyarlama,
temel analiz verisi entegrasyonu, veri sürüklenmesi (drift) izleme ve
kalıcı depolama motorlarını bir araya getiren kurumsal veri servis paketi.
"""

from __future__ import annotations

from typing import Final

from services.data.data_source import DataSource, DataSourceManager, data_source
from services.data.evidently_monitor import DataQualityReport, EvidentlyDataMonitor, data_monitor
from services.data.historical_adapter import HistoricalDataAdapter, historical_adapter
from services.data.historical_contracts import (
    CatalystSnapshot,
    EventSnapshot,
    FundamentalSnapshot,
    HistoricalDataRepository,
    InMemoryHistoricalRepository,
)
from services.data.historical_fundamental_provider import (
    HistoricalFundamentalProvider,
    historical_fundamental_provider,
)
from services.data.historical_warehouse import HistoricalDataWarehouse, historical_warehouse
from services.data.ingestion_pipeline import HistoricalIngestionPipeline, IngestionPipeline
from services.data.persistent_repository import PersistentHistoricalRepository, persistent_repository

# Geriye dönük uyumluluk takma adları
HistoricalAdapter = HistoricalDataAdapter
PersistentRepository = PersistentHistoricalRepository

__all__: Final[list[str]] = [
    "CatalystSnapshot",
    "DataQualityReport",
    "DataSource",
    "DataSourceManager",
    "EventSnapshot",
    "EvidentlyDataMonitor",
    "FundamentalSnapshot",
    "HistoricalAdapter",
    "HistoricalDataAdapter",
    "HistoricalDataRepository",
    "HistoricalDataWarehouse",
    "HistoricalFundamentalProvider",
    "HistoricalIngestionPipeline",
    "InMemoryHistoricalRepository",
    "IngestionPipeline",
    "PersistentHistoricalRepository",
    "PersistentRepository",
    "data_monitor",
    "data_source",
    "historical_adapter",
    "historical_fundamental_provider",
    "historical_warehouse",
    "persistent_repository",
]

