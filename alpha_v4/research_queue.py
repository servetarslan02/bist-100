"""Persistent research backlog for ALPHA v4 Research Brain."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple


class ResearchStatus(str, Enum):
    NEW = "NEW"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ResearchTask:
    task_id: str
    created_at: datetime
    trigger_type: str
    hypothesis: str
    experiment_type: str
    trigger_evidence_ids: Tuple[str, ...]
    priority: int
    status: ResearchStatus
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in ("task_id", "trigger_type", "hypothesis", "experiment_type"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if not self.trigger_evidence_ids:
            raise ValueError("research task requires trigger evidence")
        if not 0 <= self.priority <= 100:
            raise ValueError("priority must be between 0 and 100")


class ResearchQueue:
    def __init__(self, database_path: str | Path):
        self.database_path = str(database_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_tasks (
                    task_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    experiment_type TEXT NOT NULL,
                    trigger_evidence_ids_json TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_task_transitions (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    transitioned_at TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT NOT NULL,
                    reason TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_research_transition
                    ON research_task_transitions(task_id, sequence);
                """
            )

    def create(
        self,
        *,
        created_at: datetime,
        trigger_type: str,
        hypothesis: str,
        experiment_type: str,
        trigger_evidence_ids: Tuple[str, ...],
        priority: int,
        metadata: Optional[Mapping[str, Any]] = None,
        task_id: Optional[str] = None,
    ) -> ResearchTask:
        task = ResearchTask(
            task_id=task_id or uuid.uuid4().hex,
            created_at=created_at,
            trigger_type=trigger_type,
            hypothesis=hypothesis,
            experiment_type=experiment_type,
            trigger_evidence_ids=trigger_evidence_ids,
            priority=priority,
            status=ResearchStatus.NEW,
            metadata=dict(metadata or {}),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO research_tasks (
                    task_id, created_at, trigger_type, hypothesis, experiment_type,
                    trigger_evidence_ids_json, priority, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.created_at.isoformat(),
                    task.trigger_type,
                    task.hypothesis,
                    task.experiment_type,
                    json.dumps(task.trigger_evidence_ids, separators=(",", ":")),
                    task.priority,
                    json.dumps(task.metadata, sort_keys=True, separators=(",", ":")),
                ),
            )
            connection.execute(
                """
                INSERT INTO research_task_transitions (
                    task_id, transitioned_at, from_status, to_status, reason
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (task.task_id, created_at.isoformat(), None, ResearchStatus.NEW.value, "created"),
            )
        return task

    def _current_status(self, task_id: str) -> ResearchStatus:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT to_status FROM research_task_transitions
                WHERE task_id = ? ORDER BY sequence DESC LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            raise KeyError(task_id)
        return ResearchStatus(row["to_status"])

    def transition(
        self,
        task_id: str,
        to_status: ResearchStatus,
        *,
        transitioned_at: datetime,
        reason: str,
    ) -> None:
        if not reason.strip():
            raise ValueError("transition reason is required")
        current = self._current_status(task_id)
        allowed = {
            ResearchStatus.NEW: {ResearchStatus.RUNNING, ResearchStatus.REJECTED, ResearchStatus.BLOCKED},
            ResearchStatus.RUNNING: {ResearchStatus.COMPLETED, ResearchStatus.REJECTED, ResearchStatus.BLOCKED},
            ResearchStatus.BLOCKED: {ResearchStatus.RUNNING, ResearchStatus.REJECTED},
            ResearchStatus.COMPLETED: set(),
            ResearchStatus.REJECTED: set(),
        }
        if to_status not in allowed[current]:
            raise ValueError(f"invalid research transition: {current.value}->{to_status.value}")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO research_task_transitions (
                    task_id, transitioned_at, from_status, to_status, reason
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    transitioned_at.isoformat(),
                    current.value,
                    to_status.value,
                    reason,
                ),
            )

    def pending(self, *, limit: Optional[int] = None) -> Tuple[ResearchTask, ...]:
        """Priority scheduling limit is compute batching, never task eligibility."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM research_tasks ORDER BY priority DESC, created_at ASC, task_id ASC"
            ).fetchall()

        tasks = []
        for row in rows:
            status = self._current_status(row["task_id"])
            if status not in {ResearchStatus.NEW, ResearchStatus.BLOCKED}:
                continue
            tasks.append(
                ResearchTask(
                    task_id=row["task_id"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    trigger_type=row["trigger_type"],
                    hypothesis=row["hypothesis"],
                    experiment_type=row["experiment_type"],
                    trigger_evidence_ids=tuple(json.loads(row["trigger_evidence_ids_json"])),
                    priority=int(row["priority"]),
                    status=status,
                    metadata=json.loads(row["metadata_json"]),
                )
            )
        selected = tasks if limit is None else tasks[:limit]
        return tuple(selected)
