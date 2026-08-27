"""ALPHA BIST — Statistical Significance Test.

t-distribution, Bonferroni düzeltmesi ve cross-sectional testler.
MacKinlay (1997) metodolojisi.
"""

import numpy as np
import structlog
from scipy import stats

logger = structlog.get_logger()


def test_significance(
    car: float,
    abnormal_returns: np.ndarray,
    n_params: int = 2,
) -> dict[str, float]:
    """CAR'ın istatistiksel anlamlılığı — t-distribution.

    H0: CAR = 0 (event etkisi yok)
    H1: CAR ≠ 0 (event etkisi var)

    t = CAR / σ(CAR)
    σ(CAR) = σ(AR) × √n

    Args:
        car: Cumulative Abnormal Return
        abnormal_returns: AR dizisi
        n_params: Model parametre sayısı (market model = 2, FF3 = 4)

    Returns:
        Dict with t_statistic, p_value, significant, confidence_interval
    """
    n = len(abnormal_returns)

    if n < 3:
        return {
            "t_statistic": 0.0,
            "p_value": 1.0,
            "significant": False,
            "confidence_lower": 0.0,
            "confidence_upper": 0.0,
            "std_error": 0.0,
            "n_obs": n,
        }

    # σ(AR) — residual standard error
    ar_std = np.std(abnormal_returns, ddof=1)

    # σ(CAR) = σ(AR) × √n
    car_std = ar_std * np.sqrt(n)

    # t-statistic
    t_stat = car / car_std if car_std > 1e-10 else 0.0

    # p-value — t-distribution (n - n_params derece serbestlik)
    df = n - n_params
    if df < 1:
        df = 1
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=df))

    # %95 güven aralığı
    t_crit = stats.t.ppf(0.975, df=df)
    ci_lower = car - t_crit * car_std
    ci_upper = car + t_crit * car_std

    return {
        "t_statistic": round(float(t_stat), 4),
        "p_value": round(float(p_value), 4),
        "significant": bool(p_value < 0.05),
        "confidence_lower": round(float(ci_lower), 4),
        "confidence_upper": round(float(ci_upper), 4),
        "std_error": round(float(car_std), 6),
        "n_obs": n,
        "df": df,
    }


def test_significance_cross_sectional(
    cars: list[float],
) -> dict[str, float]:
    """Cross-sectional t-test — birden fazla event için.

    H0: Mean CAR = 0
    t = mean(CAR) / (std(CAR) / √n)

    Args:
        cars: CAR değerleri listesi

    Returns:
        Dict with t_statistic, p_value, significant, mean_car, std_car
    """
    n = len(cars)

    if n < 2:
        return {
            "t_statistic": 0.0,
            "p_value": 1.0,
            "significant": False,
            "mean_car": 0.0,
            "std_car": 0.0,
            "n_events": n,
        }

    cars_arr = np.array(cars)
    mean_car = np.mean(cars_arr)
    std_car = np.std(cars_arr, ddof=1)
    std_error = std_car / np.sqrt(n)

    t_stat = mean_car / std_error if std_error > 0 else 0.0

    # t-distribution
    df = n - 1
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=df))

    return {
        "t_statistic": round(float(t_stat), 4),
        "p_value": round(float(p_value), 4),
        "significant": bool(p_value < 0.05),
        "mean_car": round(float(mean_car), 4),
        "std_car": round(float(std_car), 4),
        "n_events": n,
        "df": df,
    }


def bonferroni_correction(
    p_values: list[float], alpha: float = 0.05
) -> dict[str, any]:
    """Bonferroni multiple testing düzeltmesi.

    Birden fazla hipotez testi yapıldığında Type I error'ı kontrol eder.

    Adjusted alpha = alpha / n_tests

    Args:
        p_values: Ham p-value'lar
        alpha: Anlamlılık seviyesi

    Returns:
        Dict with adjusted_alpha, significant_flags, n_tests
    """
    n_tests = len(p_values)

    if n_tests == 0:
        return {"adjusted_alpha": alpha, "significant_flags": [], "n_tests": 0}

    adjusted_alpha = alpha / n_tests
    significant_flags = [p < adjusted_alpha for p in p_values]

    return {
        "adjusted_alpha": round(adjusted_alpha, 6),
        "significant_flags": significant_flags,
        "n_tests": n_tests,
        "n_significant": sum(significant_flags),
    }


def benjamini_hochberg_correction(
    p_values: list[float], alpha: float = 0.05
) -> dict[str, any]:
    """Benjamini-Hochberg FDR düzeltmesi (Bonferroni'den daha az muhafazakâr).

    Args:
        p_values: Ham p-value'lar
        alpha: FDR seviyesi

    Returns:
        Dict with significant_flags, adjusted_p_values, n_tests
    """
    n_tests = len(p_values)

    if n_tests == 0:
        return {"significant_flags": [], "adjusted_p_values": [], "n_tests": 0}

    # Sırala
    sorted_indices = np.argsort(p_values)
    sorted_p = np.array(p_values)[sorted_indices]

    # BH adjusted p-values
    adjusted_p = np.zeros(n_tests)
    for i in range(n_tests):
        adjusted_p[i] = sorted_p[i] * n_tests / (i + 1)

    # Cumulative minimum (geriye doğru)
    for i in range(n_tests - 2, -1, -1):
        adjusted_p[i] = min(adjusted_p[i], adjusted_p[i + 1])

    # 1.0'dan büyük olanları düzelt
    adjusted_p = np.minimum(adjusted_p, 1.0)

    # Orijinal sıraya geri döndür
    result_p = np.zeros(n_tests)
    result_p[sorted_indices] = adjusted_p

    significant_flags = [bool(p < alpha) for p in result_p]

    return {
        "significant_flags": significant_flags,
        "adjusted_p_values": [round(float(p), 4) for p in result_p],
        "n_tests": n_tests,
        "n_significant": sum(significant_flags),
    }


def wilcoxon_test(cars: list[float]) -> dict[str, float]:
    """Wilcoxon signed-rank test — non-parametrik alternatif.

    Normal dağılmayan CAR'lar için kullanılır.
    """
    if len(cars) < 2:
        return {"statistic": 0.0, "p_value": 1.0, "significant": False}

    try:
        stat, p_value = stats.wilcoxon(cars)
        return {
            "statistic": round(float(stat), 4),
            "p_value": round(float(p_value), 4),
            "significant": bool(p_value < 0.05),
        }
    except Exception:
        return {"statistic": 0.0, "p_value": 1.0, "significant": False}
