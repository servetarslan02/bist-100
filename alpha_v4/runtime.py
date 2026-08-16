"""Canonical runtime shell for the governed ALPHA v4 rebuild."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from .acquisition import RawDocumentStore
from .audit import AuditLedger
from .contracts import CanonicalEvent
from .features import FeatureStore
from .jobs import JobCoordinator
from .market_data import RawBarStore
from .model_registry import ModelRegistry
from .paper_ledger import PaperLedger
from .relations import RelationStore
from .research_queue import ResearchQueue
from .source_catalog import OFFICIAL_SOURCE_SEEDS
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

    STORE_NAMES = (
        "raw_documents",
        "events",
        "universe",
        "market_data",
        "states",
        "features",
        "relations",
        "models",
        "research",
        "jobs",
        "audit",
        "paper_ledger",
    )

    def __init__(
        self,
        config: RuntimeConfig,
        source_registry: SourceRegistryLike | None = None,
    ):
        self.config = config
        config.database_path.parent.mkdir(parents=True, exist_ok=True)

        if source_registry is None:
            persistent_sources = PersistentSourceRegistry(config.database_path)
            for seed in OFFICIAL_SOURCE_SEEDS:
                persistent_sources.register_if_missing(seed.record)
            self.source_registry: SourceRegistryLike = persistent_sources
        else:
            self.source_registry = source_registry

        self.raw_documents = RawDocumentStore(config.database_path)
        self.events = AppendOnlyEventStore(config.database_path)
        self.universe = UniverseStore(config.database_path)
        self.market_data = RawBarStore(config.database_path)
        self.states = StateStore(config.database_path)
        self.features = FeatureStore(config.database_path)
        self.relations = RelationStore(config.database_path)
        self.models = ModelRegistry(config.database_path)
        self.research = ResearchQueue(config.database_path)
        self.jobs = JobCoordinator(config.database_path)
        self.audit = AuditLedger(config.database_path)
        self.paper = PaperLedger(config.database_path)

    def ingest_event(self, event: CanonicalEvent) -> None:
        try:
            source = self.source_registry.get(event.source_id)
        except KeyError as exc:
            raise UnknownSourceError(event.source_id) from exc
        if not source.enabled:
            raise DisabledSourceError(event.source_id)
        self.events.append(event)

    def liveness(self) -> dict[str, object]:
        """Report whether the runtime process itself is responsive."""
        return {
            "alive": True,
            "mode": self.config.mode.value,
            "real_money_execution": False,
        }

    def readiness(self) -> dict[str, object]:
        """Fail closed when durable state or governance integrity is not usable."""
        database_ok = False
        database_integrity = "unavailable"
        try:
            with sqlite3.connect(self.config.database_path, timeout=2.0) as connection:
                connection.execute("SELECT 1").fetchone()
                row = connection.execute("PRAGMA quick_check(1)").fetchone()
                database_integrity = "unknown" if row is None else str(row[0])
                database_ok = database_integrity.lower() == "ok"
        except sqlite3.Error as exc:
            database_integrity = f"sqlite_error:{type(exc).__name__}"

        try:
            audit = self.audit.verify_chain()
            audit_ok = audit.valid
            audit_checked_entries = audit.checked_entries
            audit_reason = audit.reason
        except (sqlite3.Error, ValueError, TypeError) as exc:
            audit_ok = False
            audit_checked_entries = 0
            audit_reason = f"audit_error:{type(exc).__name__}"

        try:
            registered_sources = len(self.source_registry.enabled_sources())
            sources_ok = registered_sources > 0
        except (sqlite3.Error, KeyError, TypeError) as exc:
            registered_sources = 0
            sources_ok = False
            source_error = f"source_registry_error:{type(exc).__name__}"
        else:
            source_error = None

        ready = database_ok and audit_ok and sources_ok
        return {
            "ready": ready,
            "checks": {
                "database": {
                    "ok": database_ok,
                    "integrity": database_integrity,
                },
                "audit_chain": {
                    "ok": audit_ok,
                    "checked_entries": audit_checked_entries,
                    "reason": audit_reason,
                },
                "source_registry": {
                    "ok": sources_ok,
                    "registered_sources": registered_sources,
                    "reason": source_error,
                },
            },
        }

    def health(self) -> dict[str, object]:
        readiness = self.readiness()
        checks = readiness["checks"]
        database_check = checks["database"]
        audit_check = checks["audit_chain"]
        source_check = checks["source_registry"]
        database_ok = bool(database_check["ok"])
        audit_ok = bool(audit_check["ok"])
        stores = {
            name: "ready" if database_ok else "unavailable" for name in self.STORE_NAMES
        }
        if not audit_ok:
            stores["audit"] = "corrupt"

        return {
            "mode": self.config.mode.value,
            "ready": readiness["ready"],
            "checks": checks,
            "stores": stores,
            "event_count": self.events.count() if database_ok else None,
            "registered_sources": source_check["registered_sources"],
            "audit_chain_valid": audit_ok,
            "real_money_execution": False,
        }
