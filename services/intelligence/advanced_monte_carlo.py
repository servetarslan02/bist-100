"""
ALPHA BIST — Advanced Monte Carlo Engine v1.0

Gelişmiş Monte Carlo simülasyonları:
- Merton Jump-Diffusion Model
- Student-t Distribution (Fat Tails)
- Stochastic Volatility (Heston-lite)
- Correlated Multi-Asset Paths

Kullanım:
    engine = AdvancedMonteCarloEngine()
    result = engine.jump_diffusion_sim(current_price=100, mu=0.15, sigma=0.25)
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class AdvancedMCResult:
    """Gelişmiş Monte Carlo sonucu."""
    ticker: str
    model_type: str              # "gbm", "jump_diffusion", "student_t", "heston"
    current_price: float
    horizon_days: int
    num_simulations: int

    # Percentile'ler
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float

    # Olasılıklar
    prob_positive: float
    prob_plus_5pct: float
    prob_plus_10pct: float
    prob_minus_5pct: float
    prob_minus_10pct: float

    # Risk
    var_95: float
    cvar_95: float
    max_drawdown_sim: float

    # Model-specific
    expected_return: float
    volatility: float
    skewness: float = 0.0
    kurtosis: float = 0.0
    jump_intensity: float = 0.0
    jump_mean: float = 0.0
    jump_std: float = 0.0

    sample_paths: Optional[np.ndarray] = None


class AdvancedMonteCarloEngine:
    """Gelişmiş Monte Carlo simülasyon motoru."""

    def gbm_sim(
        self,
        ticker: str,
        current_price: float,
        mu: float,
        sigma: float,
        horizon_days: int = 20,
        n_sims: int = 10000,
        seed: Optional[int] = None,
    ) -> AdvancedMCResult:
        """Geometric Brownian Motion (standart)."""
        if seed is not None:
            np.random.seed(seed)

        dt = 1 / 252
        drift = (mu - 0.5 * sigma**2) * dt
        diffusion = sigma * np.sqrt(dt)

        Z = np.random.standard_normal((n_sims, horizon_days))
        log_returns = drift + diffusion * Z
        log_returns_cum = np.cumsum(log_returns, axis=1)
        prices = current_price * np.exp(log_returns_cum)
        final = prices[:, -1]
        returns = (final / current_price - 1) * 100

        return self._build_result(ticker, "gbm", current_price, horizon_days, n_sims, prices, final, returns, sigma)

    def jump_diffusion_sim(
        self,
        ticker: str,
        current_price: float,
        mu: float,
        sigma: float,
        jump_intensity: float = 0.1,    # Yılda ortalama 0.1 atlama
        jump_mean: float = -0.02,       # Atlama ortalama getirisi
        jump_std: float = 0.05,         # Atlama standart sapması
        horizon_days: int = 20,
        n_sims: int = 10000,
        seed: Optional[int] = None,
    ) -> AdvancedMCResult:
        """Merton Jump-Diffusion Model.

        Fiyat sıçramaları (gap) modeller.
        Ani düşüşler (crash) ve sıçramaları yakalar.

        Args:
            jump_intensity: Yılda ortalama atlama sayısı
            jump_mean: Atlama ortalama getirisi (negatif = düşüş)
            jump_std: Atlama standart sapması
        """
        if seed is not None:
            np.random.seed(seed)

        dt = 1 / 252
        # Compensator: jump'ların beklenen etkisini düzelt
        lambda_t = jump_intensity * dt
        compensator = jump_intensity * (np.exp(jump_mean + 0.5 * jump_std**2) - 1)

        drift = (mu - 0.5 * sigma**2 - compensator) * dt
        diffusion = sigma * np.sqrt(dt)

        # Include t=0 so a horizon of N contains exactly N daily moves.
        prices = np.zeros((n_sims, horizon_days + 1))
        prices[:, 0] = current_price

        for t in range(1, horizon_days + 1):
            Z = np.random.standard_normal(n_sims)

            # Diffusion component
            log_return = drift + diffusion * Z

            # Jump component
            n_jumps = np.random.poisson(lambda_t, n_sims)
            jump_sizes = np.zeros(n_sims)
            for i in range(n_sims):
                if n_jumps[i] > 0:
                    jump_sizes[i] = np.sum(np.random.normal(jump_mean, jump_std, n_jumps[i]))

            # Combined return
            total_return = log_return + jump_sizes
            prices[:, t] = prices[:, t-1] * np.exp(total_return)

        final = prices[:, -1]
        returns = (final / current_price - 1) * 100

        result = self._build_result(ticker, "jump_diffusion", current_price, horizon_days, n_sims, prices, final, returns, sigma)
        result.jump_intensity = jump_intensity
        result.jump_mean = jump_mean
        result.jump_std = jump_std

        logger.info("Jump-diffusion simulation",
                   ticker=ticker,
                   jump_intensity=jump_intensity,
                   skewness=result.skewness)

        return result

    def student_t_sim(
        self,
        ticker: str,
        current_price: float,
        mu: float,
        sigma: float,
        degrees_of_freedom: float = 5.0,
        horizon_days: int = 20,
        n_sims: int = 10000,
        seed: Optional[int] = None,
    ) -> AdvancedMCResult:
        """Student-t Distribution (Fat Tails).

        Normal dağılımdan daha kalın kuyruklar.
        aşırı olayları (crash, spike) daha iyi modeller.

        Args:
            degrees_of_freedom: Serbestlik derecesi (düşük = daha kalın kuyruk)
                - 3: Çok kalın kuyruk
                - 5: Kalın kuyruk (finans için tipik)
                - 10: Orta
                - 30+: Normal'e yakın
        """
        if seed is not None:
            np.random.seed(seed)

        dt = 1 / 252
        drift = (mu - 0.5 * sigma**2) * dt
        diffusion = sigma * np.sqrt(dt)

        # Student-t rastgele sayılar
        Z = np.random.standard_t(degrees_of_freedom, (n_sims, horizon_days))
        # Normalize et (std = 1 olacak şekilde)
        Z = Z / np.sqrt(degrees_of_freedom / (degrees_of_freedom - 2))

        log_returns = drift + diffusion * Z
        log_returns_cum = np.cumsum(log_returns, axis=1)
        prices = current_price * np.exp(log_returns_cum)
        final = prices[:, -1]
        returns = (final / current_price - 1) * 100

        result = self._build_result(ticker, "student_t", current_price, horizon_days, n_sims, prices, final, returns, sigma)

        logger.info("Student-t simulation",
                   ticker=ticker,
                   df=degrees_of_freedom,
                   kurtosis=result.kurtosis)

        return result

    def heston_lite_sim(
        self,
        ticker: str,
        current_price: float,
        mu: float,
        sigma: float,
        vol_of_vol: float = 0.3,     # Volatilitenin volatilitesi
        mean_reversion: float = 2.0,  # Volatility mean reversion hızı
        horizon_days: int = 20,
        n_sims: int = 10000,
        seed: Optional[int] = None,
    ) -> AdvancedMCResult:
        """Heston-lite Stochastic Volatility.

        Volatilite sabit değil, stokastik.
        Vol clustering (yüksek vol'un yüksek vol takip etmesi) modeller.

        Args:
            vol_of_vol: Volatilitenin volatilitesi
            mean_reversion: Volatility mean reversion hızı (kappa)
        """
        if seed is not None:
            np.random.seed(seed)

        dt = 1 / 252
        kappa = mean_reversion
        theta = sigma**2  # Uzun dönem ortalama variance
        xi = vol_of_vol   # Vol of vol

        # Include t=0 for the same reason as the GBM and jump-diffusion
        # paths; otherwise the requested horizon is shortened by one day.
        prices = np.zeros((n_sims, horizon_days + 1))
        vols = np.zeros((n_sims, horizon_days + 1))
        prices[:, 0] = current_price
        vols[:, 0] = sigma

        for t in range(1, horizon_days + 1):
            Z1 = np.random.standard_normal(n_sims)
            Z2 = np.random.standard_normal(n_sims)
            # Korelasyon: -0.7 (asimetrik — fiyat düşünce vol artar)
            rho = -0.7
            Z2 = rho * Z1 + np.sqrt(1 - rho**2) * Z2

            # Stochastic volatility update (Euler-Maruyama)
            v_t = vols[:, t-1]**2
            v_t = np.maximum(v_t, 0.0001)  # Negatif variance önle
            dv = kappa * (theta - v_t) * dt + xi * np.sqrt(v_t * dt) * Z2
            v_new = np.maximum(v_t + dv, 0.0001)
            vols[:, t] = np.sqrt(v_new)

            # Fiyat update (stochastic vol ile)
            drift = (mu - 0.5 * v_new) * dt
            diffusion = np.sqrt(v_new * dt) * Z1
            prices[:, t] = prices[:, t-1] * np.exp(drift + diffusion)

        final = prices[:, -1]
        returns = (final / current_price - 1) * 100

        result = self._build_result(ticker, "heston", current_price, horizon_days, n_sims, prices, final, returns, sigma)

        logger.info("Heston-lite simulation",
                   ticker=ticker,
                   vol_of_vol=vol_of_vol,
                   mean_reversion=mean_reversion)

        return result

    def _build_result(
        self,
        ticker: str,
        model_type: str,
        current_price: float,
        horizon_days: int,
        n_sims: int,
        prices: np.ndarray,
        final: np.ndarray,
        returns: np.ndarray,
        sigma: float,
    ) -> AdvancedMCResult:
        """Sonuç objesi oluştur."""
        p10 = float(np.percentile(final, 10))
        p25 = float(np.percentile(final, 25))
        p50 = float(np.percentile(final, 50))
        p75 = float(np.percentile(final, 75))
        p90 = float(np.percentile(final, 90))

        prob_positive = float(np.mean(returns > 0))
        prob_plus_5 = float(np.mean(returns > 5))
        prob_plus_10 = float(np.mean(returns > 10))
        prob_minus_5 = float(np.mean(returns < -5))
        prob_minus_10 = float(np.mean(returns < -10))

        var_95 = float(np.percentile(returns, 5))
        var_threshold = np.percentile(returns, 5)
        tail = returns[returns <= var_threshold]
        cvar_95 = float(np.mean(tail)) if len(tail) > 0 else var_95

        # Max drawdown
        max_dds = []
        for i in range(min(200, n_sims)):
            path = prices[i]
            peak = np.maximum.accumulate(path)
            dd = (peak - path) / peak
            max_dds.append(float(np.max(dd)))
        max_dd = float(np.mean(max_dds)) * 100 if max_dds else 0

        # Skewness ve kurtosis
        skewness = float(np.mean(((returns - np.mean(returns)) / max(np.std(returns), 0.001))**3))
        kurtosis = float(np.mean(((returns - np.mean(returns)) / max(np.std(returns), 0.001))**4) - 3)

        return AdvancedMCResult(
            ticker=ticker,
            model_type=model_type,
            current_price=current_price,
            horizon_days=horizon_days,
            num_simulations=n_sims,
            p10=round(p10, 2),
            p25=round(p25, 2),
            p50=round(p50, 2),
            p75=round(p75, 2),
            p90=round(p90, 2),
            prob_positive=round(prob_positive, 4),
            prob_plus_5pct=round(prob_plus_5, 4),
            prob_plus_10pct=round(prob_plus_10, 4),
            prob_minus_5pct=round(prob_minus_5, 4),
            prob_minus_10pct=round(prob_minus_10, 4),
            var_95=round(var_95, 2),
            cvar_95=round(cvar_95, 2),
            max_drawdown_sim=round(max_dd, 2),
            expected_return=round(float(np.mean(returns)), 2),
            volatility=round(float(np.std(returns)), 2),
            skewness=round(skewness, 4),
            kurtosis=round(kurtosis, 4),
            sample_paths=prices[:100],
        )


# Singleton
advanced_mc_engine = AdvancedMonteCarloEngine()
