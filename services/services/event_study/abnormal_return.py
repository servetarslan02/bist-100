"""ALPHA BIST — Abnormal Return.

AR = R_actual - E[R_expected]
MacKinlay (1997) metodolojisi ile abnormal return hesaplama.
"""
import numpy as np
from typing import Dict, Optional
import structlog

logger = structlog.get_logger()


def calculate_abnormal_return(
    stock_returns: np.ndarray,
    market_returns: np.ndarray,
    alpha: float,
    beta: float,
    smb_returns: Optional[np.ndarray] = None,
    hml_returns: Optional[np.ndarray] = None,
    beta_smb: float = 0.0,
    beta_hml: float = 0.0,
) -> np.ndarray:
    """Abnormal Return hesapla.

    Market Model: AR = R_stock - (α + β × R_market)
    Fama-French:  AR = R_stock - (α + β_m×R_m + β_smb×SMB + β_hml×HML)

    Args:
        stock_returns: Hisse getirileri
        market_returns: Piyasa getirileri
        alpha: Intercept (expected return modelinden)
        beta: Market beta
        smb_returns: SMB factor returns (opsiyonel)
        hml_returns: HML factor returns (opsiyonel)
        beta_smb: SMB beta
        beta_hml: HML beta

    Returns:
        Abnormal return array
    """
    expected = alpha + beta * market_returns

    if smb_returns is not None:
        expected += beta_smb * smb_returns
    if hml_returns is not None:
        expected += beta_hml * hml_returns

    ar = stock_returns - expected

    logger.debug(
        "abnormal_return_calculated",
        n=len(ar),
        mean_ar=float(np.mean(ar)),
        std_ar=float(np.std(ar)),
    )

    return ar


def calculate_abnormal_return_batch(
    stocks_returns: Dict[str, np.ndarray],
    market_returns: np.ndarray,
    params: Dict[str, Dict[str, float]],
) -> Dict[str, np.ndarray]:
    """Birden fazla hisse için toplu abnormal return hesapla.

    Args:
        stocks_returns: {ticker: returns} sözlüğü
        market_returns: Piyasa getirileri
        params: {ticker: {"alpha": ..., "beta_market": ..., ...}} sözlüğü

    Returns:
        {ticker: ar_array} sözlüğü
    """
    results = {}
    for ticker, stock_ret in stocks_returns.items():
        p = params.get(ticker, {"alpha": 0.0, "beta_market": 1.0})
        n = min(len(stock_ret), len(market_returns))
        ar = calculate_abnormal_return(
            stock_ret[:n],
            market_returns[:n],
            p["alpha"],
            p["beta_market"],
            beta_smb=p.get("beta_smb", 0.0),
            beta_hml=p.get("beta_hml", 0.0),
        )
        results[ticker] = ar

    return results
