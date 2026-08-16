"""Research-only forward label contracts for ALPHA v4.

Labels explicitly expose when they became knowable. They are outcomes for research and
validation, never production-time features at their anchor timestamp.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from math import log

from .contracts import RawBar
from .data_quality import validate_raw_bar


@dataclass(frozen=True)
class ForwardReturnLabel:
    instrument_id: str
    label_id: str
    anchor_time: datetime
    outcome_time: datetime
    known_at: datetime
    value: float | None
    source_ids: tuple[str, ...]
    status: str

    def __post_init__(self) -> None:
        if self.outcome_time <= self.anchor_time:
            raise ValueError("outcome_time must be after anchor_time")
        if self.known_at < self.outcome_time:
            raise ValueError("label cannot be known before its outcome_time")
        if self.status not in {"VALID", "MASKED"}:
            raise ValueError("invalid label status")
        if self.status == "VALID" and self.value is None:
            raise ValueError("VALID label requires value")
        if not self.source_ids:
            raise ValueError("label provenance is required")

    def usable_at(self, decision_time: datetime) -> bool:
        return self.known_at <= decision_time


def compute_forward_log_return_label(
    *,
    instrument_id: str,
    anchor_bar: RawBar,
    outcome_bar: RawBar,
    horizon_name: str,
    label_version: str = "1.0",
) -> ForwardReturnLabel:
    if outcome_bar.timestamp <= anchor_bar.timestamp:
        raise ValueError("outcome bar must follow anchor bar")

    known_at = max(
        anchor_bar.observed_at, outcome_bar.observed_at, outcome_bar.timestamp
    )
    anchor_validation = validate_raw_bar(
        anchor_bar,
        decision_time=known_at,
        enforce_freshness=False,
    )
    outcome_validation = validate_raw_bar(
        outcome_bar,
        decision_time=known_at,
        enforce_freshness=False,
    )
    label_id = f"forward_log_return_{horizon_name}@{label_version}"
    sources = tuple(sorted({anchor_bar.source_id, outcome_bar.source_id}))

    if not (
        anchor_validation.usable_for_features and outcome_validation.usable_for_features
    ):
        return ForwardReturnLabel(
            instrument_id=instrument_id,
            label_id=label_id,
            anchor_time=anchor_bar.timestamp,
            outcome_time=outcome_bar.timestamp,
            known_at=known_at,
            value=None,
            source_ids=sources,
            status="MASKED",
        )

    assert anchor_bar.close is not None and outcome_bar.close is not None
    return ForwardReturnLabel(
        instrument_id=instrument_id,
        label_id=label_id,
        anchor_time=anchor_bar.timestamp,
        outcome_time=outcome_bar.timestamp,
        known_at=known_at,
        value=log(outcome_bar.close / anchor_bar.close),
        source_ids=sources,
        status="VALID",
    )


def cross_sectional_percentile_labels(
    labels: Iterable[ForwardReturnLabel],
) -> dict[str, float]:
    """Rank valid outcomes only when anchor/outcome/label definition are comparable."""
    valid = [
        label for label in labels if label.status == "VALID" and label.value is not None
    ]
    if not valid:
        return {}

    first = valid[0]
    for label in valid[1:]:
        if (
            label.label_id != first.label_id
            or label.anchor_time != first.anchor_time
            or label.outcome_time != first.outcome_time
        ):
            raise ValueError("cross-sectional labels must share label and time window")

    ordered = sorted(valid, key=lambda item: (item.value, item.instrument_id))
    if len(ordered) == 1:
        return {ordered[0].instrument_id: 0.5}

    return {
        label.instrument_id: rank / (len(ordered) - 1)
        for rank, label in enumerate(ordered)
    }
