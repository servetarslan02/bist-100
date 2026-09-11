"""ALPHA BIST — Factor Performance Tracker (Nihai).

Detaylı performans metrikleri, factor exposure, benchmark karşılaştırma.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

__all__ = ["track_factor_performance", "track_factor_performance_batch"]

# Varsayılan risk-free oran (Türkiye yıllık)
_DEFAULT_RISK_FREE_RATE: float = 0.15

# Bölünme hatası koruması
_MIN_DENOMINATOR: float = 1e-3

# Yıllık iş günü
_TRADING_DAYS_PER_YEAR: int = 252


def _safe_float(value: Any, default: float = 0.0, name: str = "unknown") -> float:
    """Değeri güvenli float'a çevirir; None, NaN veya Inf için varsayılan döndürür.

    Args:
        value: Dönüştürülecek değer.
        default: Hata durumunda dönecek varsayılan değer.
        name: Loglama için alan adı.

    Returns:
        Güvenli float değeri.
    """
    if value is None:
        logger.warning("performance_none_value", field=name, default=default)
        return default
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            logger.warning("performance_nan_or_inf", field=name, value=value, default=default)
            return default
        return result
    except (ValueError, TypeError) as exc:
        logger.warning("performance_type_conversion_failed", field=name, value=value, error=str(exc), default=default)
        return default


def _clean_array(arr: np.ndarray) -> np.ndarray:
    """Array'deki NaN ve Inf değerleri temizler.

    Args:
        arr: Temizlenecek numpy array.

    Returns:
        Temizlenmiş array (NaN/Inf olmayan değerler).
    """
    return arr[np.isfinite(arr)]


def track_factor_performance(
    factor_returns: list[float] | None,
    benchmark_returns: list[float] | None = None,
    factor_name: str = "unknown",
    risk_free_rate: float = _DEFAULT_RISK_FREE_RATE,
) -> dict[str, Any]:
    """Detaylı faktör performans analizi.

    Args:
        factor_returns: Faktör getiri serisi (günlük).
        benchmark_returns: Benchmark getiri serisi (opsiyonel).
        factor_name: Faktör adı.
        risk_free_rate: Risk-free oran (yıllık).

    Returns:
        Dict with 14+ performans metriği: factor, n_periods, total_return,
        annual_return, volatility, sharpe_ratio, sortino_ratio, calmar_ratio,
        max_drawdown, win_rate, best_day, worst_day, skewness, kurtosis.
        Benchmark verisi varsa +6: alpha, beta, tracking_error,
        information_ratio, treynor_ratio, correlation.

    Raises:
        TypeError: factor_returns None veya list değilse.
    """
    if factor_returns is None:
        raise TypeError("factor_returns parametresi None olamaz")
    if not isinstance(factor_returns, list):
        raise TypeError(f"factor_returns list olmalı, alınan tip: {type(factor_returns).__name__}")
    if len(factor_returns) < 2:
        return {"error": "Need at least 2 periods", "factor": factor_name}

    f_raw = np.array(factor_returns, dtype=float)
    f = _clean_array(f_raw)
    n = len(f)

    if n < 2:
        return {"error": "Need at least 2 valid periods", "factor": factor_name}

    # Temel metrikler
    total_return = float(np.prod(1 + f) - 1)
    annual_return = float((1 + total_return) ** (_TRADING_DAYS_PER_YEAR / max(n, 1)) - 1)
    volatility = float(np.std(f, ddof=1) * np.sqrt(_TRADING_DAYS_PER_YEAR))
    sharpe = (
        (annual_return - risk_free_rate) / max(volatility, _MIN_DENOMINATOR)
        if volatility > 1e-10
        else 0.0
    )

    # Risk metrikleri
    cumulative = np.cumprod(1 + f)
    peak = np.maximum.accumulate(cumulative)
    # peak=0 koruması (ilk getiri -100% ise)
    peak = np.where(peak == 0, 1.0, peak)
    drawdown = (cumulative - peak) / peak
    max_drawdown = float(np.min(drawdown))

    # Sortino (downside deviation)
    daily_rf = risk_free_rate / _TRADING_DAYS_PER_YEAR
    downside_diff = np.minimum(f - daily_rf, 0.0)
    downside_dev = float(np.sqrt(np.mean(downside_diff**2)) * np.sqrt(_TRADING_DAYS_PER_YEAR))
    sortino = (annual_return - risk_free_rate) / max(downside_dev, _MIN_DENOMINATOR)

    # Calmar (annual return / max drawdown)
    calmar = annual_return / max(abs(max_drawdown), _MIN_DENOMINATOR)

    # Win rate
    win_rate = float(np.sum(f > 0) / n * 100)

    # Best/worst day
    best_day = float(np.max(f))
    worst_day = float(np.min(f))

    # Skewness ve kurtosis
    try:
        from scipy.stats import kurtosis, skew

        if volatility > 1e-10:
            skewness = float(skew(f))
            kurt = float(kurtosis(f))
        else:
            skewness = 0.0
            kurt = 0.0
    except ImportError:
        skewness = 0.0
        kurt = 0.0

    result: dict[str, Any] = {
        "factor": factor_name,
        "n_periods": n,
        "total_return": round(total_return, 4),
        "annual_return": round(annual_return, 4),
        "volatility": round(volatility, 4),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "calmar_ratio": round(calmar, 4),
        "max_drawdown": round(max_drawdown, 4),
        "win_rate": round(win_rate, 1),
        "best_day": round(best_day, 4),
        "worst_day": round(worst_day, 4),
        "skewness": round(skewness, 4),
        "kurtosis": round(kurt, 4),
    }

    # Benchmark karşılaştırma
    if benchmark_returns and len(benchmark_returns) >= n:
        b_raw = np.array(benchmark_returns[:n], dtype=float)
        b = _clean_array(b_raw)
        if len(b) >= n:
            excess = f - b
            alpha = float(np.mean(excess) * _TRADING_DAYS_PER_YEAR)
            tracking_error = float(np.std(excess, ddof=1) * np.sqrt(_TRADING_DAYS_PER_YEAR))
            info_ratio = alpha / max(tracking_error, _MIN_DENOMINATOR)

            # Beta: Cov(Rp, Rm) / Var(Rm)
            if n >= 3:
                cov_matrix = np.cov(f, b)
                var_b = cov_matrix[1, 1]
                beta = float(cov_matrix[0, 1] / var_b) if var_b > 1e-10 else 0.0
            else:
                beta = 0.0

            # Treynor ratio: (Rp - Rf) / beta
            # Beta ~0 ise Treynor tanımsız → None
            if abs(beta) > 1e-6:
                treynor = (annual_return - risk_free_rate) / beta
            else:
                treynor = None

            # Korelasyon — std=0 koruması
            if np.std(f) > 1e-10 and np.std(b) > 1e-10:
                correlation = float(np.corrcoef(f, b)[0, 1])
            else:
                correlation = 0.0

            result.update({
                "alpha": round(alpha, 4),
                "beta": round(beta, 4),
                "tracking_error": round(tracking_error, 4),
                "information_ratio": round(info_ratio, 4),
                "treynor_ratio": round(treynor, 4) if treynor is not None else None,
                "correlation": round(correlation, 4),
            })

    return result


def track_factor_performance_batch(
    factors_data: dict[str, list[float]] | None,
    benchmark_returns: list[float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Birden fazla faktör için toplu performans analizi.

    Args:
        factors_data: {factor_name: returns} sözlüğü.
        benchmark_returns: Benchmark getiri serisi.

    Returns:
        {factor_name: performance_metrics} sözlüğü.

    Raises:
        TypeError: factors_data None veya dict değilse.
    """
    if factors_data is None:
        raise TypeError("factors_data parametresi None olamaz")
    if not isinstance(factors_data, dict):
        raise TypeError(f"factors_data dict olmalı, alınan tip: {type(factors_data).__name__}")

    results: dict[str, dict[str, Any]] = {}
    for name, returns in factors_data.items():
        results[name] = track_factor_performance(returns, benchmark_returns, name)
    return results
