"""Explicit drift diagnostics for ALPHA v4.

Drift detection creates evidence for diagnosis/research; it never retrains or promotes a
model by itself.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from statistics import fmean, pstdev


@dataclass(frozen=True)
class DriftPolicy:
    policy_version: str
    minimum_reference_samples: int
    minimum_recent_samples: int
    maximum_standardized_mean_shift: float
    maximum_std_ratio: float

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("policy_version is required")
        if self.minimum_reference_samples < 2 or self.minimum_recent_samples < 2:
            raise ValueError("drift windows require at least two samples")
        if self.maximum_standardized_mean_shift < 0:
            raise ValueError("mean-shift threshold cannot be negative")
        if self.maximum_std_ratio < 1:
            raise ValueError("maximum_std_ratio must be at least 1")


@dataclass(frozen=True)
class DriftAssessment:
    status: str
    detected: bool
    reference_count: int
    recent_count: int
    reference_mean: float | None
    recent_mean: float | None
    standardized_mean_shift: float | None
    std_ratio: float | None
    reasons: tuple[str, ...]
    policy_version: str


def assess_numeric_drift(
    reference: Iterable[float],
    recent: Iterable[float],
    *,
    policy: DriftPolicy,
) -> DriftAssessment:
    ref = tuple(float(value) for value in reference)
    rec = tuple(float(value) for value in recent)

    if (
        len(ref) < policy.minimum_reference_samples
        or len(rec) < policy.minimum_recent_samples
    ):
        return DriftAssessment(
            status="INSUFFICIENT_DATA",
            detected=False,
            reference_count=len(ref),
            recent_count=len(rec),
            reference_mean=None,
            recent_mean=None,
            standardized_mean_shift=None,
            std_ratio=None,
            reasons=("insufficient_samples",),
            policy_version=policy.policy_version,
        )

    ref_mean = fmean(ref)
    rec_mean = fmean(rec)
    ref_std = pstdev(ref)
    rec_std = pstdev(rec)

    if ref_std <= 1e-15:
        mean_shift = 0.0 if abs(rec_mean - ref_mean) <= 1e-15 else None
    else:
        mean_shift = abs(rec_mean - ref_mean) / ref_std

    if ref_std <= 1e-15:
        std_ratio = 1.0 if rec_std <= 1e-15 else None
    else:
        ratio = rec_std / ref_std
        std_ratio = max(ratio, 1.0 / ratio) if ratio > 0 else None

    reasons = []
    if mean_shift is None:
        reasons.append("reference_variance_zero_mean_changed")
    elif mean_shift > policy.maximum_standardized_mean_shift:
        reasons.append("standardized_mean_shift_exceeded")

    if std_ratio is None:
        if ref_std <= 1e-15 < rec_std:
            reasons.append("variance_emerged_from_constant_reference")
    elif std_ratio > policy.maximum_std_ratio:
        reasons.append("standard_deviation_ratio_exceeded")

    return DriftAssessment(
        status="DRIFT" if reasons else "STABLE",
        detected=bool(reasons),
        reference_count=len(ref),
        recent_count=len(rec),
        reference_mean=ref_mean,
        recent_mean=rec_mean,
        standardized_mean_shift=mean_shift,
        std_ratio=std_ratio,
        reasons=tuple(reasons),
        policy_version=policy.policy_version,
    )
