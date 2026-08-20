"""ALPHA BIST — Expected Return (Multi-Factor Model).

Market Model (OLS) ve Fama-French 3/5-Factor modeli destekler.
Estimation window'den α ve β parametrelerini tahmin eder.

v2.0 Yenilikler:
═════════════════
- Fama-French factor'leri (SMB/HML/RMW/CMA) otomatik hesaplama desteği
- Trading day bazlı estimation window entegrasyonu
- Newey-West HAC standard errors (otokorelasyon düzeltmesi)
- Factor verisi yoksa otomatik fallback (Market Model)
"""
import numpy as np
from typing import Tuple, Dict, Optional, Literal
import structlog

logger = structlog.get_logger()

ModelType = Literal["market", "fama_french_3", "fama_french_5"]


def calculate_expected_return(
    stock_returns: np.ndarray,
    market_returns: np.ndarray,
    model: ModelType = "market",
    smb_returns: Optional[np.ndarray] = None,
    hml_returns: Optional[np.ndarray] = None,
    rmw_returns: Optional[np.ndarray] = None,
    cma_returns: Optional[np.ndarray] = None,
    hac_lags: int = 0,
) -> Dict[str, float]:
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
    """
    n = len(stock_returns)

    if n < 10 or len(market_returns) < 10:
        logger.warning("insufficient_data_for_expected_return", n=n)
        return _default_params(model)

    try:
        if model == "fama_french_3":
            return _fama_french_3(
                stock_returns, market_returns, smb_returns, hml_returns,
                hac_lags=hac_lags,
            )
        elif model == "fama_french_5":
            return _fama_french_5(
                stock_returns, market_returns, smb_returns, hml_returns,
                rmw_returns, cma_returns, hac_lags=hac_lags,
            )
        else:
            return _market_model(stock_returns, market_returns, hac_lags=hac_lags)
    except Exception as e:
        logger.error("expected_return_calculation_error", error=str(e))
        return _default_params(model)


def _market_model(
    stock_returns: np.ndarray, market_returns: np.ndarray, hac_lags: int = 0,
) -> Dict[str, float]:
    """Basit Market Model: E[R] = α + β × R_m."""
    X = np.column_stack([np.ones(len(market_returns)), market_returns])
    y = stock_returns

    betas, residuals, rank, sv = np.linalg.lstsq(X, y, rcond=None)

    # R² hesapla
    y_pred = X @ betas
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    # Residual standard error
    n = len(y)
    k = 2  # intercept + beta
    residual_se = np.sqrt(ss_res / (n - k)) if n > k else 0.0

    # Newey-West HAC standard errors
    hac_se = None
    if hac_lags > 0:
        hac_se = _newey_west_se(X, y - y_pred, hac_lags)

    result = {
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
    smb_returns: Optional[np.ndarray],
    hml_returns: Optional[np.ndarray],
    hac_lags: int = 0,
) -> Dict[str, float]:
    """Fama-French 3-Factor Model: E[R] = α + β_m×R_m + β_smb×SMB + β_hml×HML."""
    if smb_returns is None or hml_returns is None:
        logger.warning("fama_french_3_missing_factors_falling_back_to_market")
        return _market_model(stock_returns, market_returns, hac_lags=hac_lags)

    n = min(len(stock_returns), len(market_returns), len(smb_returns), len(hml_returns))
    X = np.column_stack([
        np.ones(n),
        market_returns[:n],
        smb_returns[:n],
        hml_returns[:n],
    ])
    y = stock_returns[:n]

    betas, _, _, _ = np.linalg.lstsq(X, y, rcond=None)

    y_pred = X @ betas
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    n_obs = len(y)
    k = 4
    residual_se = np.sqrt(ss_res / (n_obs - k)) if n_obs > k else 0.0

    hac_se = None
    if hac_lags > 0:
        hac_se = _newey_west_se(X, y - y_pred, hac_lags)

    result = {
        "alpha": float(betas[0]),
        "beta_market": float(betas[1]),
        "beta_smb": float(betas[2]),
        "beta_hml": float(betas[3]),
        "beta_rmw": 0.0,
        "beta_cma": 0.0,
        "r_squared": float(r_squared),
        "residual_se": float(residual_se),
        "n_obs": n_obs,
        "model": "fama_french_3",
    }
    if hac_se is not None:
        result["hac_se"] = hac_se
    return result


def _fama_french_5(
    stock_returns: np.ndarray,
    market_returns: np.ndarray,
    smb_returns: Optional[np.ndarray],
    hml_returns: Optional[np.ndarray],
    rmw_returns: Optional[np.ndarray],
    cma_returns: Optional[np.ndarray],
    hac_lags: int = 0,
) -> Dict[str, float]:
    """Fama-French 5-Factor Model."""
    if smb_returns is None or hml_returns is None:
        return _market_model(stock_returns, market_returns, hac_lags=hac_lags)
    if rmw_returns is None or cma_returns is None:
        return _fama_french_3(
            stock_returns, market_returns, smb_returns, hml_returns, hac_lags=hac_lags
        )

    n = min(
        len(stock_returns), len(market_returns),
        len(smb_returns), len(hml_returns),
        len(rmw_returns), len(cma_returns),
    )
    X = np.column_stack([
        np.ones(n),
        market_returns[:n],
        smb_returns[:n],
        hml_returns[:n],
        rmw_returns[:n],
        cma_returns[:n],
    ])
    y = stock_returns[:n]

    betas, _, _, _ = np.linalg.lstsq(X, y, rcond=None)

    y_pred = X @ betas
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    n_obs = len(y)
    k = 6
    residual_se = np.sqrt(ss_res / (n_obs - k)) if n_obs > k else 0.0

    hac_se = None
    if hac_lags > 0:
        hac_se = _newey_west_se(X, y - y_pred, hac_lags)

    result = {
        "alpha": float(betas[0]),
        "beta_market": float(betas[1]),
        "beta_smb": float(betas[2]),
        "beta_hml": float(betas[3]),
        "beta_rmw": float(betas[4]),
        "beta_cma": float(betas[5]),
        "r_squared": float(r_squared),
        "residual_se": float(residual_se),
        "n_obs": n_obs,
        "model": "fama_french_5",
    }
    if hac_se is not None:
        result["hac_se"] = hac_se
    return result


def _newey_west_se(
    X: np.ndarray, residuals: np.ndarray, lags: int
) -> Dict[str, float]:
    """Newey-West HAC (Heteroskedasticity and Autocorrelation Consistent) standard errors.

    Otokorelasyon ve heteroskedastisite olduğunda OLS standard errors bias'lıdır.
    Newey-West (1987) düzeltmesi bu sorunu giderir.

    S_hat = (1/n) * Σ_t (e_t² * x_t * x_t')
           + (1/n) * Σ_{j=1}^{lags} w_j * Σ_{t=j+1}^{n} (e_t * e_{t-j}) * (x_t * x_{t-j}' + x_{t-j} * x_t')

    w_j = 1 - j/(lags+1)  (Bartlett kernel)

    Args:
        X: Regresör matrisi (n × k)
        residuals: OLS residual'ları (n,)
        lags: HAC lag sayısı

    Returns:
        Dict with hac_se (parameter standard errors) and hac_t_stats
    """
    n, k = X.shape
    e = residuals

    # Bartlett kernel ağırlıkları
    def w(j):
        return 1 - j / (lags + 1)

    # S_hat hesapla (k × k sandwich matrix)
    S = np.zeros((k, k))

    # j=0 terimi: Σ e_t² * x_t * x_t'
    for t in range(n):
        S += e[t] ** 2 * np.outer(X[t], X[t])

    # j>0 terimleri: Σ w_j * e_t * e_{t-j} * (x_t * x_{t-j}' + x_{t-j} * x_t')
    for j in range(1, lags + 1):
        wj = w(j)
        for t in range(j, n):
            cross = e[t] * e[t - j] * (np.outer(X[t], X[t - j]) + np.outer(X[t - j], X[t]))
            S += wj * cross

    S /= n

    # Var(kovaryans) = (X'X)^{-1} S (X'X)^{-1}
    try:
        XtX_inv = np.linalg.inv(X.T @ X / n)
        V = XtX_inv @ S @ XtX_inv / n
        hac_se = np.sqrt(np.maximum(np.diag(V), 0))
    except np.linalg.LinAlgError:
        hac_se = np.zeros(k)

    return {
        "hac_se": [round(float(s), 6) for s in hac_se],
        "hac_lags": lags,
    }


def calculate_expected_return_value(
    params: Dict[str, float],
    market_return: float,
    smb: float = 0.0,
    hml: float = 0.0,
    rmw: float = 0.0,
    cma: float = 0.0,
) -> float:
    """Parametrelerden expected return hesapla.

    E[R] = α + β_m×R_m + β_smb×SMB + β_hml×HML + β_rmw×RMW + β_cma×CMA
    """
    return (
        params["alpha"]
        + params["beta_market"] * market_return
        + params["beta_smb"] * smb
        + params["beta_hml"] * hml
        + params["beta_rmw"] * rmw
        + params["beta_cma"] * cma
    )


def _default_params(model: ModelType) -> Dict[str, float]:
    """Varsayılan parametreler (yeterli veri yoksa)."""
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


# Backward compatibility — eski API
def calculate_expected_return_simple(
    stock_returns: np.ndarray, market_returns: np.ndarray
) -> Tuple[float, float]:
    """Eski API uyumluluğu — (alpha, beta) döndür."""
    result = calculate_expected_return(stock_returns, market_returns, model="market")
    return result["alpha"], result["beta_market"]
