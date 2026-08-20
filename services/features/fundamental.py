"""
ALPHA BIST — Fundamental Feature Engine v1.0

Finansal verilerden feature üretir:
- Değerleme (P/E, P/B, EV/EBITDA, FCF Yield)
- Kârlılık (ROE, ROA, ROIC, margins)
- Büyüme (revenue growth, earnings growth, CAGR)
- Bilanço (debt/equity, current ratio, net debt/EBITDA)
- Kalite (earnings quality, cash conversion)
- Trend (margin trend, growth acceleration)

FAZ 2.2: Fundamental Features
"""

import math
from typing import Dict, List, Optional, Any
import structlog

logger = structlog.get_logger()


class FundamentalFeatureEngine:
    """Finansal verilerden feature üretir."""

    def compute_valuation_features(self, fundamentals: Dict[str, Any]) -> Dict[str, float]:
        """Değerleme çarpanları."""
        features = {}

        price = fundamentals.get("price", 0)
        if not price or price <= 0:
            return features

        # P/E
        pe = fundamentals.get("pe_ratio")
        if pe and pe > 0:
            features["pe_ratio"] = float(pe)
            features["earnings_yield"] = 1.0 / pe * 100  # %
        else:
            features["pe_ratio"] = 0.0
            features["earnings_yield"] = 0.0

        # Forward P/E
        fpe = fundamentals.get("forward_pe")
        if fpe and fpe > 0:
            features["forward_pe"] = float(fpe)
            features["forward_earnings_yield"] = 1.0 / fpe * 100

        # P/B
        pb = fundamentals.get("pb_ratio")
        if pb and pb > 0:
            features["pb_ratio"] = float(pb)
        else:
            features["pb_ratio"] = 0.0

        # EV/EBITDA
        ev_ebitda = fundamentals.get("ev_ebitda")
        if ev_ebitda and ev_ebitda > 0:
            features["ev_ebitda"] = float(ev_ebitda)
        else:
            features["ev_ebitda"] = 0.0

        # EV/Revenue
        ev_rev = fundamentals.get("ev_revenue")
        if ev_rev and ev_rev > 0:
            features["ev_revenue"] = float(ev_rev)

        # FCF Yield
        fcf_yield = fundamentals.get("fcf_yield")
        if fcf_yield is not None:
            features["fcf_yield"] = float(fcf_yield) * 100  # %

        # Dividend Yield
        div_yield = fundamentals.get("dividend_yield")
        if div_yield and div_yield > 0:
            features["dividend_yield"] = float(div_yield) * 100  # %
        else:
            features["dividend_yield"] = 0.0

        return features

    def compute_profitability_features(self, fundamentals: Dict[str, Any]) -> Dict[str, float]:
        """Kârlılık metrikleri."""
        features = {}

        for field, feature_name in [
            ("gross_margin", "gross_margin"),
            ("ebitda_margin", "ebitda_margin"),
            ("operating_margin", "operating_margin"),
            ("profit_margin", "profit_margin"),
            ("roe", "roe"),
            ("roa", "roa"),
        ]:
            val = fundamentals.get(field)
            if val is not None:
                val = float(val)
                # DÖNÜŞTÜRME YAPILMIYOR: Kaynak verinin formatı bilinmiyor.
                # Eski heuristic (abs(val)<1 → *100) tehlikeli: %0.5 marj
                # gibi küçük ama geçerli yüzde değerlerini %50'ye çeviriyordu.
                # Tüketici tarafında normalize edilmeli.
                features[feature_name] = round(val, 2)
            else:
                features[feature_name] = 0.0

        # ROIC (Return on Invested Capital) - approx
        total_equity = fundamentals.get("total_equity", 0) or 0
        total_debt = fundamentals.get("total_debt", 0) or 0
        net_income = fundamentals.get("net_income", 0) or 0

        invested_capital = total_equity + total_debt
        if invested_capital > 0 and net_income:
            features["roic"] = round(net_income / invested_capital * 100, 2)
        else:
            features["roic"] = 0.0

        return features

    def compute_growth_features(self, fundamentals: Dict[str, Any]) -> Dict[str, float]:
        """Büyüme metrikleri."""
        features = {}

        rev_growth = fundamentals.get("revenue_growth")
        if rev_growth is not None:
            val = float(rev_growth)
            # Dönüşüm yapılmıyor — kaynak format bilinmiyor
            features["revenue_growth_pct"] = round(val, 2)
        else:
            features["revenue_growth_pct"] = 0.0

        earn_growth = fundamentals.get("earnings_growth")
        if earn_growth is not None:
            val = float(earn_growth)
            # Dönüşüm yapılmıyor — kaynak format bilinmiyor
            features["earnings_growth_pct"] = round(val, 2)
        else:
            features["earnings_growth_pct"] = 0.0

        return features

    def compute_balance_sheet_features(self, fundamentals: Dict[str, Any]) -> Dict[str, float]:
        """Bilanço metrikleri."""
        features = {}

        # Debt/Equity
        de = fundamentals.get("debt_to_equity")
        if de is not None:
            features["debt_to_equity"] = float(de)
        else:
            features["debt_to_equity"] = 0.0

        # Current Ratio
        cr = fundamentals.get("current_ratio")
        if cr is not None:
            features["current_ratio"] = float(cr)
        else:
            features["current_ratio"] = 0.0

        # Net Debt / EBITDA
        total_debt = fundamentals.get("total_debt", 0) or 0
        total_cash = fundamentals.get("total_cash", 0) or 0
        ebitda = fundamentals.get("ebitda", 0) or 0

        net_debt = total_debt - total_cash
        features["net_debt"] = float(net_debt)

        if ebitda and ebitda > 0:
            features["net_debt_ebitda"] = round(net_debt / ebitda, 2)
        else:
            features["net_debt_ebitda"] = 0.0

        # Cash / Total Debt
        if total_debt and total_debt > 0:
            features["cash_debt_ratio"] = round(total_cash / total_debt, 2)
        else:
            features["cash_debt_ratio"] = 0.0

        return features

    def compute_cash_flow_features(self, fundamentals: Dict[str, Any]) -> Dict[str, float]:
        """Nakit akış metrikleri."""
        features = {}

        fcf = fundamentals.get("free_cash_flow", 0) or 0
        ocf = fundamentals.get("operating_cash_flow", 0) or 0
        revenue = fundamentals.get("revenue", 0) or 0
        net_income = fundamentals.get("net_income", 0) or 0
        market_cap = fundamentals.get("market_cap", 0) or 0

        features["free_cash_flow"] = float(fcf)
        features["operating_cash_flow"] = float(ocf)

        # FCF Margin
        if revenue and revenue > 0:
            features["fcf_margin"] = round(fcf / revenue * 100, 2)
        else:
            features["fcf_margin"] = 0.0

        # FCF Yield
        if market_cap and market_cap > 0:
            features["fcf_yield_pct"] = round(fcf / market_cap * 100, 2)
        else:
            features["fcf_yield_pct"] = 0.0

        # Cash Conversion (OCF / Net Income)
        if net_income and net_income > 0 and ocf:
            features["cash_conversion"] = round(ocf / net_income, 2)
        else:
            features["cash_conversion"] = 0.0

        return features

    def compute_quality_features(self, fundamentals: Dict[str, Any]) -> Dict[str, float]:
        """Büyüme kalitesi — sadece büyüme miktarı değil, birlikte değerlendirme."""
        features = {}

        rev_growth = fundamentals.get("revenue_growth", 0) or 0
        profit_margin = fundamentals.get("profit_margin", 0) or 0
        fcf = fundamentals.get("free_cash_flow", 0) or 0
        total_debt = fundamentals.get("total_debt", 0) or 0
        total_equity = fundamentals.get("total_equity", 0) or 0

        # NOT: Dönüşüm yapılmıyor — kaynak format bilinmiyor.
        # Eski heuristic (abs(val)<1 → *100) %0.5 marj gibi küçük
        # ama geçerli değerleri yanlış %50'ye çeviriyordu.

        # Growth quality score
        score = 0

        # Revenue growth positive
        if rev_growth > 5:
            score += 25
        elif rev_growth > 0:
            score += 10

        # Profit margin healthy
        if profit_margin > 10:
            score += 25
        elif profit_margin > 5:
            score += 15
        elif profit_margin > 0:
            score += 5

        # FCF positive
        if fcf and fcf > 0:
            score += 25

        # Debt manageable
        if total_equity and total_equity > 0:
            de_ratio = total_debt / total_equity if total_debt else 0
            if de_ratio < 0.5:
                score += 25
            elif de_ratio < 1.0:
                score += 15
            elif de_ratio < 2.0:
                score += 5

        features["growth_quality_score"] = float(score)

        # High growth + low margin + high debt = warning
        de_check = total_debt / total_equity if total_equity and total_equity > 0 and total_debt else 0
        if rev_growth > 20 and profit_margin < 5 and de_check > 1.5:
            features["growth_quality_warning"] = 1.0
        else:
            features["growth_quality_warning"] = 0.0

        return features

    def compute_all_fundamental_features(self, fundamentals: Dict[str, Any]) -> Dict[str, float]:
        """Tüm fundamental feature'ları hesapla."""
        features = {}
        features.update(self.compute_valuation_features(fundamentals))
        features.update(self.compute_profitability_features(fundamentals))
        features.update(self.compute_growth_features(fundamentals))
        features.update(self.compute_balance_sheet_features(fundamentals))
        features.update(self.compute_cash_flow_features(fundamentals))
        features.update(self.compute_quality_features(fundamentals))

        # NaN/Inf temizle
        cleaned = {}
        for k, v in features.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                cleaned[k] = 0.0
            else:
                cleaned[k] = v

        return cleaned

    def compute_trend_features(self, quarterly_data: List[Dict[str, Any]]) -> Dict[str, float]:
        """Çeyreklik verilerden trend feature'ları.

        Args:
            quarterly_data: [{"period": "2026-03-31", "total_revenue": ..., "net_income": ...}, ...]
        """
        features = {}

        if not quarterly_data or len(quarterly_data) < 2:
            return features

        # Revenue trend
        revenues = []
        for q in quarterly_data:
            rev = q.get("total_revenue")
            if rev:
                revenues.append(float(rev))

        if len(revenues) >= 2:
            # Son 2 dönem karşılaştırma
            if revenues[-2] != 0:
                growth = (revenues[-1] / revenues[-2] - 1) * 100
                features["quarterly_revenue_growth"] = round(growth, 2)

            # Acceleration (hızlanma/yavaşlama)
            if len(revenues) >= 3 and revenues[-2] != 0 and revenues[-3] != 0:
                growth_recent = (revenues[-1] / revenues[-2] - 1) * 100
                growth_prev = (revenues[-2] / revenues[-3] - 1) * 100
                features["revenue_acceleration"] = round(growth_recent - growth_prev, 2)

                if growth_recent > growth_prev:
                    features["revenue_trend"] = 1.0  # Accelerating
                elif growth_recent < growth_prev:
                    features["revenue_trend"] = -1.0  # Decelerating
                else:
                    features["revenue_trend"] = 0.0  # Stable

        # Net income trend
        incomes = []
        for q in quarterly_data:
            ni = q.get("net_income")
            if ni:
                incomes.append(float(ni))

        if len(incomes) >= 2 and incomes[-2] != 0:
            growth = (incomes[-1] / incomes[-2] - 1) * 100
            features["quarterly_earnings_growth"] = round(growth, 2)

        return features


# Singleton
fundamental_feature_engine = FundamentalFeatureEngine()
