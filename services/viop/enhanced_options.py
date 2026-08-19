"""
ALPHA BIST — Enhanced Options System v2.0

Gelişmiş opsiyon sistemi:
- Implied Volatility (Newton-Raphson)
- Portfolio Greeks aggregation
- 8+ strateji (Collar, Iron Condor, Straddle, Strangle, Bull/Bear Spread, Butterfly)
- Dynamic Delta Hedging
- SPAN Margin (16 senaryo)
- Futures-Spot Arbitrage

Kaynaklar: TradingBlock (2025), arXiv LLM Options (2026), DaystoExpiry (2025), BIST
"""

import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from scipy.stats import norm
import structlog

logger = structlog.get_logger()


# =====================================================
# Black-Scholes + Greeks
# =====================================================

def black_scholes(S: float, K: float, T: float, r: float, sigma: float,
                  option_type: str = "call") -> float:
    """Black-Scholes opsiyon fiyatlaması."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0

    d1 = (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    if option_type == "call":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def calculate_greeks(S: float, K: float, T: float, r: float, sigma: float,
                     option_type: str = "call") -> Dict[str, float]:
    """Delta, Gamma, Theta, Vega, Rho."""
    if T <= 0 or sigma <= 0:
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "rho": 0}

    d1 = (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
    vega = S * norm.pdf(d1) * np.sqrt(T) / 100

    if option_type == "call":
        delta = norm.cdf(d1)
        theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T)) - r * K * np.exp(-r * T) * norm.cdf(d2)) / 365
        rho = K * T * np.exp(-r * T) * norm.cdf(d2) / 100
    else:
        delta = norm.cdf(d1) - 1
        theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T)) + r * K * np.exp(-r * T) * norm.cdf(-d2)) / 365
        rho = -K * T * np.exp(-r * T) * norm.cdf(-d2) / 100

    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 4),
        "vega": round(vega, 4),
        "rho": round(rho, 4),
    }


# =====================================================
# Implied Volatility
# =====================================================

class ImpliedVolatility:
    """Implied volatility hesaplama (Newton-Raphson).

    Piyasa opsiyon fiyatından gizli volatiliteyi bulur.
    """

    def calculate(
        self,
        market_price: float,
        S: float,
        K: float,
        T: float,
        r: float,
        option_type: str = "call",
        max_iterations: int = 100,
        tolerance: float = 1e-6,
    ) -> float:
        """Newton-Raphson ile implied volatility.

        Args:
            market_price: Piyasa opsiyon fiyatı
            S: Dayanak fiyat
            K: Kullanım fiyatı
            T: Vade (yıl)
            r: Risksiz faiz
            option_type: call / put
            max_iterations: Maksimum iterasyon
            tolerance: Tolerans

        Returns:
            Implied volatility
        """
        if market_price <= 0 or S <= 0 or K <= 0 or T <= 0:
            return 0.0

        sigma = 0.30  # Başlangıç tahmini

        for _ in range(max_iterations):
            price = black_scholes(S, K, T, r, sigma, option_type)
            diff = price - market_price

            if abs(diff) < tolerance:
                return round(sigma, 4)

            # Vega
            d1 = (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))
            vega = S * norm.pdf(d1) * np.sqrt(T)

            if abs(vega) < 1e-10:
                break

            # Newton-Raphson güncelleme
            sigma = sigma - diff / vega
            sigma = max(0.01, min(sigma, 2.0))

        return round(sigma, 4)

    def calculate_batch(
        self,
        options: List[Dict[str, Any]],
        S: float,
        r: float,
    ) -> List[Dict[str, Any]]:
        """Toplu IV hesaplama.

        Args:
            options: Opsiyon listesi [{"market_price", "K", "T", "option_type"}]
            S: Dayanak fiyat
            r: Risksiz faiz

        Returns:
            IV sonuçları
        """
        results = []
        for opt in options:
            iv = self.calculate(
                market_price=opt.get("market_price", 0),
                S=S,
                K=opt.get("K", 0),
                T=opt.get("T", 0),
                r=r,
                option_type=opt.get("option_type", "call"),
            )
            results.append({
                "strike": opt.get("K"),
                "option_type": opt.get("option_type"),
                "market_price": opt.get("market_price"),
                "implied_vol": iv,
            })
        return results


# =====================================================
# Portfolio Greeks
# =====================================================

@dataclass
class PortfolioGreeksResult:
    """Portföy Greeks sonucu."""
    total_delta: float
    total_gamma: float
    total_theta: float
    total_vega: float
    total_rho: float
    n_positions: int
    delta_neutral: bool
    position_details: List[Dict[str, Any]]


class PortfolioGreeks:
    """Portföy bazlı Greeks aggregation.

    Tüm opsiyon pozisyonlarının Greeks'lerini toplar.
    """

    def aggregate(
        self,
        positions: List[Dict[str, Any]],
    ) -> PortfolioGreeksResult:
        """Portföy Greeks hesapla.

        Args:
            positions: Pozisyon listesi
                [{"option_type", "S", "K", "T", "r", "sigma", "quantity", "side"}]

        Returns:
            PortfolioGreeksResult
        """
        total_delta = 0.0
        total_gamma = 0.0
        total_theta = 0.0
        total_vega = 0.0
        total_rho = 0.0
        details = []

        for pos in positions:
            greeks = calculate_greeks(
                S=pos.get("S", 0),
                K=pos.get("K", 0),
                T=pos.get("T", 0),
                r=pos.get("r", 0.15),
                sigma=pos.get("sigma", 0.25),
                option_type=pos.get("option_type", "call"),
            )

            multiplier = pos.get("quantity", 1) * (
                1 if pos.get("side", "long") == "long" else -1
            )

            pos_delta = greeks["delta"] * multiplier
            pos_gamma = greeks["gamma"] * multiplier
            pos_theta = greeks["theta"] * multiplier
            pos_vega = greeks["vega"] * multiplier
            pos_rho = greeks["rho"] * multiplier

            total_delta += pos_delta
            total_gamma += pos_gamma
            total_theta += pos_theta
            total_vega += pos_vega
            total_rho += pos_rho

            details.append({
                "option_type": pos.get("option_type"),
                "strike": pos.get("K"),
                "side": pos.get("side"),
                "quantity": pos.get("quantity"),
                "delta": round(pos_delta, 4),
                "gamma": round(pos_gamma, 6),
                "theta": round(pos_theta, 4),
                "vega": round(pos_vega, 4),
            })

        return PortfolioGreeksResult(
            total_delta=round(total_delta, 4),
            total_gamma=round(total_gamma, 6),
            total_theta=round(total_theta, 4),
            total_vega=round(total_vega, 4),
            total_rho=round(total_rho, 4),
            n_positions=len(positions),
            delta_neutral=abs(total_delta) < 0.05,
            position_details=details,
        )


# =====================================================
# Options Strategies
# =====================================================

@dataclass
class StrategyResult:
    """Strateji sonucu."""
    strategy: str
    max_profit: float
    max_loss: float
    breakeven: List[float]
    risk_reward: float
    description: str
    legs: List[Dict[str, Any]]


class OptionsStrategies:
    """Opsiyon strateji kütüphanesi.

    8+ strateji:
    - Covered Call
    - Protective Put
    - Collar
    - Iron Condor
    - Straddle
    - Strangle
    - Bull Call Spread
    - Bear Put Spread
    - Butterfly
    """

    def covered_call(
        self,
        spot: float,
        call_strike: float,
        call_premium: float,
        shares: int = 100,
    ) -> StrategyResult:
        """Covered Call: hisse sahibi + call sat.

        Kullanım: Düşük volatilite, gelir elde etme.
        """
        max_profit = (call_strike - spot + call_premium) * shares
        max_loss = (spot - call_premium) * shares
        breakeven = spot - call_premium

        return StrategyResult(
            strategy="COVERED_CALL",
            max_profit=round(max_profit, 2),
            max_loss=round(-max_loss, 2),
            breakeven=[round(breakeven, 2)],
            risk_reward=round(abs(max_profit / max_loss), 2) if max_loss != 0 else 0,
            description="Hisse sahibi + Call sat → gelir elde et, sınırlı upside",
            legs=[
                {"action": "LONG", "instrument": "STOCK", "quantity": shares, "price": spot},
                {"action": "SHORT", "instrument": "CALL", "strike": call_strike, "premium": call_premium},
            ],
        )

    def protective_put(
        self,
        spot: float,
        put_strike: float,
        put_premium: float,
        shares: int = 100,
    ) -> StrategyResult:
        """Protective Put: hisse sahibi + put al.

        Kullanım: Düşüş koruması.
        """
        max_loss = (spot - put_strike + put_premium) * shares
        breakeven = spot + put_premium

        return StrategyResult(
            strategy="PROTECTIVE_PUT",
            max_profit=999999,  # Unlimited upside
            max_loss=round(-max_loss, 2),
            breakeven=[round(breakeven, 2)],
            risk_reward=0,  # Unlimited
            description="Hisse sahibi + Put al → düşüş koruması, unlimited upside",
            legs=[
                {"action": "LONG", "instrument": "STOCK", "quantity": shares, "price": spot},
                {"action": "LONG", "instrument": "PUT", "strike": put_strike, "premium": put_premium},
            ],
        )

    def collar(
        self,
        spot: float,
        put_strike: float,
        put_premium: float,
        call_strike: float,
        call_premium: float,
        shares: int = 100,
    ) -> StrategyResult:
        """Collar: protective put + covered call.

        Kullanım: Sınırlı risk, sınırlı ödül.
        """
        net_premium = call_premium - put_premium
        max_profit = (call_strike - spot + net_premium) * shares
        max_loss = (spot - put_strike + net_premium) * shares
        breakeven = spot - net_premium

        return StrategyResult(
            strategy="COLLAR",
            max_profit=round(max_profit, 2),
            max_loss=round(-max_loss, 2),
            breakeven=[round(breakeven, 2)],
            risk_reward=round(abs(max_profit / max_loss), 2) if max_loss != 0 else 0,
            description="Protective Put + Covered Call → sınırlı risk, sınırlı ödül",
            legs=[
                {"action": "LONG", "instrument": "STOCK", "quantity": shares, "price": spot},
                {"action": "LONG", "instrument": "PUT", "strike": put_strike, "premium": put_premium},
                {"action": "SHORT", "instrument": "CALL", "strike": call_strike, "premium": call_premium},
            ],
        )

    def iron_condor(
        self,
        spot: float,
        put_sell_strike: float,
        put_buy_strike: float,
        call_sell_strike: float,
        call_buy_strike: float,
        put_sell_premium: float,
        put_buy_premium: float,
        call_sell_premium: float,
        call_buy_premium: float,
        contracts: int = 1,
    ) -> StrategyResult:
        """Iron Condor: düşük volatilite stratejisi.

        Kullanım: Dar aralıkta kalma beklentisi.
        """
        net_credit = (put_sell_premium - put_buy_premium + call_sell_premium - call_buy_premium) * contracts * 100
        max_loss = max(
            (put_sell_strike - put_buy_strike) * 100 * contracts - net_credit,
            (call_buy_strike - call_sell_strike) * 100 * contracts - net_credit,
        )

        return StrategyResult(
            strategy="IRON_CONDOR",
            max_profit=round(net_credit, 2),
            max_loss=round(-max_loss, 2),
            breakeven=[
                round(put_sell_strike - net_credit / (contracts * 100), 2),
                round(call_sell_strike + net_credit / (contracts * 100), 2),
            ],
            risk_reward=round(abs(net_credit / max_loss), 2) if max_loss != 0 else 0,
            description="Düşük volatilite → dar aralıkta kalma beklentisi",
            legs=[
                {"action": "LONG", "instrument": "PUT", "strike": put_buy_strike, "premium": put_buy_premium},
                {"action": "SHORT", "instrument": "PUT", "strike": put_sell_strike, "premium": put_sell_premium},
                {"action": "SHORT", "instrument": "CALL", "strike": call_sell_strike, "premium": call_sell_premium},
                {"action": "LONG", "instrument": "CALL", "strike": call_buy_strike, "premium": call_buy_premium},
            ],
        )

    def straddle(
        self,
        spot: float,
        strike: float,
        call_premium: float,
        put_premium: float,
        contracts: int = 1,
    ) -> StrategyResult:
        """Straddle: yüksek volatilite stratejisi.

        Kullanım: Büyük hareket beklentisi (yön belirsiz).
        """
        total_premium = (call_premium + put_premium) * contracts * 100
        breakeven_up = strike + call_premium + put_premium
        breakeven_down = strike - call_premium - put_premium

        return StrategyResult(
            strategy="STRADDLE",
            max_profit=999999,  # Unlimited
            max_loss=round(-total_premium, 2),
            breakeven=[round(breakeven_down, 2), round(breakeven_up, 2)],
            risk_reward=0,  # Unlimited
            description="Yüksek volatilite → büyük hareket beklentisi (yön belirsiz)",
            legs=[
                {"action": "LONG", "instrument": "CALL", "strike": strike, "premium": call_premium},
                {"action": "LONG", "instrument": "PUT", "strike": strike, "premium": put_premium},
            ],
        )

    def strangle(
        self,
        spot: float,
        put_strike: float,
        call_strike: float,
        put_premium: float,
        call_premium: float,
        contracts: int = 1,
    ) -> StrategyResult:
        """Strangle: straddle'dan daha ucuz.

        Kullanım: Çok büyük hareket beklentisi.
        """
        total_premium = (call_premium + put_premium) * contracts * 100
        breakeven_up = call_strike + call_premium + put_premium
        breakeven_down = put_strike - call_premium - put_premium

        return StrategyResult(
            strategy="STRANGLE",
            max_profit=999999,
            max_loss=round(-total_premium, 2),
            breakeven=[round(breakeven_down, 2), round(breakeven_up, 2)],
            risk_reward=0,
            description="Straddle'dan daha ucuz → çok büyük hareket beklentisi",
            legs=[
                {"action": "LONG", "instrument": "PUT", "strike": put_strike, "premium": put_premium},
                {"action": "LONG", "instrument": "CALL", "strike": call_strike, "premium": call_premium},
            ],
        )

    def bull_call_spread(
        self,
        buy_strike: float,
        sell_strike: float,
        buy_premium: float,
        sell_premium: float,
        contracts: int = 1,
    ) -> StrategyResult:
        """Bull Call Spread: yükseliş beklentisi.

        Kullanım: Orta düzey yükseliş beklentisi.
        """
        net_debit = (buy_premium - sell_premium) * contracts * 100
        max_profit = (sell_strike - buy_strike) * contracts * 100 - net_debit

        return StrategyResult(
            strategy="BULL_CALL_SPREAD",
            max_profit=round(max_profit, 2),
            max_loss=round(-net_debit, 2),
            breakeven=[round(buy_strike + net_debit / (contracts * 100), 2)],
            risk_reward=round(abs(max_profit / net_debit), 2) if net_debit != 0 else 0,
            description="Yükseliş beklentisi → sınırlı risk, sınırlı ödül",
            legs=[
                {"action": "LONG", "instrument": "CALL", "strike": buy_strike, "premium": buy_premium},
                {"action": "SHORT", "instrument": "CALL", "strike": sell_strike, "premium": sell_premium},
            ],
        )

    def bear_put_spread(
        self,
        buy_strike: float,
        sell_strike: float,
        buy_premium: float,
        sell_premium: float,
        contracts: int = 1,
    ) -> StrategyResult:
        """Bear Put Spread: düşüş beklentisi.

        Kullanım: Orta düzey düşüş beklentisi.
        """
        net_debit = (buy_premium - sell_premium) * contracts * 100
        max_profit = (buy_strike - sell_strike) * contracts * 100 - net_debit

        return StrategyResult(
            strategy="BEAR_PUT_SPREAD",
            max_profit=round(max_profit, 2),
            max_loss=round(-net_debit, 2),
            breakeven=[round(buy_strike - net_debit / (contracts * 100), 2)],
            risk_reward=round(abs(max_profit / net_debit), 2) if net_debit != 0 else 0,
            description="Düşüş beklentisi → sınırlı risk, sınırlı ödül",
            legs=[
                {"action": "LONG", "instrument": "PUT", "strike": buy_strike, "premium": buy_premium},
                {"action": "SHORT", "instrument": "PUT", "strike": sell_strike, "premium": sell_premium},
            ],
        )

    def butterfly(
        self,
        lower_strike: float,
        middle_strike: float,
        upper_strike: float,
        lower_premium: float,
        middle_premium: float,
        upper_premium: float,
        contracts: int = 1,
    ) -> StrategyResult:
        """Butterfly: dar aralık beklentisi.

        Kullanım: Fiyatın belirli bir seviyede kalma beklentisi.
        """
        net_debit = (lower_premium - 2 * middle_premium + upper_premium) * contracts * 100
        max_profit = (middle_strike - lower_strike) * contracts * 100 - net_debit

        return StrategyResult(
            strategy="BUTTERFLY",
            max_profit=round(max_profit, 2),
            max_loss=round(-net_debit, 2),
            breakeven=[
                round(lower_strike + net_debit / (contracts * 100), 2),
                round(upper_strike - net_debit / (contracts * 100), 2),
            ],
            risk_reward=round(abs(max_profit / net_debit), 2) if net_debit != 0 else 0,
            description="Dar aralık beklentisi → düşük risk, sınırlı ödül",
            legs=[
                {"action": "LONG", "instrument": "CALL", "strike": lower_strike, "premium": lower_premium},
                {"action": "SHORT", "instrument": "CALL", "strike": middle_strike, "premium": middle_premium, "quantity": 2},
                {"action": "LONG", "instrument": "CALL", "strike": upper_strike, "premium": upper_premium},
            ],
        )


# =====================================================
# Dynamic Delta Hedging
# =====================================================

@dataclass
class DeltaHedgeResult:
    """Delta hedge sonucu."""
    current_delta: float
    target_delta: float
    delta_gap: float
    contracts_needed: int
    hedge_instrument: str
    action: str
    estimated_cost: float


class DeltaHedger:
    """Dynamic delta hedging.

    Options pozisyonlarında delta riskini yönetir.
    """

    def hedge(
        self,
        portfolio_delta: float,
        spot_price: float,
        futures_price: float = 0,
        contract_multiplier: float = 100,
        hedge_instrument: str = "futures",
    ) -> DeltaHedgeResult:
        """Delta hedge pozisyonu öner.

        Args:
            portfolio_delta: Mevcut portföy delta
            spot_price: Dayanak fiyat
            futures_price: Futures fiyatı
            contract_multiplier: Sözleşme çarpanı
            hedge_instrument: Hedge aracı

        Returns:
            DeltaHedgeResult
        """
        target_delta = 0.0  # Delta neutral
        delta_gap = target_delta - portfolio_delta

        if hedge_instrument == "futures":
            # Futures delta = 1, delta_gap shares cinsinden
            # Pozitif delta → short futures (negatif contracts)
            contracts_needed = int(round(delta_gap / contract_multiplier))
        else:
            # ATM call delta ≈ 0.5
            contracts_needed = int(round(delta_gap / 0.5))

        action = "BUY" if contracts_needed > 0 else "SELL" if contracts_needed < 0 else "NONE"
        estimated_cost = abs(contracts_needed) * futures_price * contract_multiplier * 0.001  # %0.1 komisyon

        return DeltaHedgeResult(
            current_delta=round(portfolio_delta, 4),
            target_delta=target_delta,
            delta_gap=round(delta_gap, 4),
            contracts_needed=contracts_needed,
            hedge_instrument=hedge_instrument,
            action=action,
            estimated_cost=round(estimated_cost, 2),
        )

    def gamma_scalp(
        self,
        portfolio_gamma: float,
        spot_price: float,
        price_move: float,
        contract_multiplier: float = 100,
    ) -> Dict[str, Any]:
        """Gamma scalping — delta hedge'den kar.

        Args:
            portfolio_gamma: Portföy gamma
            spot_price: Dayanak fiyat
            price_move: Fiyat hareketi (%)
            contract_multiplier: Sözleşme çarpanı

        Returns:
            Gamma scalping sonucu
        """
        # Gamma P&L = 0.5 × Γ × (ΔS)²
        delta_s = spot_price * price_move / 100
        gamma_pnl = 0.5 * portfolio_gamma * (delta_s ** 2) * contract_multiplier

        return {
            "gamma_pnl": round(gamma_pnl, 2),
            "price_move_pct": price_move,
            "delta_s": round(delta_s, 2),
            "description": "Gamma scalping: fiyat hareketinden delta hedge P&L",
        }


# =====================================================
# SPAN Margin Calculator
# =====================================================

class SPANMarginCalculator:
    """SPAN teminat hesaplama (16 senaryo).

    BIST SPAN modeline uygun senaryo bazlı teminat hesabı.
    """

    # 16 SPAN senaryosu
    SCENARIOS = [
        {"price_change": 0, "vol_change": 0},       # Base
        {"price_change": 0.03, "vol_change": 0},     # +3%
        {"price_change": -0.03, "vol_change": 0},    # -3%
        {"price_change": 0.03, "vol_change": 0.02},  # +3% + vol up
        {"price_change": -0.03, "vol_change": 0.02}, # -3% + vol up
        {"price_change": 0.06, "vol_change": 0},     # +6%
        {"price_change": -0.06, "vol_change": 0},    # -6%
        {"price_change": 0.06, "vol_change": 0.04},  # +6% + vol up
        {"price_change": -0.06, "vol_change": 0.04}, # -6% + vol up
        {"price_change": 0.10, "vol_change": 0},     # +10%
        {"price_change": -0.10, "vol_change": 0},    # -10%
        {"price_change": 0.10, "vol_change": 0.06},  # +10% + vol up
        {"price_change": -0.10, "vol_change": 0.06}, # -10% + vol up
        {"price_change": 0.15, "vol_change": 0},     # +15%
        {"price_change": -0.15, "vol_change": 0},    # -15%
        {"price_change": 0, "vol_change": 0.08},     # Vol up only
    ]

    def calculate(self, positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """SPAN teminat hesapla.

        Args:
            positions: Pozisyon listesi [{"ticker", "value", "delta", "gamma", "vega"}]

        Returns:
            Teminat sonucu
        """
        total_margin = 0
        position_margins = []

        for pos in positions:
            worst_loss = 0
            scenario_pnls = []

            for scenario in self.SCENARIOS:
                pnl = self._calculate_scenario_pnl(pos, scenario)
                worst_loss = min(worst_loss, pnl)
                scenario_pnls.append(round(pnl, 2))

            margin = abs(worst_loss)
            total_margin += margin

            position_margins.append({
                "ticker": pos.get("ticker", ""),
                "margin": round(margin, 2),
                "worst_scenario_loss": round(worst_loss, 2),
                "scenario_pnls": scenario_pnls,
            })

        return {
            "total_margin": round(total_margin, 2),
            "position_margins": position_margins,
            "scenarios_tested": len(self.SCENARIOS),
        }

    def _calculate_scenario_pnl(self, position: Dict, scenario: Dict) -> float:
        """Senaryo P&L hesaplama."""
        value = position.get("value", 0)
        delta = position.get("delta", 1.0)
        gamma = position.get("gamma", 0)
        vega = position.get("vega", 0)

        price_pnl = value * delta * scenario["price_change"]
        gamma_pnl = 0.5 * gamma * (scenario["price_change"] ** 2) * value
        vol_pnl = vega * scenario["vol_change"] * 100

        return price_pnl + gamma_pnl + vol_pnl


# =====================================================
# Futures-Spot Arbitrage
# =====================================================

@dataclass
class ArbitrageResult:
    """Arbitrage sonucu."""
    spot_price: float
    futures_price: float
    theoretical_futures: float
    basis: float
    fair_basis: float
    basis_diff: float
    basis_pct: float
    arbitrage_opportunity: bool
    strategy: str
    estimated_profit: float


class FuturesSpotArbitrage:
    """Futures-spot arbitraj tespiti.

    Basis analizi ile arbitraj fırsatlarını bulur.
    """

    def analyze(
        self,
        spot_price: float,
        futures_price: float,
        risk_free_rate: float = 0.15,
        dividend_yield: float = 0.02,
        time_to_expiry: float = 0.25,
        contract_multiplier: float = 100,
    ) -> ArbitrageResult:
        """Futures-spot basis analizi.

        Args:
            spot_price: Spot fiyat
            futures_price: Futures fiyatı
            risk_free_rate: Risksiz faiz
            dividend_yield: Temettü verimi
            time_to_expiry: Vadeye kalan süre (yıl)
            contract_multiplier: Sözleşme çarpanı

        Returns:
            ArbitrageResult
        """
        # Teorik futures fiyatı
        theoretical = spot_price * np.exp((risk_free_rate - dividend_yield) * time_to_expiry)

        # Basis
        basis = futures_price - spot_price
        fair_basis = theoretical - spot_price
        basis_diff = basis - fair_basis
        basis_pct = basis_diff / spot_price * 100

        # Arbitraj sinyali
        threshold = 0.5  # %0.5
        arbitrage_opportunity = abs(basis_pct) > threshold

        if basis_diff > threshold / 100 * spot_price:
            strategy = "SELL_FUTURES_BUY_SPOT"
            estimated_profit = abs(basis_diff) * contract_multiplier
        elif basis_diff < -threshold / 100 * spot_price:
            strategy = "BUY_FUTURES_SELL_SPOT"
            estimated_profit = abs(basis_diff) * contract_multiplier
        else:
            strategy = "NO_ARBITRAGE"
            estimated_profit = 0

        return ArbitrageResult(
            spot_price=spot_price,
            futures_price=futures_price,
            theoretical_futures=round(theoretical, 2),
            basis=round(basis, 2),
            fair_basis=round(fair_basis, 2),
            basis_diff=round(basis_diff, 2),
            basis_pct=round(basis_pct, 4),
            arbitrage_opportunity=arbitrage_opportunity,
            strategy=strategy,
            estimated_profit=round(estimated_profit, 2),
        )


# =====================================================
# Singleton instances
# =====================================================

implied_volatility = ImpliedVolatility()
portfolio_greeks = PortfolioGreeks()
options_strategies = OptionsStrategies()
delta_hedger = DeltaHedger()
span_margin = SPANMarginCalculator()
futures_spot_arbitrage = FuturesSpotArbitrage()
