"""Persistent governed model/evaluation registry for ALPHA v4."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from .artifacts import EvaluationArtifact, ModelArtifact, ModelLifecycle
from .governance import GovernanceDecision, GovernancePolicy, evaluate_transition


class ModelRegistry:
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
                CREATE TABLE IF NOT EXISTS model_artifacts (
                    model_id TEXT PRIMARY KEY,
                    model_type TEXT NOT NULL,
                    horizon TEXT NOT NULL,
                    dataset_manifest_id TEXT NOT NULL,
                    code_commit TEXT NOT NULL,
                    hyperparameters_json TEXT NOT NULL,
                    random_seed INTEGER,
                    calibration_method TEXT,
                    initial_lifecycle TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_evaluations (
                    evaluation_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    dataset_manifest_id TEXT NOT NULL,
                    evaluator_code_commit TEXT NOT NULL,
                    fold_ids_json TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    cost_assumptions_json TEXT NOT NULL,
                    independently_recomputed INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_transitions (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_id TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    from_lifecycle TEXT NOT NULL,
                    requested_lifecycle TEXT NOT NULL,
                    approved INTEGER NOT NULL,
                    reasons_json TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    evaluation_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_model_transition
                    ON model_transitions(model_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_model_evaluation
                    ON model_evaluations(model_id, created_at);
                """
            )

    def register(self, artifact: ModelArtifact) -> None:
        try:
            hyperparameters_json = json.dumps(
                artifact.hyperparameters,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("model hyperparameters must be JSON-serializable") from exc
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO model_artifacts (
                    model_id, model_type, horizon, dataset_manifest_id, code_commit,
                    hyperparameters_json, random_seed, calibration_method,
                    initial_lifecycle, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.model_id,
                    artifact.model_type,
                    artifact.horizon,
                    artifact.dataset_manifest_id,
                    artifact.code_commit,
                    hyperparameters_json,
                    artifact.random_seed,
                    artifact.calibration_method,
                    artifact.lifecycle.value,
                    artifact.created_at.isoformat(),
                ),
            )

    def get(self, model_id: str) -> ModelArtifact:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM model_artifacts WHERE model_id = ?", (model_id,)
            ).fetchone()
        if row is None:
            raise KeyError(model_id)
        return ModelArtifact(
            model_id=row["model_id"],
            model_type=row["model_type"],
            horizon=row["horizon"],
            dataset_manifest_id=row["dataset_manifest_id"],
            code_commit=row["code_commit"],
            hyperparameters=json.loads(row["hyperparameters_json"]),
            random_seed=row["random_seed"],
            calibration_method=row["calibration_method"],
            lifecycle=self.current_lifecycle(model_id),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def current_lifecycle(self, model_id: str) -> ModelLifecycle:
        with self._connect() as connection:
            initial = connection.execute(
                "SELECT initial_lifecycle FROM model_artifacts WHERE model_id = ?",
                (model_id,),
            ).fetchone()
            if initial is None:
                raise KeyError(model_id)
            transition = connection.execute(
                """
                SELECT requested_lifecycle FROM model_transitions
                WHERE model_id = ? AND approved = 1
                ORDER BY sequence DESC LIMIT 1
                """,
                (model_id,),
            ).fetchone()
        if transition is None:
            return ModelLifecycle(initial["initial_lifecycle"])
        return ModelLifecycle(transition["requested_lifecycle"])

    def add_evaluation(self, evaluation_id: str, artifact: EvaluationArtifact) -> None:
        if not evaluation_id.strip():
            raise ValueError("evaluation_id is required")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO model_evaluations (
                    evaluation_id, model_id, dataset_manifest_id, evaluator_code_commit,
                    fold_ids_json, metrics_json, cost_assumptions_json,
                    independently_recomputed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evaluation_id,
                    artifact.model_id,
                    artifact.dataset_manifest_id,
                    artifact.evaluator_code_commit,
                    json.dumps(artifact.fold_ids, separators=(",", ":")),
                    json.dumps(artifact.metrics, sort_keys=True, separators=(",", ":")),
                    json.dumps(artifact.cost_assumptions, sort_keys=True, separators=(",", ":")),
                    1 if artifact.independently_recomputed else 0,
                    artifact.created_at.isoformat(),
                ),
            )

    def get_evaluation(self, evaluation_id: str) -> EvaluationArtifact:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM model_evaluations WHERE evaluation_id = ?",
                (evaluation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(evaluation_id)
        return EvaluationArtifact(
            model_id=row["model_id"],
            dataset_manifest_id=row["dataset_manifest_id"],
            evaluator_code_commit=row["evaluator_code_commit"],
            fold_ids=tuple(json.loads(row["fold_ids_json"])),
            metrics=json.loads(row["metrics_json"]),
            cost_assumptions=json.loads(row["cost_assumptions_json"]),
            independently_recomputed=bool(row["independently_recomputed"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def request_transition(
        self,
        model_id: str,
        requested_lifecycle: ModelLifecycle,
        *,
        requested_at: datetime,
        policy: GovernancePolicy,
        evaluation_id: Optional[str] = None,
    ) -> GovernanceDecision:
        model = self.get(model_id)
        evaluation = None if evaluation_id is None else self.get_evaluation(evaluation_id)
        decision = evaluate_transition(
            model,
            requested_lifecycle,
            policy=policy,
            evaluation=evaluation,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO model_transitions (
                    model_id, requested_at, from_lifecycle, requested_lifecycle,
                    approved, reasons_json, policy_version, evaluation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_id,
                    requested_at.isoformat(),
                    model.lifecycle.value,
                    requested_lifecycle.value,
                    1 if decision.approved else 0,
                    json.dumps(decision.reasons, separators=(",", ":")),
                    decision.policy_version,
                    evaluation_id,
                ),
            )
        return decision

    def transition_history(self, model_id: str) -> Tuple[dict, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM model_transitions WHERE model_id = ? ORDER BY sequence ASC",
                (model_id,),
            ).fetchall()
        return tuple(dict(row) for row in rows)
