"""ALPHA BIST — Factor Correlation Analysis.

Faktörler arası korelasyon, çoklu doğrusallık tespiti, diversifikasyon skoru.
"""
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


def calculate_factor_correlation(
    factor_returns: dict[str, list[float]],
) -> dict[str, Any]:
    """Faktörler arası korelasyon matrisi.

    Args:
        factor_returns: {factor_name: returns} sözlüğü

    Returns:
        Dict with correlation_matrix, avg_correlation, diversification_score
    """
    names = list(factor_returns.keys())
    n_factors = len(names)

    if n_factors < 2:
        return {"error": "Need at least 2 factors", "n_factors": n_factors}

    # Getiri matrisi
    returns_matrix = np.array([factor_returns[name] for name in names], dtype=float)
    n_periods = returns_matrix.shape[1]

    if n_periods < 3:
        return {"error": "Need at least 3 periods", "n_periods": n_periods}

    # Korelasyon matrisi
    corr_matrix = np.corrcoef(returns_matrix)

    # NaN kontrolü
    corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)

    # Ortalama korelasyon (off-diagonal)
    mask = ~np.eye(n_factors, dtype=bool)
    avg_corr = float(np.mean(corr_matrix[mask]))

    # Diversifikasyon skoru (1 = mükemmel diversifikasyon, 0 = tam korelasyon)
    diversification_score = 1.0 - abs(avg_corr)

    # En yüksek korelasyonlu çiftler
    high_corr_pairs = []
    for i in range(n_factors):
        for j in range(i + 1, n_factors):
            if abs(corr_matrix[i, j]) > 0.7:
                high_corr_pairs.append({
                    "factor_1": names[i],
                    "factor_2": names[j],
                    "correlation": round(float(corr_matrix[i, j]), 4),
                })

    # Çoklu doğrusallık uyarısı (VIF)
    # VIF = 1 / (1 - R²), burada R² = factor_i'nin diğer faktörlerle açıklanan varyansı
    # Basitleştirilmiş: max off-diagonal korelasyon kullanarak yaklaşık VIF
    vif_warnings = []
    for i in range(n_factors):
        # Factor i'nin diğer faktörlerle max korelasyonu
        off_diag = [abs(corr_matrix[i, j]) for j in range(n_factors) if i != j]
        max_corr = max(off_diag) if off_diag else 0.0
        # VIF ≈ 1 / (1 - max_corr²)
        r_squared = max_corr ** 2
        vif = 1.0 / max(1.0 - r_squared, 0.001)
        if vif > 5.0:  # VIF > 5 = yüksek çoklu doğrusallık
            vif_warnings.append({
                "factor": names[i],
                "vif": round(float(vif), 2),
                "max_corr_with": names[[j for j in range(n_factors) if j != i][np.argmax(off_diag)]],
            })

    # Korelasyon matrisini dict'e çevir
    corr_dict = {}
    for i, name_i in enumerate(names):
        corr_dict[name_i] = {}
        for j, name_j in enumerate(names):
            corr_dict[name_i][name_j] = round(float(corr_matrix[i, j]), 4)

    return {
        "correlation_matrix": corr_dict,
        "avg_correlation": round(avg_corr, 4),
        "diversification_score": round(diversification_score, 4),
        "high_correlation_pairs": high_corr_pairs,
        "vif_warnings": vif_warnings,
        "n_factors": n_factors,
        "n_periods": n_periods,
    }


def calculate_rolling_correlation(
    factor1_returns: list[float],
    factor2_returns: list[float],
    window: int = 60,
) -> list[float]:
    """Rolling korelasyon serisi.

    Args:
        factor1_returns: Faktör 1 getiri serisi
        factor2_returns: Faktör 2 getiri serisi
        window: Pencere boyutu

    Returns:
        Rolling korelasyon serisi
    """
    f1 = np.array(factor1_returns, dtype=float)
    f2 = np.array(factor2_returns, dtype=float)
    n = min(len(f1), len(f2))

    if n < window:
        return []

    correlations = []
    for i in range(window, n + 1):
        corr = np.corrcoef(f1[i - window:i], f2[i - window:i])[0, 1]
        correlations.append(round(float(corr) if not np.isnan(corr) else 0.0, 4))

    return correlations
