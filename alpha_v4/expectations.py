"""Point-in-time expectation and surprise primitives for event intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class NumericExpectation:
    metric: str
    expected_value: float
    known_at: datetime
    source_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.metric.strip():
            raise ValueError("metric is required")
        if not self.source_event_ids:
            raise ValueError("expectation provenance is required")


@dataclass(frozen=True)
class NumericObservation:
    metric: str
    observed_value: float
    event_time: datetime
    known_at: datetime
    source_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.metric.strip():
            raise ValueError("metric is required")
        if self.known_at < self.event_time:
            raise ValueError("observation cannot be known before event_time")
        if not self.source_event_ids:
            raise ValueError("observation provenance is required")


@dataclass(frozen=True)
class SurpriseResult:
    metric: str
    expected_value: float
    observed_value: float
    absolute_surprise: float
    relative_surprise: float | None
    classification: str


def compare_expectation(
    expectation: NumericExpectation,
    observation: NumericObservation,
    *,
    absolute_tolerance: float,
) -> SurpriseResult:
    """Compare only a genuinely pre-event expectation with the observed value."""
    if expectation.metric != observation.metric:
        raise ValueError("expectation and observation metric mismatch")
    if expectation.known_at >= observation.event_time:
        raise ValueError("expectation must have been known before event_time")
    if absolute_tolerance < 0:
        raise ValueError("absolute_tolerance cannot be negative")

    surprise = observation.observed_value - expectation.expected_value
    denominator = abs(expectation.expected_value)
    relative = None if denominator == 0 else surprise / denominator

    if abs(surprise) <= absolute_tolerance:
        classification = "IN_LINE"
    elif surprise > 0:
        classification = "ABOVE_EXPECTATION"
    else:
        classification = "BELOW_EXPECTATION"

    return SurpriseResult(
        metric=expectation.metric,
        expected_value=expectation.expected_value,
        observed_value=observation.observed_value,
        absolute_surprise=surprise,
        relative_surprise=relative,
        classification=classification,
    )
