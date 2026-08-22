"""
ALPHA BIST — Monte Carlo Engine v1.0

Fiyat yolu simülasyonu:
- Binlerce olası gelecek yol
- Percentile dağılımları (P10, P25, P50, P75, P90)
- Olasılık hesaplamaları (P(+10%), P(-5%), vb.)
- Portfolio-level Monte Carlo (korelasyon matrisi ile)
- VaR / CVaR

FAZ 5.1-5.2: Monte Carlo Engine
"""

import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class MonteCarloResult:
    """Tek hisse Monte Carlo sonucu."""
    ticker: str
    current_price: float
    horizon_days: int
    num_simulations: int
    expected_return: float
    volatility: float

    # Percentile'ler
    p10: float   # %10 olasılıkla bu fiyatın altında
    p25: float
    p50: float   # Medyan
    p75: float
    p90: float

    # Olasılıklar
    prob_positive: float       # P(getiri > 0)
    prob_plus_5pct: float      # P(getiri > %5)
    prob_plus_10pct: float     # P(getiri > %10)
    prob_minus_5pct: float     # P(getiri < -%5)
    prob_minus_10pct: float    # P(getiri < -%10)

    # Risk
    var_95: float              # Value at Risk %95
    cvar_95: float             # Conditional VaR (Expected Shortfall)
    max_drawdown_sim: float    # Simülasyondaki max drawdown

    # Paths (opsiyonel, son 100 yol)
    sample_paths: Optional[np.ndarray] = None


@dataclass
class PortfolioMonteCarloResult:
    """Portföy Monte Carlo sonucu."""
    portfolio_value: float
    horizon_days: int
    num_simulations: int

    # Percentile'ler
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float

    # Risk
    var_95: float
    cvar_95: float
    prob_loss: float
    expected_return: float
    expected_drawdown: float


class MonteCarloEngine:
    """Monte Carlo simülasyon motoru."""

    def simulate_price_paths(
        self,
        ticker: str,
        current_price: float,
        expected_return_annual: float,
        volatility_annual: float,
        horizon_days: int = 20,
        num_simulations: int = 10000,
        seed: Optional[int] = None,
    ) -> MonteCarloResult:
        """Fiyat yolu simülasyonu (Geometric Brownian Motion).

        Args:
            current_price: Mevcut fiyat
            expected_return_annual: Yıllık beklenen getiri (örn: 0.15 = %15)
            volatility_annual: Yıllık volatilite (örn: 0.25 = %25)
            horizon_days: Simülasyon süresi (iş günü)
            num_simulations: Simülasyon sayısı
        """
        if seed is not None:
            np.random.seed(seed)

        # Günlük parametreler
        dt = 1 / 252  # 1 iş günü
        mu_daily = expected_return_annual * dt
        sigma_daily = volatility_annual * np.sqrt(dt)

        # Simülasyon
        # GBM: S(t+1) = S(t) * exp((mu - sigma^2/2)*dt + sigma*sqrt(dt)*Z)
        drift = (expected_return_annual - 0.5 * volatility_annual ** 2) * dt
        diffusion = sigma_daily

        # Rastgele sayılar
        Z = np.random.standard_normal((num_simulations, horizon_days))

        # Fiyat yolları
        log_returns = drift + diffusion * Z
        log_returns_cumulative = np.cumsum(log_returns, axis=1)

        # Başlangıç fiyatları
        prices = current_price * np.exp(log_returns_cumulative)

        # Son gün fiyatları
        final_prices = prices[:, -1]

        # Getiriler
        returns = (final_prices / current_price - 1) * 100

        # Percentile'ler
        p10 = float(np.percentile(final_prices, 10))
        p25 = float(np.percentile(final_prices, 25))
        p50 = float(np.percentile(final_prices, 50))
        p75 = float(np.percentile(final_prices, 75))
        p90 = float(np.percentile(final_prices, 90))

        # Olasılıklar
        prob_positive = float(np.mean(returns > 0))
        prob_plus_5 = float(np.mean(returns > 5))
        prob_plus_10 = float(np.mean(returns > 10))
        prob_minus_5 = float(np.mean(returns < -5))
        prob_minus_10 = float(np.mean(returns < -10))

        # VaR (95%)
        var_95 = float(np.percentile(returns, 5))  # %5'lik kayıp

        # CVaR (Expected Shortfall) — VaR'dan kötü durumların ortalaması
        var_threshold = np.percentile(returns, 5)
        tail_returns = returns[returns <= var_threshold]
        cvar_95 = float(np.mean(tail_returns)) if len(tail_returns) > 0 else var_95

        # Max drawdown (simülasyon içinden)
        max_dds = []
        for i in range(min(100, num_simulations)):  # İlk 100 yol için
            path = prices[i]
            peak = np.maximum.accumulate(path)
            dd = (peak - path) / peak
            max_dds.append(float(np.max(dd)))
        max_drawdown_sim = float(np.mean(max_dds)) if max_dds else 0

        # Sample paths (son 100 yol)
        sample = prices[:100] if num_simulations >= 100 else prices

        return MonteCarloResult(
            ticker=ticker,
            current_price=current_price,
            horizon_days=horizon_days,
            num_simulations=num_simulations,
            expected_return=round(float(np.mean(returns)), 2),
            volatility=round(float(np.std(returns)), 2),
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
            max_drawdown_sim=round(max_drawdown_sim * 100, 2),
            sample_paths=sample,
        )

    def simulate_portfolio(
        self,
        positions: List[Dict[str, Any]],
        correlation_matrix: np.ndarray,
        horizon_days: int = 20,
        num_simulations: int = 10000,
        seed: Optional[int] = None,
    ) -> PortfolioMonteCarloResult:
        """Portföy seviyesinde Monte Carlo.

        Args:
            positions: [{"ticker": "THYAO", "value": 10000, "return": 0.15, "vol": 0.25}, ...]
            correlation_matrix: NxN korelasyon matrisi
        """
        if seed is not None:
            np.random.seed(seed)

        n = len(positions)
        if n == 0:
            return PortfolioMonteCarloResult(
                portfolio_value=0, horizon_days=horizon_days,
                num_simulations=num_simulations,
                p10=0, p25=0, p50=0, p75=0, p90=0,
                var_95=0, cvar_95=0, prob_loss=0,
                expected_return=0, expected_drawdown=0,
            )

        # Pozisyon değerleri ve parametreler
        values = np.array([p.get("value", 0) for p in positions])
        returns_annual = np.array([p.get("return", 0.10) for p in positions])
        vols_annual = np.array([p.get("vol", 0.25) for p in positions])

        total_value = np.sum(values)
        weights = values / total_value if total_value > 0 else np.ones(n) / n

        # Korelasyon matrisinden kovaryans matrisi
        dt = 1 / 252
        daily_vols = vols_annual * np.sqrt(dt)
        cov_matrix = np.outer(daily_vols, daily_vols) * correlation_matrix

        # Cholesky decomposition
        try:
            L = np.linalg.cholesky(cov_matrix)
        except np.linalg.LinAlgError:
            # Pozitif tanımlı değilse, diyagonal kullan
            L = np.diag(daily_vols)

        # Simülasyon
        Z = np.random.standard_normal((num_simulations, horizon_days, n))
        correlated_Z = Z @ L.T  # (n_sims, horizon_days, n_assets) @ (n_assets, n_assets)

        # Her gün için portföy getirisi (vektörize)
        # stock_returns shape: (n_sims, horizon_days, n_assets)
        drift = (returns_annual - 0.5 * vols_annual ** 2) * dt  # (n_assets,)
        stock_returns = drift + correlated_Z  # broadcasting: (n_sims, horizon_days, n)
        # Ağırlıklı portföy getirisi
        daily_returns = np.einsum('ijk,k->ij', stock_returns, weights)  # (n_sims, horizon_days)

        # Kümülatif getiri
        cumulative_returns = np.cumprod(1 + daily_returns, axis=1)
        final_values = total_value * cumulative_returns[:, -1]

        # Percentile'ler
        p10 = float(np.percentile(final_values, 10))
        p25 = float(np.percentile(final_values, 25))
        p50 = float(np.percentile(final_values, 50))
        p75 = float(np.percentile(final_values, 75))
        p90 = float(np.percentile(final_values, 90))

        # Risk
        portfolio_returns = (final_values / total_value - 1) * 100
        var_95 = float(np.percentile(portfolio_returns, 5))

        var_threshold = np.percentile(portfolio_returns, 5)
        tail = portfolio_returns[portfolio_returns <= var_threshold]
        cvar_95 = float(np.mean(tail)) if len(tail) > 0 else var_95

        prob_loss = float(np.mean(portfolio_returns < 0))
        expected_return = float(np.mean(portfolio_returns))

        # Max drawdown
        max_dds = []
        for i in range(min(100, num_simulations)):
            path = cumulative_returns[i]
            peak = np.maximum.accumulate(path)
            dd = (peak - path) / peak
            max_dds.append(float(np.max(dd)))
        expected_drawdown = float(np.mean(max_dds)) * 100 if max_dds else 0

        return PortfolioMonteCarloResult(
            portfolio_value=round(total_value, 2),
            horizon_days=horizon_days,
            num_simulations=num_simulations,
            p10=round(p10, 2),
            p25=round(p25, 2),
            p50=round(p50, 2),
            p75=round(p75, 2),
            p90=round(p90, 2),
            var_95=round(var_95, 2),
            cvar_95=round(cvar_95, 2),
            prob_loss=round(prob_loss, 4),
            expected_return=round(expected_return, 2),
            expected_drawdown=round(expected_drawdown, 2),
        )

    def compute_dynamic_scenario_count(
        self,
        volatility: float,
        model_uncertainty: float,
        portfolio_size: float,
        compute_budget_ms: float = 1000,
    ) -> int:
        """Dinamik senaryo sayısı (volatilite ve belirsizliğe göre).

        Yüksek volatilite → daha fazla senaryo
        Yüksek belirsizlik → daha fazla senaryo
        """
        base = 1000
        vol_mult = max(1.0, volatility / 0.20)
        uncertainty_mult = max(1.0, model_uncertainty / 0.30)
        size_mult = max(1.0, portfolio_size / 100000)

        count = int(base * vol_mult * uncertainty_mult * size_mult)
        max_count = int(compute_budget_ms / 0.001)  # ~0.001s per scenario

        return min(count, max_count, 50000)


# Singleton
monte_carlo_engine = MonteCarloEngine()
