"""
ALPHA BIST — Portfolio Enhancements v1.0

- Tax Model (stopaj, BSMV)
- Dividend Handling
- Corporate Action Adjustment
- Benchmark Comparison
- Performance Attribution
- Multi-Currency Support
"""

import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


class TaxModel:
    """Vergi modeli — BIST Türkiye."""

    # Stopaj oranları (2026 tahmini)
    STOCK_DIVIDEND_TAX = 0.15      # %15 temettü stopajı (2025 itibariyle)
    STOCK_CAPITAL_GAINS_TAX = 0.0  # Hisse sermaye kazancı (şu an 0)
    BSMV_RATE = 0.05               # BSMV (komisyon üzerinden)
    KKDF_RATE = 0.0                # KKDF (şu an 0)

    def compute_dividend_tax(self, gross_dividend: float) -> Dict[str, float]:
        """Temettü vergisi hesapla."""
        stopaj = gross_dividend * self.STOCK_DIVIDEND_TAX
        net = gross_dividend - stopaj
        return {
            "gross": round(gross_dividend, 2),
            "stopaj": round(stopaj, 2),
            "net": round(net, 2),
            "effective_rate": self.STOCK_DIVIDEND_TAX,
        }

    def compute_capital_gains_tax(self, realized_gain: float) -> Dict[str, float]:
        """Sermaye kazancı vergisi hesapla."""
        if realized_gain <= 0:
            return {"gain": round(realized_gain, 2), "tax": 0, "net": round(realized_gain, 2)}

        tax = realized_gain * self.STOCK_CAPITAL_GAINS_TAX
        return {
            "gain": round(realized_gain, 2),
            "tax": round(tax, 2),
            "net": round(realized_gain - tax, 2),
            "effective_rate": self.STOCK_CAPITAL_GAINS_TAX,
        }

    def compute_commission_tax(self, commission: float) -> Dict[str, float]:
        """Komisyon üzerinden BSMV."""
        bsmv = commission * self.BSMV_RATE
        return {
            "commission": round(commission, 2),
            "bsmv": round(bsmv, 2),
            "total": round(commission + bsmv, 2),
        }


class DividendHandler:
    """Temettü işleme."""

    def process_dividend(
        self,
        ticker: str,
        quantity: int,
        dividend_per_share: float,
        ex_date: str,
        payment_date: str,
    ) -> Dict[str, Any]:
        """Temettü işle."""
        gross = quantity * dividend_per_share
        tax_model = TaxModel()
        tax_result = tax_model.compute_dividend_tax(gross)

        return {
            "ticker": ticker,
            "quantity": quantity,
            "dividend_per_share": dividend_per_share,
            "gross_dividend": tax_result["gross"],
            "tax": tax_result["stopaj"],
            "net_dividend": tax_result["net"],
            "ex_date": ex_date,
            "payment_date": payment_date,
            "yield_pct": round(dividend_per_share / 100 * 100, 2),  # Approximate
        }


class BenchmarkEngine:
    """Benchmark karşılaştırma."""

    def compare(
        self,
        portfolio_returns: List[float],
        benchmark_returns: List[float],
        risk_free_rate: float = 0.15,  # %15 yıllık (Türkiye)
    ) -> Dict[str, float]:
        """Portföy vs benchmark karşılaştır."""
        if len(portfolio_returns) != len(benchmark_returns) or len(portfolio_returns) < 2:
            return {}

        p = np.array(portfolio_returns)
        b = np.array(benchmark_returns)
        rf_daily = risk_free_rate / 252

        # Alpha (Jensen's Alpha)
        excess_p = p - rf_daily
        excess_b = b - rf_daily
        if np.std(excess_b) > 0:
            beta = np.cov(excess_p, excess_b)[0, 1] / np.var(excess_b)
            alpha = np.mean(excess_p) - beta * np.mean(excess_b)
        else:
            beta = 1.0
            alpha = 0.0

        # Tracking Error
        active_returns = p - b
        tracking_error = np.std(active_returns) * np.sqrt(252)

        # Information Ratio
        ir = (np.mean(active_returns) * 252) / tracking_error if tracking_error > 0 else 0

        # Up/Down Capture
        up_mask = b > 0
        down_mask = b < 0
        up_capture = np.mean(p[up_mask]) / np.mean(b[up_mask]) if up_mask.any() and np.mean(b[up_mask]) != 0 else 1.0
        down_capture = np.mean(p[down_mask]) / np.mean(b[down_mask]) if down_mask.any() and np.mean(b[down_mask]) != 0 else 1.0

        return {
            "alpha_annual": round(float(alpha * 252), 4),
            "beta": round(float(beta), 4),
            "tracking_error": round(float(tracking_error), 4),
            "information_ratio": round(float(ir), 4),
            "up_capture": round(float(up_capture), 4),
            "down_capture": round(float(down_capture), 4),
            "correlation": round(float(np.corrcoef(p, b)[0, 1]), 4) if np.std(p) > 0 and np.std(b) > 0 else 0,
        }


class PerformanceAttribution:
    """Performans ayrıştırması."""

    def decompose(
        self,
        portfolio_weights: Dict[str, float],
        portfolio_returns: Dict[str, float],
        benchmark_weights: Dict[str, float],
        benchmark_returns: Dict[str, float],
    ) -> Dict[str, Any]:
        """Toplam getiriyi bileşenlerine ayır."""
        # Allocation effect (ağırlık farkı × benchmark getiri)
        allocation = 0
        for ticker in set(list(portfolio_weights.keys()) + list(benchmark_weights.keys())):
            pw = portfolio_weights.get(ticker, 0)
            bw = benchmark_weights.get(ticker, 0)
            br = benchmark_returns.get(ticker, 0)
            allocation += (pw - bw) * br

        # Selection effect (getiri farkı × benchmark ağırlığı)
        selection = 0
        for ticker in set(list(portfolio_returns.keys()) + list(benchmark_returns.keys())):
            bw = benchmark_weights.get(ticker, 0)
            pr = portfolio_returns.get(ticker, 0)
            br = benchmark_returns.get(ticker, 0)
            selection += bw * (pr - br)

        # Interaction effect
        interaction = 0
        for ticker in set(list(portfolio_weights.keys()) + list(benchmark_weights.keys())):
            pw = portfolio_weights.get(ticker, 0)
            bw = benchmark_weights.get(ticker, 0)
            pr = portfolio_returns.get(ticker, 0)
            br = benchmark_returns.get(ticker, 0)
            interaction += (pw - bw) * (pr - br)

        total_active = allocation + selection + interaction

        return {
            "allocation_effect": round(allocation * 100, 4),
            "selection_effect": round(selection * 100, 4),
            "interaction_effect": round(interaction * 100, 4),
            "total_active_return": round(total_active * 100, 4),
        }


class MultiCurrencyHandler:
    """Çoklu para birimi desteği."""

    def __init__(self):
        self._rates: Dict[str, float] = {"TRY": 1.0, "USD": 47.88, "EUR": 55.38}

    def update_rate(self, currency: str, rate_to_try: float):
        """Döviz kuru güncelle."""
        self._rates[currency] = rate_to_try

    def convert(self, amount: float, from_currency: str, to_currency: str) -> float:
        """Para birimi çevir."""
        if from_currency == to_currency:
            return amount

        from_rate = self._rates.get(from_currency, 1.0)
        to_rate = self._rates.get(to_currency, 1.0)

        # Önce TRY'ye çevir, sonra hedef para birimine
        try_amount = amount * from_rate
        return try_amount / to_rate

    def get_fx_impact(self, positions: List[Dict], from_currency: str = "TRY") -> Dict[str, float]:
        """FX etkisini hesapla."""
        total_try = sum(self.convert(p.get("value", 0), p.get("currency", "TRY"), "TRY") for p in positions)
        total_usd = self.convert(total_try, "TRY", "USD")

        return {
            "total_try": round(total_try, 2),
            "total_usd": round(total_usd, 2),
            "usdtry_rate": self._rates.get("USD", 0),
        }


# Singletons
tax_model = TaxModel()
dividend_handler = DividendHandler()
benchmark_engine = BenchmarkEngine()
performance_attribution = PerformanceAttribution()
multi_currency = MultiCurrencyHandler()
