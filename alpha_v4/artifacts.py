"""Reproducible research artifact contracts for ALPHA v4."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256


class MissingPolicy(str, Enum):
    REJECT = "reject"
    MASK = "mask"
    EXPLICIT_CATEGORY = "explicit_category"


class ModelLifecycle(str, Enum):
    RESEARCH = "RESEARCH"
    VALIDATED = "VALIDATED"
    SHADOW = "SHADOW"
    CHALLENGER = "CHALLENGER"
    PAPER_ELIGIBLE = "PAPER_ELIGIBLE"
    CHAMPION = "CHAMPION"
    DEGRADED = "DEGRADED"
    RETIRED = "RETIRED"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True)
class FeatureDefinition:
    name: str
    version: str
    inputs: tuple[str, ...]
    lookback: str
    availability_rule: str
    missing_policy: MissingPolicy
    horizon: str

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.version.strip():
            raise ValueError("feature name/version are required")
        if not self.inputs:
            raise ValueError("feature inputs are required")
        if not self.availability_rule.strip():
            raise ValueError("availability_rule is required")

    @property
    def feature_id(self) -> str:
        return f"{self.name}@{self.version}"


@dataclass(frozen=True)
class LabelDefinition:
    name: str
    version: str
    horizon: str
    target: str
    benchmark: str | None
    execution_adjusted: bool = False

    @property
    def label_id(self) -> str:
        return f"{self.name}@{self.version}"


@dataclass(frozen=True)
class DatasetManifest:
    universe_snapshot_id: str
    feature_ids: tuple[str, ...]
    label_ids: tuple[str, ...]
    start_time: datetime
    end_time: datetime
    code_commit: str
    source_manifest_hash: str
    mask_policy_version: str
    created_at: datetime
    manifest_id: str = field(default="")

    def __post_init__(self) -> None:
        if self.end_time <= self.start_time:
            raise ValueError("dataset end_time must be after start_time")
        if not self.feature_ids or not self.label_ids:
            raise ValueError("dataset requires features and labels")
        if not self.code_commit.strip() or not self.source_manifest_hash.strip():
            raise ValueError("code_commit and source_manifest_hash are required")
        if not self.manifest_id:
            payload = {
                "universe_snapshot_id": self.universe_snapshot_id,
                "feature_ids": sorted(self.feature_ids),
                "label_ids": sorted(self.label_ids),
                "start_time": self.start_time.isoformat(),
                "end_time": self.end_time.isoformat(),
                "code_commit": self.code_commit,
                "source_manifest_hash": self.source_manifest_hash,
                "mask_policy_version": self.mask_policy_version,
            }
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            object.__setattr__(
                self, "manifest_id", sha256(encoded.encode("utf-8")).hexdigest()
            )


@dataclass(frozen=True)
class ModelArtifact:
    model_id: str
    model_type: str
    horizon: str
    dataset_manifest_id: str
    code_commit: str
    hyperparameters: Mapping[str, object]
    random_seed: int | None
    calibration_method: str | None
    lifecycle: ModelLifecycle
    created_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "model_id",
            "model_type",
            "horizon",
            "dataset_manifest_id",
            "code_commit",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")
        if (
            self.lifecycle
            in {
                ModelLifecycle.PAPER_ELIGIBLE,
                ModelLifecycle.CHAMPION,
            }
            and self.random_seed is None
        ):
            raise ValueError(
                "promotable deterministic models require a recorded random_seed"
            )


@dataclass(frozen=True)
class EvaluationArtifact:
    model_id: str
    dataset_manifest_id: str
    evaluator_code_commit: str
    fold_ids: tuple[str, ...]
    metrics: Mapping[str, float]
    cost_assumptions: Mapping[str, float]
    independently_recomputed: bool
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.fold_ids:
            raise ValueError("evaluation requires fold evidence")
        if not self.metrics:
            raise ValueError("evaluation requires metrics")
