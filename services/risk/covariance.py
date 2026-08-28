"""
ALPHA BIST — Covariance Estimation v3.0

ROADMAP v3.0 FAZ 5:
- Ledoit-Wolf shrinkage (basit sample covariance yerine)
- Robust covariance estimation
- Positive Semi-Definite (PSD) eigenvalue floor guarantee
- Higham-style nearest PSD projection

KURAL: Sample covariance = gürültü. Shrinkage = gerçek. PSD = matematiksel zorunluluk.
"""

from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


def ensure_positive_semi_definite(
    cov_matrix: np.ndarray,
    min_eigenvalue: float = 1e-7,
) -> np.ndarray:
    """Kovaryans matrisinin Pozitif Yarı-Tanımlı (PSD) olmasını garanti eder.

    Eigenvalue floor clipping ve simetrizasyon uygular.
    Negatif veya sıfıra çok yakın özdeğerleri min_eigenvalue seviyesine çeker.

    Args:
        cov_matrix: (N x N) simetrik kare kovaryans matrisi
        min_eigenvalue: Taban özdeğer (numerik stabilite için)

    Returns:
        PSD garanti edilmiş (N x N) kovaryans matrisi
    """
    if cov_matrix.ndim != 2 or cov_matrix.shape[0] != cov_matrix.shape[1]:
        raise ValueError("Covariance matrix must be a 2D square matrix")

    # Symmetrize first
    sym_cov = 0.5 * (cov_matrix + cov_matrix.T)

    # Eigenvalue decomposition for symmetric matrices
    eigvals, eigvecs = np.linalg.eigh(sym_cov)

    # If all eigenvalues >= min_eigenvalue, matrix is already strictly PSD
    if np.all(eigvals >= min_eigenvalue):
        return sym_cov

    # Floor eigenvalues
    clipped_eigvals = np.maximum(eigvals, min_eigenvalue)

    # Reconstruct: Sigma = V * diag(lambda) * V^T
    psd_cov = eigvecs @ np.diag(clipped_eigvals) @ eigvecs.T

    # Final symmetrization to eliminate numerical residual asymmetry
    psd_cov = 0.5 * (psd_cov + psd_cov.T)

    return psd_cov


def is_positive_semi_definite(matrix: np.ndarray, tol: float = 1e-8) -> bool:
    """Matrisin pozitif yarı-tanımlı olup olmadığını test eder."""
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        return False
    # Symmetrize
    sym = 0.5 * (matrix + matrix.T)
    eigvals = np.linalg.eigvalsh(sym)
    return bool(np.all(eigvals >= -tol))


class CovarianceEstimator:
    """Ledoit-Wolf shrinkage covariance estimator with guaranteed Positive Semi-Definiteness."""

    def __init__(self, shrinkage_target: str = "constant_correlation", min_eigenvalue: float = 1e-7):
        self.shrinkage_target = shrinkage_target
        self.min_eigenvalue = min_eigenvalue
        logger.info("CovarianceEstimator initialized", target=shrinkage_target, min_eig=min_eigenvalue)

    def estimate(
        self,
        returns: np.ndarray,  # (n_samples, n_assets)
        tickers: list[str] | None = None,
    ) -> dict[str, Any]:
        """Ledoit-Wolf shrinkage covariance tahmini ve PSD garantisi.

        Args:
            returns: Getiri matrisi (n_samples × n_assets)
            tickers: Hisse kodları (opsiyonel)

        Returns:
            {"covariance": np.ndarray, "correlation": np.ndarray,
             "shrinkage": float, "condition_number": float, "is_psd": bool}
        """
        returns = np.asarray(returns, dtype=float)
        # Clean any NaN/Inf
        if np.isnan(returns).any() or np.isinf(returns).any():
            returns = np.nan_to_num(returns, nan=0.0, posinf=0.0, neginf=0.0)

        if returns.ndim == 1:
            returns = returns.reshape(-1, 1)

        n_samples, n_assets = returns.shape
        if tickers is None:
            tickers = [f"ASSET_{i}" for i in range(n_assets)]

        if n_samples < n_assets:
            logger.warning("Sample size < assets, strong shrinkage needed", samples=n_samples, assets=n_assets)

        if n_assets == 1:
            var_val = float(np.var(returns, ddof=1)) if n_samples > 1 else 1e-4
            var_val = max(var_val, self.min_eigenvalue)
            cov_1 = np.array([[var_val]])
            return {
                "covariance": cov_1,
                "correlation": np.array([[1.0]]),
                "shrinkage": 0.0,
                "condition_number": 1.0,
                "is_psd": True,
                "tickers": tickers,
            }

        # Sample covariance
        sample_cov = np.cov(returns, rowvar=False, bias=False)
        if sample_cov.ndim == 0:
            sample_cov = np.array([[max(float(sample_cov), self.min_eigenvalue)]])
            return {
                "covariance": sample_cov,
                "correlation": np.array([[1.0]]),
                "shrinkage": 0.0,
                "condition_number": 1.0,
                "is_psd": True,
                "tickers": tickers,
            }

        # Shrinkage target: Constant correlation
        variances = np.diag(sample_cov)
        variances = np.maximum(variances, self.min_eigenvalue)
        stds = np.sqrt(variances)
        
        outer_stds = np.outer(stds, stds)
        outer_stds = np.maximum(outer_stds, 1e-12)
        corr = sample_cov / outer_stds
        np.fill_diagonal(corr, 1.0)
        
        # Triu correlation mean
        triu_indices = np.triu_indices_from(corr, k=1)
        avg_corr = float(np.mean(corr[triu_indices])) if len(triu_indices[0]) > 0 else 0.0
        avg_corr = max(-1.0, min(1.0, avg_corr))

        target = np.zeros_like(sample_cov)
        np.fill_diagonal(target, variances)
        off_diag_mask = ~np.eye(n_assets, dtype=bool)
        target[off_diag_mask] = avg_corr * outer_stds[off_diag_mask]

        # Optimal shrinkage intensity (Ledoit-Wolf)
        delta = self._compute_shrinkage_intensity(returns, sample_cov, target)

        # Shrinkage estimator
        shrunk_cov = delta * target + (1 - delta) * sample_cov

        # Enforce PSD via eigenvalue floor
        psd_cov = ensure_positive_semi_definite(shrunk_cov, min_eigenvalue=self.min_eigenvalue)

        # Condition number (numerical stability)
        eigvals = np.linalg.eigvalsh(psd_cov)
        min_eig = max(float(np.min(eigvals)), 1e-12)
        max_eig = float(np.max(eigvals))
        condition_number = max_eig / min_eig

        # Correlation matrix
        shrunk_std = np.sqrt(np.maximum(np.diag(psd_cov), self.min_eigenvalue))
        outer_psd_std = np.maximum(np.outer(shrunk_std, shrunk_std), 1e-12)
        shrunk_corr = psd_cov / outer_psd_std
        np.fill_diagonal(shrunk_corr, 1.0)
        shrunk_corr = np.clip(shrunk_corr, -1.0, 1.0)

        is_psd = is_positive_semi_definite(psd_cov)

        logger.debug(
            "Covariance estimated with PSD guarantee",
            shrinkage=round(delta, 4),
            condition_number=round(condition_number, 2),
            is_psd=is_psd,
            assets=n_assets,
        )

        return {
            "covariance": psd_cov,
            "correlation": shrunk_corr,
            "shrinkage": round(float(delta), 4),
            "condition_number": round(float(condition_number), 2),
            "is_psd": is_psd,
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
        if n_samples <= 1:
            return 1.0

        # Mean-centered returns
        mean_r = np.mean(returns, axis=0)
        centered_r = returns - mean_r

        # Pi: Sample covariance variance (vektörize)
        # diff[i,j] = sum_t (r_ti * r_tj - cov[i,j])^2
        outer_products = np.einsum("ti,tj->tij", centered_r, centered_r)  # (n_samples, n_assets, n_assets)
        diff_sq = (outer_products - sample_cov) ** 2  # (n_samples, n_assets, n_assets)
        pi = float(np.sum(diff_sq)) / n_samples

        # Rho: Target bias
        rho = float(np.sum((target - sample_cov) ** 2))

        # Optimal shrinkage delta = pi / (pi + rho)
        denom = pi + rho
        if denom <= 1e-12:
            delta = 0.2
        else:
            delta = max(0.0, min(1.0, pi / denom))

        # Minimum shrinkage (numerical stability buffer)
        delta = max(delta, 0.05)

        return delta

    def compute_portfolio_volatility(
        self,
        weights: np.ndarray,
        cov_matrix: np.ndarray,
    ) -> float:
        """Portföy volatilite (yıllıklandırılmamış) hesapla."""
        weights = np.asarray(weights, dtype=float)
        cov_matrix = np.asarray(cov_matrix, dtype=float)
        # Ensure PSD
        cov_matrix = ensure_positive_semi_definite(cov_matrix, self.min_eigenvalue)
        variance = float(weights.T @ cov_matrix @ weights)
        return float(np.sqrt(max(variance, 0.0)))

    def compute_diversification_ratio(
        self,
        weights: np.ndarray,
        cov_matrix: np.ndarray,
    ) -> float:
        """Diversification ratio (Choueifaty)."""
        weights = np.asarray(weights, dtype=float)
        cov_matrix = np.asarray(cov_matrix, dtype=float)
        port_vol = self.compute_portfolio_volatility(weights, cov_matrix)
        weighted_vols = weights * np.sqrt(np.maximum(np.diag(cov_matrix), 0.0))
        return float(np.sum(weighted_vols) / port_vol) if port_vol > 0 else 0.0


# Singleton
covariance_estimator = CovarianceEstimator()

