"""Canonical runtime shell for the governed ALPHA v4 rebuild."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from .contracts import CanonicalEvent
from .source_registry import SourceRegistry
from .storage import AppendOnlyEventStore


class RuntimeMode(str, Enum):
    TEST = "test"
    DEV = "dev"
    RESEARCH = "research"
    PAPER = "paper"


@dataclass(frozen=True)
class RuntimeConfig:
    mode: RuntimeMode
    database_path: Path


class UnknownSourceError(RuntimeError):
    pass


class DisabledSourceError(RuntimeError):
    pass


class AlphaRuntime:
    """Minimal canonical composition root.

    The legacy service graph remains outside this runtime until each component passes
    migration gates. New V4 code enters through this composition root rather than
    creating another hidden application entry point.
    """

    def __init__(self, config: RuntimeConfig, source_registry: Optional[SourceRegistry] = None):
        self.config = config
        self.source_registry = source_registry or SourceRegistry()
        self.events = AppendOnlyEventStore(config.database_path)

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
            "event_store": "ready",
            "event_count": self.events.count(),
            "registered_sources": len(self.source_registry.enabled_sources()),
            "real_money_execution": False,
        }
