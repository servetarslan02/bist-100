"""Performance metrics for ALPHA v4 paper/research evaluation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from statistics import stdev


@dataclass(frozen=True)
class EquityPoint:
    timestamp: datetime
    equity: float

    def __post_init__(self) -> None:
        if self.equity <= 0:
            raise ValueError("equity must be positive")


@dataclass(frozen=True)
class PerformanceSummary:
    total_return: float
    cagr: float | None
    annualized_volatility: float | None
    sharpe: float | None
    sortino: float | None
    max_drawdown: float
    max_drawdown_start: datetime
    max_drawdown_end: datetime
    calmar: float | None
    observation_count: int


def _ordered_points(points: Iterable[EquityPoint]) -> tuple[EquityPoint, ...]:
    ordered = tuple(sorted(points, key=lambda item: item.timestamp))
    if len(ordered) < 2:
        raise ValueError("at least two equity points are required")
    if len({point.timestamp for point in ordered}) != len(ordered):
        raise ValueError("equity timestamps must be unique")
    return ordered


def summarize_performance(
    points: Iterable[EquityPoint],
    *,
    periods_per_year: float,
    annual_risk_free_rate: float = 0.0,
) -> PerformanceSummary:
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")
    ordered = _ordered_points(points)

    returns = [
        ordered[index].equity / ordered[index - 1].equity - 1.0
        for index in range(1, len(ordered))
    ]
    total_return = ordered[-1].equity / ordered[0].equity - 1.0

    elapsed_seconds = (ordered[-1].timestamp - ordered[0].timestamp).total_seconds()
    if elapsed_seconds <= 0:
        raise ValueError("equity time range must be positive")
    years = elapsed_seconds / (365.2425 * 24 * 60 * 60)
    cagr = (
        (ordered[-1].equity / ordered[0].equity) ** (1.0 / years) - 1.0
        if years > 0
        else None
    )

    annualized_volatility = None
    sharpe = None
    sortino = None
    if len(returns) >= 2:
        period_rf = (1.0 + annual_risk_free_rate) ** (1.0 / periods_per_year) - 1.0
        excess = [value - period_rf for value in returns]
        volatility = stdev(returns)
        annualized_volatility = volatility * sqrt(periods_per_year)
        excess_stdev = stdev(excess)
        if excess_stdev > 0:
            sharpe = (sum(excess) / len(excess)) / excess_stdev * sqrt(periods_per_year)

        downside_squares = [min(value, 0.0) ** 2 for value in excess]
        downside_deviation = sqrt(sum(downside_squares) / len(downside_squares))
        if downside_deviation > 0:
            sortino = (
                (sum(excess) / len(excess))
                / downside_deviation
                * sqrt(periods_per_year)
            )

    peak_equity = ordered[0].equity
    peak_time = ordered[0].timestamp
    max_drawdown = 0.0
    max_start = peak_time
    max_end = peak_time
    for point in ordered:
        if point.equity > peak_equity:
            peak_equity = point.equity
            peak_time = point.timestamp
        drawdown = point.equity / peak_equity - 1.0
        if drawdown < max_drawdown:
            max_drawdown = drawdown
            max_start = peak_time
            max_end = point.timestamp

    drawdown_magnitude = abs(max_drawdown)
    calmar = None
    if cagr is not None and drawdown_magnitude > 0:
        calmar = cagr / drawdown_magnitude

    return PerformanceSummary(
        total_return=total_return,
        cagr=cagr,
        annualized_volatility=annualized_volatility,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=drawdown_magnitude,
        max_drawdown_start=max_start,
        max_drawdown_end=max_end,
        calmar=calmar,
        observation_count=len(ordered),
    )
