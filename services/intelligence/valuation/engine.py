"""
ALPHA BIST — Valuation Engine v1.0

Çoklu değerleme yöntemleri:
- Multiples (P/E, P/B, EV/EBITDA)
- Peer comparison (sektör medyan/ortalaması)
- DCF (Discounted Cash Flow)
- Bear/Base/Bull senaryoları

FAZ 4.2-4.5: Valuation Engine
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class MultiplesValuation:
    """Multiples değerleme sonucu."""
    ticker: str
    metric: str           # P/E, P/B, EV/EBITDA
    company_value: float  # Şirketin mevcut çarpanı
    sector_median: float  # Sektör medyanı
    sector_avg: float     # Sektör ortalaması
    historical_avg: float # Şirketin kendi tarihsel ortalaması
    implied_price: float  # Sektör medyanına göre ima edilen fiyat
    upside_pct: float     # Mevcut fiyata göre upside/downside


@dataclass
class DCFResult:
    """DCF değerleme sonucu."""
    ticker: str
    enterprise_value: float
    equity_value: float
    implied_price: float
    current_price: float
    upside_pct: float
    wacc: float
    terminal_growth: float
    pv_fcfs: List[float]     # Bugünkü değerler
    terminal_value: float
    sensitivity_table: Dict[str, Dict[str, float]]  # WACC × growth → price


@dataclass
class ValuationScenario:
    """Değerleme senaryosu."""
    name: str              # Bear, Base, Bull
    probability: float     # Olasılık
    assumptions: Dict[str, float]
    implied_price: float
    upside_pct: float


@dataclass
class ValuationSummary:
    """Değerleme özeti."""
    ticker: str
    current_price: float
    multiples: List[MultiplesValuation]
    dcf: Optional[DCFResult]
    scenarios: List[ValuationScenario]
    expected_value: float  # Olasılık ağırlıklı
    overall_upside_pct: float
    overall_view: str      # UNDERVALUED, FAIR, OVERVALUED


class ValuationEngine:
    """Değerleme motoru."""

    # F-021: Türkiye enflasyon/faiz gerçeğine uygun güncel varsayılanlar
    DEFAULT_WACC = 0.45        # %45 (yüksek enflasyon ortamı WACC)
    DEFAULT_TERMINAL_GROWTH = 0.15  # %15 (uzun vadeli enflasyon beklentisi)
    DEFAULT_TAX_RATE = 0.25    # %25 güncel kurumlar vergisi

    def __init__(
        self,
        wacc: Optional[float] = None,
        tax_rate: Optional[float] = None,
        terminal_growth: Optional[float] = None,
    ):
        """F-021: Sabitler constructor'dan override edilebilir."""
        self._wacc = wacc if wacc is not None else self.DEFAULT_WACC
        self._tax_rate = tax_rate if tax_rate is not None else self.DEFAULT_TAX_RATE
        self._terminal_growth = terminal_growth if terminal_growth is not None else self.DEFAULT_TERMINAL_GROWTH

    def compute_multiples_valuation(
        self,
        ticker: str,
        current_price: float,
        company_multiples: Dict[str, float],
        sector_multiples: Dict[str, Dict[str, float]],
        historical_multiples: Optional[Dict[str, float]] = None,
    ) -> List[MultiplesValuation]:
        """Multiples karşılaştırmalı değerleme.

        Args:
            ticker: Hisse kodu
            current_price: Mevcut fiyat
            company_multiples: {"pe": 8.5, "pb": 1.4, "ev_ebitda": 5.1}
            sector_multiples: {"pe": {"median": 11.0, "avg": 12.5}, ...}
            historical_multiples: {"pe_avg_5y": 10.0, ...}
        """
        results = []

        for metric, company_val in company_multiples.items():
            if not company_val or company_val <= 0:
                continue

            sector = sector_multiples.get(metric, {})
            sector_median = sector.get("median", 0)
            sector_avg = sector.get("avg", 0)
            hist_avg = (historical_multiples or {}).get(f"{metric}_avg_5y", 0)

            # Sektör medyanına göre ima edilen fiyat
            implied_price = 0
            if sector_median > 0 and company_val > 0:
                if metric in ("pe", "pb", "ev_ebitda"):
                    # Düşük çarpan = ucuz
                    implied_price = current_price * (sector_median / company_val)

            upside_pct = ((implied_price / current_price) - 1) * 100 if current_price > 0 and implied_price > 0 else 0

            results.append(MultiplesValuation(
                ticker=ticker,
                metric=metric.upper(),
                company_value=round(company_val, 2),
                sector_median=round(sector_median, 2),
                sector_avg=round(sector_avg, 2),
                historical_avg=round(hist_avg, 2),
                implied_price=round(implied_price, 2),
                upside_pct=round(upside_pct, 2),
            ))

        return results

    def compute_dcf(
        self,
        ticker: str,
        current_price: float,
        revenue_forecast: List[float],      # 5 yıllık gelir tahmini
        margin_forecast: List[float],        # 5 yıllık marj tahmini
        capex_forecast: List[float],         # 5 yıllık capex tahmini
        wc_change_forecast: List[float],     # 5 yıllık working capital değişimi
        shares_outstanding: int,
        total_debt: float = 0,
        total_cash: float = 0,
        wacc: float = 0.0,
        terminal_growth: float = 0.0,
        tax_rate: float = 0.0,
    ) -> DCFResult:
        """Basitleştirilmiş DCF.

        Args:
            revenue_forecast: [100M, 120M, 140M, 160M, 180M]
            margin_forecast: [0.10, 0.11, 0.12, 0.12, 0.13]
            capex_forecast: [5M, 6M, 7M, 8M, 9M]
            wc_change_forecast: [1M, 2M, 1M, 2M, 1M]
        """
        if not wacc:
            wacc = self._wacc
        if not terminal_growth:
            terminal_growth = self._terminal_growth
        if not tax_rate:
            tax_rate = self._tax_rate

        # Free Cash Flow projeksiyonları
        fcfs = []
        for i in range(min(len(revenue_forecast), len(margin_forecast))):
            ebit = revenue_forecast[i] * margin_forecast[i]
            nopat = ebit * (1 - tax_rate)
            capex = capex_forecast[i] if i < len(capex_forecast) else 0
            wc = wc_change_forecast[i] if i < len(wc_change_forecast) else 0
            fcf = nopat - capex - wc
            fcfs.append(max(0, fcf))

        # Bugünkü değerler
        pv_fcfs = []
        for i, fcf in enumerate(fcfs):
            pv = fcf / ((1 + wacc) ** (i + 1))
            pv_fcfs.append(round(pv, 2))

        # Terminal value (Gordon Growth Model)
        terminal_fcf = fcfs[-1] * (1 + terminal_growth) if fcfs else 0
        terminal_value = terminal_fcf / (wacc - terminal_growth) if wacc > terminal_growth else 0
        pv_terminal = terminal_value / ((1 + wacc) ** len(fcfs))

        # Enterprise value
        enterprise_value = sum(pv_fcfs) + pv_terminal

        # Equity value
        equity_value = enterprise_value + total_cash - total_debt

        # Hisse fiyatı
        implied_price = equity_value / shares_outstanding if shares_outstanding > 0 else 0
        upside_pct = ((implied_price / current_price) - 1) * 100 if current_price > 0 else 0

        # Sensitivity table (WACC × terminal growth)
        sensitivity = {}
        for w in [wacc - 0.03, wacc - 0.015, wacc, wacc + 0.015, wacc + 0.03]:
            sensitivity[f"{w:.1%}"] = {}
            for g in [terminal_growth - 0.01, terminal_growth, terminal_growth + 0.01]:
                if w > g:
                    tv = terminal_fcf / (w - g)
                    pv_tv = tv / ((1 + w) ** len(fcfs))
                    ev = sum(fcf / ((1 + w) ** (i + 1)) for i, fcf in enumerate(fcfs)) + pv_tv
                    eq = ev + total_cash - total_debt
                    price = eq / shares_outstanding if shares_outstanding > 0 else 0
                    sensitivity[f"{w:.1%}"][f"{g:.1%}"] = round(price, 2)
                else:
                    sensitivity[f"{w:.1%}"][f"{g:.1%}"] = 0

        return DCFResult(
            ticker=ticker,
            enterprise_value=round(enterprise_value, 2),
            equity_value=round(equity_value, 2),
            implied_price=round(implied_price, 2),
            current_price=current_price,
            upside_pct=round(upside_pct, 2),
            wacc=wacc,
            terminal_growth=terminal_growth,
            pv_fcfs=pv_fcfs,
            terminal_value=round(pv_terminal, 2),
            sensitivity_table=sensitivity,
        )

    def compute_valuation_scenarios(
        self,
        ticker: str,
        current_price: float,
        base_assumptions: Dict[str, float],
        bear_adjustments: Dict[str, float],
        bull_adjustments: Dict[str, float],
        shares_outstanding: int,
        total_debt: float = 0,
        total_cash: float = 0,
    ) -> List[ValuationScenario]:
        """Bear/Base/Bull senaryoları.

        Args:
            base_assumptions: {"revenue_growth": 0.10, "margin": 0.12, "wacc": 0.20, "terminal_growth": 0.03}
            bear_adjustments: {"revenue_growth": -0.05, "margin": -0.03, "wacc": 0.03}
            bull_adjustments: {"revenue_growth": 0.05, "margin": 0.03, "wacc": -0.02}
        """
        scenarios = []

        for name, adjustments, probability in [
            ("BEAR", bear_adjustments, 0.25),
            ("BASE", base_assumptions, 0.50),
            ("BULL", bull_adjustments, 0.25),
        ]:
            assumptions = dict(base_assumptions)
            if name != "BASE":
                for k, v in adjustments.items():
                    if k in assumptions:
                        assumptions[k] = assumptions[k] + v
                    else:
                        assumptions[k] = v

            # Basitleştirilmiş değerleme
            rev_growth = assumptions.get("revenue_growth", 0.10)
            margin = assumptions.get("margin", 0.10)
            wacc = assumptions.get("wacc", 0.20)
            tg = assumptions.get("terminal_growth", 0.03)

            # 5 yıllık FCF tahmini (basitleştirilmiş)
            base_revenue = assumptions.get("base_revenue", 100_000_000)
            fcfs = []
            rev = base_revenue
            for _ in range(5):
                rev *= (1 + rev_growth)
                ebit = rev * margin
                nopat = ebit * 0.77  # %23 vergi
                fcf = nopat * 0.7   # %30 capex+WC
                fcfs.append(fcf)

            # Terminal value
            if wacc > tg and fcfs:
                terminal_fcf = fcfs[-1] * (1 + tg)
                tv = terminal_fcf / (wacc - tg)
                pv_tv = tv / ((1 + wacc) ** 5)
            else:
                pv_tv = 0

            pv_fcfs = sum(fcf / ((1 + wacc) ** (i + 1)) for i, fcf in enumerate(fcfs))
            ev = pv_fcfs + pv_tv
            equity = ev + total_cash - total_debt
            implied_price = equity / shares_outstanding if shares_outstanding > 0 else 0
            upside = ((implied_price / current_price) - 1) * 100 if current_price > 0 else 0

            scenarios.append(ValuationScenario(
                name=name,
                probability=probability,
                assumptions=assumptions,
                implied_price=round(implied_price, 2),
                upside_pct=round(upside, 2),
            ))

        return scenarios

    def compute_expected_value(self, scenarios: List[ValuationScenario]) -> float:
        """Olasılık ağırlıklı beklenen değer."""
        if not scenarios:
            return 0.0
        return sum(s.implied_price * s.probability for s in scenarios)

    def compute_valuation_summary(
        self,
        ticker: str,
        current_price: float,
        multiples: List[MultiplesValuation],
        dcf: Optional[DCFResult],
        scenarios: List[ValuationScenario],
    ) -> ValuationSummary:
        """Değerleme özeti oluştur."""
        expected_value = self.compute_expected_value(scenarios) if scenarios else 0

        # Multiples'ten ortalama upside
        if multiples:
            avg_multiples_upside = sum(m.upside_pct for m in multiples) / len(multiples)
        else:
            avg_multiples_upside = 0

        # DCF upside
        dcf_upside = dcf.upside_pct if dcf else 0

        # Genel view
        all_upsides = [avg_multiples_upside]
        if dcf:
            all_upsides.append(dcf_upside)
        if scenarios:
            expected_upside = ((expected_value / current_price) - 1) * 100 if current_price > 0 else 0
            all_upsides.append(expected_upside)

        avg_upside = sum(all_upsides) / len(all_upsides) if all_upsides else 0

        if avg_upside > 15:
            overall_view = "UNDERVALUED"
        elif avg_upside < -15:
            overall_view = "OVERVALUED"
        else:
            overall_view = "FAIR"

        return ValuationSummary(
            ticker=ticker,
            current_price=current_price,
            multiples=multiples,
            dcf=dcf,
            scenarios=scenarios,
            expected_value=round(expected_value, 2),
            overall_upside_pct=round(avg_upside, 2),
            overall_view=overall_view,
        )


# Singleton
valuation_engine = ValuationEngine()
