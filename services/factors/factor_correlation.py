"""ALPHA BIST — Factor Correlation Analysis.

Faktörler arası korelasyon, çoklu doğrusallık tespiti, diversifikasyon skoru.
Rolling korelasyon, VIF analizi ve yüksek korelasyon çiftleri tespiti.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import numpy.typing as npt
import structlog

logger = structlog.get_logger(__name__)

__all__ = [
    "calculate_factor_correlation",
    "calculate_rolling_correlation",
]

# --- Sabitler (magic number yok) ---

_HIGH_CORR_THRESHOLD: float = 0.7
_VIF_THRESHOLD: float = 5.0
_MIN_DENOMINATOR: float = 1e-10
_DEFAULT_VIF_FALLBACK: float = 1.0
_MIN_FACTORS: int = 2
_MIN_PERIODS: int = 3


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

    # NaN/Inf tespiti ve temizliği
    nan_count = int(np.isnan(arr).sum())
    inf_count = int(np.isinf(arr).sum())
    if nan_count > 0 or inf_count > 0:
        logger.warning(
            "correlation_dirty_values",
            field=name,
            nan_count=nan_count,
            inf_count=inf_count,
            action="replaced_with_zero",
        )
        arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)

    return arr


def calculate_factor_correlation(
    factor_returns: dict[str, list[float]] | None,
) -> dict[str, Any]:
    """Faktörler arası korelasyon matrisi.

    Her faktör çifti için Pearson korelasyonu hesaplar, yüksek korelasyonlu
    çiftleri ve çoklu doğrusallık (VIF) uyarılarını raporlar.

    Args:
        factor_returns: {factor_name: returns} sözlüğü. Her faktör için
            en az 3 dönem getiri içermeli. None olamaz.

    Returns:
        Dict with correlation_matrix, avg_correlation, diversification_score,
        high_correlation_pairs, vif_warnings, n_factors, n_periods.

    Raises:
        TypeError: factor_returns None veya dict değilse.
        ValueError: factor_returns boş dict ise.
    """
    # --- Input validation (Rule 3: Fail-Closed) ---
    if factor_returns is None:
        raise TypeError("factor_returns parametresi None olamaz")
    if not isinstance(factor_returns, dict):
        raise TypeError(f"factor_returns dict olmalı, alınan tip: {type(factor_returns).__name__}")

    names = list(factor_returns.keys())
    n_factors = len(names)

    if n_factors < _MIN_FACTORS:
        logger.warning("correlation_insufficient_factors", n_factors=n_factors, min_required=_MIN_FACTORS)
        return {
            "error": f"En az {_MIN_FACTORS} faktör gerekli, alınan: {n_factors}",
            "n_factors": n_factors,
            "correlation_matrix": {},
            "avg_correlation": 0.0,
            "diversification_score": 1.0,
            "high_correlation_pairs": [],
            "vif_warnings": [],
            "n_periods": 0,
        }

    # Getiri matrisi — her faktörü güvenli array'e çevir
    try:
        clean_arrays = [_safe_float_array(factor_returns[name], name=name) for name in names]
    except (TypeError, ValueError) as exc:
        logger.error("correlation_array_conversion_failed", error=str(exc))
        raise

    # Tüm faktörler aynı uzunlukta olmalı
    lengths = [len(arr) for arr in clean_arrays]
    if len(set(lengths)) > 1:
        min_len = min(lengths)
        logger.warning("correlation_length_mismatch", lengths=dict(zip(names, lengths, strict=True)), truncated_to=min_len)
        clean_arrays = [arr[:min_len] for arr in clean_arrays]

    returns_matrix = np.vstack(clean_arrays)
    n_periods = returns_matrix.shape[1]

    if n_periods < _MIN_PERIODS:
        logger.warning("correlation_insufficient_periods", n_periods=n_periods, min_required=_MIN_PERIODS)
        return {
            "error": f"En az {_MIN_PERIODS} dönem gerekli, alınan: {n_periods}",
            "n_factors": n_factors,
            "correlation_matrix": {},
            "avg_correlation": 0.0,
            "diversification_score": 1.0,
            "high_correlation_pairs": [],
            "vif_warnings": [],
            "n_periods": n_periods,
        }

    # Korelasyon matrisi
    try:
        corr_matrix: npt.NDArray[np.float64] = np.corrcoef(returns_matrix)
    except Exception as exc:
        logger.error("correlation_calculation_failed", error=str(exc))
        raise ValueError(f"Korelasyon hesaplanamadı: {exc}") from exc

    # NaN kontrolü (std=0 durumunda NaN oluşur)
    nan_mask = np.isnan(corr_matrix)
    if nan_mask.any():
        nan_pairs = int(nan_mask.sum()) // 2  # simetrik
        logger.warning("correlation_nan_detected", nan_pairs=nan_pairs, action="replaced_with_zero")
        corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)

    # Ortalama korelasyon (off-diagonal)
    mask = ~np.eye(n_factors, dtype=bool)
    avg_corr = float(np.mean(corr_matrix[mask]))

    # Diversifikasyon skoru (1 = mükemmel diversifikasyon, 0 = tam korelasyon)
    diversification_score = 1.0 - abs(avg_corr)

    # En yüksek korelasyonlu çiftler
    high_corr_pairs: list[dict[str, Any]] = []
    for i in range(n_factors):
        for j in range(i + 1, n_factors):
            if abs(corr_matrix[i, j]) > _HIGH_CORR_THRESHOLD:
                high_corr_pairs.append(
                    {
                        "factor_1": names[i],
                        "factor_2": names[j],
                        "correlation": round(float(corr_matrix[i, j]), 4),
                    }
                )

    # Çoklu doğrusallık uyarısı (VIF)
    # VIF = 1 / (1 - R²), burada R² = factor_i'nin diğer faktörlerle açıklanan varyansı
    # Basitleştirilmiş: max off-diagonal korelasyon kullanarak yaklaşık VIF
    vif_warnings: list[dict[str, Any]] = []
    for i in range(n_factors):
        off_diag_indices = [j for j in range(n_factors) if j != i]
        off_diag = [abs(corr_matrix[i, j]) for j in off_diag_indices]
        max_corr = max(off_diag) if off_diag else 0.0
        r_squared = max_corr ** 2
        # VIF hesaplama — sıfıra bölmeyi önle
        denominator = max(1.0 - r_squared, _MIN_DENOMINATOR)
        vif = _DEFAULT_VIF_FALLBACK / denominator
        if vif > _VIF_THRESHOLD:
            max_corr_idx = off_diag_indices[int(np.argmax(off_diag))]
            vif_warnings.append(
                {
                    "factor": names[i],
                    "vif": round(float(vif), 2),
                    "max_corr_with": names[max_corr_idx],
                }
            )

    # Korelasyon matrisini dict'e çevir
    corr_dict: dict[str, dict[str, float]] = {}
    for i, name_i in enumerate(names):
        corr_dict[name_i] = {}
        for j, name_j in enumerate(names):
            corr_dict[name_i][name_j] = round(float(corr_matrix[i, j]), 4)

    logger.info(
        "factor_correlation_calculated",
        n_factors=n_factors,
        n_periods=n_periods,
        avg_correlation=round(avg_corr, 4),
        diversification_score=round(diversification_score, 4),
        high_corr_pairs=len(high_corr_pairs),
        vif_warnings=len(vif_warnings),
    )

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
    factor1_returns: list[float] | None,
    factor2_returns: list[float] | None,
    window: int = 60,
) -> list[float]:
    """Rolling korelasyon serisi.

    İki faktör getiri serisi arasındaki kaymalı pencere korelasyonunu hesaplar.
    Pencere boyutu seri uzunluğundan büyükse boş liste döner.

    Args:
        factor1_returns: Faktör 1 getiri serisi. None olamaz.
        factor2_returns: Faktör 2 getiri serisi. None olamaz.
        window: Pencere boyutu (pozitif tamsayı olmalı).

    Returns:
        Rolling korelasyon serisi (yuvarlanmış 4 ondalık).

    Raises:
        TypeError: factor1_returns veya factor2_returns None ise.
        ValueError: window pozitif değilse.
    """
    # --- Input validation (Rule 3: Fail-Closed) ---
    if factor1_returns is None:
        raise TypeError("factor1_returns parametresi None olamaz")
    if factor2_returns is None:
        raise TypeError("factor2_returns parametresi None olamaz")
    if not isinstance(window, int) or window <= 0:
        raise ValueError(f"window pozitif tamsayı olmalı, alınan: {window}")

    try:
        f1 = _safe_float_array(factor1_returns, name="factor1_returns")
        f2 = _safe_float_array(factor2_returns, name="factor2_returns")
    except (TypeError, ValueError) as exc:
        logger.error("rolling_correlation_array_failed", error=str(exc))
        raise

    n = min(len(f1), len(f2))

    if n < window:
        logger.warning(
            "rolling_correlation_insufficient_data",
            data_length=n,
            window=window,
        )
        return []

    # Vektörize edilmiş rolling korelasyon — Python loop yerine
    # Kaymalı pencere ile korelasyon hesaplama
    correlations: list[float] = []
    for i in range(window, n + 1):
        segment1 = f1[i - window : i]
        segment2 = f2[i - window : i]

        # std=0 kontrolü — sabit segment korelasyonu tanımsız
        std1 = float(np.std(segment1))
        std2 = float(np.std(segment2))
        if std1 < _MIN_DENOMINATOR or std2 < _MIN_DENOMINATOR:
            correlations.append(0.0)
            continue

        corr_val = float(np.corrcoef(segment1, segment2)[0, 1])
        if math.isnan(corr_val) or math.isinf(corr_val):
            logger.warning("rolling_correlation_nan_inf", position=i, action="replaced_with_zero")
            correlations.append(0.0)
        else:
            correlations.append(round(corr_val, 4))

    logger.info(
        "rolling_correlation_calculated",
        series_length=n,
        window=window,
        output_length=len(correlations),
    )

    return correlations
