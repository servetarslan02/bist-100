"""
ALPHA BIST — Factor Engine v1.1

Faktör bazlı analiz:
- Value (P/E, P/B, FCF Yield)
- Momentum (ROC, relative strength)
- Quality (ROE, margins, cash flow)
- Size (market cap)
- Low Volatility
- Factor Exposure

FAZ 10.8: Factor Engine
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger()

# ─── Sabitler ────────────────────────────────────────────────────────
DEFAULT_SCORE: float = 50.0
SCORE_MIN: float = 0.0
SCORE_MAX: float = 100.0

# Value factor eşikleri
VALUE_PE_DEEP_DISCOUNT: float = 0.6
VALUE_PE_DISCOUNT: float = 0.8
VALUE_PE_PREMIUM: float = 1.2
VALUE_PE_HIGH_PREMIUM: float = 1.5
VALUE_PB_DEEP_DISCOUNT: float = 0.6
VALUE_PB_DISCOUNT: float = 0.9
VALUE_PB_HIGH_PREMIUM: float = 1.5
VALUE_FCF_HIGH: float = 8.0
VALUE_FCF_MEDIUM: float = 5.0
VALUE_FCF_LOW: float = 3.0
VALUE_DIV_THRESHOLD: float = 3.0
VALUE_DEFAULT_PE_MEDIAN: float = 15.0
VALUE_DEFAULT_PB_MEDIAN: float = 2.0

# Momentum eşikleri
MOM_ROC_STRONG: float = 3.0
MOM_ROC_WEAK: float = -3.0
MOM_ROC_20D_STRONG: float = 10.0
MOM_ROC_20D_WEAK: float = -10.0
MOM_ROC_CAP: float = 20.0

# Quality eşikleri
QUALITY_ROE_STRONG: float = 15.0
QUALITY_ROE_GOOD: float = 10.0
QUALITY_MARGIN_STRONG: float = 15.0
QUALITY_MARGIN_GOOD: float = 10.0
QUALITY_DE_LOW: float = 0.5
QUALITY_DE_HIGH: float = 2.0
QUALITY_CASH_CONV: float = 1.0
QUALITY_PCT_THRESHOLD: float = 1.0

# Size eşikleri (rölatif)
SIZE_VERY_LARGE: float = 5.0
SIZE_LARGE: float = 2.0
SIZE_MEDIUM: float = 0.5
SIZE_SMALL: float = 0.1
SIZE_DEFAULT_MC_MEDIAN: float = 30e9
SIZE_VERY_LARGE_SCORE: float = 30.0
SIZE_LARGE_SCORE: float = 40.0
SIZE_MEDIUM_SCORE: float = 55.0
SIZE_SMALL_SCORE: float = 70.0
SIZE_MICRO_SCORE: float = 85.0

# Volatilite eşikleri
VOL_VERY_LOW: float = 15.0
VOL_LOW: float = 20.0
VOL_MEDIUM: float = 30.0
VOL_HIGH: float = 40.0
VOL_DEFAULT: float = 20.0
VOL_VERY_LOW_SCORE: float = 80.0
VOL_LOW_SCORE: float = 65.0
VOL_MEDIUM_SCORE: float = 50.0
VOL_HIGH_SCORE: float = 35.0
VOL_VERY_HIGH_SCORE: float = 20.0

# Skor bonusları
BONUS_DEEP_DISCOUNT: int = 25
BONUS_DISCOUNT: int = 15
BONUS_SLIGHT_DISCOUNT: int = 5
BONUS_PB_DEEP: int = 20
BONUS_PB_DISCOUNT: int = 10
PENALTY_PREMIUM: int = 15
PENALTY_PB_PREMIUM: int = 10
BONUS_FCF_HIGH: int = 20
BONUS_FCF_MEDIUM: int = 10
BONUS_FCF_LOW: int = 5
BONUS_DIV: int = 10
BONUS_TREND_UP: int = 5
PENALTY_TREND_DOWN: int = 5
BONUS_ROE_STRONG: int = 20
BONUS_ROE_GOOD: int = 10
PENALTY_ROE_NEG: int = 15
BONUS_MARGIN_STRONG: int = 15
BONUS_MARGIN_GOOD: int = 10
PENALTY_MARGIN_NEG: int = 15
BONUS_DE_LOW: int = 10
PENALTY_DE_HIGH: int = 10
BONUS_CASH_CONV: int = 5

# Faktör ağırlıkları
DEFAULT_WEIGHT_VALUE: float = 0.20
DEFAULT_WEIGHT_MOMENTUM: float = 0.25
DEFAULT_WEIGHT_QUALITY: float = 0.25
DEFAULT_WEIGHT_SIZE: float = 0.10
DEFAULT_WEIGHT_LOW_VOL: float = 0.20

__all__ = [
    "FactorScore",
    "FactorExposure",
    "FactorEngine",
    "factor_engine",
    "compute_financial_scores",
]


@dataclass
class FactorScore:
    """Faktör skoru.

    Bir hissenin beş faktör (value, momentum, quality, size, low_vol) skorunu
    ve ağırlıklı bileşik skorunu temsil eder.
    """

    ticker: str
    value_score: float = 0.0
    momentum_score: float = 0.0
    quality_score: float = 0.0
    size_score: float = 0.0
    low_vol_score: float = 0.0
    composite_score: float = 0.0

    def __repr__(self) -> str:
        return (
            f"<FactorScore ticker={self.ticker!r} "
            f"val={self.value_score:.0f} mom={self.momentum_score:.0f} "
            f"qual={self.quality_score:.0f} size={self.size_score:.0f} "
            f"lvol={self.low_vol_score:.0f} comp={self.composite_score:.1f}>"
        )


@dataclass
class FactorExposure:
    """Portföy faktör maruziyeti.

    Portföyün her faktöre ne ölçüde maruz kaldığını ve konsantrasyon riskini gösterir.
    """

    value_exposure: float = 0.0
    momentum_exposure: float = 0.0
    quality_exposure: float = 0.0
    size_exposure: float = 0.0
    low_vol_exposure: float = 0.0
    concentration_risk: float = 0.0

    def __repr__(self) -> str:
        return (
            f"<FactorExposure val={self.value_exposure:+.3f} "
            f"mom={self.momentum_exposure:+.3f} qual={self.quality_exposure:+.3f} "
            f"conc={self.concentration_risk:.3f}>"
        )


class FactorEngine:
    """Faktör motoru.

    Value, momentum, quality, size ve low-volatility faktörlerini hesaplar,
    ağırlıklı bileşik skor üretir.
    """

    DEFAULT_WEIGHTS: dict[str, float] = {
        "value": DEFAULT_WEIGHT_VALUE,
        "momentum": DEFAULT_WEIGHT_MOMENTUM,
        "quality": DEFAULT_WEIGHT_QUALITY,
        "size": DEFAULT_WEIGHT_SIZE,
        "low_vol": DEFAULT_WEIGHT_LOW_VOL,
    }

    def __repr__(self) -> str:
        return "<FactorEngine>"

    def get_features(self, ticker: str) -> dict[str, Any]:
        """Hisse için faktör özelliklerini döndür.

        Args:
            ticker: Hisse sembolü.

        Returns:
            Faktör skorları sözlüğü. Hisse bulunamazsa boş dict.
        """
        score = self.get_ticker_factor_score(ticker)
        if score is None:
            return {}
        return {
            "value_score": score.value_score,
            "momentum_score": score.momentum_score,
            "quality_score": score.quality_score,
            "size_score": score.size_score,
            "low_vol_score": score.low_vol_score,
            "composite_score": score.composite_score,
        }

    def get_ticker_factor_score(self, ticker: str) -> FactorScore | None:
        """Ticker için faktör skoru döndür.

        Args:
            ticker: Hisse sembolü.

        Returns:
            FactorScore veya None (veri yoksa).
        """
        # Alt sınıflar tarafından override edilir
        return None

    def compute_factor_scores(
        self,
        ticker: str,
        fundamentals: dict[str, float],
        technicals: dict[str, float],
    ) -> FactorScore:
        """Tek hisse için faktör skorları hesapla.

        Args:
            ticker: Hisse sembolü.
            fundamentals: Temel veriler sözlüğü (pe_ratio, roe, vb.).
            technicals: Teknik veriler sözlüğü (momentum, vol, vb.).

        Returns:
            FactorScore: Hesaplanmış beş faktör ve bileşik skor.
        """
        score = FactorScore(ticker=ticker)
        score.value_score = self._compute_value(fundamentals)
        score.momentum_score = self._compute_momentum(technicals)
        score.quality_score = self._compute_quality(fundamentals)
        score.size_score = self._compute_size(fundamentals)
        score.low_vol_score = self._compute_low_vol(technicals)

        weights = self.DEFAULT_WEIGHTS
        score.composite_score = (
            score.value_score * weights["value"]
            + score.momentum_score * weights["momentum"]
            + score.quality_score * weights["quality"]
            + score.size_score * weights["size"]
            + score.low_vol_score * weights["low_vol"]
        )
        return score

    def _compute_value(self, f: dict[str, Any]) -> float:
        """Value factor hesapla (düşük çarpan = yüksek skor).

        Args:
            f: Temel veriler sözlüğü.

        Returns:
            Value skoru (0-100).
        """
        score = DEFAULT_SCORE

        pe = f.get("pe_ratio", 0)
        pe_median = f.get("sector_pe_median", f.get("market_pe_median", VALUE_DEFAULT_PE_MEDIAN))
        if pe and pe > 0 and pe_median > 0:
            pe_relative = pe / pe_median
            if pe_relative < VALUE_PE_DEEP_DISCOUNT:
                score += BONUS_DEEP_DISCOUNT
            elif pe_relative < VALUE_PE_DISCOUNT:
                score += BONUS_DISCOUNT
            elif pe_relative < VALUE_PE_PREMIUM:
                score += BONUS_SLIGHT_DISCOUNT
            elif pe_relative > VALUE_PE_HIGH_PREMIUM:
                score -= PENALTY_PREMIUM

        pb = f.get("pb_ratio", 0)
        pb_median = f.get("sector_pb_median", f.get("market_pb_median", VALUE_DEFAULT_PB_MEDIAN))
        if pb and pb > 0 and pb_median > 0:
            pb_relative = pb / pb_median
            if pb_relative < VALUE_PB_DEEP_DISCOUNT:
                score += BONUS_PB_DEEP
            elif pb_relative < VALUE_PB_DISCOUNT:
                score += BONUS_PB_DISCOUNT
            elif pb_relative > VALUE_PB_HIGH_PREMIUM:
                score -= PENALTY_PB_PREMIUM

        fcf_yield = f.get("fcf_yield", 0) or f.get("fcf_yield_pct", 0)
        if fcf_yield and fcf_yield > 0:
            if fcf_yield > VALUE_FCF_HIGH:
                score += BONUS_FCF_HIGH
            elif fcf_yield > VALUE_FCF_MEDIUM:
                score += BONUS_FCF_MEDIUM
            elif fcf_yield > VALUE_FCF_LOW:
                score += BONUS_FCF_LOW

        div_yield = f.get("dividend_yield", 0)
        if div_yield and div_yield > VALUE_DIV_THRESHOLD:
            score += BONUS_DIV

        return max(SCORE_MIN, min(SCORE_MAX, score))

    def _compute_momentum(self, f: dict[str, Any]) -> float:
        """Momentum factor hesapla.

        Args:
            f: Teknik veriler sözlüğü.

        Returns:
            Momentum skoru (0-100).
        """
        score = DEFAULT_SCORE

        roc_5d = f.get("roc_5d", 0)
        roc_20d = f.get("roc_20d", 0) or f.get("momentum_20d", 0)

        if roc_5d > MOM_ROC_STRONG:
            score += min(roc_5d * 3, MOM_ROC_CAP)
        elif roc_5d < MOM_ROC_WEAK:
            score += max(roc_5d * 3, -MOM_ROC_CAP)

        if roc_20d > MOM_ROC_20D_STRONG:
            score += min(roc_20d, MOM_ROC_CAP)
        elif roc_20d < MOM_ROC_20D_WEAK:
            score += max(roc_20d, -MOM_ROC_CAP)

        trend = f.get("trend_slope_20d", 0)
        if trend > 0:
            score += BONUS_TREND_UP
        elif trend < 0:
            score -= PENALTY_TREND_DOWN

        return max(SCORE_MIN, min(SCORE_MAX, score))

    def _compute_quality(self, f: dict[str, Any]) -> float:
        """Quality factor hesapla.

        Args:
            f: Temel veriler sözlüğü.

        Returns:
            Quality skoru (0-100).
        """
        score = DEFAULT_SCORE

        roe = f.get("roe", 0)
        if roe:
            if abs(roe) < QUALITY_PCT_THRESHOLD:
                roe = roe * 100
            if roe > QUALITY_ROE_STRONG:
                score += BONUS_ROE_STRONG
            elif roe > QUALITY_ROE_GOOD:
                score += BONUS_ROE_GOOD
            elif roe < 0:
                score -= PENALTY_ROE_NEG

        profit_margin = f.get("profit_margin", 0)
        if profit_margin:
            if abs(profit_margin) < QUALITY_PCT_THRESHOLD:
                profit_margin = profit_margin * 100
            if profit_margin > QUALITY_MARGIN_STRONG:
                score += BONUS_MARGIN_STRONG
            elif profit_margin > QUALITY_MARGIN_GOOD:
                score += BONUS_MARGIN_GOOD
            elif profit_margin < 0:
                score -= PENALTY_MARGIN_NEG

        de = f.get("debt_to_equity", 0)
        if de:
            if de < QUALITY_DE_LOW:
                score += BONUS_DE_LOW
            elif de > QUALITY_DE_HIGH:
                score -= PENALTY_DE_HIGH

        cash_conv = f.get("cash_conversion", 0)
        if cash_conv and cash_conv > QUALITY_CASH_CONV:
            score += BONUS_CASH_CONV

        return max(SCORE_MIN, min(SCORE_MAX, score))

    def _compute_size(self, f: dict[str, Any]) -> float:
        """Size factor hesapla (rölatif: küçük şirket = yüksek skor).

        Args:
            f: Temel veriler sözlüğü.

        Returns:
            Size skoru (0-100).
        """
        market_cap = f.get("market_cap", 0)
        if not market_cap or market_cap <= 0:
            return DEFAULT_SCORE

        mc_median = f.get("sector_mc_median", f.get("market_mc_median", SIZE_DEFAULT_MC_MEDIAN))
        if mc_median > 0:
            relative_size = market_cap / mc_median
            if relative_size > SIZE_VERY_LARGE:
                return SIZE_VERY_LARGE_SCORE
            elif relative_size > SIZE_LARGE:
                return SIZE_LARGE_SCORE
            elif relative_size > SIZE_MEDIUM:
                return SIZE_MEDIUM_SCORE
            elif relative_size > SIZE_SMALL:
                return SIZE_SMALL_SCORE
            else:
                return SIZE_MICRO_SCORE

        return DEFAULT_SCORE

    def _compute_low_vol(self, f: dict[str, Any]) -> float:
        """Low Volatility factor hesapla (düşük volatilite = yüksek skor).

        Args:
            f: Teknik veriler sözlüğü.

        Returns:
            Low-volatility skoru (0-100).
        """
        vol = f.get("realized_vol_20d", VOL_DEFAULT)
        if not vol or vol <= 0:
            return DEFAULT_SCORE

        if vol < VOL_VERY_LOW:
            return VOL_VERY_LOW_SCORE
        elif vol < VOL_LOW:
            return VOL_LOW_SCORE
        elif vol < VOL_MEDIUM:
            return VOL_MEDIUM_SCORE
        elif vol < VOL_HIGH:
            return VOL_HIGH_SCORE
        else:
            return VOL_VERY_HIGH_SCORE

    def compute_portfolio_exposure(
        self,
        positions: list[dict[str, Any]],
        factor_scores: dict[str, FactorScore],
    ) -> FactorExposure:
        """Portföy faktör maruziyeti hesapla.

        Args:
            positions: Pozisyon listesi [{ticker, value}, ...].
            factor_scores: Ticker → FactorScore sözlüğü.

        Returns:
            FactorExposure: Faktör maruziyetleri ve konsantrasyon riski.
        """
        total_value = sum(p.get("value", 0) for p in positions)
        if total_value <= 0:
            logger.warning("portfoy_bos")
            return FactorExposure()

        exposure = FactorExposure()

        for pos in positions:
            ticker = pos.get("ticker", "")
            value = pos.get("value", 0)
            weight = value / total_value

            scores = factor_scores.get(ticker)
            if not scores:
                continue

            exposure.value_exposure += weight * (scores.value_score - DEFAULT_SCORE) / DEFAULT_SCORE
            exposure.momentum_exposure += weight * (scores.momentum_score - DEFAULT_SCORE) / DEFAULT_SCORE
            exposure.quality_exposure += weight * (scores.quality_score - DEFAULT_SCORE) / DEFAULT_SCORE
            exposure.size_exposure += weight * (scores.size_score - DEFAULT_SCORE) / DEFAULT_SCORE
            exposure.low_vol_exposure += weight * (scores.low_vol_score - DEFAULT_SCORE) / DEFAULT_SCORE

        # Concentration risk (HHI)
        weights = [p.get("value", 0) / total_value for p in positions if total_value > 0]
        exposure.concentration_risk = sum(w**2 for w in weights)

        return exposure


# Singleton
factor_engine = FactorEngine()


# =====================================================
# B30 Factor Investing entegrasyonu
# =====================================================
def compute_financial_scores(financials: dict[str, Any]) -> dict[str, Any]:
    """Piotroski F-Score, Beneish M-Score, Altman Z-Score hesapla.

    Args:
        financials: Finansal veriler sözlüğü.

    Returns:
        f_score, m_score, z_score ve detayları içeren sözlük.
        Modül bulunamazsa boş dict döner.
    """
    result: dict[str, Any] = {}
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
        logger.warning("faktor_modul_bulunamadi", modul="services.factors")
    return result
