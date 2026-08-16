"""Honest cross-sectional baselines for ALPHA v4.

A baseline score is deliberately *not* called confidence or probability. It exists to
establish a reproducible bar that future ML models must beat out-of-sample.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Tuple

from .features import FeatureRecord


@dataclass(frozen=True)
class BaselineRank:
    instrument_id: str
    rank: int
    percentile: float
    raw_feature_value: float
    score_kind: str = "NON_PROBABILISTIC_RANK"


@dataclass(frozen=True)
class BaselineRanking:
    feature_id: str
    effective_at: datetime
    direction: str
    ranks: Tuple[BaselineRank, ...]


def rank_single_feature(
    records: Iterable[FeatureRecord],
    *,
    higher_is_better: bool,
) -> BaselineRanking:
    """Rank comparable VALID feature records with no fabricated probability."""
    valid = [record for record in records if record.status == "VALID" and record.value is not None]
    if not valid:
        raise ValueError("at least one VALID feature record is required")

    feature_id = valid[0].feature_id
    effective_at = valid[0].effective_at
    for record in valid[1:]:
        if record.feature_id != feature_id or record.effective_at != effective_at:
            raise ValueError("baseline records must share feature_id and effective_at")

    ordered = sorted(
        valid,
        key=lambda item: (item.value, item.instrument_id),
        reverse=higher_is_better,
    )
    count = len(ordered)
    ranks = []
    for index, record in enumerate(ordered, start=1):
        percentile = 1.0 if count == 1 else 1.0 - (index - 1) / (count - 1)
        ranks.append(
            BaselineRank(
                instrument_id=record.instrument_id,
                rank=index,
                percentile=percentile,
                raw_feature_value=float(record.value),
            )
        )

    return BaselineRanking(
        feature_id=feature_id,
        effective_at=effective_at,
        direction="HIGHER_IS_BETTER" if higher_is_better else "LOWER_IS_BETTER",
        ranks=tuple(ranks),
    )
