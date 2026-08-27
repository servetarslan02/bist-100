"""
ALPHA BIST — Portfolio Enhancements v1.0

- Tax Model (stopaj, BSMV)
- Dividend Handling
- Corporate Action Adjustment
- Benchmark Comparison
- Performance Attribution
- Multi-Currency Support
"""

from datetime import datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


class TaxModel:
    """Vergi modeli — BIST Türkiye (detaylı).

    Holding period: Kısa vadeli (< 1 yıl) vs Uzun vadeli (>= 1 yıl)
    Stopaj: Temettü %15, Sermaye kazancı %0 (2026)
    BSMV: Komisyon üzerinden %5
    Wash sale: Aynı hisseyi 30 gün içinde tekrar alırsan zarar düşülmez
    """

    # Stopaj oranları (2026)
    STOCK_DIVIDEND_TAX = 0.15  # %15 temettü stopajı
    STOCK_CAPITAL_GAINS_TAX = 0.0  # Hisse sermaye kazancı (şu an 0)
    BSMV_RATE = 0.05  # BSMV (komisyon üzerinden)
    KKDF_RATE = 0.0  # KKDF (şu an 0)
    WASH_SALE_WINDOW_DAYS = 30  # Wash sale kuralı penceresi

    # Holding period eşikleri
    SHORT_TERM_DAYS = 365  # Kısa vadeli < 1 yıl

    def compute_dividend_tax(self, gross_dividend: float) -> dict[str, float]:
        """Temettü vergisi hesapla."""
        stopaj = gross_dividend * self.STOCK_DIVIDEND_TAX
        net = gross_dividend - stopaj
        return {
            "gross": round(gross_dividend, 2),
            "stopaj": round(stopaj, 2),
            "net": round(net, 2),
            "effective_rate": self.STOCK_DIVIDEND_TAX,
        }

    def compute_capital_gains_tax(
        self,
        realized_gain: float,
        holding_days: int = 0,
    ) -> dict[str, float]:
        """Sermaye kazancı vergisi hesapla.

        Args:
            realized_gain: Gerçekleşen kar/zarar
            holding_days: Tutma süresi (gün)
        """
        if realized_gain <= 0:
            return {
                "gain": round(realized_gain, 2),
                "tax": 0,
                "net": round(realized_gain, 2),
                "holding_period": "N/A",
                "tax_rate": 0,
            }

        # Holding period belirle
        is_short_term = holding_days < self.SHORT_TERM_DAYS
        holding_period = "SHORT_TERM" if is_short_term else "LONG_TERM"

        # Vergi oranı (şu an ikisi de 0 ama gelecekte değişebilir)
        tax_rate = self.STOCK_CAPITAL_GAINS_TAX
        tax = realized_gain * tax_rate

        return {
            "gain": round(realized_gain, 2),
            "tax": round(tax, 2),
            "net": round(realized_gain - tax, 2),
            "effective_rate": tax_rate,
            "holding_period": holding_period,
            "holding_days": holding_days,
            "tax_rate": tax_rate,
        }

    def compute_commission_tax(self, commission: float) -> dict[str, float]:
        """Komisyon üzerinden BSMV."""
        bsmv = commission * self.BSMV_RATE
        return {
            "commission": round(commission, 2),
            "bsmv": round(bsmv, 2),
            "total": round(commission + bsmv, 2),
        }

    def check_wash_sale(
        self,
        ticker: str,
        sell_date: datetime,
        buy_history: list[dict],
    ) -> bool:
        """Wash sale kontrolü — 30 gün içinde aynı hisseyi tekrar aldın mı?

        Args:
            ticker: Hisse kodu
            sell_date: Satış tarihi
            buy_history: Alış geçmişi [{"ticker", "date", "action"}]

        Returns:
            True: Wash sale kuralı ihlal edildi
        """
        for buy in buy_history:
            if buy.get("ticker") != ticker:
                continue
            if buy.get("action") != "BUY":
                continue
            buy_date = buy.get("date")
            if isinstance(buy_date, str):
                buy_date = datetime.fromisoformat(buy_date)
            if not isinstance(buy_date, datetime):
                continue

            days_diff = abs((buy_date - sell_date).days)
            if days_diff <= self.WASH_SALE_WINDOW_DAYS:
                return True

        return False

    def compute_total_tax(
        self,
        trades: list[dict],
        dividends: list[dict],
        commissions: float,
    ) -> dict[str, Any]:
        """Toplam vergi yükü hesapla.

        Args:
            trades: Tamamlanmış trades [{"realized_pnl", "holding_days"}]
            dividends: Temettüler [{"gross_dividend"}]
            commissions: Toplam komisyon

        Returns:
            Toplam vergi analizi
        """
        # Sermaye kazancı vergisi
        total_capital_tax = 0.0
        total_gain = 0.0
        total_loss = 0.0
        for t in trades:
            pnl = t.get("realized_pnl", 0)
            holding = t.get("holding_days", 0)
            if pnl > 0:
                tax_result = self.compute_capital_gains_tax(pnl, holding)
                total_capital_tax += tax_result["tax"]
                total_gain += pnl
            else:
                total_loss += abs(pnl)

        # Temettü vergisi
        total_dividend_tax = 0.0
        total_dividend_gross = 0.0
        for d in dividends:
            gross = d.get("gross_dividend", 0)
            tax_result = self.compute_dividend_tax(gross)
            total_dividend_tax += tax_result["stopaj"]
            total_dividend_gross += gross

        # BSMV
        bsmv = commissions * self.BSMV_RATE

        # Toplam
        total_tax = total_capital_tax + total_dividend_tax + bsmv
        total_income = total_gain + total_dividend_gross

        return {
            "capital_gains_tax": round(total_capital_tax, 2),
            "dividend_tax": round(total_dividend_tax, 2),
            "bsmv": round(bsmv, 2),
            "total_tax": round(total_tax, 2),
            "effective_tax_rate": round(total_tax / total_income * 100, 2) if total_income > 0 else 0,
            "total_gain": round(total_gain, 2),
            "total_loss": round(total_loss, 2),
            "net_after_tax": round(total_income - total_tax - total_loss, 2),
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
    ) -> dict[str, Any]:
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
        portfolio_returns: list[float],
        benchmark_returns: list[float],
        risk_free_rate: float = 0.15,  # %15 yıllık — TCMB faizinden güncellenmeli
    ) -> dict[str, float]:
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
        down_capture = (
            np.mean(p[down_mask]) / np.mean(b[down_mask]) if down_mask.any() and np.mean(b[down_mask]) != 0 else 1.0
        )

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
    """Performans ayrıştırması — Brinson + Factor."""

    def decompose(
        self,
        portfolio_weights: dict[str, float],
        portfolio_returns: dict[str, float],
        benchmark_weights: dict[str, float],
        benchmark_returns: dict[str, float],
    ) -> dict[str, Any]:
        """Toplam getiriyi bileşenlerine ayır (Brinson modeli)."""
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

    def factor_attribution(
        self,
        portfolio_returns: np.ndarray,
        factor_returns: dict[str, np.ndarray],
    ) -> dict[str, Any]:
        """Faktör bazlı performans attribüsyonu.

                Faktörler: value, momentum, quality, size, volatility
                Beta × faktör getirisi = faktör katkısı
                Residual = alpha (açıklanamayan kısım)

                Args:
                    portfolio_returns: Portföy getiri dizisi
        n            factor_returns: {"factor_name": getiri dizisi}

                Returns:
                    Faktör attribüsyonu
        """
        p = np.array(portfolio_returns)
        if len(p) < 10:
            return {"error": "Yetersiz veri"}

        results = {}
        annualized_p = float(np.mean(p) * 252)

        for factor_name, factor_ret in factor_returns.items():
            f = np.array(factor_ret)
            if len(f) != len(p) or len(f) < 5:
                continue

            # Beta hesapla
            if np.std(f) > 0 and np.std(p) > 0:
                cov_pf = np.cov(p, f)[0, 1]
                var_f = np.var(f)
                beta = cov_pf / var_f if var_f > 0 else 0
                correlation = float(np.corrcoef(p, f)[0, 1])
            else:
                beta = 0
                correlation = 0

            # Factor contribution (yıllık)
            factor_contribution = beta * float(np.mean(f)) * 252

            results[factor_name] = {
                "beta": round(float(beta), 4),
                "contribution": round(factor_contribution, 4),
                "contribution_pct": round(factor_contribution / abs(annualized_p) * 100, 2) if annualized_p != 0 else 0,
                "correlation": round(correlation, 4),
            }

        # Residual (alpha)
        explained = sum(r["contribution"] for r in results.values())
        residual = annualized_p - explained
        results["residual_alpha"] = {
            "contribution": round(residual, 4),
            "contribution_pct": round(residual / abs(annualized_p) * 100, 2) if annualized_p != 0 else 0,
        }

        results["total_return_annualized"] = round(annualized_p, 4)

        return results

    def sector_attribution(
        self,
        positions: list[dict],
        sector_returns: dict[str, float],
        total_value: float,
    ) -> dict[str, Any]:
        """Sektör bazlı attribüsyon.

        Args:
            positions: Pozisyonlar [{"ticker", "sector", "market_value"}]
            sector_returns: {"sector": getiri}
            total_value: Toplam portföy değeri

        Returns:
            Sektör attribüsyonu
        """
        sector_weights = {}
        for p in positions:
            sector = p.get("sector", "OTHER")
            value = p.get("market_value", 0)
            sector_weights[sector] = sector_weights.get(sector, 0) + value / total_value if total_value > 0 else 0

        sector_contributions = {}
        for sector, weight in sector_weights.items():
            ret = sector_returns.get(sector, 0)
            contribution = weight * ret
            sector_contributions[sector] = {
                "weight": round(weight, 4),
                "return": round(ret, 4),
                "contribution": round(contribution, 4),
                "contribution_pct": round(contribution * 100, 2),
            }

        total_contribution = sum(c["contribution"] for c in sector_contributions.values())

        return {
            "sectors": sector_contributions,
            "total_contribution": round(total_contribution, 4),
            "total_contribution_pct": round(total_contribution * 100, 2),
        }


class MultiCurrencyHandler:
    """Çoklu para birimi desteği."""

    def __init__(self):
        # Başlangıç kurları — update_rate() ile güncellenmeli
        # Gerçek değerler TCMB API veya config'den yüklenmeli
        self._rates: dict[str, float] = {"TRY": 1.0, "USD": 47.88, "EUR": 55.38}
        self._rates_stale = True  # Kurların güncel olup olmadığını takip et

    def update_rate(self, currency: str, rate_to_try: float):
        """Döviz kuru güncelle."""
        self._rates[currency] = rate_to_try
        self._rates_stale = False

    def convert(self, amount: float, from_currency: str, to_currency: str) -> float:
        """Para birimi çevir."""
        if from_currency == to_currency:
            return amount

        if self._rates_stale:
            logger.warning("FX rates are stale — using default rates. Call update_rate() or load from API.")

        from_rate = self._rates.get(from_currency, 1.0)
        to_rate = self._rates.get(to_currency, 1.0)

        # Önce TRY'ye çevir, sonra hedef para birimine
        try_amount = amount * from_rate
        return try_amount / to_rate

    def get_fx_impact(self, positions: list[dict], from_currency: str = "TRY") -> dict[str, float]:
        """FX etkisini hesapla."""
        total_try = sum(self.convert(p.get("value", 0), p.get("currency", "TRY"), "TRY") for p in positions)
        total_usd = self.convert(total_try, "TRY", "USD")

        return {
            "total_try": round(total_try, 2),
            "total_usd": round(total_usd, 2),
            "usdtry_rate": self._rates.get("USD", 0),
        }


class TransactionCostAnalyzer:
    """İşlem maliyeti analizi (TCA).

    Bileşenler:
    - Broker komisyonu
    - BIST payı
    - MKK payı
    - BSMV
    - Spread (bid/ask)
    - Slippage (volatilite bazlı)
    - Market impact (büyük emirler)
    """

    def analyze(
        self,
        order_value: float,
        daily_volume: float = 0,
        volatility: float = 0.02,
        spread_pct: float = 0.05,
    ) -> dict[str, Any]:
        """Detaylı işlem maliyeti analizi.

        Args:
            order_value: Emir değeri (TL)
            daily_volume: Günlük hacim (TL)
            volatility: Günlük volatilite
            spread_pct: Spread yüzdesi

        Returns:
            Maliyet detayları
        """
        # Komisyon (BIST modeli)
        broker = order_value * 0.0003
        exchange = order_value * 0.000056
        mkk = order_value * 0.0000109
        bsmv = (broker + exchange) * 0.05
        commission = max(broker + exchange + mkk + bsmv, 1.0)

        # Spread maliyeti
        spread_cost = order_value * spread_pct / 100

        # Slippage (volatilite bazlı)
        slippage_pct = volatility * 0.1  # Volatilite'nin %10'u
        slippage_cost = order_value * slippage_pct / 100

        # Market impact (square root model)
        impact_cost = 0.0
        if daily_volume > 0:
            participation = order_value / daily_volume
            impact_pct = 0.1 * participation**0.5
            impact_cost = order_value * impact_pct / 100

        total_cost = commission + spread_cost + slippage_cost + impact_cost

        return {
            "commission": round(commission, 2),
            "commission_breakdown": {
                "broker": round(broker, 2),
                "exchange": round(exchange, 2),
                "mkk": round(mkk, 2),
                "bsmv": round(bsmv, 2),
            },
            "spread_cost": round(spread_cost, 2),
            "slippage_cost": round(slippage_cost, 2),
            "market_impact": round(impact_cost, 2),
            "total_cost": round(total_cost, 2),
            "total_cost_pct": round(total_cost / order_value * 100, 4) if order_value > 0 else 0,
        }

    def estimate_slippage(
        self,
        quantity: int,
        price: float,
        daily_volume: int,
        volatility: float,
    ) -> dict[str, float]:
        """Slippage tahmini.

        Args:
            quantity: Emir adedi
            price: Fiyat
            daily_volume: Günlük hacim (adet)
            volatility: Volatilite

        Returns:
            Slippage tahmini
        """
        quantity * price
        participation = quantity / max(daily_volume, 1)

        # Volatilite bazlı slippage
        vol_slippage = volatility * price * 0.1

        # Hacim bazlı slippage (büyük emirler daha fazla)
        volume_slippage = price * 0.001 * (participation * 100) ** 0.5

        total_slippage = max(vol_slippage, volume_slippage)
        total_slippage_value = total_slippage * quantity

        return {
            "per_share": round(total_slippage, 4),
            "total": round(total_slippage_value, 2),
            "pct": round(total_slippage / price * 100, 4) if price > 0 else 0,
            "participation_pct": round(participation * 100, 4),
        }


# Singletons
tax_model = TaxModel()
dividend_handler = DividendHandler()
benchmark_engine = BenchmarkEngine()
performance_attribution = PerformanceAttribution()
multi_currency = MultiCurrencyHandler()
tca = TransactionCostAnalyzer()
