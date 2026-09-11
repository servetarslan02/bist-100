"""ALPHA BIST — Factor Time-Series Analysis.

Faktör getiri serisi hesaplama, trend analizi, momentum ve mevsimsellik.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import numpy.typing as npt
import structlog
from scipy import stats as scipy_stats

logger = structlog.get_logger(__name__)

__all__ = [
    "calculate_factor_returns",
    "analyze_factor_trend",
    "calculate_factor_momentum",
    "detect_seasonality",
]

# --- Sabitler (magic number yok) ---

_P_VALUE_THRESHOLD: float = 0.05
_MIN_SEASONALITY_DATA: int = 60
_MONTHLY_TRADING_DAYS: int = 21
_MIN_MONTHLY_SAMPLES: int = 3
_DEFAULT_MOMENTUM_PERIODS: list[int] = [1, 5, 20, 60, 120]
_MIN_WINDOW_SIZE: int = 1


def _safe_float_array(values: Any, name: str = "unknown") -> npt.NDArray[np.float64]:
    """Değerleri güvenli float64 array'e çevirir; None, NaN, Inf temizler.

    Args:
        values: Dönüştürülecek değerler (list, array veya None).
        name: Loglama için alan adı.

    Returns:
        Temizlenmiş float64 numpy array.

    Raises:
        TypeError: values None ise.
        ValueError: values boş ise.
    """
    if values is None:
        raise TypeError(f"{name} parametresi None olamaz")
    arr = np.array(values, dtype=float)
    if arr.size == 0:
        raise ValueError(f"{name} parametresi boş olamaz")

    nan_count = int(np.isnan(arr).sum())
    inf_count = int(np.isinf(arr).sum())
    if nan_count > 0 or inf_count > 0:
        logger.warning(
            "time_series_dirty_values",
            field=name,
            nan_count=nan_count,
            inf_count=inf_count,
            action="replaced_with_zero",
        )
        arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)

    return arr


def calculate_factor_returns(
    factor_long: list[float] | None,
    factor_short: list[float] | None,
    method: str = "long_short",
) -> list[float]:
    """Faktör getiri serisi hesapla.

    Long-short: factor_return = long_return - short_return
    Long-only: factor_return = long_return

    Args:
        factor_long: Long portföy getirileri. None olamaz.
        factor_short: Short portföy getirileri. None olamaz.
        method: "long_short" veya "long_only".

    Returns:
        Faktör getiri serisi.

    Raises:
        TypeError: factor_long veya factor_short None ise.
        ValueError: method geçersiz ise.
    """
    if factor_long is None:
        raise TypeError("factor_long parametresi None olamaz")
    if factor_short is None:
        raise TypeError("factor_short parametresi None olamaz")
    if method not in ("long_short", "long_only"):
        raise ValueError(
            f"method 'long_short' veya 'long_only' olmalı, alınan: '{method}'"
        )

    try:
        long = _safe_float_array(factor_long, name="factor_long")
        short = _safe_float_array(factor_short, name="factor_short")
    except (TypeError, ValueError) as exc:
        logger.error("factor_returns_array_failed", error=str(exc))
        raise

    n = min(len(long), len(short))

    if n == 0:
        logger.warning("factor_returns_empty_after_clean")
        return []

    if method == "long_short":
        result = (long[:n] - short[:n]).tolist()
    else:
        result = long[:n].tolist()

    logger.info("factor_returns_calculated", method=method, n_periods=n)
    return result


def analyze_factor_trend(
    factor_returns: list[float] | None,
    window: int = 60,
) -> dict[str, Any]:
    """Faktör trend analizi.

    Son window periyodunda kümülatif getiriye lineer regresyon uygulayarak
    trend yönü, gücü ve istatistiksel anlamlılığını hesaplar.

    Args:
        factor_returns: Faktör getiri serisi. None olamaz.
        window: Analiz penceresi (pozitif tamsayı olmalı).

    Returns:
        Dict with trend_direction, trend_strength, slope, r_squared, p_value, n_periods.

    Raises:
        TypeError: factor_returns None ise.
        ValueError: window pozitif değilse.
    """
    if factor_returns is None:
        raise TypeError("factor_returns parametresi None olamaz")
    if not isinstance(window, int) or window < _MIN_WINDOW_SIZE:
        raise ValueError(f"window pozitif tamsayı olmalı, alınan: {window}")

    try:
        r = _safe_float_array(factor_returns, name="factor_returns")
    except (TypeError, ValueError) as exc:
        logger.error("trend_analysis_array_failed", error=str(exc))
        raise

    n = len(r)

    if n < window:
        logger.warning("trend_insufficient_data", data_length=n, required=window)
        return {
            "error": f"Yetersiz veri: {n} gözlem, en az {window} gerekli",
            "n": n,
            "trend_direction": "UNKNOWN",
            "trend_strength": 0.0,
            "slope": 0.0,
            "r_squared": 0.0,
            "p_value": 1.0,
            "n_periods": 0,
        }

    # Son window periyodu
    recent = r[-window:]
    cumulative = np.cumprod(1 + recent)

    # NaN/Inf kontrolü (kümülatif getiri)
    if np.any(np.isnan(cumulative)) or np.any(np.isinf(cumulative)):
        logger.warning("trend_cumulative_nan_inf", action="replaced")
        cumulative = np.nan_to_num(cumulative, nan=1.0, posinf=1.0, neginf=0.0)

    # Lineer regresyon
    x = np.arange(len(cumulative), dtype=float)
    try:
        slope, intercept, r_value, p_value, std_err = scipy_stats.linregress(x, cumulative)
    except Exception as exc:
        logger.error("trend_regression_failed", error=str(exc))
        raise ValueError(f"Trend regresyonu hesaplanamadı: {exc}") from exc

    # NaN/Inf kontrolü (regresyon sonuçları)
    if any(math.isnan(v) or math.isinf(v) for v in [slope, r_value, p_value]):
        logger.warning("trend_regression_nan_result")
        return {
            "trend_direction": "UNKNOWN",
            "trend_strength": 0.0,
            "slope": 0.0,
            "r_squared": 0.0,
            "p_value": 1.0,
            "n_periods": len(recent),
            "error": "Regresyon sonucu NaN/Inf",
        }

    # Trend yönü
    if slope > 0 and p_value < _P_VALUE_THRESHOLD:
        direction = "UP"
    elif slope < 0 and p_value < _P_VALUE_THRESHOLD:
        direction = "DOWN"
    else:
        direction = "FLAT"

    # Trend gücü (R²)
    strength = float(r_value ** 2)

    logger.info(
        "factor_trend_analyzed",
        direction=direction,
        strength=round(strength, 4),
        p_value=round(float(p_value), 4),
    )

    return {
        "trend_direction": direction,
        "trend_strength": round(strength, 4),
        "slope": round(float(slope), 6),
        "r_squared": round(strength, 4),
        "p_value": round(float(p_value), 4),
        "n_periods": len(recent),
    }


def calculate_factor_momentum(
    factor_returns: list[float] | None,
    periods: list[int] | None = None,
) -> dict[str, float | None]:
    """Faktör momentum hesaplama (çeşitli periyotlar).

    Her periyot için kümülatif getiri hesaplar. Yetersiz veri olan
    periyotlar için None döner.

    Args:
        factor_returns: Faktör getiri serisi. None olamaz.
        periods: Periyot listesi (pozitif tamsayılar). None ise varsayılan kullanılır.

    Returns:
        Dict with momentum for each period (None if insufficient data).

    Raises:
        TypeError: factor_returns None ise.
        ValueError: periods içinde pozitif olmayan tamsayı varsa.
    """
    if factor_returns is None:
        raise TypeError("factor_returns parametresi None olamaz")

    if periods is None:
        periods = _DEFAULT_MOMENTUM_PERIODS

    # Periyot doğrulama
    for p in periods:
        if not isinstance(p, int) or p < _MIN_WINDOW_SIZE:
            raise ValueError(
                f"periods içindeki değerler pozitif tamsayı olmalı, alınan: {p}"
            )

    try:
        r = _safe_float_array(factor_returns, name="factor_returns")
    except (TypeError, ValueError) as exc:
        logger.error("momentum_array_failed", error=str(exc))
        raise

    n = len(r)

    momentum: dict[str, float | None] = {}
    for p in periods:
        if n >= p:
            segment = r[-p:]
            # NaN/Inf kontrolü
            if np.any(np.isnan(segment)) or np.any(np.isinf(segment)):
                logger.warning("momentum_nan_inf_segment", period=p, action="skipped")
                momentum[f"mom_{p}d"] = None
                continue
            cum_ret = float(np.prod(1 + segment) - 1)
            # Sonuç kontrolü
            if math.isnan(cum_ret) or math.isinf(cum_ret):
                logger.warning("momentum_result_nan_inf", period=p)
                momentum[f"mom_{p}d"] = None
            else:
                momentum[f"mom_{p}d"] = round(cum_ret, 4)
        else:
            momentum[f"mom_{p}d"] = None

    logger.info("factor_momentum_calculated", periods=periods, n_periods=n)
    return momentum


def detect_seasonality(
    factor_returns: list[float] | None,
    period: int = 252,
) -> dict[str, Any]:
    """Faktör mevsimsellik analizi.

    Günlük getiri serisini aylık gruplara bölerek her ayın ortalama
    getirisini hesaplar ve en iyi/kötü ayı belirler.

    Args:
        factor_returns: Faktör getiri serisi (günlük). None olamaz.
        period: Mevsimsellik periyodu (bilgi amaçlı, aylık gruplama için
            _MONTHLY_TRADING_DAYS kullanılır).

    Returns:
        Dict with monthly_avg_returns, best_month, worst_month, n_months.

    Raises:
        TypeError: factor_returns None ise.
        ValueError: factor_returns boş ise.
    """
    if factor_returns is None:
        raise TypeError("factor_returns parametresi None olamaz")

    try:
        r = _safe_float_array(factor_returns, name="factor_returns")
    except (TypeError, ValueError) as exc:
        logger.error("seasonality_array_failed", error=str(exc))
        raise

    n = len(r)

    if n < _MIN_SEASONALITY_DATA:
        logger.warning(
            "seasonality_insufficient_data",
            data_length=n,
            required=_MIN_SEASONALITY_DATA,
        )
        return {
            "error": f"Yetersiz veri: {n} gözlem, en az {_MIN_SEASONALITY_DATA} gerekli",
            "monthly_avg_returns": {},
            "best_month": None,
            "worst_month": None,
            "n_months": 0,
        }

    # Aylık getiri (yaklaşık 21 gün/ay)
    monthly_returns: list[float] = []
    for i in range(0, n - _MONTHLY_TRADING_DAYS + 1, _MONTHLY_TRADING_DAYS):
        month_slice = r[i : i + _MONTHLY_TRADING_DAYS]
        # NaN/Inf kontrolü
        if np.any(np.isnan(month_slice)) or np.any(np.isinf(month_slice)):
            logger.warning("seasonality_nan_inf_month", month_idx=len(monthly_returns))
            monthly_returns.append(0.0)
            continue
        month_ret = float(np.prod(1 + month_slice) - 1)
        if math.isnan(month_ret) or math.isinf(month_ret):
            logger.warning("seasonality_month_result_nan", month_idx=len(monthly_returns))
            monthly_returns.append(0.0)
        else:
            monthly_returns.append(month_ret)

    if len(monthly_returns) < _MIN_MONTHLY_SAMPLES:
        logger.warning(
            "seasonality_insufficient_months",
            n_months=len(monthly_returns),
            required=_MIN_MONTHLY_SAMPLES,
        )
        return {
            "error": f"Yetersiz aylık veri: {len(monthly_returns)} ay, en az {_MIN_MONTHLY_SAMPLES} gerekli",
            "monthly_avg_returns": {},
            "best_month": None,
            "worst_month": None,
            "n_months": len(monthly_returns),
        }

    # Ay bazlı ortalama
    month_names = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
    monthly_avg: dict[str, list[float]] = {}
    for i, ret in enumerate(monthly_returns):
        month_idx = i % 12
        month_name = month_names[month_idx]
        if month_name not in monthly_avg:
            monthly_avg[month_name] = []
        monthly_avg[month_name].append(ret)

    monthly_mean: dict[str, float] = {
        k: round(float(np.mean(v)), 4) for k, v in monthly_avg.items()
    }

    best_month = max(monthly_mean, key=monthly_mean.get)
    worst_month = min(monthly_mean, key=monthly_mean.get)

    logger.info(
        "seasonality_detected",
        best_month=best_month,
        worst_month=worst_month,
        n_months=len(monthly_returns),
    )

    return {
        "monthly_avg_returns": monthly_mean,
        "best_month": best_month,
        "best_month_return": monthly_mean[best_month],
        "worst_month": worst_month,
        "worst_month_return": monthly_mean[worst_month],
        "n_months": len(monthly_returns),
    }
