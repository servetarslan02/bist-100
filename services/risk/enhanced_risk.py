"""
ALPHA BIST — Enhanced Risk & Portfolio Engine v1.0

Risk:
- Ledoit-Wolf covariance estimation
- Volatility targeting
- Correlation risk
- Concentration risk

Portfolio:
- Markowitz optimization with transaction costs
- Kelly criterion position sizing
- Rebalance rules

Kaynak: Du (2026) — Ledoit-Wolf; Oxford — volatility targeting
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class PortfolioWeights:
    """Portföy ağırlıkları."""

    weights: dict[str, float]  # ticker → weight (0-1)
    total_weight: float
    n_positions: int
    max_weight: float
    min_weight: float


@dataclass
class RiskMetrics:
    """Risk metrikleri."""

    portfolio_volatility: float
    concentration_hhi: float
    max_position_weight: float
    sector_concentration: dict[str, float]
    correlation_risk: float
    var_95: float
    cvar_95: float
    var_99: float = 0.0
    cvar_99: float = 0.0
    component_var: dict[str, float] | None = None
    risk_score: float = 0.0  # 0-100


class LedoitWolfCovariance:
    """Ledoit-Wolf shrinkage covariance estimation with PSD guarantee."""

    def estimate(self, returns: np.ndarray, shrinkage: float | None = None) -> np.ndarray:
        """Kovaryans matrisi tahmin et.

        Args:
            returns: Getiri matrisi (n_days × n_assets)
            shrinkage: Shrinkage katsayısı (0-1). None ise otomatik.
        """
        from .covariance import ensure_positive_semi_definite

        returns = np.asarray(returns, dtype=float)
        if np.isnan(returns).any() or np.isinf(returns).any():
            returns = np.nan_to_num(returns, nan=0.0, posinf=0.0, neginf=0.0)

        n_days, n_assets = returns.shape if returns.ndim == 2 else (len(returns), 1)

        if n_days < 2 or n_assets < 2:
            return np.eye(max(1, n_assets))

        # Sample covariance
        sample_cov = np.cov(returns.T)

        # Ledoit-Wolf shrinkage target (diagonal)
        target = np.diag(np.diag(sample_cov))

        # Otomatik shrinkage
        if shrinkage is None:
            shrinkage = self._estimate_shrinkage(returns, sample_cov, target)

        # Shrunk covariance
        shrunk_cov = (1 - shrinkage) * sample_cov + shrinkage * target

        # Ensure positive semi-definiteness
        psd_cov = ensure_positive_semi_definite(shrunk_cov)

        return psd_cov

    def _estimate_shrinkage(self, returns: np.ndarray, sample_cov: np.ndarray, target: np.ndarray) -> float:
        """Otomatik shrinkage katsayısı tahmin et."""
        n = returns.shape[0]
        if n < 2:
            return 0.5

        # Veri azaldıkça shrinkage artar
        shrinkage = min(0.9, max(0.1, 1 - n / 252))
        return shrinkage



class VolatilityTargeter:
    """Volatility targeting — portföy volatilitesini hedefle.

    Düşük volatilite → kaldıraç artır
    Yüksek volatilite → pozisyon küçült
    """

    def compute_leverage(
        self,
        current_vol: float,
        target_vol: float,
        max_leverage: float = 2.0,
        min_leverage: float = 0.1,
    ) -> float:
        """Kaldıraç hesapla."""
        if current_vol <= 0:
            return 1.0

        leverage = target_vol / current_vol
        return max(min_leverage, min(max_leverage, leverage))

    def adjust_weights(
        self,
        weights: dict[str, float],
        current_vol: float,
        target_vol: float,
    ) -> dict[str, float]:
        """Ağırlıkları volatility target'a göre ayarla."""
        leverage = self.compute_leverage(current_vol, target_vol)

        adjusted = {}
        for ticker, weight in weights.items():
            adjusted[ticker] = weight * leverage

        # Normalize to sum <= 1
        total = sum(adjusted.values())
        if total > 1:
            for ticker in adjusted:
                adjusted[ticker] /= total

        return adjusted


class PositionSizer:
    """Pozisyon büyüklüğü hesaplama (Kelly criterion benzeri)."""

    def kelly_criterion(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        fraction: float = 0.5,
    ) -> float:
        """Kelly criterion.

        f* = (p * b - q) / b
        p = win_rate, q = 1-p, b = avg_win/avg_loss

        fraction: Kelly fraction (0.5 = half-Kelly, daha güvenli)
        """
        if avg_loss == 0 or win_rate <= 0 or win_rate >= 1:
            return 0.0

        b = avg_win / avg_loss
        q = 1 - win_rate
        kelly = (win_rate * b - q) / b

        # Negatif = bahis yapma
        if kelly <= 0:
            return 0.0

        # Fraction (yarım Kelly daha güvenli)
        return kelly * fraction

    def compute_position_size(
        self,
        capital: float,
        kelly_fraction: float,
        price: float,
        stop_distance: float,
        max_position_pct: float = 10.0,
    ) -> int:
        """Pozisyon büyüklüğü (lot)."""
        if price <= 0 or stop_distance <= 0:
            return 0

        # Kelly'den pozisyon büyüklüğü
        position_value = capital * kelly_fraction

        # Stop'a göre maksimum zarar
        max_loss_per_share = stop_distance
        shares_from_stop = int(position_value / max_loss_per_share) if max_loss_per_share > 0 else 0

        # Max position limit
        max_position_value = capital * (max_position_pct / 100)
        shares_from_limit = int(max_position_value / price)

        # Minimum olanı seç
        return min(shares_from_stop, shares_from_limit) if shares_from_stop > 0 else shares_from_limit


class RebalanceEngine:
    """Portföy rebalance motoru."""

    def __init__(self, turnover_limit: float = 0.3, threshold_pct: float = 5.0):
        self.turnover_limit = turnover_limit  # Maksimum turnover (0-1)
        self.threshold_pct = threshold_pct  # Sapma eşiği (%)

    def compute_rebalance(
        self,
        current_weights: dict[str, float],
        target_weights: dict[str, float],
        portfolio_value: float,
    ) -> dict[str, dict]:
        """Rebalance emirleri hesapla.

        Returns:
            {ticker: {"action": "BUY"|"SELL", "shares": int, "value": float}}
        """
        orders = {}

        all_tickers = set(list(current_weights.keys()) + list(target_weights.keys()))

        for ticker in all_tickers:
            current = current_weights.get(ticker, 0)
            target = target_weights.get(ticker, 0)
            diff = target - current

            # Eşik kontrolü
            if abs(diff) < self.threshold_pct / 100:
                continue

            value = diff * portfolio_value
            action = "BUY" if diff > 0 else "SELL"

            orders[ticker] = {
                "action": action,
                "value": round(abs(value), 2),
                "weight_change": round(diff * 100, 2),
            }

        # Turnover limit kontrolü
        total_turnover = sum(abs(o["weight_change"]) for o in orders.values()) / 100
        if total_turnover > self.turnover_limit:
            # Turnover'ı sınırla
            scale = self.turnover_limit / total_turnover
            for ticker in orders:
                orders[ticker]["value"] = round(orders[ticker]["value"] * scale, 2)
                orders[ticker]["weight_change"] = round(orders[ticker]["weight_change"] * scale, 2)

        return orders

    def compute_next_rebalance(
        self,
        last_rebalance: datetime,
        frequency_days: int = 7,
    ) -> datetime:
        """Sonraki rebalance tarihi."""
        return last_rebalance + timedelta(days=frequency_days)


class ConcentrationRisk:
    """Konsantrasyon riski hesaplama."""

    def compute_hhi(self, weights: dict[str, float]) -> float:
        """Herfindahl-Hirschman Index (HHI).

        HHI = sum(w_i²)
        1/N = perfect diversification
        1.0 = all in one stock
        """
        return sum(w**2 for w in weights.values())

    def compute_sector_concentration(
        self,
        weights: dict[str, float],
        sector_map: dict[str, str],
    ) -> dict[str, float]:
        """Sektör konsantrasyonu."""
        sector_weights = {}
        for ticker, weight in weights.items():
            sector = sector_map.get(ticker, "OTHER")
            sector_weights[sector] = sector_weights.get(sector, 0) + weight
        return sector_weights

    def compute_max_concentration(self, weights: dict[str, float]) -> tuple[str, float]:
        """En konsantre pozisyon."""
        if not weights:
            return "", 0.0
        max_ticker = max(weights, key=weights.get)
        return max_ticker, weights[max_ticker]


# Singletons
ledoit_wolf = LedoitWolfCovariance()
volatility_targeter = VolatilityTargeter()
position_sizer = PositionSizer()
rebalance_engine = RebalanceEngine()
concentration_risk = ConcentrationRisk()


def compute_full_risk_metrics(
    returns: np.ndarray,
    weights: dict[str, float],
    cov_matrix: np.ndarray = None,
    sector_map: dict[str, str] = None,
    portfolio_value: float = 100000.0,
) -> RiskMetrics:
    """Kapsamlı risk metrikleri hesapla.

    VaR/CVaR + concentration + volatility + correlation birlikte.

    Args:
        returns: Portföy getiri dizisi
        weights: Pozisyon ağırlıkları
        cov_matrix: Kovaryans matrisi (opsiyonel)
        sector_map: Sektör eşleme (opsiyonel)
        portfolio_value: Portföy değeri

    Returns:
        RiskMetrics
    """
    from .var_cvar import var_calculator

    weights_array = np.array(list(weights.values()))
    tickers = list(weights.keys())

    # VaR/CVaR
    var_95 = var_calculator.calculate_historical_var(returns, 0.95, portfolio_value)
    cvar_95 = var_calculator.calculate_historical_cvar(returns, 0.95, portfolio_value)
    var_99 = var_calculator.calculate_historical_var(returns, 0.99, portfolio_value)
    cvar_99 = var_calculator.calculate_historical_cvar(returns, 0.99, portfolio_value)

    # Portfolio volatility
    port_vol = float(np.std(returns, ddof=1) * np.sqrt(252))

    # Concentration
    hhi = concentration_risk.compute_hhi(weights)
    max_ticker, max_weight = concentration_risk.compute_max_concentration(weights)

    # Sector concentration
    sector_conc = {}
    if sector_map:
        sector_conc = concentration_risk.compute_sector_concentration(weights, sector_map)

    # Correlation risk
    corr_risk = 0.0
    if cov_matrix is not None and len(weights) > 1:
        corr_matrix = cov_matrix / np.outer(np.sqrt(np.diag(cov_matrix)), np.sqrt(np.diag(cov_matrix)))
        upper_tri = corr_matrix[np.triu_indices_from(corr_matrix, k=1)]
        corr_risk = float(np.mean(np.abs(upper_tri)))

    # Component VaR
    component_var = None
    if cov_matrix is not None and len(weights) > 1:
        try:
            cv = var_calculator.calculate_component_var(weights_array, cov_matrix, 0.95, portfolio_value, tickers)
            component_var = {cvr.ticker: cvr.component_var_95 for cvr in cv}
        except Exception:
            logger.warning("Caught Exception in compute_full_risk_metrics", exc_info=True)

    # Risk score (0-100)
    risk_score = 50.0
    risk_score += min(20, (var_95 / portfolio_value * 100) * 4)  # VaR etkisi
    risk_score += min(15, hhi * 100)  # Konsantrasyon etkisi
    risk_score += min(15, port_vol * 50)  # Volatilite etkisi
    risk_score = min(100, risk_score)

    return RiskMetrics(
        portfolio_volatility=port_vol,
        concentration_hhi=hhi,
        max_position_weight=max_weight,
        sector_concentration=sector_conc,
        correlation_risk=corr_risk,
        var_95=var_95,
        cvar_95=cvar_95,
        var_99=var_99,
        cvar_99=cvar_99,
        component_var=component_var,
        risk_score=round(risk_score, 1),
    )


# =====================================================
# VIOP Hedging Entegrasyonu (B32)
# =====================================================
def suggest_hedge(portfolio_value: float, beta: float, futures_price: float) -> dict[str, Any]:
    """Portföy hedge önerisi."""
    try:
        from services.viop.hedging import hedge_portfolio

        return hedge_portfolio(portfolio_value, beta, futures_price)
    except Exception as e:
        logger.warning("VIOP hedging failed", error=str(e))
        return {"error": "VIOP hedging not available"}


def check_options_strategy(
    spot_price: float, strike: float, premium: float, strategy_type: str = "covered_call"
) -> dict[str, Any]:
    """Opsiyon stratejisi kontrolü."""
    try:
        from services.viop.strategies import create_covered_call, create_protective_put

        if strategy_type == "covered_call":
            return create_covered_call(spot_price, strike, premium, 100)
        elif strategy_type == "protective_put":
            return create_protective_put(spot_price, strike, premium, 100)
    except Exception as e:
        logger.warning("VIOP strategies failed", error=str(e))
        return {"error": "VIOP strategies not available"}
