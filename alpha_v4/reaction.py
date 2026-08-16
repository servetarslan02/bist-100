"""Event-reaction intelligence primitives.

These functions deliberately distinguish raw return from benchmark/sector-relative
reaction. A positive raw return is not automatically a positive event reaction.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReactionSnapshot:
    asset_return: float
    benchmark_return: float | None
    sector_return: float | None
    benchmark_relative: float | None
    sector_relative: float | None
    interpretation: str


def classify_reaction(
    *,
    asset_return: float,
    benchmark_return: float | None = None,
    sector_return: float | None = None,
    expected_direction: str | None = None,
    tolerance: float = 0.0025,
) -> ReactionSnapshot:
    """Classify market confirmation/absorption without pretending causality is proven."""
    benchmark_relative = (
        None if benchmark_return is None else asset_return - benchmark_return
    )
    sector_relative = None if sector_return is None else asset_return - sector_return

    relative_candidates = [
        v for v in (benchmark_relative, sector_relative) if v is not None
    ]
    relative_signal = (
        sum(relative_candidates) / len(relative_candidates)
        if relative_candidates
        else asset_return
    )

    if expected_direction is None:
        interpretation = "observed_reaction_only"
    else:
        direction = expected_direction.upper()
        if direction not in {"POSITIVE", "NEGATIVE"}:
            raise ValueError("expected_direction must be POSITIVE, NEGATIVE or None")

        if abs(relative_signal) <= tolerance:
            interpretation = "reaction_ambiguous"
        elif direction == "POSITIVE" and relative_signal > tolerance:
            interpretation = "good_news_confirmed_by_market"
        elif direction == "POSITIVE" and relative_signal < -tolerance:
            interpretation = "good_news_sold_or_rejected"
        elif direction == "NEGATIVE" and relative_signal < -tolerance:
            interpretation = "bad_news_accelerating"
        else:
            interpretation = "bad_news_absorbed"

    return ReactionSnapshot(
        asset_return=asset_return,
        benchmark_return=benchmark_return,
        sector_return=sector_return,
        benchmark_relative=benchmark_relative,
        sector_relative=sector_relative,
        interpretation=interpretation,
    )
