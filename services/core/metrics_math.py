"""
ALPHA BIST - Metrics Math Library

Centralized mathematical and financial metrics for Backtest and Learning modules.
Avoids DRY violations and ensures consistency across the platform.
"""

import numpy as np


def calculate_sharpe_ratio(returns: np.ndarray, risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    """Yıllıklandırılmış Sharpe Oranı."""
    if len(returns) == 0:
        return 0.0
    excess_returns = returns - risk_free_rate / periods_per_year
    std_dev = np.std(excess_returns)
    if std_dev == 0:
        return 0.0
    return float(np.mean(excess_returns) / std_dev * np.sqrt(periods_per_year))


def calculate_sortino_ratio(returns: np.ndarray, risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    """Yıllıklandırılmış Sortino Oranı (sadece negatif sapma)."""
    if len(returns) == 0:
        return 0.0
    excess_returns = returns - risk_free_rate / periods_per_year
    downside_returns = excess_returns[excess_returns < 0]
    downside_std = np.std(downside_returns) if len(downside_returns) > 0 else 0
    if downside_std == 0:
        return 0.0
    return float(np.mean(excess_returns) / downside_std * np.sqrt(periods_per_year))


def calculate_max_drawdown(returns: np.ndarray) -> float:
    """Maksimum Drawdown (yüzdesel)."""
    if len(returns) == 0:
        return 0.0
    cum_returns = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(cum_returns)
    drawdown = (cum_returns - peak) / peak
    return float(np.min(drawdown))


def calculate_win_rate(returns: np.ndarray) -> float:
    """Kazanma Oranı (Win Rate)."""
    if len(returns) == 0:
        return 0.0
    wins = np.sum(returns > 0)
    return float(wins / len(returns))


def calculate_ic(scores: np.ndarray, actuals: np.ndarray) -> float:
    """Information Coefficient (IC) - Tahmin ve gerçekleşme korelasyonu."""
    if len(scores) < 5 or len(actuals) < 5:
        return 0.0
    try:
        ic = np.corrcoef(scores, actuals)[0, 1]
        return float(0.0 if np.isnan(ic) else ic)
    except Exception:
        return 0.0
