"""
ALPHA BIST — Factor Engine v1.0

Faktör bazlı analiz:
- Value (P/E, P/B, FCF Yield)
- Momentum (ROC, relative strength)
- Quality (ROE, margins, cash flow)
- Size (market cap)
- Low Volatility
- Factor Exposure

FAZ 10.8: Factor Engine
"""

from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class FactorScore:
    """Faktör skoru."""
    ticker: str
    value_score: float = 0.0       # 0-100
    momentum_score: float = 0.0    # 0-100
    quality_score: float = 0.0     # 0-100
    size_score: float = 0.0        # 0-100
    low_vol_score: float = 0.0     # 0-100
    composite_score: float = 0.0   # Ağırlıklı toplam


@dataclass
class FactorExposure:
    """Portföy faktör maruziyeti."""
    value_exposure: float = 0.0    # -1 (short) ile +1 (long) arası
    momentum_exposure: float = 0.0
    quality_exposure: float = 0.0
    size_exposure: float = 0.0
    low_vol_exposure: float = 0.0
    concentration_risk: float = 0.0


class FactorEngine:
    """Faktör motoru."""

    # Faktör ağırlıkları
    DEFAULT_WEIGHTS = {
        "value": 0.20,
        "momentum": 0.25,
        "quality": 0.25,
        "size": 0.10,
        "low_vol": 0.20,
    }

    def compute_factor_scores(
        self,
        ticker: str,
        fundamentals: dict[str, float],
        technicals: dict[str, float],
    ) -> FactorScore:
        """Tek hisse için faktör skorları hesapla."""
        score = FactorScore(ticker=ticker)

        # Value factor
        score.value_score = self._compute_value(fundamentals)

        # Momentum factor
        score.momentum_score = self._compute_momentum(technicals)

        # Quality factor
        score.quality_score = self._compute_quality(fundamentals)

        # Size factor
        score.size_score = self._compute_size(fundamentals)

        # Low Volatility factor
        score.low_vol_score = self._compute_low_vol(technicals)

        # Composite
        weights = self.DEFAULT_WEIGHTS
        score.composite_score = (
            score.value_score * weights["value"]
            + score.momentum_score * weights["momentum"]
            + score.quality_score * weights["quality"]
            + score.size_score * weights["size"]
            + score.low_vol_score * weights["low_vol"]
        )

        return score

    def _compute_value(self, f: dict) -> float:
        """Value factor (düşük çarpan = yüksek skor). Sektör/Piyasa medyanına rölatif çalışır."""
        score = 50.0

        pe = f.get("pe_ratio", 0)
        pe_median = f.get("sector_pe_median", f.get("market_pe_median", 15.0))
        if pe and pe > 0 and pe_median > 0:
            pe_relative = pe / pe_median
            if pe_relative < 0.6:
                score += 25
            elif pe_relative < 0.8:
                score += 15
            elif pe_relative < 1.2:
                score += 5
            elif pe_relative > 1.5:
                score -= 15

        pb = f.get("pb_ratio", 0)
        pb_median = f.get("sector_pb_median", f.get("market_pb_median", 2.0))
        if pb and pb > 0 and pb_median > 0:
            pb_relative = pb / pb_median
            if pb_relative < 0.6:
                score += 20
            elif pb_relative < 0.9:
                score += 10
            elif pb_relative > 1.5:
                score -= 10

        fcf_yield = f.get("fcf_yield", 0) or f.get("fcf_yield_pct", 0)
        if fcf_yield and fcf_yield > 0:
            if fcf_yield > 8:
                score += 20
            elif fcf_yield > 5:
                score += 10
            elif fcf_yield > 3:
                score += 5

        div_yield = f.get("dividend_yield", 0)
        if div_yield and div_yield > 3:
            score += 10

        return max(0, min(100, score))

    def _compute_momentum(self, f: dict) -> float:
        """Momentum factor."""
        score = 50.0

        roc_5d = f.get("roc_5d", 0)
        roc_20d = f.get("roc_20d", 0) or f.get("momentum_20d", 0)

        if roc_5d > 3:
            score += min(roc_5d * 3, 20)
        elif roc_5d < -3:
            score += max(roc_5d * 3, -20)

        if roc_20d > 10:
            score += min(roc_20d, 20)
        elif roc_20d < -10:
            score += max(roc_20d, -20)

        # Trend
        trend = f.get("trend_slope_20d", 0)
        if trend > 0:
            score += 5
        elif trend < 0:
            score -= 5

        return max(0, min(100, score))

    def _compute_quality(self, f: dict) -> float:
        """Quality factor."""
        score = 50.0

        roe = f.get("roe", 0)
        if roe:
            if abs(roe) < 1:
                roe = roe * 100
            if roe > 15:
                score += 20
            elif roe > 10:
                score += 10
            elif roe < 0:
                score -= 15

        profit_margin = f.get("profit_margin", 0)
        if profit_margin:
            if abs(profit_margin) < 1:
                profit_margin = profit_margin * 100
            if profit_margin > 15:
                score += 15
            elif profit_margin > 10:
                score += 10
            elif profit_margin < 0:
                score -= 15

        de = f.get("debt_to_equity", 0)
        if de:
            if de < 0.5:
                score += 10
            elif de > 2.0:
                score -= 10

        cash_conv = f.get("cash_conversion", 0)
        if cash_conv and cash_conv > 1.0:
            score += 5

        return max(0, min(100, score))

    def _compute_size(self, f: dict) -> float:
        """Size factor (büyük şirket = düşük skor, küçük şirket = yüksek skor). Rölatif hesaplar."""
        market_cap = f.get("market_cap", 0)
        if not market_cap or market_cap <= 0:
            return 50.0

        mc_median = f.get("sector_mc_median", f.get("market_mc_median", 30e9))
        if mc_median > 0:
            relative_size = market_cap / mc_median
            if relative_size > 5.0:
                return 30.0  # Çok büyük
            elif relative_size > 2.0:
                return 40.0
            elif relative_size > 0.5:
                return 55.0
            elif relative_size > 0.1:
                return 70.0  # Orta
            else:
                return 85.0  # Küçük

        return 50.0

    def _compute_low_vol(self, f: dict) -> float:
        """Low Volatility factor (düşük volatilite = yüksek skor)."""
        vol = f.get("realized_vol_20d", 20)
        if not vol or vol <= 0:
            return 50.0

        if vol < 15:
            return 80.0
        elif vol < 20:
            return 65.0
        elif vol < 30:
            return 50.0
        elif vol < 40:
            return 35.0
        else:
            return 20.0

    def compute_portfolio_exposure(
        self,
        positions: list[dict[str, Any]],
        factor_scores: dict[str, FactorScore],
    ) -> FactorExposure:
        """Portföy faktör maruziyeti hesapla."""
        total_value = sum(p.get("value", 0) for p in positions)
        if total_value <= 0:
            return FactorExposure()

        exposure = FactorExposure()

        for pos in positions:
            ticker = pos.get("ticker", "")
            value = pos.get("value", 0)
            weight = value / total_value

            scores = factor_scores.get(ticker)
            if not scores:
                continue

            # Normalize to -1 to +1
            exposure.value_exposure += weight * (scores.value_score - 50) / 50
            exposure.momentum_exposure += weight * (scores.momentum_score - 50) / 50
            exposure.quality_exposure += weight * (scores.quality_score - 50) / 50
            exposure.size_exposure += weight * (scores.size_score - 50) / 50
            exposure.low_vol_exposure += weight * (scores.low_vol_score - 50) / 50

        # Concentration risk (HHI)
        weights = [p.get("value", 0) / total_value for p in positions if total_value > 0]
        exposure.concentration_risk = sum(w ** 2 for w in weights)

        return exposure


# Singleton
factor_engine = FactorEngine()


# =====================================================
# B30 Factor Investing entegrasyonu
# =====================================================
def compute_financial_scores(financials: dict[str, Any]) -> dict[str, Any]:
    """Piotroski F-Score, Beneish M-Score, Altman Z-Score hesapla."""
    result = {}
    try:
        from services.factors.altman import calculate_z_score
        from services.factors.beneish import calculate_m_score
        from services.factors.piotroski import calculate_f_score
        f_result = calculate_f_score(financials)
        m_result = calculate_m_score(financials)
        z_result = calculate_z_score(financials)
        result["f_score"] = f_result["f_score"]
        result["f_score_detail"] = f_result
        result["m_score"] = m_result["m_score"]
        result["m_score_detail"] = m_result
        result["z_score"] = z_result["z_score"]
        result["z_score_detail"] = z_result
    except ImportError:
        logger.debug("Optional import not available in compute_financial_scores", exc_info=True)
    return result
