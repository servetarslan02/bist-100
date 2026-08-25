"""ALPHA BIST — Multi-Factor Expected Return (Fama-French).

Fama-French 3-Factor ve 5-Factor modeli ile expected return hesaplama.
BIST için SMB (Small Minus Big) ve HML (High Minus Low) factor'leri.
"""
import numpy as np
from typing import Dict, Optional
import structlog

logger = structlog.get_logger()


class MultiFactorModel:
    """Fama-French Multi-Factor Model."""

    def __init__(self, model_type: str = "fama_french_3"):
        """
        Args:
            model_type: "market", "fama_french_3", "fama_french_5"
        """
        self.model_type = model_type
        self.params = None

    def fit(
        self,
        stock_returns: np.ndarray,
        market_returns: np.ndarray,
        smb_returns: Optional[np.ndarray] = None,
        hml_returns: Optional[np.ndarray] = None,
        rmw_returns: Optional[np.ndarray] = None,
        cma_returns: Optional[np.ndarray] = None,
    ) -> Dict[str, float]:
        """Modeli estimation window verisi ile eğit.

        Args:
            stock_returns: Hisse getirileri
            market_returns: BIST-100 getirileri
            smb_returns: Small Minus Big
            hml_returns: High Minus Low
            rmw_returns: Robust Minus Weak (FF5)
            cma_returns: Conservative Minus Aggressive (FF5)

        Returns:
            Model parametreleri
        """
        from .expected_return import calculate_expected_return

        self.params = calculate_expected_return(
            stock_returns=stock_returns,
            market_returns=market_returns,
            model=self.model_type,
            smb_returns=smb_returns,
            hml_returns=hml_returns,
            rmw_returns=rmw_returns,
            cma_returns=cma_returns,
        )

        logger.info(
            "multi_factor_model_fitted",
            model=self.model_type,
            r_squared=self.params["r_squared"],
            n_obs=self.params["n_obs"],
        )

        return self.params

    def predict(
        self,
        market_return: float,
        smb: float = 0.0,
        hml: float = 0.0,
        rmw: float = 0.0,
        cma: float = 0.0,
    ) -> float:
        """Expected return tahmini.

        E[R] = α + β_m×R_m + β_smb×SMB + β_hml×HML + β_rmw×RMW + β_cma×CMA
        """
        if self.params is None:
            raise ValueError("Model henüz eğitilmedi — fit() çağrılmalı")

        return (
            self.params["alpha"]
            + self.params["beta_market"] * market_return
            + self.params["beta_smb"] * smb
            + self.params["beta_hml"] * hml
            + self.params["beta_rmw"] * rmw
            + self.params["beta_cma"] * cma
        )

    def get_params(self) -> Dict[str, float]:
        """Model parametrelerini döndür."""
        return self.params or {}


class FamaFrenchFactors:
    """BIST için Fama-French factor hesaplama."""

    @staticmethod
    def calculate_smb(
        small_cap_returns: np.ndarray,
        large_cap_returns: np.ndarray,
    ) -> np.ndarray:
        """SMB (Small Minus Big) = Small Cap Return - Large Cap Return."""
        return small_cap_returns - large_cap_returns

    @staticmethod
    def calculate_hml(
        value_returns: np.ndarray,
        growth_returns: np.ndarray,
    ) -> np.ndarray:
        """HML (High Minus Low) = Value Return - Growth Return."""
        return value_returns - growth_returns

    @staticmethod
    def calculate_rmw(
        robust_returns: np.ndarray,
        weak_returns: np.ndarray,
    ) -> np.ndarray:
        """RMW (Robust Minus Weak) = Robust Return - Weak Return."""
        return robust_returns - weak_returns

    @staticmethod
    def calculate_cma(
        conservative_returns: np.ndarray,
        aggressive_returns: np.ndarray,
    ) -> np.ndarray:
        """CMA (Conservative Minus Aggressive) = Conservative Return - Aggressive Return."""
        return conservative_returns - aggressive_returns

    @staticmethod
    def classify_stocks(
        market_caps: np.ndarray,
        book_to_market: np.ndarray,
        size_threshold: float = 0.5,
        bm_threshold_low: float = 0.3,
        bm_threshold_high: float = 0.7,
    ) -> Dict[str, np.ndarray]:
        """Hisseleri Fama-French kategorilerine ayır.

        Args:
            market_caps: Piyasa değerleri
            book_to_market: Book-to-market oranları
            size_threshold: Boyut eşik değeri (median)
            bm_threshold_low: B/M alt eşik
            bm_threshold_high: B/M üst eşik

        Returns:
            {"small": mask, "big": mask, "value": mask, "growth": mask}
        """
        median_cap = np.median(market_caps)

        small = market_caps <= median_cap
        big = market_caps > median_cap

        value = book_to_market >= bm_threshold_high
        growth = book_to_market <= bm_threshold_low

        return {
            "small": small,
            "big": big,
            "value": value,
            "growth": growth,
        }
