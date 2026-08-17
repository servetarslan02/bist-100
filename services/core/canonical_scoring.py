"""
ALPHA BIST — Canonical Scoring Pipeline v1.0

TEK KARAR MİMARİSİ:
Tüm scoring mekanizmalarını tek bir canonical pipeline altında birleştirir.

EĞİTİM MİMARİSİ:
VERİ → FEATURE CONTRACT → 9 MOTOR → CROSS-SECTIONAL → CANONICAL SCORE → DECISION → RİSK → PORTFÖY

Bu modül:
- 9 motorun çıktısını tek bir ScoreVector'da birleştirir
- Eksik/STALE/MISSING veriyi 0'a çevirmez
- Risk ve opportunity'yi ayrı tutar
- Decision Engine'e yapılandırılmış girdi sağlar
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
import numpy as np
import structlog

logger = structlog.get_logger()


# =====================================================
# SCORE VECTOR
# =====================================================

@dataclass
class ScoreVector:
    """Çok boyutlu skor vektörü — her boyut 0-100 arası.

    0 = bilgi yok / ilgisiz
    Pozitif = olumlu
    Negatif = olumsuz (şimdilik kullanılmıyor, 0-100 arası)
    """

    # Motor bazlı boyutlar
    technical: float = 0.0          # Calculator + Motor2 (trend, momentum, RSI, MACD)
    momentum: float = 0.0           # Motor2 (roc, acceleration, breakout)
    relative_strength: float = 0.0  # Motor1 (vs BIST, vs sector, vs peers)
    volume: float = 0.0             # Motor3 (z-score, trend, tick rule)
    fundamental: float = 0.0        # Motor4 (value, quality, growth)
    news_sentiment: float = 0.0     # Motor5 (KAP + news + combined)
    catalyst: float = 0.0           # Motor6 (upcoming events, time decay)
    mean_reversion: float = 0.0     # Motor8 (BB, RSI oversold/overbought)
    seasonality: float = 0.0        # Motor9 (monthly, quarterly patterns)
    market_regime: float = 0.0      # Regime detector (BULL/BEAR/SIDEWAYS fit)

    # Risk boyutları (ayrı tutulmalı)
    risk: float = 0.0               # Volatilite, drawdown, ATR, correlation
    data_quality: float = 0.0       # Feature availability, freshness, completeness

    # Meta
    ticker: str = ""
    timestamp: str = ""
    regime: str = "UNKNOWN"

    def to_dict(self) -> Dict[str, float]:
        """Skor vektörünü dict'e çevir."""
        return {
            "technical": self.technical,
            "momentum": self.momentum,
            "relative_strength": self.relative_strength,
            "volume": self.volume,
            "fundamental": self.fundamental,
            "news_sentiment": self.news_sentiment,
            "catalyst": self.catalyst,
            "mean_reversion": self.mean_reversion,
            "seasonality": self.seasonality,
            "market_regime": self.market_regime,
            "risk": self.risk,
            "data_quality": self.data_quality,
        }

    def get_opportunity_dimensions(self) -> Dict[str, float]:
        """Fırsat boyutlarını döndür (risk ve data_quality hariç)."""
        return {k: v for k, v in self.to_dict().items()
                if k not in ("risk", "data_quality")}

    def get_nonzero_count(self) -> int:
        """Sıfır olmayan boyut sayısı."""
        return sum(1 for v in self.to_dict().values() if v != 0)


@dataclass
class CanonicalScore:
    """Canonical skor — tek çıktı."""

    # Boyut vektörü
    vector: ScoreVector = field(default_factory=ScoreVector)

    # Nihai skorlar (tek sayı)
    opportunity_score: float = 0.0   # "Ne kadar cazip?" (0-100)
    risk_score: float = 0.0          # "Ne kadar tehlikeli?" (0-100, yüksek = güvenli)
    confidence: float = 0.0          # "Buna ne kadar güveniyoruz?" (0-1)

    # Yön
    direction: str = "NEUTRAL"       # LONG / SHORT / NEUTRAL

    # Decomposition
    decomposition: Dict[str, float] = field(default_factory=dict)

    # Metadata
    ticker: str = ""
    timestamp: str = ""
    regime: str = ""
    feature_count: int = 0
    nonzero_dimensions: int = 0

    # ML model bilgisi
    ml_score: Optional[float] = None    # ML prediction (0-100)
    ml_confidence: float = 0.0          # ML güven skoru (0-1)
    rule_score: float = 0.0             # Rule-based skor (ML blend öncesi)


# =====================================================
# CANONICAL SCORING PIPELINE
# =====================================================

class CanonicalScoringPipeline:
    """Tek canonical scoring pipeline.

    Mevcut ağırlıkları korur:
    - RankingModel._rule_based_score ile aynı ağırlıklar
    - OpportunityDiscoveryEngine.DEFAULT_WEIGHTS ile aynı yapı
    - Strateji değişikliği YAPMAZ
    """

    # Mevcut rule-based score ile aynı ağırlıklar (BULL rejim)
    # Kaynak: services/ml/ranking_model.py _rule_based_score()
    REGIME_WEIGHTS = {
        "BULL": {
            "technical": 0.15,
            "momentum": 0.20,
            "relative_strength": 0.10,
            "volume": 0.08,
            "fundamental": 0.10,
            "news_sentiment": 0.08,
            "catalyst": 0.05,
            "mean_reversion": 0.02,
            "seasonality": 0.02,
            "market_regime": 0.10,
            "risk": 0.10,
        },
        "BEAR": {
            "technical": 0.10,
            "momentum": 0.05,
            "relative_strength": 0.05,
            "volume": 0.08,
            "fundamental": 0.15,
            "news_sentiment": 0.05,
            "catalyst": 0.05,
            "mean_reversion": 0.10,
            "seasonality": 0.02,
            "market_regime": 0.10,
            "risk": 0.25,
        },
        "SIDEWAYS": {
            "technical": 0.12,
            "momentum": 0.08,
            "relative_strength": 0.08,
            "volume": 0.06,
            "fundamental": 0.15,
            "news_sentiment": 0.05,
            "catalyst": 0.05,
            "mean_reversion": 0.12,
            "seasonality": 0.02,
            "market_regime": 0.10,
            "risk": 0.17,
        },
        "UNKNOWN": {
            "technical": 0.12,
            "momentum": 0.12,
            "relative_strength": 0.08,
            "volume": 0.06,
            "fundamental": 0.10,
            "news_sentiment": 0.06,
            "catalyst": 0.05,
            "mean_reversion": 0.06,
            "seasonality": 0.02,
            "market_regime": 0.10,
            "risk": 0.22,
        },
    }

    def compute_score_vector(
        self,
        ticker: str,
        features: Dict[str, Any],
        regime: str = "UNKNOWN",
    ) -> ScoreVector:
        """Feature'lardan çok boyutlu skor vektörü üret.

        Her boyut bağımsız hesaplanır — birbirini etkilemez.
        Eksik feature'lar 0'a çevrilmez, o boyut düşük güvenle işaretlenir.
        """
        sv = ScoreVector(
            ticker=ticker,
            timestamp=datetime.now(timezone.utc).isoformat(),
            regime=regime,
        )

        # === TECHNICAL ===
        sv.technical = self._score_technical(features)

        # === MOMENTUM ===
        sv.momentum = self._score_momentum(features)

        # === RELATIVE STRENGTH ===
        sv.relative_strength = self._score_relative_strength(features)

        # === VOLUME ===
        sv.volume = self._score_volume(features)

        # === FUNDAMENTAL ===
        sv.fundamental = self._score_fundamental(features)

        # === NEWS SENTIMENT ===
        sv.news_sentiment = self._score_news_sentiment(features)

        # === CATALYST ===
        sv.catalyst = self._score_catalyst(features)

        # === MEAN REVERSION ===
        sv.mean_reversion = self._score_mean_reversion(features)

        # === SEASONALITY ===
        sv.seasonality = self._score_seasonality(features)

        # === MARKET REGIME ===
        sv.market_regime = self._score_regime_fit(features, regime)

        # === RISK (ayrı tutulmalı) ===
        sv.risk = self._score_risk(features)

        # === DATA QUALITY ===
        sv.data_quality = self._score_data_quality(features)

        return sv

    def compute_canonical_score(
        self,
        ticker: str,
        features: Dict[str, Any],
        regime: str = "UNKNOWN",
        ml_model=None,
    ) -> CanonicalScore:
        """Tek canonical skor üret.

        Args:
            ticker: Hisse kodu
            features: Feature dict
            regime: Piyasa rejimi
            ml_model: TrainedModel instance (None → rule-based only)
        """
        vector = self.compute_score_vector(ticker, features, regime)
        weights = self.REGIME_WEIGHTS.get(regime, self.REGIME_WEIGHTS["UNKNOWN"])

        # Ağırlıklı fırsat skoru (risk hariç)
        opportunity_dims = vector.get_opportunity_dimensions()
        weighted_sum = sum(
            opportunity_dims[dim] * weights.get(dim, 0)
            for dim in opportunity_dims
        )
        total_weight = sum(
            weights.get(dim, 0)
            for dim in opportunity_dims
        )
        rule_score = weighted_sum / total_weight if total_weight > 0 else 50.0

        # ML prediction (varsa)
        ml_score = None
        ml_confidence = 0.0
        if ml_model is not None:
            try:
                # MultiHorizonModel veya TrainedModel — ikisi de predict(features) destekler
                ml_pred = ml_model.predict(features)
                # ML prediction'ı 0-100 aralığına normalize et
                ml_score = max(0, min(100, 50 + ml_pred * 10))
                ml_confidence = min(1.0, abs(ml_pred) / 2.0)
            except Exception:
                pass  # ML prediction başarısızsa rule-based kullan

        # Ensemble: ML varsa %70 ML + %30 rule-based
        if ml_score is not None:
            opportunity_score = 0.7 * ml_score + 0.3 * rule_score
        else:
            opportunity_score = rule_score

        # Risk skoru (0-100, yüksek = güvenli)
        risk_score = vector.risk

        # Confidence: data_quality'den türetilir
        confidence = min(1.0, vector.data_quality / 100)

        # Yön belirleme
        direction = self._determine_direction(vector, opportunity_score, regime)

        # Decomposition
        decomposition = {
            dim: round(vector.to_dict()[dim] * weights.get(dim, 0), 2)
            for dim in opportunity_dims
        }

        return CanonicalScore(
            vector=vector,
            opportunity_score=round(opportunity_score, 2),
            risk_score=round(risk_score, 2),
            confidence=round(confidence, 4),
            direction=direction,
            decomposition=decomposition,
            ticker=ticker,
            timestamp=datetime.now(timezone.utc).isoformat(),
            regime=regime,
            feature_count=len(features),
            nonzero_dimensions=vector.get_nonzero_count(),
            ml_score=round(ml_score, 2) if ml_score is not None else None,
            ml_confidence=round(ml_confidence, 4),
            rule_score=round(rule_score, 2),
        )

    # =====================================================
    # BOYUT HESAPLAMA (mevcut rule-based score ile uyumlu)
    # =====================================================

    def _score_technical(self, f: Dict) -> float:
        """Teknik skor (RSI, MACD, Bollinger, ADX)."""
        score = 50.0

        rsi = self._s(f.get("rsi_14", 50))
        if rsi > 70:
            score -= 10
        elif rsi < 30:
            score += 10
        elif 40 < rsi < 60:
            score += 5

        macd = self._s(f.get("macd_hist", 0))
        if macd > 0:
            score += 5
        elif macd < 0:
            score -= 5

        bb = self._s(f.get("bb_position", 0.5))
        if bb > 0.9:
            score -= 5
        elif bb < 0.1:
            score += 10

        adx = self._s(f.get("adx", 0))
        if adx > 25:
            score += 5

        # Trend kalitesi
        trend_slope = self._s(f.get("trend_slope_20d", 0))
        trend_r2 = self._s(f.get("trend_r2_20d", 0))
        if trend_r2 > 0.5 and trend_slope > 0:
            score += trend_slope * 0.05 * trend_r2
        elif trend_r2 > 0.5 and trend_slope < 0:
            score += trend_slope * 0.05 * trend_r2 * 0.5

        return max(0, min(100, score))

    def _score_momentum(self, f: Dict) -> float:
        """Momentum skoru."""
        score = 50.0

        roc_5d = self._s(f.get("roc_5d", 0))
        roc_20d = self._s(f.get("roc_20d", 0))

        if roc_5d > 3:
            score += min(roc_5d * 3, 20)
        elif roc_5d < -3:
            score += max(roc_5d * 3, -20)

        if roc_20d > 5:
            score += min(roc_20d, 15)
        elif roc_20d < -5:
            score += max(roc_20d, -15)

        accel = self._s(f.get("momentum_acceleration", 0))
        if accel > 0:
            score += 5
        elif accel < 0:
            score -= 5

        # Trend kalitesi bonusu
        trend_r2 = self._s(f.get("trend_r2_20d", 0))
        if trend_r2 > 0.7:
            score += 5

        return max(0, min(100, score))

    def _score_relative_strength(self, f: Dict) -> float:
        """Relatif güç skoru."""
        score = 50.0

        rs_5d = self._s(f.get("rs_vs_bist_5d", 0))
        score += rs_5d * 0.10  # Mevcut ağırlıkla uyumlu

        rs_sector = self._s(f.get("rs_vs_sector_5d", 0))
        score += rs_sector * 0.05

        rs_trend = self._s(f.get("rs_trend", 0))
        score += rs_trend * 5

        return max(0, min(100, score))

    def _score_volume(self, f: Dict) -> float:
        """Hacim skoru."""
        score = 50.0

        vol_z = self._s(f.get("volume_zscore", 0))
        score += vol_z * 8  # Mevcut ağırlıkla uyumlu

        vol_trend = self._s(f.get("volume_trend", 0))
        score += vol_trend * 0.3

        tick = self._s(f.get("tick_rule", 0))
        score += tick * 5

        return max(0, min(100, score))

    def _score_fundamental(self, f: Dict) -> float:
        """Fundamental skor."""
        score = 50.0

        fcf = self._s(f.get("fcf_yield_pct", 0))
        if fcf != 0:
            score += fcf * 0.04  # Mevcut ağırlıkla uyumlu

        bsq = self._s(f.get("balance_sheet_quality", 0))
        if bsq != 0:
            score += bsq * 0.0003

        value = self._s(f.get("value_score", 0))
        score += value * 0.1

        quality = self._s(f.get("quality_score", 0))
        score += quality * 0.05

        return max(0, min(100, score))

    def _score_news_sentiment(self, f: Dict) -> float:
        """Haber sentiment skoru."""
        score = 50.0

        kap_sent = self._s(f.get("kap_sentiment_weighted",
                          f.get("kap_sentiment_avg", 0)))
        news_sent = self._s(f.get("news_sentiment_weighted", 0))

        # Ağırlıklı kombinasyon (Motor5 ile aynı: 0.6 KAP + 0.4 news)
        if kap_sent != 0 or news_sent != 0:
            combined = 0.6 * kap_sent + 0.4 * news_sent
            score += combined * 20

        # Sentiment momentum
        sent_mom = self._s(f.get("sentiment_momentum", 0))
        score += sent_mom * 10

        return max(0, min(100, score))

    def _score_catalyst(self, f: Dict) -> float:
        """Katalizör skoru."""
        score = 50.0

        cat_count = self._s(f.get("catalyst_count", 0))
        cat_importance = self._s(f.get("catalyst_importance", 0))
        cat_days = self._s(f.get("catalyst_days_nearest", 999))
        cat_decay = self._s(f.get("catalyst_time_decay_score", 0))

        if cat_count > 0:
            score += cat_decay * 20
            if cat_days <= 7:
                score += cat_importance * 15

        return max(0, min(100, score))

    def _score_mean_reversion(self, f: Dict) -> float:
        """Mean reversion skoru."""
        score = 50.0

        rsi = self._s(f.get("rsi_14", 50))
        bb_zscore = self._s(f.get("bb_zscore_20d", 0))

        # Aşırı satım = fırsat
        if rsi < 30:
            score += (30 - rsi) * 0.8
        elif rsi > 70:
            score -= (rsi - 70) * 0.5

        # Bollinger alt banda yakınlık
        if bb_zscore < -2:
            score += abs(bb_zscore) * 5
        elif bb_zscore > 2:
            score -= bb_zscore * 3

        # Mean reversion sinyali
        mr_signal = self._s(f.get("mean_reversion_signal", 0))
        score += mr_signal * 10

        return max(0, min(100, score))

    def _score_seasonality(self, f: Dict) -> float:
        """Mevsimsellik skoru."""
        score = 50.0

        month_avg = self._s(f.get("seasonality_current_month_avg", 0))
        month_wr = self._s(f.get("seasonality_current_month_win_rate", 0))

        if month_wr > 0:
            # Win rate >50% = olumlu, <50% = olumsuz
            score += (month_wr - 0.5) * 40

        if month_avg != 0:
            score += month_avg * 5

        quarter_avg = self._s(f.get("seasonality_current_quarter_avg", 0))
        if quarter_avg != 0:
            score += quarter_avg * 2

        return max(0, min(100, score))

    def _score_regime_fit(self, f: Dict, regime: str) -> float:
        """Rejim uyumu skoru."""
        mom = self._s(f.get("momentum_20d", 0))

        regime_fit = {
            "BULL": {"LONG": 85, "SHORT": 15},
            "BEAR": {"LONG": 15, "SHORT": 85},
            "SIDEWAYS": {"LONG": 50, "SHORT": 50},
            "HIGH_VOL": {"LONG": 35, "SHORT": 65},
            "UNKNOWN": {"LONG": 50, "SHORT": 50},
        }

        direction = "LONG" if mom > 0 else "SHORT"
        fit = regime_fit.get(regime, {"LONG": 50, "SHORT": 50})
        return fit.get(direction, 50)

    def _score_risk(self, f: Dict) -> float:
        """Risk skoru (0-100, yüksek = güvenli)."""
        score = 70.0

        atr = self._s(f.get("atr_pct", 0))
        if atr > 5:
            score -= 25
        elif atr > 3:
            score -= 10
        elif atr < 1.5:
            score += 10

        vol_20d = self._s(f.get("volatility_20d", 20))
        if vol_20d > 40:
            score -= 20
        elif vol_20d > 25:
            score -= 5
        elif vol_20d < 15:
            score += 10

        dd = self._s(f.get("drawdown_20d", 0))
        if dd > 15:
            score -= 15
        elif dd > 10:
            score -= 8

        # Düşüş analizi (Motor7)
        falling_temp = self._s(f.get("falling_is_temporary", 0.5))
        if falling_temp > 0.7:
            score += 5  # Geçici düşüş = daha az risk

        catch_knife = self._s(f.get("catch_falling_knife_risk", 0))
        if catch_knife > 50:
            score -= 10

        return max(0, min(100, score))

    def _score_data_quality(self, f: Dict) -> float:
        """Veri kalitesi skoru (0-100).

        Feature availability, freshness, completeness.
        """
        score = 100.0

        # Temel feature'lar var mı?
        critical_features = [
            "rsi_14", "momentum_20d", "volume_zscore", "atr_pct",
            "rs_vs_bist_5d", "kap_sentiment_avg",
        ]
        missing_critical = sum(1 for feat in critical_features
                              if f.get(feat) is None)
        score -= missing_critical * 10

        # STALE/MISSING oranı
        stale_count = sum(1 for k, v in f.items()
                         if isinstance(v, str) and v in ("STALE", "MISSING", "UNKNOWN"))
        total_features = len(f)
        if total_features > 0:
            stale_pct = stale_count / total_features
            score -= stale_pct * 30

        # Fundamental veri var mı?
        if f.get("fcf_yield_pct") is None and f.get("balance_sheet_quality") is None:
            score -= 10  # Fundamental veri eksik

        # KAP/haber veri var mı?
        if f.get("kap_sentiment_avg") is None and f.get("news_sentiment_weighted") is None:
            score -= 5  # Sentiment veri eksik

        return max(0, min(100, score))

    def _determine_direction(
        self, vector: ScoreVector, opportunity_score: float, regime: str
    ) -> str:
        """Yön belirle."""
        mom = vector.momentum
        technical = vector.technical
        rs = vector.relative_strength

        if opportunity_score < 40:
            return "SHORT"
        elif opportunity_score > 60:
            return "LONG"
        elif mom > 55 and technical > 55:
            return "LONG"
        elif mom < 45 and technical < 45:
            return "SHORT"

        return "NEUTRAL"

    @staticmethod
    def _s(val) -> float:
        """Safe float conversion."""
        if val is None:
            return 0.0
        if isinstance(val, np.ndarray):
            return float(val.flat[0]) if val.size > 0 else 0.0
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0


# =====================================================
# CANONICAL FEATURE REGISTRY (tek kaynak)
# =====================================================

# Bu liste canonical scoring pipeline'ın kullandığı TÜM feature'ları içerir.
# Training ve inference aynı bu listeyi kullanır.
# Regex veya source parsing GEREKTİRMEZ.
#
# Kural: Yeni feature eklendiğinde BURAYA da ekle.
CANONICAL_FEATURE_REGISTRY: List[str] = [
    # Motor 1: Relatif Güç
    "rs_vs_bist_1d", "rs_vs_bist_5d", "rs_vs_bist_20d", "rs_vs_bist_60d",
    "rs_vs_sector_5d", "rs_vs_peers_5d", "rs_trend", "rs_peer_rank",
    # Motor 2: Momentum + Trend
    "roc_5d", "roc_20d", "roc_60d", "momentum_20d",
    "trend_slope_20d", "trend_r2_20d", "momentum_acceleration",
    "momentum_accel_trend", "price_vs_sma20", "price_vs_sma50", "price_vs_sma200",
    "near_20d_high", "near_60d_high", "near_120d_high",
    "breakout_failure", "drawdown_20d", "recovery_strength",
    # Motor 3: Hacim + Mikroyapı
    "volume_percentile", "volume_zscore", "volume_trend",
    "volume_up_down_ratio", "tick_rule", "vwap_deviation",
    "avg_volume_5d", "obv",
    # Motor 4: Fundamental
    "sector_norm_pe_ratio", "sector_norm_pb_ratio", "fcf_yield_pct",
    "fcf_margin", "balance_sheet_quality", "profit_margin_pct",
    "roe", "roa",
    # Motor 5: KAP + Haber
    "kap_sentiment_avg", "kap_sentiment_latest", "news_sentiment_weighted",
    "sentiment_momentum", "kap_avg_importance",
    # Motor 6: Katalizör
    "catalyst_count", "catalyst_importance", "catalyst_days_nearest",
    # Motor 7: Neden Düşüyor?
    "falling_is_temporary", "fall_market_selloff", "fall_sector_selloff",
    # Teknik (canonical scoring)
    "rsi_14", "macd_hist", "bb_position", "adx",
    "bb_zscore_20d", "mean_reversion_signal",
    # Mevsimsellik
    "seasonality_current_month_avg", "seasonality_current_month_win_rate",
    "seasonality_current_quarter_avg",
    # Katalizör detay
    "catalyst_time_decay_score",
    # Risk
    "atr_pct", "volatility_20d", "realized_vol_20d",
    "catch_falling_knife_risk",
    # Cross-Sectional (canonical scoring)
    "rank_return_5d", "rank_return_20d", "rank_volume_zscore", "rank_rsi_14",
    "sector_rel_return_5d", "sector_zscore_momentum_20d",
    "cs_zscore_roc_5d", "cs_zscore_roc_20d",
    # Market Breadth
    "market_breadth", "market_ad_ratio",
]

# Unique, order preserved
CANONICAL_FEATURE_REGISTRY = list(dict.fromkeys(CANONICAL_FEATURE_REGISTRY))


def get_canonical_features() -> List[str]:
    """Canonical feature listesini döndür (tek kaynak)."""
    return list(CANONICAL_FEATURE_REGISTRY)


# Singleton
canonical_scoring = CanonicalScoringPipeline()
