"""
ALPHA BIST — VIOP Dynamic Portfolio Hedging & Risk Shield Engine (Institutional Grade)

Portföy beta koruması, Delta-nötr dengeleme, Gamma scalping ve Tail-risk (Kuyruk Riski) VIOP hedge optimizasyonu.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .enhanced_options import DeltaHedger, DeltaHedgeResult, delta_hedger


@dataclass
class TailRiskHedgePlan:
    """Kuyruk riski ve ani piyasa çöküşlerine karşı OTM Put hedge planı."""

    portfolio_value: float
    otm_strike: float
    contracts_needed: int
    total_cost_tl: float
    cost_percentage: float
    downside_protection_coverage: float
    expiry_days: int

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return (
            f"TailRiskHedgePlan(contracts={self.contracts_needed}, "
            f"cost={self.total_cost_tl:.2f}TL, cost_pct=%{self.cost_percentage:.2f})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Hedge planını sözlük olarak döndürür."""
        return {
            "portfolio_value": round(self.portfolio_value, 2),
            "otm_strike": round(self.otm_strike, 2),
            "contracts_needed": self.contracts_needed,
            "total_cost_tl": round(self.total_cost_tl, 2),
            "cost_percentage": round(self.cost_percentage, 2),
            "downside_protection_coverage": round(self.downside_protection_coverage, 2),
            "expiry_days": self.expiry_days,
        }


def hedge_portfolio(
    portfolio_value: float,
    beta: float,
    futures_price: float,
    target_beta: float = 0.0,
    contract_multiplier: int = 10,
) -> dict[str, Any]:
    """Portföy için BIST-30 endeks vadeli sözleşmesi ile dinamik hedge önerisi hesaplar.

    Args:
        portfolio_value: Portföy toplam büyüklüğü (TL).
        beta: Portföyün endekse göre ağırlıklı betası.
        futures_price: BIST-30 yakın vade vadeli işlem fiyatı (TL).
        target_beta: Hedeflenen net beta (varsayılan 0 = tam beta-nötr).
        contract_multiplier: VIOP sözleşme büyüklüğü çarpanı.

    Returns:
        Sözleşme adedi, işlem yönü, koruma tutarı ve marj maliyet analizi.
    """
    if futures_price <= 0:
        return {
            "contracts_needed": 0,
            "action": "HOLD",
            "hedge_value": 0.0,
            "estimated_cost": 0.0,
            "current_delta": 0.0,
            "target_delta": 0.0,
            "delta_gap": 0.0,
        }

    # BIST Endeks sözleşme nominal değeri = Fiyat * Çarpan (ör. 11.500 * 10 = 115.000 TL)
    contract_nominal_value = futures_price * contract_multiplier
    beta_gap = beta - target_beta

    # Hedge edilecek toplam nominal tutar = Portföy Değeri * (Beta - Hedef Beta)
    total_hedge_amount = portfolio_value * beta_gap
    exact_contracts = total_hedge_amount / contract_nominal_value if contract_nominal_value > 0 else 0
    contracts_needed = round(exact_contracts)

    action = "SELL_FUTURES" if contracts_needed > 0 else "BUY_FUTURES" if contracts_needed < 0 else "HOLD"
    abs_contracts = abs(contracts_needed)
    actual_hedge_value = abs_contracts * contract_nominal_value

    # VIOP yaklaşık başlangıç teminatı (%12-15 civarı)
    estimated_initial_margin = actual_hedge_value * 0.12

    return {
        "contracts_needed": abs_contracts,
        "action": action,
        "hedge_value": round(actual_hedge_value, 2),
        "estimated_cost": round(estimated_initial_margin, 2),
        "current_delta": round(portfolio_value * beta, 2),
        "target_delta": round(portfolio_value * target_beta, 2),
        "delta_gap": round(total_hedge_amount, 2),
        "net_expected_beta": round(target_beta, 2),
    }


def calculate_tail_risk_hedge(
    portfolio_value: float,
    spot_index: float,
    put_strike_drop_pct: float = 0.10,
    put_premium_pct: float = 0.015,
    coverage_ratio: float = 1.0,
    expiry_days: int = 30,
    contract_multiplier: int = 10,
) -> TailRiskHedgePlan:
    """Olası kara kuğu (%10+ düşüş) senaryolarına karşı OTM Put opsiyon koruması tasarlar."""
    otm_strike = spot_index * (1.0 - put_strike_drop_pct)
    contract_coverage = spot_index * contract_multiplier

    target_coverage_amount = portfolio_value * coverage_ratio
    contracts = math.ceil(target_coverage_amount / contract_coverage) if contract_coverage > 0 else 0

    unit_premium = spot_index * put_premium_pct
    total_premium_tl = contracts * unit_premium * contract_multiplier
    cost_pct = (total_premium_tl / portfolio_value * 100.0) if portfolio_value > 0 else 0.0

    return TailRiskHedgePlan(
        portfolio_value=portfolio_value,
        otm_strike=otm_strike,
        contracts_needed=contracts,
        total_cost_tl=total_premium_tl,
        cost_percentage=cost_pct,
        downside_protection_coverage=coverage_ratio * 100.0,
        expiry_days=expiry_days,
    )


__all__ = [
    "hedge_portfolio",
    "calculate_tail_risk_hedge",
    "TailRiskHedgePlan",
    "delta_hedger",
    "DeltaHedger",
    "DeltaHedgeResult",
]
