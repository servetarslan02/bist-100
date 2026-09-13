"""
ALPHA BIST — VIOP Greeks & Risk Sensitivity Engine (Institutional Grade)

Delta, Gamma, Theta, Vega, Rho, Vanna, Volga ve yüksek dereceli duyarlılık hesaplayıcıları.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from .enhanced_options import _norm_cdf, _norm_pdf, calculate_greeks


@dataclass
class GreeksResult:
    """Detaylı birinci ve ikinci derece opsiyon Greeks sonuç modeli."""

    delta: float  # dV/dS (fiyat hassasiyeti)
    gamma: float  # d2V/dS2 (delta hassasiyeti)
    theta: float  # dV/dt (günlük zaman erimesi)
    vega: float   # dV/dsigma (%1 volatilite değişimi)
    rho: float    # dV/dr (%1 faiz değişimi)
    vanna: float  # d(delta)/dsigma veya d(vega)/dS
    volga: float  # d(vega)/dsigma (vomma)

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return (
            f"GreeksResult(delta={self.delta:.4f}, gamma={self.gamma:.6f}, "
            f"theta={self.theta:.4f}, vega={self.vega:.4f}, rho={self.rho:.4f})"
        )

    def to_dict(self) -> dict[str, float]:
        """Greeks değerlerini sözlük olarak döndürür."""
        return {
            "delta": round(self.delta, 4),
            "gamma": round(self.gamma, 6),
            "theta": round(self.theta, 4),
            "vega": round(self.vega, 4),
            "rho": round(self.rho, 4),
            "vanna": round(self.vanna, 6),
            "volga": round(self.volga, 6),
        }


class GreeksEngine:
    """Kurumsal opsiyon Greeks ve portföy duyarlılık analiz motoru."""

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return "GreeksEngine(orders=['1st_order', '2nd_order'])"

    def compute(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        option_type: Literal["call", "put"] = "call",
    ) -> GreeksResult:
        """Tüm analitik Greeks metriklerini hesaplar.

        Args:
            S: Spot fiyat.
            K: Kullanım fiyatı.
            T: Vade (yıl).
            r: Risksiz faiz oranı.
            sigma: Yıllık volatilite.
            option_type: "call" veya "put".

        Returns:
            GreeksResult analitik modeli.
        """
        if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
            delta = (1.0 if S > K else 0.0) if option_type == "call" else -1.0 if S < K else 0.0
            return GreeksResult(delta=delta, gamma=0.0, theta=0.0, vega=0.0, rho=0.0, vanna=0.0, volga=0.0)

        sqrt_t = math.sqrt(T)
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt_t)
        d2 = d1 - sigma * sqrt_t

        pdf_d1 = _norm_pdf(d1)
        cdf_d1 = _norm_cdf(d1)
        cdf_d2 = _norm_cdf(d2)
        cdf_neg_d2 = _norm_cdf(-d2)

        exp_rt = math.exp(-r * T)

        # 1. Derece Greeks
        if option_type == "call":
            delta = cdf_d1
            theta = (-S * pdf_d1 * sigma / (2.0 * sqrt_t) - r * K * exp_rt * cdf_d2) / 365.0
            rho = (K * T * exp_rt * cdf_d2) / 100.0
        else:
            delta = cdf_d1 - 1.0
            theta = (-S * pdf_d1 * sigma / (2.0 * sqrt_t) + r * K * exp_rt * cdf_neg_d2) / 365.0
            rho = (-K * T * exp_rt * cdf_neg_d2) / 100.0

        gamma = pdf_d1 / (S * sigma * sqrt_t)
        vega = (S * sqrt_t * pdf_d1) / 100.0

        # 2. Derece Yüksek Düzey Greeks (Vanna & Volga)
        vanna = (-pdf_d1 * d2 / sigma) / 100.0
        volga = (vega * d1 * d2 / sigma)

        return GreeksResult(
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            rho=rho,
            vanna=vanna,
            volga=volga,
        )

    def portfolio_greeks(self, positions: list[dict[str, Any]]) -> dict[str, float]:
        """Birden çok opsiyon pozisyonunun kümülatif portföy Greeks değerlerini toplar."""
        total_delta = 0.0
        total_gamma = 0.0
        total_theta = 0.0
        total_vega = 0.0
        total_rho = 0.0

        for pos in positions:
            g = self.compute(
                S=pos["spot"],
                K=pos["strike"],
                T=pos["expiry_years"],
                r=pos.get("rate", 0.45),
                sigma=pos["volatility"],
                option_type=pos.get("type", "call"),
            )
            qty = pos.get("quantity", 1)
            mult = pos.get("multiplier", 100)
            total_delta += g.delta * qty * mult
            total_gamma += g.gamma * qty * mult
            total_theta += g.theta * qty * mult
            total_vega += g.vega * qty * mult
            total_rho += g.rho * qty * mult

        return {
            "net_delta": round(total_delta, 2),
            "net_gamma": round(total_gamma, 4),
            "net_theta": round(total_theta, 2),
            "net_vega": round(total_vega, 2),
            "net_rho": round(total_rho, 2),
        }


greeks_engine = GreeksEngine()

__all__ = [
    "calculate_greeks",
    "GreeksEngine",
    "GreeksResult",
    "greeks_engine",
]
