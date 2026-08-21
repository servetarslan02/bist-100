"""
ALPHA BIST — Data Service

Modüller:
- data_source: Ana veri kaynağı (yfinance wrapper)
- historical_adapter: Tarihsel veri adaptörü
- historical_contracts: Tarihsel sözleşme verileri
- historical_fundamental_provider: Tarihsel fundamental veri sağlayıcı
- ingestion_pipeline: Veri ingestion pipeline
- persistent_repository: Kalıcı veri deposu
"""

from .data_source import data_source
from .historical_adapter import historical_adapter
from .persistent_repository import persistent_repository

__all__ = [
    "data_source",
    "historical_adapter",
    "persistent_repository",
]
