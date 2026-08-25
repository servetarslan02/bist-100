"""ALPHA BIST — Factor Time-Series Analysis.

Faktör getiri serisi hesaplama, trend analizi, mevsimsellik.
"""
from typing import Dict, Any, List
import numpy as np
from scipy import stats as scipy_stats
import structlog

logger = structlog.get_logger()


def calculate_factor_returns(
    factor_long: List[float],
    factor_short: List[float],
    method: str = "long_short",
) -> List[float]:
    """Faktör getiri serisi hesapla.

    Long-short: factor_return = long_return - short_return
    Long-only: factor_return = long_return

    Args:
        factor_long: Long portföy getirileri
        factor_short: Short portföy getirileri
        method: "long_short" veya "long_only"

    Returns:
        Faktör getiri serisi
    """
    long = np.array(factor_long, dtype=float)
    short = np.array(factor_short, dtype=float)
    n = min(len(long), len(short))

    if method == "long_short":
        return (long[:n] - short[:n]).tolist()
    else:
        return long[:n].tolist()


def analyze_factor_trend(
    factor_returns: List[float],
    window: int = 60,
) -> Dict[str, Any]:
    """Faktör trend analizi.

    Args:
        factor_returns: Faktör getiri serisi
        window: Analiz penceresi

    Returns:
        Dict with trend_direction, trend_strength, slope, r_squared
    """
    r = np.array(factor_returns, dtype=float)
    n = len(r)

    if n < window:
        return {"error": "Insufficient data", "n": n}

    # Son window periyodu
    recent = r[-window:]
    cumulative = np.cumprod(1 + recent)

    # Lineer regresyon
    x = np.arange(len(cumulative))
    slope, intercept, r_value, p_value, std_err = scipy_stats.linregress(x, cumulative)

    # Trend yönü
    if slope > 0 and p_value < 0.05:
        direction = "UP"
    elif slope < 0 and p_value < 0.05:
        direction = "DOWN"
    else:
        direction = "FLAT"

    # Trend gücü (R²)
    strength = float(r_value ** 2)

    return {
        "trend_direction": direction,
        "trend_strength": round(strength, 4),
        "slope": round(float(slope), 6),
        "r_squared": round(strength, 4),
        "p_value": round(float(p_value), 4),
        "n_periods": len(recent),
    }


def calculate_factor_momentum(
    factor_returns: List[float],
    periods: List[int] = None,
) -> Dict[str, float]:
    """Faktör momentum hesaplama (çeşitli periyotlar).

    Args:
        factor_returns: Faktör getiri serisi
        periods: Periyot listesi (varsayılan: [1, 5, 20, 60, 120])

    Returns:
        Dict with momentum for each period
    """
    if periods is None:
        periods = [1, 5, 20, 60, 120]

    r = np.array(factor_returns, dtype=float)
    n = len(r)

    momentum = {}
    for p in periods:
        if n >= p:
            cum_ret = float(np.prod(1 + r[-p:]) - 1)
            momentum[f"mom_{p}d"] = round(cum_ret, 4)
        else:
            momentum[f"mom_{p}d"] = None

    return momentum


def detect_seasonality(
    factor_returns: List[float],
    period: int = 252,
) -> Dict[str, Any]:
    """Faktör mevsimsellik analizi.

    Args:
        factor_returns: Faktör getiri serisi (günlük)
        period: Mevsimsellik periyodu (252 = yıllık)

    Returns:
        Dict with monthly_returns, best_month, worst_month
    """
    r = np.array(factor_returns, dtype=float)
    n = len(r)

    if n < 60:
        return {"error": "Insufficient data"}

    # Aylık getiri (yaklaşık 21 gün/ay)
    monthly_returns = []
    for i in range(0, n - 20, 21):
        month_ret = float(np.prod(1 + r[i:i + 21]) - 1)
        monthly_returns.append(month_ret)

    if len(monthly_returns) < 3:
        return {"error": "Insufficient monthly data"}

    # Ay bazlı ortalama
    month_names = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
    monthly_avg = {}
    for i, ret in enumerate(monthly_returns):
        month_idx = i % 12
        month_name = month_names[month_idx]
        if month_name not in monthly_avg:
            monthly_avg[month_name] = []
        monthly_avg[month_name].append(ret)

    monthly_mean = {k: round(float(np.mean(v)), 4) for k, v in monthly_avg.items()}

    best_month = max(monthly_mean, key=monthly_mean.get)
    worst_month = min(monthly_mean, key=monthly_mean.get)

    return {
        "monthly_avg_returns": monthly_mean,
        "best_month": best_month,
        "best_month_return": monthly_mean[best_month],
        "worst_month": worst_month,
        "worst_month_return": monthly_mean[worst_month],
        "n_months": len(monthly_returns),
    }
