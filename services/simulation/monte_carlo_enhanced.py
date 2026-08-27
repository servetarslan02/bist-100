"""
ALPHA BIST — Enhanced Monte Carlo Simulation v2.0

Gelişmiş Monte Carlo modelleri:
- Jump-Diffusion (Merton model)
- Correlated Paths (Cholesky decomposition)
- Regime-Conditioned parameters
- Fat Tails (Student-t)
- GARCH(1,1) volatility clustering

Kaynaklar: Springer Data-Driven Monte Carlo (2026), LinkedIn Jump-Diffusion (2025)
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class MonteCarloResult:
    """Monte Carlo simülasyon sonucu."""

    ticker: str
    current_price: float
    horizon_days: int
    num_simulations: int
    model: str

    # Getiri istatistikleri
    expected_return_pct: float
    median_return_pct: float
    std_return_pct: float

    # Risk metrikleri
    var_95: float
    var_99: float
    cvar_95: float
    cvar_99: float

    # Olasılıklar
    prob_positive: float
    prob_up_5pct: float
    prob_down_5pct: float
    prob_down_10pct: float

    # Percentiles
    percentiles: dict[int, float]

    # Path istatistikleri
    max_return_pct: float
    min_return_pct: float
    avg_max_drawdown_pct: float


class JumpDiffusionMonteCarlo:
    """Merton Jump-Diffusion Monte Carlo.

    Model: dS/S = (μ - λk)dt + σdW + JdN

    λ = jump intensity (yılda ~5 jump → günlük 0.02)
    k = E[J] = expected jump size
    J ~ N(jump_mean, jump_std²)
    N ~ Poisson(λt)

    Kaynak: LinkedIn Jump-Diffusion (2025)
    """

    def simulate(
        self,
        current_price: float,
        daily_return: float,
        daily_vol: float,
        num_sims: int = 10000,
        horizon: int = 20,
        jump_intensity: float = 0.02,
        jump_mean: float = 0.0,
        jump_std: float = 0.05,
        seed: int | None = None,
    ) -> MonteCarloResult:
        """Jump-diffusion Monte Carlo simülasyonu.

        Args:
            current_price: Güncel fiyat
            daily_return: Günlük ortalama getiri
            daily_vol: Günlük volatilite
            num_sims: Simülasyon sayısı
            horizon: Tahmin ufku (gün)
            jump_intensity: Jump yoğunluğu (günlük)
            jump_mean: Jump ortalama boyutu
            jump_std: Jump standart sapması
            seed: Rastgele tohum

        Returns:
            MonteCarloResult
        """
        rng = np.random.default_rng(seed) if seed is not None else np.random.default_rng()

        paths = np.zeros((num_sims, horizon + 1))
        paths[:, 0] = current_price

        # Input parameters are explicitly daily.  Applying a further 1/252
        # here made both the drift and jump frequency about 252x too small.
        drift = daily_return - jump_intensity * jump_mean

        for t in range(1, horizon + 1):
            # Brownian motion: z ~ N(0,1)
            z = rng.standard_normal(num_sims)

            # Jump process (Poisson)
            n_jumps = rng.poisson(jump_intensity, num_sims)
            max_jumps = max(n_jumps.max(), 1)
            jump_sizes_all = rng.normal(jump_mean, jump_std, (num_sims, max_jumps))
            # A path with one jump must receive one jump size, not every
            # generated size up to the batch maximum.
            jump_mask = np.arange(max_jumps) < n_jumps[:, None]
            jump_effect = np.sum(jump_sizes_all * jump_mask, axis=1)

            # Fiyat güncelleme: GBM + jump
            # daily_vol zaten günlük std (yıllık değil), √dt ile çarpılmaz
            # log-return: daily drift + daily σ*z + sum of daily jumps
            log_return = drift + daily_vol * z + jump_effect
            paths[:, t] = paths[:, t - 1] * np.exp(log_return)

        # İstatistikler
        return self._compute_stats(paths, current_price, horizon, num_sims, "Jump-Diffusion")

    def _compute_stats(
        self,
        paths: np.ndarray,
        current_price: float,
        horizon: int,
        num_sims: int,
        model: str,
    ) -> MonteCarloResult:
        """İstatistikleri hesapla."""
        final_prices = paths[:, -1]
        returns = (final_prices / current_price - 1) * 100

        # Max drawdown (her simülasyon için)
        max_drawdowns = np.zeros(num_sims)
        for i in range(num_sims):
            running_max = np.maximum.accumulate(paths[i])
            drawdowns = (paths[i] - running_max) / running_max * 100
            max_drawdowns[i] = np.min(drawdowns)

        # Percentiles
        percentiles = {
            1: float(np.percentile(returns, 1)),
            5: float(np.percentile(returns, 5)),
            10: float(np.percentile(returns, 10)),
            25: float(np.percentile(returns, 25)),
            50: float(np.percentile(returns, 50)),
            75: float(np.percentile(returns, 75)),
            90: float(np.percentile(returns, 90)),
            95: float(np.percentile(returns, 95)),
            99: float(np.percentile(returns, 99)),
        }

        # VaR/CVaR
        var_95 = float(np.percentile(returns, 5))
        var_99 = float(np.percentile(returns, 1))
        tail_95 = returns[returns <= var_95]
        cvar_95 = float(np.mean(tail_95)) if len(tail_95) > 0 else var_95
        tail_99 = returns[returns <= var_99]
        cvar_99 = float(np.mean(tail_99)) if len(tail_99) > 0 else var_99

        return MonteCarloResult(
            ticker="",
            current_price=current_price,
            horizon_days=horizon,
            num_simulations=num_sims,
            model=model,
            expected_return_pct=round(float(np.mean(returns)), 2),
            median_return_pct=round(float(np.median(returns)), 2),
            std_return_pct=round(float(np.std(returns)), 2),
            var_95=round(var_95, 2),
            var_99=round(var_99, 2),
            cvar_95=round(cvar_95, 2),
            cvar_99=round(cvar_99, 2),
            prob_positive=round(float(np.mean(returns > 0) * 100), 1),
            prob_up_5pct=round(float(np.mean(returns > 5) * 100), 1),
            prob_down_5pct=round(float(np.mean(returns < -5) * 100), 1),
            prob_down_10pct=round(float(np.mean(returns < -10) * 100), 1),
            percentiles={k: round(v, 2) for k, v in percentiles.items()},
            max_return_pct=round(float(np.max(returns)), 2),
            min_return_pct=round(float(np.min(returns)), 2),
            avg_max_drawdown_pct=round(float(np.mean(max_drawdowns)), 2),
        )


class CorrelatedMonteCarlo:
    """Korelli Monte Carlo simülasyonu (portföy bazlı).

    Cholesky decomposition ile korelli random returns üretir.
    Portföy bazlı risk analizi için kullanılır.
    """

    def simulate_portfolio(
        self,
        tickers: list[str],
        prices: np.ndarray,
        returns_matrix: np.ndarray,
        weights: np.ndarray,
        num_sims: int = 10000,
        horizon: int = 20,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Portföy bazlı Monte Carlo.

        Args:
            tickers: Hisse kodları
            prices: Güncel fiyatlar (n_assets,)
            returns_matrix: Getiri matrisi (n_days × n_assets)
            weights: Portföy ağırlıkları (n_assets,)
            num_sims: Simülasyon sayısı
            horizon: Tahmin ufku
            seed: Rastgele tohum

        Returns:
            Portföy Monte Carlo sonuçları
        """
        rng = np.random.default_rng(seed) if seed is not None else np.random.default_rng()

        n_assets = len(tickers)
        returns_matrix.shape[0]

        # Korelasyon matrisi
        corr_matrix = np.corrcoef(returns_matrix.T)

        # Cholesky decomposition
        try:
            L = np.linalg.cholesky(corr_matrix)
        except np.linalg.LinAlgError:
            # Pozitif definite değilse düzelt
            eigvals, eigvecs = np.linalg.eigh(corr_matrix)
            eigvals = np.maximum(eigvals, 1e-6)
            corr_matrix = eigvecs @ np.diag(eigvals) @ eigvecs.T
            L = np.linalg.cholesky(corr_matrix)

        # Her asset için parametreler
        mean_returns = np.mean(returns_matrix, axis=0)
        std_returns = np.std(returns_matrix, axis=0)

        # Korelli simülasyon
        portfolio_returns = np.zeros(num_sims)
        asset_final_prices = np.zeros((num_sims, n_assets))

        for sim in range(num_sims):
            # Bağımsız random returns
            independent_z = rng.standard_normal((horizon, n_assets))

            # Korelli returns
            correlated_z = independent_z @ L.T

            # Her asset için fiyat yolu
            prices_path = np.zeros((horizon + 1, n_assets))
            prices_path[0] = prices

            for t in range(1, horizon + 1):
                daily_returns = mean_returns + std_returns * correlated_z[t - 1]
                prices_path[t] = prices_path[t - 1] * (1 + daily_returns)

            asset_final_prices[sim] = prices_path[-1]

            # Portföy getirisi
            weighted_returns = weights * (prices_path[-1] / prices - 1)
            portfolio_returns[sim] = np.sum(weighted_returns) * 100

        # İstatistikler
        var_95 = float(np.percentile(portfolio_returns, 5))
        tail_95 = portfolio_returns[portfolio_returns <= var_95]
        cvar_95 = float(np.mean(tail_95)) if len(tail_95) > 0 else var_95

        # Asset bazlı istatistikler
        asset_stats = {}
        for i, ticker in enumerate(tickers):
            asset_ret = (asset_final_prices[:, i] / prices[i] - 1) * 100
            asset_stats[ticker] = {
                "expected_return_pct": round(float(np.mean(asset_ret)), 2),
                "std_pct": round(float(np.std(asset_ret)), 2),
                "var_95": round(float(np.percentile(asset_ret, 5)), 2),
            }

        return {
            "portfolio": {
                "expected_return_pct": round(float(np.mean(portfolio_returns)), 2),
                "std_pct": round(float(np.std(portfolio_returns)), 2),
                "var_95": round(var_95, 2),
                "cvar_95": round(cvar_95, 2),
                "prob_positive": round(float(np.mean(portfolio_returns > 0) * 100), 1),
                "max_return_pct": round(float(np.max(portfolio_returns)), 2),
                "min_return_pct": round(float(np.min(portfolio_returns)), 2),
            },
            "assets": asset_stats,
            "correlation_matrix": corr_matrix.tolist(),
            "num_simulations": num_sims,
            "horizon_days": horizon,
        }


class RegimeConditionedMonteCarlo:
    """Rejime göre Monte Carlo parametreleri.

    Farklı rejimlerde farklı getiri ve volatilite parametreleri kullanır.
    """

    REGIME_PARAMS = {
        "BULL": {"return_mult": 1.5, "vol_mult": 0.8, "jump_intensity": 0.01},
        "BEAR": {"return_mult": 0.3, "vol_mult": 1.5, "jump_intensity": 0.03},
        "SIDEWAYS": {"return_mult": 0.8, "vol_mult": 1.0, "jump_intensity": 0.02},
        "HIGH-VOLATILITY": {"return_mult": 0.5, "vol_mult": 2.0, "jump_intensity": 0.04},
        "LOW-VOLATILITY": {"return_mult": 1.2, "vol_mult": 0.6, "jump_intensity": 0.01},
        "RISK-OFF": {"return_mult": 0.2, "vol_mult": 1.8, "jump_intensity": 0.05},
        "PANIC": {"return_mult": 0.0, "vol_mult": 3.0, "jump_intensity": 0.08},
        "CRISIS": {"return_mult": -0.5, "vol_mult": 3.5, "jump_intensity": 0.10},
        "RECOVERY": {"return_mult": 1.3, "vol_mult": 1.2, "jump_intensity": 0.02},
    }

    def simulate(
        self,
        current_price: float,
        daily_return: float,
        daily_vol: float,
        regime: str,
        num_sims: int = 10000,
        horizon: int = 20,
        seed: int | None = None,
    ) -> MonteCarloResult:
        """Rejim-conditioned Monte Carlo.

        Args:
            current_price: Güncel fiyat
            daily_return: Günlük getiri
            daily_vol: Günlük volatilite
            regime: Piyasa rejimi
            num_sims: Simülasyon sayısı
            horizon: Tahmin ufku
            seed: Rastgele tohum

        Returns:
            MonteCarloResult
        """
        params = self.REGIME_PARAMS.get(regime, self.REGIME_PARAMS["SIDEWAYS"])

        adjusted_return = daily_return * params["return_mult"]
        adjusted_vol = daily_vol * params["vol_mult"]
        jump_intensity = params["jump_intensity"]

        # Jump-diffusion ile simüle et
        mc = JumpDiffusionMonteCarlo()
        result = mc.simulate(
            current_price=current_price,
            daily_return=adjusted_return,
            daily_vol=adjusted_vol,
            num_sims=num_sims,
            horizon=horizon,
            jump_intensity=jump_intensity,
            jump_mean=-0.02,  # Negatif bias (crash risk)
            jump_std=0.05,
            seed=seed,
        )

        result.model = f"Regime-Conditioned ({regime})"
        return result


# Singleton
jump_diffusion_mc = JumpDiffusionMonteCarlo()
correlated_mc = CorrelatedMonteCarlo()
regime_mc = RegimeConditionedMonteCarlo()
