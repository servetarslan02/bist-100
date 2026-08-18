"""ALPHA BIST — Expected Return (Multi-Factor Model).

Market Model (OLS) ve Fama-French 3-Factor modeli destekler.
Estimation window'den α ve β parametrelerini tahmin eder.
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
) -> Dict[str, float]:
    """Expected return modeli — parametre tahmini.

    Args:
        stock_returns: Hisse getirileri (estimation window)
        market_returns: Piyasa getirileri (BIST-100)
        model: Model tipi
        smb_returns: Small Minus Big factor (Fama-French)
        hml_returns: High Minus Low factor (Fama-French)
        rmw_returns: Robust Minus Weak (FF5)
        cma_returns: Conservative Minus Aggressive (FF5)

    Returns:
        Dict with alpha, beta_market, beta_smb, beta_hml, r_squared, residuals
    """
    n = len(stock_returns)

    if n < 10 or len(market_returns) < 10:
        logger.warning("insufficient_data_for_expected_return", n=n)
        return _default_params(model)

    try:
        if model == "fama_french_3":
            return _fama_french_3(
                stock_returns, market_returns, smb_returns, hml_returns
            )
        elif model == "fama_french_5":
            return _fama_french_5(
                stock_returns, market_returns, smb_returns, hml_returns,
                rmw_returns, cma_returns,
            )
        else:
            return _market_model(stock_returns, market_returns)
    except Exception as e:
        logger.error("expected_return_calculation_error", error=str(e))
        return _default_params(model)


def _market_model(
    stock_returns: np.ndarray, market_returns: np.ndarray
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

    return {
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


def _fama_french_3(
    stock_returns: np.ndarray,
    market_returns: np.ndarray,
    smb_returns: Optional[np.ndarray],
    hml_returns: Optional[np.ndarray],
) -> Dict[str, float]:
    """Fama-French 3-Factor Model: E[R] = α + β_m×R_m + β_smb×SMB + β_hml×HML."""
    if smb_returns is None or hml_returns is None:
        logger.warning("fama_french_3_missing_factors_falling_back_to_market")
        return _market_model(stock_returns, market_returns)

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

    return {
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


def _fama_french_5(
    stock_returns: np.ndarray,
    market_returns: np.ndarray,
    smb_returns: Optional[np.ndarray],
    hml_returns: Optional[np.ndarray],
    rmw_returns: Optional[np.ndarray],
    cma_returns: Optional[np.ndarray],
) -> Dict[str, float]:
    """Fama-French 5-Factor Model."""
    if smb_returns is None or hml_returns is None:
        return _market_model(stock_returns, market_returns)
    if rmw_returns is None or cma_returns is None:
        return _fama_french_3(stock_returns, market_returns, smb_returns, hml_returns)

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

    return {
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
