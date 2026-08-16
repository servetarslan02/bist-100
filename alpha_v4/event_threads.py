"""Event lifecycle/thread primitives.

The purpose is to stop ALPHA from counting tender participation, tender win and
signed contract as unrelated positive news when they are stages of the same event.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from hashlib import sha256
from typing import Tuple


class EventStage(IntEnum):
    RUMOR = 10
    INTENTION = 20
    TENDER_PARTICIPATION = 30
    TENDER_WIN = 40
    SIGNED_CONTRACT = 50
    REGULATORY_APPROVAL = 60
    EXECUTION_STARTED = 70
    REVENUE_RECOGNITION = 80
    COMPLETED = 90
    CANCELLED = 100


@dataclass(frozen=True)
class ThreadEvent:
    event_id: str
    company_id: str
    project_key: str
    event_type: str
    stage: EventStage
    is_correction: bool = False

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id must not be empty")
        if not self.company_id.strip():
            raise ValueError("company_id must not be empty")
        if not self.project_key.strip():
            raise ValueError("project_key must not be empty")


@dataclass(frozen=True)
class ThreadUpdate:
    thread_id: str
    classification: str
    current_stage: EventStage
    event_ids: Tuple[str, ...]


class EventThreadTracker:
    def __init__(self):
        self._threads: dict[str, list[ThreadEvent]] = {}

    @staticmethod
    def thread_id(company_id: str, project_key: str) -> str:
        normalized = f"{company_id.strip().upper()}|{project_key.strip().lower()}"
        return sha256(normalized.encode("utf-8")).hexdigest()

    def append(self, event: ThreadEvent) -> ThreadUpdate:
        thread_id = self.thread_id(event.company_id, event.project_key)
        events = self._threads.setdefault(thread_id, [])

        if any(existing.event_id == event.event_id for existing in events):
            current_stage = max((e.stage for e in events), default=event.stage)
            return ThreadUpdate(
                thread_id=thread_id,
                classification="duplicate_event",
                current_stage=current_stage,
                event_ids=tuple(e.event_id for e in events),
            )

        previous_stage = max((e.stage for e in events), default=None)
        events.append(event)

        if event.is_correction:
            classification = "correction"
        elif previous_stage is None:
            classification = "new_thread"
        elif event.stage > previous_stage:
            classification = "stage_advance"
        elif event.stage == previous_stage:
            classification = "same_stage_update"
        else:
            classification = "out_of_order_or_revision"

        current_stage = max(e.stage for e in events)
        return ThreadUpdate(
            thread_id=thread_id,
            classification=classification,
            current_stage=current_stage,
            event_ids=tuple(e.event_id for e in events),
        )
