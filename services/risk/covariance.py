"""
ALPHA BIST — Covariance Estimation v3.0

ROADMAP v3.0 FAZ 5:
- Ledoit-Wolf shrinkage (basit sample covariance yerine)
- Robust covariance estimation
- Factor model covariance (opsiyonel)

KURAL: Sample covariance = gürültü. Shrinkage = gerçek.
"""

import numpy as np
from typing import Dict, List, Optional, Tuple, Any
import structlog

logger = structlog.get_logger()


class CovarianceEstimator:
    """Ledoit-Wolf shrinkage covariance estimator."""

    def __init__(self, shrinkage_target: str = "constant_correlation"):
        self.shrinkage_target = shrinkage_target
        logger.info("CovarianceEstimator initialized", target=shrinkage_target)

    def estimate(
        self,
        returns: np.ndarray,  # (n_samples, n_assets)
        tickers: List[str],
    ) -> Dict[str, Any]:
        """Ledoit-Wolf shrinkage covariance tahmini.

        Args:
            returns: Getiri matrisi (n_samples × n_assets)
            tickers: Hisse kodları

        Returns:
            {"covariance": np.ndarray, "correlation": np.ndarray,
             "shrinkage": float, "condition_number": float}
        """
        n_samples, n_assets = returns.shape

        if n_samples < n_assets:
            logger.warning("Sample size < assets, strong shrinkage needed",
                         samples=n_samples, assets=n_assets)

        # Sample covariance
        sample_cov = np.cov(returns, rowvar=False, bias=False)

        if n_assets == 1:
            return {
                "covariance": sample_cov,
                "correlation": np.array([[1.0]]),
                "shrinkage": 0.0,
                "condition_number": 1.0,
            }

        # Shrinkage target: Constant correlation
        variances = np.diag(sample_cov)
        stds = np.sqrt(variances)
        corr = sample_cov / np.outer(stds, stds)
        avg_corr = np.mean(corr[np.triu_indices_from(corr, k=1)])

        target = np.zeros_like(sample_cov)
        for i in range(n_assets):
            for j in range(n_assets):
                if i == j:
                    target[i, j] = variances[i]
                else:
                    target[i, j] = avg_corr * stds[i] * stds[j]

        # Optimal shrinkage intensity (Ledoit-Wolf)
        delta = self._compute_shrinkage_intensity(returns, sample_cov, target)

        # Shrinkage estimator
        shrunk_cov = delta * target + (1 - delta) * sample_cov

        # Condition number (numerical stability)
        eigvals = np.linalg.eigvalsh(shrunk_cov)
        condition_number = np.max(eigvals) / np.max(np.min(eigvals), 1e-10)

        # Correlation matrix
        shrunk_std = np.sqrt(np.diag(shrunk_cov))
        shrunk_corr = shrunk_cov / np.outer(shrunk_std, shrunk_std)

        logger.info("Covariance estimated",
                   shrinkage=round(delta, 4),
                   condition_number=round(condition_number, 2),
                   assets=n_assets)

        return {
            "covariance": shrunk_cov,
            "correlation": shrunk_corr,
            "shrinkage": round(float(delta), 4),
            "condition_number": round(float(condition_number), 2),
            "tickers": tickers,
        }

    def _compute_shrinkage_intensity(
        self,
        returns: np.ndarray,
        sample_cov: np.ndarray,
        target: np.ndarray,
    ) -> float:
        """Ledoit-Wolf optimal shrinkage intensity."""
        n_samples, n_assets = returns.shape

        # Pi: Sample covariance variance
        pi = 0
        for i in range(n_assets):
            for j in range(n_assets):
                diff = returns[:, i] * returns[:, j] - sample_cov[i, j]
                pi += np.sum(diff ** 2)
        pi /= n_samples

        # Rho: Target bias
        rho = np.sum((target - sample_cov) ** 2)

        # Gamma: Target variance
        gamma = np.sum(target ** 2)

        # Optimal shrinkage
        if pi + rho > 0:
            delta = max(0, min(1, pi / (pi + rho)))
        else:
            delta = 0.0

        # Minimum shrinkage (numerical stability)
        delta = max(delta, 0.1)

        return delta

    def compute_portfolio_volatility(
        self,
        weights: np.ndarray,
        cov_matrix: np.ndarray,
    ) -> float:
        """Portföy volatilitesi hesapla."""
        return float(np.sqrt(weights.T @ cov_matrix @ weights))

    def compute_diversification_ratio(
        self,
        weights: np.ndarray,
        cov_matrix: np.ndarray,
    ) -> float:
        """Diversification ratio (Choueifaty)."""
        port_vol = self.compute_portfolio_volatility(weights, cov_matrix)
        weighted_vols = weights * np.sqrt(np.diag(cov_matrix))
        return float(np.sum(weighted_vols) / port_vol) if port_vol > 0 else 0


# Singleton
covariance_estimator = CovarianceEstimator()
