"""Mask-first market data validation for ALPHA v4."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import log
from typing import Iterable, List, Optional, Tuple

from .contracts import RawBar, ValidationStatus


@dataclass(frozen=True)
class BarValidation:
    status: ValidationStatus
    reasons: Tuple[str, ...]

    @property
    def usable_for_features(self) -> bool:
        return self.status is ValidationStatus.VALID


def validate_raw_bar(
    bar: RawBar,
    *,
    decision_time: Optional[datetime] = None,
    freshness_limit: timedelta = timedelta(days=5),
    enforce_freshness: bool = True,
) -> BarValidation:
    """Validate a raw observation before dependent features are calculated.

    ``freshness`` is a state/serving concept, not a reason to invalidate legitimate
    historical observations inside a lookback window. Callers computing historical
    series therefore disable freshness while retaining point-in-time, structural and
    tradability checks.

    Exchange-specific price-limit rules are deliberately not guessed from OHLC alone;
    authoritative market-status data must set ``is_tradable`` upstream.
    """
    decision_time = decision_time or datetime.now(timezone.utc)
    reasons: List[str] = []

    if bar.observed_at > decision_time:
        return BarValidation(ValidationStatus.NOT_YET_KNOWN, ("observed_after_decision_time",))

    values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
    if any(v is None for v in values):
        return BarValidation(ValidationStatus.MISSING, ("missing_ohlcv",))

    assert bar.open is not None
    assert bar.high is not None
    assert bar.low is not None
    assert bar.close is not None
    assert bar.volume is not None

    if any(v < 0 for v in (bar.open, bar.high, bar.low, bar.close, bar.volume)):
        reasons.append("negative_ohlcv")
    if min(bar.open, bar.high, bar.low, bar.close) <= 0:
        reasons.append("non_positive_price")
    if bar.low > bar.high:
        reasons.append("low_above_high")
    if not (bar.low <= bar.open <= bar.high):
        reasons.append("open_outside_range")
    if not (bar.low <= bar.close <= bar.high):
        reasons.append("close_outside_range")

    if reasons:
        return BarValidation(ValidationStatus.INVALID, tuple(reasons))

    if not bar.is_tradable:
        return BarValidation(ValidationStatus.UNTRADABLE, ("upstream_market_status_untradable",))

    if enforce_freshness and decision_time - bar.observed_at > freshness_limit:
        return BarValidation(ValidationStatus.STALE, ("observation_stale",))

    return BarValidation(ValidationStatus.VALID, ())


def masked_log_returns(
    bars: Iterable[RawBar],
    *,
    decision_time: datetime,
    freshness_limit: timedelta = timedelta(days=5),
) -> List[Optional[float]]:
    """Compute returns only when both adjacent observations were valid first.

    Historical observations are not rejected merely because they are older than the
    serving freshness limit. They are still rejected for future knowledge, missing or
    invalid values, or explicit untradability. Freshness of the *current state* should
    be checked separately with ``validate_raw_bar(..., enforce_freshness=True)``.
    """
    ordered = sorted(bars, key=lambda b: b.timestamp)
    result: List[Optional[float]] = [None] * len(ordered)

    validations = [
        validate_raw_bar(
            b,
            decision_time=decision_time,
            freshness_limit=freshness_limit,
            enforce_freshness=False,
        )
        for b in ordered
    ]

    for idx in range(1, len(ordered)):
        previous = ordered[idx - 1]
        current = ordered[idx]
        if not (validations[idx - 1].usable_for_features and validations[idx].usable_for_features):
            continue
        assert previous.close is not None and current.close is not None
        result[idx] = log(current.close / previous.close)

    return result
