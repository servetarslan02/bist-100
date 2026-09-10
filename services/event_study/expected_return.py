"""ALPHA BIST — Expected Return (Multi-Factor Model).

Market Model (OLS) ve Fama-French 3/5-Factor modeli destekler.
Estimation window'den α ve β parametrelerini tahmin eder.

v2.0 Yenilikler:
═════════════════
- Fama-French factor'leri (SMB/HML/RMW/CMA) otomatik hesaplama desteği
- Trading day bazlı estimation window entegrasyonu
- Newey-West HAC standard errors (otokorelasyon düzeltmesi)
- Factor verisi yoksa otomatik fallback (Market Model)

Sayısal kararlılık notları:
- float64 dtype zorunlu
- Condition number kontrolü (ill-conditioned matris uyarısı)
- np.isfinite tek traversal NaN/Inf tespiti
"""

from typing import Any, Literal

import numpy as np
import structlog

logger = structlog.get_logger()

ModelType = Literal["market", "fama_french_3", "fama_french_5"]

# Varsayılan sabitler
MIN_OBSERVATIONS: int = 10
ARRAY_DIM: int = 1
CONDITION_NUMBER_THRESHOLD: float = 1e12


def _validate_array(arr: np.ndarray, name: str, min_len: int = 0) -> None:
    """Array doğrulama — tip, boyut, NaN/Inf kontrolü.

    Args:
        arr: Doğrulanacak array
        name: Array adı
        min_len: Minimum uzunluk

    Raises:
        TypeError: numpy array değilse
        ValueError: Boş, NaN/Inf içeriyorsa veya yanlış boyuttaysa
    """
    if not isinstance(arr, np.ndarray):
        logger.error("beklenen_donuyor_dizi_tip_hatasi", beklenti="np.ndarray", gercek=type(arr).__name__, dizi=name)
        raise TypeError(f"{name} numpy array olmalı, gelen tip: {type(arr).__name__}")

    if arr.ndim != ARRAY_DIM:
        logger.error("beklenen_donuyor_dizi_boyut_hatasi", beklenti=ARRAY_DIM, gercek=arr.ndim, dizi=name)
        raise ValueError(f"{name} tek boyutlu olmalı, gelen boyut: {arr.ndim}")

    if len(arr) == 0:
        logger.error("beklenen_donuyor_dizi_bos", dizi=name, uzunluk=0, minimum=0)
        raise ValueError(f"{name} dizisi boş.")

    if min_len > 0 and len(arr) < min_len:
        logger.error("beklenen_donuyor_dizi_bos", dizi=name, uzunluk=len(arr), minimum=min_len)
        raise ValueError(f"{name} yetersiz veri: {len(arr)} gözlem, minimum {min_len} gerekli.")

    if np.issubdtype(arr.dtype, np.number) and not np.all(np.isfinite(arr)):
        has_nan = bool(np.any(np.isnan(arr)))
        has_inf = bool(np.any(np.isinf(arr)))
        logger.error("beklenen_donuyor_dizi_gecersiz_deger", dizi=name, nan_var=has_nan, inf_var=has_inf)
        raise ValueError(f"{name} dizisinde {'NaN' if has_nan else ''}{' ve ' if has_nan and has_inf else ''}{'Inf' if has_inf else ''} değeri var.")


def _ensure_float64(arr: np.ndarray) -> np.ndarray:
    """Array'i float64'e dönüştür (zaten float64 ise kopyasız döndür)."""
    if arr.dtype == np.float64:
        return arr
    return arr.astype(np.float64, copy=False)


def _check_condition_number(X: np.ndarray) -> None:
    """Condition number kontrolü — ill-conditioned matris uyarısı.

    Args:
        X: Regresör matrisi
    """
    try:
        cond_num = np.linalg.cond(X)
        if cond_num > CONDITION_NUMBER_THRESHOLD:
            logger.warning(
                "beklenen_donuyor_kotu_durum_matris",
                condition_number=round(float(cond_num), 2),
                esik=CONDITION_NUMBER_THRESHOLD,
            )
    except np.linalg.LinAlgError:
        logger.debug("beklenen_donuyor_durum_kontrolu_atlandi", neden="matris_singular")


def calculate_expected_return(
    stock_returns: np.ndarray,
    market_returns: np.ndarray,
    model: ModelType = "market",
    smb_returns: np.ndarray | None = None,
    hml_returns: np.ndarray | None = None,
    rmw_returns: np.ndarray | None = None,
    cma_returns: np.ndarray | None = None,
    hac_lags: int = 0,
) -> dict[str, float]:
    """Expected return modeli — parametre tahmini.

    Args:
        stock_returns: Hisse getirileri (estimation window, trading day)
        market_returns: Piyasa getirileri (BIST-100)
        model: Model tipi
        smb_returns: Small Minus Big factor (Fama-French)
        hml_returns: High Minus Low factor (Fama-French)
        rmw_returns: Robust Minus Weak (FF5)
        cma_returns: Conservative Minus Aggressive (FF5)
        hac_lags: Newey-West HAC lags (0 = otokorelasyon düzeltmesi yok)

    Returns:
        Dict with alpha, beta_market, beta_smb, beta_hml, beta_rmw, beta_cma,
        r_squared, residual_se, n_obs, model, hac_se (opsiyonel)

    Raises:
        TypeError: Girdiler numpy array değilse
        ValueError: Boş array, uzunluk uyuşmazlığı, NaN/Inf varsa
    """
    _validate_array(stock_returns, "stock_returns")
    _validate_array(market_returns, "market_returns")

    if len(stock_returns) != len(market_returns):
        logger.error(
            "beklenen_donuyor_uzunluk_uyusmazligi",
            hisse_uzunluk=len(stock_returns),
            piyasa_uzunluk=len(market_returns),
        )
        raise ValueError(
            f"stock_returns ve market_returns uzunlukları eşit olmalı: "
            f"stock={len(stock_returns)}, market={len(market_returns)}"
        )

    n = len(stock_returns)
    if n < MIN_OBSERVATIONS:
        logger.warning("beklenen_donuyor_yetersiz_veri", n=n, minimum=MIN_OBSERVATIONS)
        return _default_params(model)

    stock_f64 = _ensure_float64(stock_returns)
    market_f64 = _ensure_float64(market_returns)

    if model == "fama_french_3":
        return _fama_french_3(stock_f64, market_f64, smb_returns, hml_returns, hac_lags=hac_lags)
    elif model == "fama_french_5":
        return _fama_french_5(stock_f64, market_f64, smb_returns, hml_returns, rmw_returns, cma_returns, hac_lags=hac_lags)
    else:
        return _market_model(stock_f64, market_f64, hac_lags=hac_lags)


def _market_model(
    stock_returns: np.ndarray,
    market_returns: np.ndarray,
    hac_lags: int = 0,
) -> dict[str, float]:
    """Basit Market Model: E[R] = α + β × R_m.

    Args:
        stock_returns: Hisse getirileri (float64)
        market_returns: Piyasa getirileri (float64)
        hac_lags: Newey-West HAC lags

    Returns:
        Model parametreleri sözlüğü

    Raises:
        ValueError: OLS çözümü başarısız olursa (LinAlgError)
    """
    n = len(stock_returns)
    X = np.column_stack([np.ones(n), market_returns])
    y = stock_returns

    _check_condition_number(X)

    try:
        betas, residuals, rank, sv = np.linalg.lstsq(X, y, rcond=None)
    except np.linalg.LinAlgError as e:
        logger.error("beklenen_donuyor_pazar_modeli_hatasi", hata=str(e))
        raise ValueError(f"Market model OLS hatası: {e}") from e

    y_pred = X @ betas
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    k = 2  # intercept + beta
    residual_se = np.sqrt(ss_res / (n - k)) if n > k else 0.0

    hac_se = None
    if hac_lags > 0:
        hac_se = _newey_west_se(X, y - y_pred, hac_lags)

    result: dict[str, Any] = {
        "alpha": float(betas[0]),
        "beta_market": float(betas[1]),
        "beta_smb": 0.0,
        "beta_hml": 0.0,
        "beta_rmw": 0.0,
        "beta_cma": 0.0,
        "r_squared": float(r_squared),
        "residual_se": float(residual_se),
        "n_obs": n,
        "model": "market",
    }
    if hac_se is not None:
        result["hac_se"] = hac_se
    return result


def _fama_french_3(
    stock_returns: np.ndarray,
    market_returns: np.ndarray,
    smb_returns: np.ndarray | None,
    hml_returns: np.ndarray | None,
    hac_lags: int = 0,
) -> dict[str, float]:
    """Fama-French 3-Factor Model: E[R] = α + β_m×R_m + β_smb×SMB + β_hml×HML.

    Args:
        stock_returns: Hisse getirileri (float64)
        market_returns: Piyasa getirileri (float64)
        smb_returns: SMB factor (opsiyonel)
        hml_returns: HML factor (opsiyonel)
        hac_lags: HAC lags

    Returns:
        Model parametreleri sözlüğü

    Raises:
        ValueError: OLS çözümü başarısız olursa (LinAlgError)
    """
    if smb_returns is None or hml_returns is None:
        logger.warning("beklenen_donuyor_ff3_factor_eksik", smb_eksik=smb_returns is None, hml_eksik=hml_returns is None)
        return _market_model(stock_returns, market_returns, hac_lags=hac_lags)

    _validate_array(smb_returns, "smb_returns")
    _validate_array(hml_returns, "hml_returns")

    n = min(len(stock_returns), len(market_returns), len(smb_returns), len(hml_returns))
    if n < MIN_OBSERVATIONS:
        logger.warning("beklenen_donuyor_ff3_yetersiz_veri", n=n)
        return _market_model(stock_returns[:n], market_returns[:n], hac_lags=hac_lags)

    X = np.column_stack([
        np.ones(n),
        _ensure_float64(market_returns[:n]),
        _ensure_float64(smb_returns[:n]),
        _ensure_float64(hml_returns[:n]),
    ])
    y = stock_returns[:n]

    _check_condition_number(X)

    try:
        betas, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    except np.linalg.LinAlgError as e:
        logger.error("beklenen_donuyor_ff3_hatasi", hata=str(e))
        raise ValueError(f"FF3 OLS hatası: {e}") from e

    y_pred = X @ betas
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    k = 4
    residual_se = np.sqrt(ss_res / (n - k)) if n > k else 0.0

    hac_se = None
    if hac_lags > 0:
        hac_se = _newey_west_se(X, y - y_pred, hac_lags)

    result: dict[str, Any] = {
        "alpha": float(betas[0]),
        "beta_market": float(betas[1]),
        "beta_smb": float(betas[2]),
        "beta_hml": float(betas[3]),
        "beta_rmw": 0.0,
        "beta_cma": 0.0,
        "r_squared": float(r_squared),
        "residual_se": float(residual_se),
        "n_obs": n,
        "model": "fama_french_3",
    }
    if hac_se is not None:
        result["hac_se"] = hac_se
    return result


def _fama_french_5(
    stock_returns: np.ndarray,
    market_returns: np.ndarray,
    smb_returns: np.ndarray | None,
    hml_returns: np.ndarray | None,
    rmw_returns: np.ndarray | None,
    cma_returns: np.ndarray | None,
    hac_lags: int = 0,
) -> dict[str, float]:
    """Fama-French 5-Factor Model.

    Args:
        stock_returns: Hisse getirileri (float64)
        market_returns: Piyasa getirileri (float64)
        smb_returns: SMB factor (opsiyonel)
        hml_returns: HML factor (opsiyonel)
        rmw_returns: RMW factor (opsiyonel)
        cma_returns: CMA factor (opsiyonel)
        hac_lags: HAC lags

    Returns:
        Model parametreleri sözlüğü

    Raises:
        ValueError: OLS çözümü başarısız olursa (LinAlgError)
    """
    if smb_returns is None or hml_returns is None:
        return _market_model(stock_returns, market_returns, hac_lags=hac_lags)
    if rmw_returns is None or cma_returns is None:
        return _fama_french_3(stock_returns, market_returns, smb_returns, hml_returns, hac_lags=hac_lags)

    _validate_array(smb_returns, "smb_returns")
    _validate_array(hml_returns, "hml_returns")
    _validate_array(rmw_returns, "rmw_returns")
    _validate_array(cma_returns, "cma_returns")

    n = min(
        len(stock_returns),
        len(market_returns),
        len(smb_returns),
        len(hml_returns),
        len(rmw_returns),
        len(cma_returns),
    )
    if n < MIN_OBSERVATIONS:
        logger.warning("beklenen_donuyor_ff5_yetersiz_veri", n=n)
        return _fama_french_3(stock_returns[:n], market_returns[:n], smb_returns[:n], hml_returns[:n], hac_lags=hac_lags)

    X = np.column_stack([
        np.ones(n),
        _ensure_float64(market_returns[:n]),
        _ensure_float64(smb_returns[:n]),
        _ensure_float64(hml_returns[:n]),
        _ensure_float64(rmw_returns[:n]),
        _ensure_float64(cma_returns[:n]),
    ])
    y = stock_returns[:n]

    _check_condition_number(X)

    try:
        betas, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    except np.linalg.LinAlgError as e:
        logger.error("beklenen_donuyor_ff5_hatasi", hata=str(e))
        raise ValueError(f"FF5 OLS hatası: {e}") from e

    y_pred = X @ betas
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    k = 6
    residual_se = np.sqrt(ss_res / (n - k)) if n > k else 0.0

    hac_se = None
    if hac_lags > 0:
        hac_se = _newey_west_se(X, y - y_pred, hac_lags)

    result: dict[str, Any] = {
        "alpha": float(betas[0]),
        "beta_market": float(betas[1]),
        "beta_smb": float(betas[2]),
        "beta_hml": float(betas[3]),
        "beta_rmw": float(betas[4]),
        "beta_cma": float(betas[5]),
        "r_squared": float(r_squared),
        "residual_se": float(residual_se),
        "n_obs": n,
        "model": "fama_french_5",
    }
    if hac_se is not None:
        result["hac_se"] = hac_se
    return result


def _newey_west_se(X: np.ndarray, residuals: np.ndarray, lags: int) -> dict[str, Any]:
    """Newey-West HAC standard errors.

    Otokorelasyon ve heteroskedastisite olduğunda OLS standard errors bias'lıdır.
    Newey-West (1987) düzeltmesi bu sorunu giderir.

    Args:
        X: Regresör matrisi (n × k)
        residuals: OLS residual'ları (n,)
        lags: HAC lag sayısı

    Returns:
        Dict with hac_se and hac_lags

    Raises:
        ValueError: lags negatif ise
    """
    if lags < 0:
        logger.error("beklenen_donuyor_hac_negatif_lags", lags=lags)
        raise ValueError(f"HAC lags negatif olamaz: {lags}")

    n, k = X.shape
    e = residuals

    # Bartlett kernel ağırlıkları
    # w_j = 1 - j/(lags+1)
    S = np.zeros((k, k))

    # j=0 terimi: Σ e_t² * x_t * x_t'
    for t in range(n):
        S += e[t] ** 2 * np.outer(X[t], X[t])

    # j>0 terimleri
    for j in range(1, lags + 1):
        wj = 1.0 - j / (lags + 1.0)
        for t in range(j, n):
            cross = e[t] * e[t - j] * (np.outer(X[t], X[t - j]) + np.outer(X[t - j], X[t]))
            S += wj * cross

    S /= n

    try:
        XtX_inv = np.linalg.inv(X.T @ X / n)
        V = XtX_inv @ S @ XtX_inv / n
        hac_se = np.sqrt(np.maximum(np.diag(V), 0))
    except np.linalg.LinAlgError:
        logger.warning("beklenen_donuyor_hac_ters_hatasi")
        hac_se = np.zeros(k)

    return {
        "hac_se": [round(float(s), 6) for s in hac_se],
        "hac_lags": lags,
    }


def calculate_expected_return_value(
    params: dict[str, float],
    market_return: float,
    smb: float = 0.0,
    hml: float = 0.0,
    rmw: float = 0.0,
    cma: float = 0.0,
) -> float:
    """Parametrelerden expected return hesapla.

    E[R] = α + β_m×R_m + β_smb×SMB + β_hml×HML + β_rmw×RMW + β_cma×CMA

    Args:
        params: Model parametreleri
        market_return: Piyasa getirisi
        smb: SMB factor
        hml: HML factor
        rmw: RMW factor
        cma: CMA factor

    Returns:
        Expected return değeri
    """
    return (
        params["alpha"]
        + params["beta_market"] * market_return
        + params["beta_smb"] * smb
        + params["beta_hml"] * hml
        + params["beta_rmw"] * rmw
        + params["beta_cma"] * cma
    )


def _default_params(model: ModelType) -> dict[str, float]:
    """Varsayılan parametreler (yeterli veri yoksa).

    Args:
        model: Model tipi

    Returns:
        Varsayılan parametre sözlüğü
    """
    return {
        "alpha": 0.0,
        "beta_market": 1.0,
        "beta_smb": 0.0,
        "beta_hml": 0.0,
        "beta_rmw": 0.0,
        "beta_cma": 0.0,
        "r_squared": 0.0,
        "residual_se": 0.0,
        "n_obs": 0,
        "model": model,
    }


def calculate_expected_return_simple(stock_returns: np.ndarray, market_returns: np.ndarray) -> tuple[float, float]:
    """Eski API uyumluluğu — (alpha, beta) döndür.

    Args:
        stock_returns: Hisse getirileri
        market_returns: Piyasa getirileri

    Returns:
        (alpha, beta_market) tuple
    """
    result = calculate_expected_return(stock_returns, market_returns, model="market")
    return result["alpha"], result["beta_market"]
