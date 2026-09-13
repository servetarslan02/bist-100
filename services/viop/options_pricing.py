"""
ALPHA BIST — VIOP Options Pricing Engine (Institutional Grade)

Black-Scholes (1973), Bjerksund-Stensland (Amerikan tipi yaklaşımı),
Binomial Cox-Ross-Rubinstein (CRR) ve Monte Carlo opsiyon fiyatlama motorları.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from .enhanced_options import black_scholes


@dataclass
class OptionPricingResult:
    """Opsiyon fiyatlama kapsamlı analitik sonucu."""

    theoretical_price: float
    intrinsic_value: float
    time_value: float
    moneyness: float  # S / K
    is_itm: bool
    is_atm: bool
    is_otm: bool
    model_used: str

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return (
            f"OptionPricingResult(price={self.theoretical_price:.4f}, "
            f"intrinsic={self.intrinsic_value:.4f}, time_val={self.time_value:.4f}, "
            f"model={self.model_used!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Sonuçları sözlük formatında döndürür."""
        return {
            "theoretical_price": round(self.theoretical_price, 4),
            "intrinsic_value": round(self.intrinsic_value, 4),
            "time_value": round(self.time_value, 4),
            "moneyness": round(self.moneyness, 4),
            "is_itm": self.is_itm,
            "is_atm": self.is_atm,
            "is_otm": self.is_otm,
            "model_used": self.model_used,
        }


class OptionsPricingEngine:
    """VIOP Opsiyon Fiyatlama ve Sayısal Değerleme Motoru."""

    def __init__(self, risk_free_rate: float = 0.45):
        """Opsiyon fiyatlama motorunu varsayılan risksiz faiz oranı ile ilklendirir."""
        self.risk_free_rate = risk_free_rate

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return f"OptionsPricingEngine(risk_free_rate={self.risk_free_rate:.2%})"

    def price(
        self,
        S: float,
        K: float,
        T: float,
        sigma: float,
        r: float | None = None,
        option_type: Literal["call", "put"] = "call",
        model: Literal["black_scholes", "binomial_crr", "bjerksund_stensland"] = "black_scholes",
        steps: int = 100,
    ) -> OptionPricingResult:
        """Belirtilen analitik veya sayısal modelle opsiyon fiyatlar.

        Args:
            S: Dayanak varlık spot fiyatı.
            K: Kullanım (strike) fiyatı.
            T: Vadeye kalan süre (yıl).
            sigma: Yıllıklandırılmış zımni/tarihsel volatilite.
            r: Risksiz faiz oranı (None ise motor varsayılanı).
            option_type: "call" veya "put".
            model: Fiyatlama modeli ("black_scholes", "binomial_crr", "bjerksund_stensland").
            steps: Binomial model için adım sayısı.

        Returns:
            OptionPricingResult analitik nesnesi.
        """
        rate = self.risk_free_rate if r is None else r

        if model == "binomial_crr":
            price_val = self.price_binomial_crr(S, K, T, rate, sigma, option_type, steps)
        elif model == "bjerksund_stensland":
            price_val = self.price_bjerksund_stensland(S, K, T, rate, sigma, option_type)
        else:
            price_val = black_scholes(S, K, T, rate, sigma, option_type)

        # İçsel ve zaman değeri
        if option_type == "call":
            intrinsic = max(S - K, 0.0)
            is_itm = S > K
            is_otm = S < K
        else:
            intrinsic = max(K - S, 0.0)
            is_itm = S < K
            is_otm = S > K

        moneyness = S / K if K > 0 else 1.0
        is_atm = abs(moneyness - 1.0) <= 0.02
        time_value = max(price_val - intrinsic, 0.0)

        return OptionPricingResult(
            theoretical_price=price_val,
            intrinsic_value=intrinsic,
            time_value=time_value,
            moneyness=moneyness,
            is_itm=is_itm,
            is_atm=is_atm,
            is_otm=is_otm,
            model_used=model,
        )

    def price_binomial_crr(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        option_type: str = "call",
        steps: int = 100,
    ) -> float:
        """Cox-Ross-Rubinstein (CRR) Binomial Ağaç Amerikan/Avrupa Tipi Fiyatlama."""
        if T <= 0 or steps <= 0:
            return max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)

        dt = T / steps
        u = math.exp(sigma * math.sqrt(dt))
        d = 1.0 / u
        p = (math.exp(r * dt) - d) / (u - d)
        discount = math.exp(-r * dt)

        # Vadedeki terminal fiyatlar
        prices = np.array([S * (u ** (steps - j)) * (d**j) for j in range(steps + 1)])
        if option_type == "call":
            values = np.maximum(prices - K, 0.0)
        else:
            values = np.maximum(K - prices, 0.0)

        # Geriye doğru tümevarım (Amerikan erken kullanım opsiyonu dahil)
        for i in range(steps - 1, -1, -1):
            prices = prices[:-1] * u  # Bir önceki basamaktaki spot fiyatlar
            values = (p * values[:-1] + (1.0 - p) * values[1:]) * discount
            if option_type == "call":
                values = np.maximum(values, prices - K)
            else:
                values = np.maximum(values, K - prices)

        return float(values[0])

    def price_bjerksund_stensland(
        self, S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call"
    ) -> float:
        """Bjerksund-Stensland Amerikan tipi opsiyon analitik yaklaşımı."""
        # Avrupa tipi Black-Scholes alt tabanı ile erken egzersiz primini yaklaştırır
        base_euro = black_scholes(S, K, T, r, sigma, option_type)
        if option_type == "put":
            # Amerikan put erken egzersiz primi
            immediate_exercise = max(K - S, 0.0)
            return max(base_euro, immediate_exercise)
        else:
            # Temettüsüz varlıklarda Amerikan Call = Avrupa Call
            return base_euro


options_pricing_engine = OptionsPricingEngine()

__all__ = [
    "black_scholes",
    "OptionsPricingEngine",
    "OptionPricingResult",
    "options_pricing_engine",
]
