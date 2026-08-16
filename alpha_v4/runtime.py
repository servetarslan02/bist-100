"""Canonical runtime shell for the governed ALPHA v4 rebuild."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Protocol

from .acquisition import RawDocumentStore
from .contracts import CanonicalEvent
from .features import FeatureStore
from .market_data import RawBarStore
from .paper_ledger import PaperLedger
from .source_history import PersistentSourceRegistry
from .state import StateStore
from .storage import AppendOnlyEventStore
from .universe import UniverseStore


class RuntimeMode(str, Enum):
    TEST = "test"
    DEV = "dev"
    RESEARCH = "research"
    PAPER = "paper"


@dataclass(frozen=True)
class RuntimeConfig:
    mode: RuntimeMode
    database_path: Path


class SourceRegistryLike(Protocol):
    def get(self, source_id: str): ...
    def enabled_sources(self): ...


class UnknownSourceError(RuntimeError):
    pass


class DisabledSourceError(RuntimeError):
    pass


class AlphaRuntime:
    """Single V4 composition root.

    Legacy services stay outside this runtime until they pass migration gates. All
    persistent V4 primitives intentionally share one bootstrap SQLite database today;
    storage engines may later split by measured workload without changing contracts.
    """

    def __init__(
        self,
        config: RuntimeConfig,
        source_registry: Optional[SourceRegistryLike] = None,
    ):
        self.config = config
        config.database_path.parent.mkdir(parents=True, exist_ok=True)

        self.source_registry: SourceRegistryLike = (
            source_registry or PersistentSourceRegistry(config.database_path)
        )
        self.raw_documents = RawDocumentStore(config.database_path)
        self.events = AppendOnlyEventStore(config.database_path)
        self.universe = UniverseStore(config.database_path)
        self.market_data = RawBarStore(config.database_path)
        self.states = StateStore(config.database_path)
        self.features = FeatureStore(config.database_path)
        self.paper = PaperLedger(config.database_path)

    def ingest_event(self, event: CanonicalEvent) -> None:
        try:
            source = self.source_registry.get(event.source_id)
        except KeyError as exc:
            raise UnknownSourceError(event.source_id) from exc
        if not source.enabled:
            raise DisabledSourceError(event.source_id)
        self.events.append(event)

    def health(self) -> dict[str, object]:
        return {
            "mode": self.config.mode.value,
            "stores": {
                "raw_documents": "ready",
                "events": "ready",
                "universe": "ready",
                "market_data": "ready",
                "states": "ready",
                "features": "ready",
                "paper_ledger": "ready",
            },
            "event_count": self.events.count(),
            "registered_sources": len(self.source_registry.enabled_sources()),
            "real_money_execution": False,
        }
