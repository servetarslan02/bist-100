"""ALPHA BIST — Statistical Significance Test.

t-distribution, Bonferroni düzeltmesi ve cross-sectional testler.
MacKinlay (1997) metodolojisi.

Sayısal kararlılık notları:
- float64 dtype zorunlu
- np.isfinite tek traversal NaN/Inf tespiti
- p_value aralık kontrolü [0, 1]
"""

from typing import Any

import numpy as np
import structlog
from scipy import stats

logger = structlog.get_logger()

# Varsayılan sabitler
MIN_OBS_FOR_TTEST: int = 3
MIN_OBS_FOR_CROSS_SECTIONAL: int = 2
SIGNIFICANCE_LEVEL: float = 0.05
STD_ERROR_THRESHOLD: float = 1e-10
DEFAULT_STATISTIC: float = 0.0
DEFAULT_P_VALUE: float = 1.0
ROUND_DECIMALS: int = 4
ROUND_DECIMALS_STDERR: int = 6


def _validate_float(value: float, name: str) -> None:
    """Float değer doğrulama — NaN/Inf kontrolü.

    Args:
        value: Doğrulanacak değer
        name: Değer adı

    Raises:
        ValueError: NaN veya Inf ise
    """
    if not np.isfinite(value):
        logger.error("istatistik_gecersiz_skaler", deger_ad=name, deger=value)
        raise ValueError(f"{name} değeri NaN veya Inf olamaz: {value}")


def _validate_array(arr: np.ndarray, name: str, min_len: int = 0) -> None:
    """Array doğrulama.

    Args:
        arr: Doğrulanacak array
        name: Array adı
        min_len: Minimum uzunluk

    Raises:
        TypeError: numpy array değilse
        ValueError: Boş, NaN/Inf içeriyorsa
    """
    if not isinstance(arr, np.ndarray):
        logger.error("istatistik_dizi_tip_hatasi", beklenti="np.ndarray", gercek=type(arr).__name__, dizi=name)
        raise TypeError(f"{name} numpy array olmalı, gelen tip: {type(arr).__name__}")

    if min_len > 0 and len(arr) < min_len:
        logger.error("istatistik_dizi_yetersiz", dizi=name, uzunluk=len(arr), minimum=min_len)
        raise ValueError(f"{name} yetersiz veri: {len(arr)}, minimum {min_len} gerekli.")

    if np.issubdtype(arr.dtype, np.number) and not np.all(np.isfinite(arr)):
        has_nan = bool(np.any(np.isnan(arr)))
        has_inf = bool(np.any(np.isinf(arr)))
        logger.error("istatistik_dizi_gecersiz_deger", dizi=name, nan_var=has_nan, inf_var=has_inf)
        raise ValueError(f"{name} dizisinde {'NaN' if has_nan else ''}{' ve ' if has_nan and has_inf else ''}{'Inf' if has_inf else ''} değeri var.")


def _validate_p_values(p_values: list[float], name: str = "p_values") -> None:
    """P-value listesi doğrulama — aralık [0, 1] ve NaN/Inf kontrolü.

    Args:
        p_values: P-value listesi
        name: Değer adı

    Raises:
        ValueError: Aralık dışı veya NaN/Inf değer varsa
    """
    for i, p in enumerate(p_values):
        if not np.isfinite(p):
            logger.error("istatistik_pvalue_gecersiz", index=i, deger=p)
            raise ValueError(f"{name}[{i}] geçersiz: {p}")
        if p < 0.0 or p > 1.0:
            logger.error("istatistik_pvalue_aralik_disi", index=i, deger=p)
            raise ValueError(f"{name}[{i}] aralık dışı [0,1]: {p}")


def test_significance(
    car: float,
    abnormal_returns: np.ndarray,
    n_params: int = 2,
) -> dict[str, Any]:
    """CAR'ın istatistiksel anlamlılığı — t-distribution.

    H0: CAR = 0 (event etkisi yok)
    H1: CAR ≠ 0 (event etkisi var)

    t = CAR / σ(CAR)
    σ(CAR) = σ(AR) × √n

    Args:
        car: Cumulative Abnormal Return
        abnormal_returns: AR dizisi (numpy array)
        n_params: Model parametre sayısı (market model = 2, FF3 = 4)

    Returns:
        Dict with t_statistic, p_value, significant, confidence_interval

    Raises:
        TypeError: abnormal_returns numpy array değilse
        ValueError: car NaN/Inf ise veya abnormal_returns NaN/Inf içeriyorsa
    """
    _validate_float(car, "car")
    _validate_array(abnormal_returns, "abnormal_returns")

    n = len(abnormal_returns)
    if n < MIN_OBS_FOR_TTEST:
        logger.warning("istatistik_yetersiz_gozlem", n=n, minimum=MIN_OBS_FOR_TTEST)
        return {
            "t_statistic": DEFAULT_STATISTIC,
            "p_value": DEFAULT_P_VALUE,
            "significant": False,
            "confidence_lower": DEFAULT_STATISTIC,
            "confidence_upper": DEFAULT_STATISTIC,
            "std_error": DEFAULT_STATISTIC,
            "n_obs": n,
        }

    # σ(AR) — residual standard error
    ar_std = float(np.std(abnormal_returns, ddof=1))

    # σ(CAR) = σ(AR) × √n
    car_std = ar_std * np.sqrt(n)

    # t-statistic
    t_stat = car / car_std if car_std > STD_ERROR_THRESHOLD else DEFAULT_STATISTIC

    # p-value — t-distribution (n - n_params derece serbestlik)
    df = max(n - n_params, 1)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=df))

    # %95 güven aralığı
    t_crit = stats.t.ppf(0.975, df=df)
    ci_lower = car - t_crit * car_std
    ci_upper = car + t_crit * car_std

    return {
        "t_statistic": round(float(t_stat), ROUND_DECIMALS),
        "p_value": round(float(p_value), ROUND_DECIMALS),
        "significant": bool(p_value < SIGNIFICANCE_LEVEL),
        "confidence_lower": round(float(ci_lower), ROUND_DECIMALS),
        "confidence_upper": round(float(ci_upper), ROUND_DECIMALS),
        "std_error": round(float(car_std), ROUND_DECIMALS_STDERR),
        "n_obs": n,
        "df": df,
    }


def test_significance_cross_sectional(
    cars: list[float],
) -> dict[str, Any]:
    """Cross-sectional t-test — birden fazla event için.

    H0: Mean CAR = 0
    t = mean(CAR) / (std(CAR) / √n)

    Args:
        cars: CAR değerleri listesi

    Returns:
        Dict with t_statistic, p_value, significant, mean_car, std_car

    Raises:
        ValueError: cars içinde NaN/Inf varsa
    """
    # NaN/Inf kontrolü
    for i, c in enumerate(cars):
        if not np.isfinite(c):
            logger.error("istatistik_capraz_gecersiz_car", index=i, deger=c)
            raise ValueError(f"cars[{i}] geçersiz: {c}")

    n = len(cars)
    if n < MIN_OBS_FOR_CROSS_SECTIONAL:
        logger.warning("istatistik_capraz_yetersiz", n=n)
        return {
            "t_statistic": DEFAULT_STATISTIC,
            "p_value": DEFAULT_P_VALUE,
            "significant": False,
            "mean_car": DEFAULT_STATISTIC,
            "std_car": DEFAULT_STATISTIC,
            "n_events": n,
        }

    cars_arr = np.array(cars, dtype=np.float64)
    mean_car = float(np.mean(cars_arr))
    std_car = float(np.std(cars_arr, ddof=1))
    std_error = std_car / np.sqrt(n)

    t_stat = mean_car / std_error if std_error > STD_ERROR_THRESHOLD else DEFAULT_STATISTIC

    df = n - 1
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=df))

    return {
        "t_statistic": round(float(t_stat), ROUND_DECIMALS),
        "p_value": round(float(p_value), ROUND_DECIMALS),
        "significant": bool(p_value < SIGNIFICANCE_LEVEL),
        "mean_car": round(float(mean_car), ROUND_DECIMALS),
        "std_car": round(float(std_car), ROUND_DECIMALS),
        "n_events": n,
        "df": df,
    }


def bonferroni_correction(p_values: list[float], alpha: float = SIGNIFICANCE_LEVEL) -> dict[str, Any]:
    """Bonferroni multiple testing düzeltmesi.

    Birden fazla hipotez testi yapıldığında Type I error'ı kontrol eder.
    Adjusted alpha = alpha / n_tests

    Args:
        p_values: Ham p-value'lar
        alpha: Anlamlılık seviyesi

    Returns:
        Dict with adjusted_alpha, significant_flags, n_tests

    Raises:
        ValueError: p_values aralık dışı veya NaN/Inf içeriyorsa
    """
    _validate_p_values(p_values, "p_values")

    n_tests = len(p_values)
    if n_tests == 0:
        return {"adjusted_alpha": alpha, "significant_flags": [], "n_tests": 0}

    adjusted_alpha = alpha / n_tests
    significant_flags = [bool(p < adjusted_alpha) for p in p_values]

    return {
        "adjusted_alpha": round(adjusted_alpha, ROUND_DECIMALS_STDERR),
        "significant_flags": significant_flags,
        "n_tests": n_tests,
        "n_significant": sum(significant_flags),
    }


def benjamini_hochberg_correction(p_values: list[float], alpha: float = SIGNIFICANCE_LEVEL) -> dict[str, Any]:
    """Benjamini-Hochberg FDR düzeltmesi (Bonferroni'den daha az muhafazakâr).

    Args:
        p_values: Ham p-value'lar
        alpha: FDR seviyesi

    Returns:
        Dict with significant_flags, adjusted_p_values, n_tests

    Raises:
        ValueError: p_values aralık dışı veya NaN/Inf içeriyorsa
    """
    _validate_p_values(p_values, "p_values")

    n_tests = len(p_values)
    if n_tests == 0:
        return {"significant_flags": [], "adjusted_p_values": [], "n_tests": 0}

    sorted_indices = np.argsort(p_values)
    sorted_p = np.array(p_values, dtype=np.float64)[sorted_indices]

    adjusted_p = np.zeros(n_tests, dtype=np.float64)
    for i in range(n_tests):
        adjusted_p[i] = sorted_p[i] * n_tests / (i + 1)

    for i in range(n_tests - 2, -1, -1):
        adjusted_p[i] = min(adjusted_p[i], adjusted_p[i + 1])

    adjusted_p = np.minimum(adjusted_p, 1.0)

    result_p = np.zeros(n_tests, dtype=np.float64)
    result_p[sorted_indices] = adjusted_p

    significant_flags = [bool(p < alpha) for p in result_p]

    return {
        "significant_flags": significant_flags,
        "adjusted_p_values": [round(float(p), ROUND_DECIMALS) for p in result_p],
        "n_tests": n_tests,
        "n_significant": sum(significant_flags),
    }


def wilcoxon_test(cars: list[float]) -> dict[str, Any]:
    """Wilcoxon signed-rank test — non-parametrik alternatif.

    Normal dağılmayan CAR'lar için kullanılır.

    Args:
        cars: CAR değerleri listesi

    Returns:
        Dict with statistic, p_value, significant

    Raises:
        ValueError: cars içinde NaN/Inf varsa
    """
    for i, c in enumerate(cars):
        if not np.isfinite(c):
            logger.error("istatistik_wilcoxon_gecersiz", index=i, deger=c)
            raise ValueError(f"cars[{i}] geçersiz: {c}")

    if len(cars) < MIN_OBS_FOR_CROSS_SECTIONAL:
        logger.warning("istatistik_wilcoxon_yetersiz", n=len(cars))
        return {"statistic": DEFAULT_STATISTIC, "p_value": DEFAULT_P_VALUE, "significant": False}

    try:
        stat, p_value = stats.wilcoxon(cars)
        return {
            "statistic": round(float(stat), ROUND_DECIMALS),
            "p_value": round(float(p_value), ROUND_DECIMALS),
            "significant": bool(p_value < SIGNIFICANCE_LEVEL),
        }
    except ValueError as e:
        # Tüm değerler aynıysa Wilcoxon hata verir
        logger.warning("istatistik_wilcoxon_atlandi", neden=str(e))
        return {"statistic": DEFAULT_STATISTIC, "p_value": DEFAULT_P_VALUE, "significant": False}
