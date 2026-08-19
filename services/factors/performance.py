"""ALPHA BIST — Factor Performance Tracker (Nihai).

Detaylı performans metrikleri, factor exposure, benchmark karşılaştırma.
"""
from typing import Dict, Any, List, Optional
import numpy as np
import structlog

logger = structlog.get_logger()


def track_factor_performance(
    factor_returns: List[float],
    benchmark_returns: Optional[List[float]] = None,
    factor_name: str = "unknown",
    risk_free_rate: float = 0.15,  # Türkiye risk-free (yıllık)
) -> Dict[str, Any]:
    """Detaylı faktör performans analizi.

    Args:
        factor_returns: Faktör getiri serisi
        benchmark_returns: Benchmark getiri serisi (opsiyonel)
        factor_name: Faktör adı
        risk_free_rate: Risk-free oran (yıllık)

    Returns:
        Dict with 10+ performans metriği
    """
    if not factor_returns:
        return {"error": "Insufficient data", "factor": factor_name}

    f = np.array(factor_returns, dtype=float)
    n = len(f)

    if n < 2:
        return {"error": "Need at least 2 periods", "factor": factor_name}

    # Temel metrikler
    total_return = float(np.prod(1 + f) - 1)
    annual_return = float((1 + total_return) ** (252 / max(n, 1)) - 1)
    volatility = float(np.std(f, ddof=1) * np.sqrt(252))
    daily_rf = risk_free_rate / 252
    sharpe = (annual_return - risk_free_rate) / max(volatility, 0.001) if volatility > 1e-10 else 0.0

    # Risk metrikleri
    cumulative = np.cumprod(1 + f)
    peak = np.maximum.accumulate(cumulative)
    drawdown = (cumulative - peak) / peak
    max_drawdown = float(np.min(drawdown))

    # Sortino (sadece negatif getiriler)
    downside = f[f < 0]
    downside_std = float(np.std(downside, ddof=1) * np.sqrt(252)) if len(downside) > 1 else 0.001
    sortino = (annual_return - risk_free_rate) / max(downside_std, 0.001)

    # Calmar (annual return / max drawdown)
    calmar = annual_return / max(abs(max_drawdown), 0.001)

    # Win rate
    win_rate = float(np.sum(f > 0) / n * 100)

    # Best/worst day
    best_day = float(np.max(f))
    worst_day = float(np.min(f))

    # Skewness ve kurtosis
    try:
        from scipy.stats import skew, kurtosis
        if volatility > 1e-10:
            skewness = float(skew(f))
            kurt = float(kurtosis(f))
        else:
            skewness = 0.0
            kurt = 0.0
    except Exception as e:
        skewness = 0.0
        kurt = 0.0

    result = {
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
        b = np.array(benchmark_returns[:n], dtype=float)
        excess = f - b
        alpha = float(np.mean(excess) * 252)
        tracking_error = float(np.std(excess, ddof=1) * np.sqrt(252))
        info_ratio = alpha / max(tracking_error, 0.001)

        # Beta
        if n > 2:
            cov_matrix = np.cov(f, b)
            beta = float(cov_matrix[0, 1] / max(cov_matrix[1, 1], 0.0001))
        else:
            beta = 1.0

        # Treynor ratio
        treynor = (annual_return - risk_free_rate) / max(abs(beta), 0.001)

        result.update({
            "alpha": round(alpha, 4),
            "beta": round(beta, 4),
            "tracking_error": round(tracking_error, 4),
            "information_ratio": round(info_ratio, 4),
            "treynor_ratio": round(treynor, 4),
            "correlation": round(float(np.corrcoef(f, b)[0, 1]), 4),
        })

    return result


def track_factor_performance_batch(
    factors_data: Dict[str, List[float]],
    benchmark_returns: Optional[List[float]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Birden fazla faktör için toplu performans analizi.

    Args:
        factors_data: {factor_name: returns} sözlüğü
        benchmark_returns: Benchmark getiri serisi

    Returns:
        {factor_name: performance_metrics} sözlüğü
    """
    results = {}
    for name, returns in factors_data.items():
        results[name] = track_factor_performance(returns, benchmark_returns, name)
    return results
