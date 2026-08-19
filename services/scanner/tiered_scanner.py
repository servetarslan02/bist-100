"""
ALPHA BIST — Katmanlı Tarama Motoru v1.0

800 hisseyi her saniye baştan analiz ETMEZ.
Katmanlı filtreleme: ucuz → pahalı → çok pahalı

Tier 0: Continuous Watch    → 800 hisse, çok ucuz state tracking
Tier 1: Quant Scan          → 800 hisse, matematiksel filtreler
Tier 2: Opportunity Engine  → 800 → 50, en ilginç hisseler
Tier 3: Deep Analysis       → 50 → 10, pahalı işlemler
Tier 4: Gemma               → 10 → 3-5, LLM reasoning
Tier 5: Decision            → 3-5 → 0-3, risk kontrollü karar

Haber/KAP/makro → herhangi bir hisseyi Tier 0'dan Tier 3'e atlayabilir.
"""

import math
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import numpy as np
import structlog

logger = structlog.get_logger()


# =====================================================
# Tier Definitions
# =====================================================

class Tier:
    """Tarama tier'ı."""
    CONTINUOUS_WATCH = 0   # 800 hisse, ucuz state
    QUANT_SCAN = 1         # 800 hisse, matematiksel filtre
    OPPORTUNITY = 2        # 800 → 50
    DEEP_ANALYSIS = 3      # 50 → 10
    GEMMA = 4              # 10 → 3-5
    DECISION = 5           # 3-5 → 0-3


@dataclass
class AssetTierState:
    """Her hissenin tier durumu."""
    ticker: str
    instrument_id: int = 0
    current_tier: int = Tier.CONTINUOUS_WATCH
    tier_score: float = 0.0
    last_tier_update: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Tier 0 — State tracking
    price: float = 0.0
    price_change_pct: float = 0.0
    volume: int = 0
    volume_ratio: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    spread: float = 0.0
    vwap: float = 0.0
    day_high: float = 0.0
    day_low: float = 0.0

    # Bar states
    bar_1m: Optional[Dict] = None
    bar_5m: Optional[Dict] = None
    bar_15m: Optional[Dict] = None
    bar_1h: Optional[Dict] = None
    bar_1d: Optional[Dict] = None

    # Index/sector relations
    index_beta: float = 1.0
    sector_rank: int = 0
    sector_relative: float = 0.0

    # Tier 1 — Quant features
    momentum_score: float = 0.0
    volume_anomaly_score: float = 0.0
    breakout_score: float = 0.0
    volatility_score: float = 0.0
    relative_strength_score: float = 0.0
    sector_divergence_score: float = 0.0
    flow_correlation_score: float = 0.0
    liquidity_score: float = 0.0

    # Tier 2 — Opportunity
    opportunity_score: float = 0.0
    opportunity_rank: int = 0

    # Tier 3 — Deep analysis
    ml_return_5d: float = 0.0
    ml_return_20d: float = 0.0
    ml_confidence: float = 0.0
    historical_analogues: int = 0
    scenario_expected_return: float = 0.0
    risk_reward_ratio: float = 0.0

    # Tier 4 — Gemma
    ai_assessment: str = ""
    ai_confidence: float = 0.0
    ai_direction: str = ""

    # Tier 5 — Decision
    action: str = ""  # BUY | SELL | HOLD
    conviction: str = ""  # HIGH | MEDIUM | LOW
    entry_price: float = 0.0
    target_price: float = 0.0
    stop_loss: float = 0.0

    # Event escalation
    escalated_by_event: bool = False
    escalation_reason: str = ""


@dataclass
class MarketRegime:
    """Piyasa rejimi — tarama kriterlerini etkiler."""
    regime: str = "RANGE"
    confidence: float = 0.5

    # Rejime göre ağırlıklar
    weights: Dict[str, float] = field(default_factory=lambda: {
        "momentum": 1.0,
        "volume_anomaly": 1.0,
        "breakout": 1.0,
        "volatility": 1.0,
        "relative_strength": 1.0,
        "sector_divergence": 1.0,
        "flow_correlation": 1.0,
        "liquidity": 1.0,
    })

    def update_weights(self, regime: str):
        """Rejime göre ağırlıkları güncelle."""
        self.regime = regime

        if regime in ["TRENDING-UP", "MOMENTUM-EXPANSION"]:
            self.weights = {
                "momentum": 1.5, "volume_anomaly": 1.2, "breakout": 1.4,
                "volatility": 0.7, "relative_strength": 1.3, "sector_divergence": 1.0,
                "flow_correlation": 0.8, "liquidity": 0.6,
            }
        elif regime in ["RISK-OFF", "PANIC"]:
            self.weights = {
                "momentum": 0.3, "volume_anomaly": 0.8, "breakout": 0.4,
                "volatility": 1.5, "relative_strength": 0.5, "sector_divergence": 0.7,
                "flow_correlation": 1.2, "liquidity": 1.5,
            }
        elif regime == "HIGH-VOLATILITY":
            self.weights = {
                "momentum": 0.6, "volume_anomaly": 1.3, "breakout": 0.8,
                "volatility": 1.4, "relative_strength": 0.7, "sector_divergence": 1.0,
                "flow_correlation": 1.0, "liquidity": 1.2,
            }
        elif regime == "RANGE":
            self.weights = {
                "momentum": 0.8, "volume_anomaly": 1.0, "breakout": 1.2,
                "volatility": 1.0, "relative_strength": 1.0, "sector_divergence": 1.0,
                "flow_correlation": 1.0, "liquidity": 1.0,
            }
        else:  # RECOVERY, LOW-VOLATILITY, vb.
            self.weights = {
                "momentum": 1.0, "volume_anomaly": 1.0, "breakout": 1.0,
                "volatility": 1.0, "relative_strength": 1.0, "sector_divergence": 1.0,
                "flow_correlation": 1.0, "liquidity": 1.0,
            }


# =====================================================
# Tiered Scanner
# =====================================================

class TieredScanner:
    """Katmanlı tarama motoru."""

    def __init__(self):
        self._assets: Dict[str, AssetTierState] = {}
        self._regime = MarketRegime()
        self._scan_count = 0
        self._tier_counts = {i: 0 for i in range(6)}

    def register_asset(self, ticker: str, instrument_id: int = 0):
        """Hisse kaydet."""
        if ticker not in self._assets:
            self._assets[ticker] = AssetTierState(
                ticker=ticker, instrument_id=instrument_id
            )

    def register_assets(self, tickers: List[str]):
        """Birden fazla hisse kaydet."""
        for i, ticker in enumerate(tickers):
            self.register_asset(ticker, instrument_id=i + 1)

    # =====================================================
    # Tier 0: Continuous Watch (Ucuz State Tracking)
    # =====================================================

    def process_tick(self, ticker: str, price: float, volume: int,
                     bid: float = 0, ask: float = 0, timestamp: Optional[datetime] = None):
        """
        Yeni tick → sadece state güncelle.
        800 hissenin geçmişini baştan okumaz.
        """
        if ticker not in self._assets:
            return

        asset = self._assets[ticker]
        prev_price = asset.price

        # State güncelle
        asset.price = price
        asset.volume = volume
        asset.bid = bid
        asset.ask = ask
        asset.spread = (ask - bid) if ask > 0 and bid > 0 else 0
        asset.day_high = max(asset.day_high, price)
        asset.day_low = min(asset.day_low, price) if asset.day_low > 0 else price

        if prev_price > 0:
            asset.price_change_pct = (price / prev_price - 1) * 100

        asset.last_tier_update = timestamp or datetime.now(timezone.utc)

    # =====================================================
    # Tier 1: Quant Scan (Matematiksel Filtreler)
    # =====================================================

    def run_quant_scan(self, features_map: Dict[str, Dict[str, float]]):
        """
        800 hisse için quant skorları hesapla.
        Her hisse için sadece feature'lardan skor üret.
        """
        for ticker, features in features_map.items():
            if ticker not in self._assets:
                continue

            asset = self._assets[ticker]

            # Her bileşen için skor (0-100)
            asset.momentum_score = self._score_momentum(features)
            asset.volume_anomaly_score = self._score_volume_anomaly(features)
            asset.breakout_score = self._score_breakout(features)
            asset.volatility_score = self._score_volatility(features)
            asset.relative_strength_score = self._score_relative_strength(features)
            asset.sector_divergence_score = self._score_sector_divergence(features)
            asset.flow_correlation_score = self._score_flow_correlation(features)
            asset.liquidity_score = self._score_liquidity(features)

            # Weighted opportunity score (rejime göre ağırlıklı)
            w = self._regime.weights
            asset.opportunity_score = (
                asset.momentum_score * w["momentum"]
                + asset.volume_anomaly_score * w["volume_anomaly"]
                + asset.breakout_score * w["breakout"]
                + asset.volatility_score * w["volatility"]
                + asset.relative_strength_score * w["relative_strength"]
                + asset.sector_divergence_score * w["sector_divergence"]
                + asset.flow_correlation_score * w["flow_correlation"]
                + asset.liquidity_score * w["liquidity"]
            ) / sum(w.values())

            asset.current_tier = Tier.QUANT_SCAN

        logger.info("Quant scan completed", stocks=len(features_map))

    # =====================================================
    # Tier 2: Opportunity Engine (800 → 50)
    # =====================================================

    def select_opportunities(self, top_n: int = 50) -> List[AssetTierState]:
        """
        En ilginç N hisseyi seç.
        Sadece quant skoruna göre filtrele.
        """
        ranked = sorted(
            self._assets.values(),
            key=lambda a: a.opportunity_score,
            reverse=True,
        )

        for i, asset in enumerate(ranked):
            asset.opportunity_rank = i + 1
            if i < top_n:
                asset.current_tier = Tier.OPPORTUNITY

        selected = ranked[:top_n]
        logger.info("Opportunities selected", count=len(selected),
                    top=selected[0].ticker if selected else "none")
        return selected

    # =====================================================
    # Tier 3: Deep Analysis (50 → 10)
    # =====================================================

    def run_deep_analysis(self, opportunities: List[AssetTierState],
                          ml_results: Dict[str, Dict],
                          historical_data: Dict[str, Any]) -> List[AssetTierState]:
        """
        50 aday için derin analiz.
        ML ensemble, historical analogues, scenario analysis.
        """
        for asset in opportunities:
            ticker = asset.ticker

            # ML sonuçları
            ml = ml_results.get(ticker, {})
            asset.ml_return_5d = ml.get("return_5d", 0)
            asset.ml_return_20d = ml.get("return_20d", 0)
            asset.ml_confidence = ml.get("confidence", 0)

            # Historical analogues
            analogues = historical_data.get(ticker, [])
            asset.historical_analogues = len(analogues)

            # Scenario expected return
            if analogues:
                returns = [a.get("outcome_return", 0) for a in analogues]
                asset.scenario_expected_return = np.mean(returns) if returns else 0

            # Risk/reward
            if asset.ml_return_5d > 0 and asset.ml_confidence > 0.5:
                asset.risk_reward_ratio = abs(asset.ml_return_5d / max(asset.volatility_score, 1))

            asset.current_tier = Tier.DEEP_ANALYSIS

        # En iyi 10'u seç
        ranked = sorted(opportunities, key=lambda a: (
            a.ml_confidence * 0.4
            + a.scenario_expected_return * 0.3
            + a.risk_reward_ratio * 0.3
        ), reverse=True)

        top_10 = ranked[:10]
        for asset in top_10:
            asset.current_tier = Tier.DEEP_ANALYSIS

        logger.info("Deep analysis completed", candidates=len(top_10))
        return top_10

    # =====================================================
    # Tier 4: Gemma (10 → 3-5)
    # =====================================================

    def select_for_gemma(self, deep_candidates: List[AssetTierState]) -> List[AssetTierState]:
        """
        Gemma'ya gönderilecek en güçlü adayları seç.
        Sadece en yüksek confidence + expected return olanlar.
        """
        gemma_candidates = []
        for asset in deep_candidates:
            # Gemma kriterleri
            if (asset.ml_confidence > 0.6
                and asset.scenario_expected_return > 2.0
                and asset.risk_reward_ratio > 1.5):
                asset.current_tier = Tier.GEMMA
                gemma_candidates.append(asset)

        # En fazla 5
        gemma_candidates = gemma_candidates[:5]
        logger.info("Gemma candidates selected", count=len(gemma_candidates))
        return gemma_candidates

    # =====================================================
    # Tier 5: Decision (3-5 → 0-3)
    # =====================================================

    def make_decisions(self, gemma_results: List[AssetTierState],
                       risk_limits: Dict[str, float]) -> List[AssetTierState]:
        """
        Risk motoru son kararı verir.
        """
        decisions = []
        for asset in gemma_results:
            # Risk kontrolleri
            if asset.ai_confidence < 0.7:
                continue

            if asset.risk_reward_ratio < 2.0:
                continue

            # Pozisyon limiti kontrolü
            max_position = risk_limits.get("max_position_pct", 10.0)

            asset.action = "BUY" if asset.ai_direction == "LONG" else "SELL" if asset.ai_direction == "SHORT" else "HOLD"
            asset.conviction = "HIGH" if asset.ai_confidence > 0.8 else "MEDIUM"
            asset.current_tier = Tier.DECISION
            decisions.append(asset)

        logger.info("Decisions made", count=len(decisions))
        return decisions

    # =====================================================
    # Event Escalation (Haber/KAP → Tier atla)
    # =====================================================

    def escalate_by_event(self, ticker: str, reason: str, importance: float):
        """
        Haber/KAP geldiğinde hisseyi normal sırasını atlayarak
        doğrudan derin analize sok.
        """
        if ticker not in self._assets:
            return

        asset = self._assets[ticker]
        old_tier = asset.current_tier

        # Yüksek önem → Tier 3'e atla
        if importance > 0.8:
            asset.current_tier = Tier.DEEP_ANALYSIS
            asset.escalated_by_event = True
            asset.escalation_reason = reason
            logger.warning("EVENT ESCALATION", ticker=ticker,
                          from_tier=old_tier, to_tier=Tier.DEEP_ANALYSIS,
                          reason=reason, importance=importance)
        elif importance > 0.5:
            # Orta önem → Tier 2'ye atla
            asset.current_tier = Tier.OPPORTUNITY
            asset.escalated_by_event = True
            asset.escalation_reason = reason
            logger.info("Event escalation (medium)", ticker=ticker,
                       from_tier=old_tier, to_tier=Tier.OPPORTUNITY)

    # =====================================================
    # Rejim Değişikliği
    # =====================================================

    def update_regime(self, new_regime: str, confidence: float = 0.5):
        """
        Piyasa rejimi değişti → tarama kriterleri değişir.
        """
        old_regime = self._regime.regime
        self._regime.update_weights(new_regime)
        self._regime.confidence = confidence

        logger.info("Regime changed", old=old_regime, new=new_regime,
                   weights=self._regime.weights)

    # =====================================================
    # Quant Scoring Fonksiyonları
    # =====================================================

    def _score_momentum(self, features: Dict) -> float:
        """Momentum skoru (0-100)."""
        mom5 = features.get("roc_5d", 0)
        mom20 = features.get("momentum_20d", 0)
        accel = features.get("price_acceleration", 0)

        score = 50
        if mom5 > 3:
            score += min(mom5 * 3, 25)
        elif mom5 < -3:
            score += max(mom5 * 3, -25)

        if mom20 > 5:
            score += min(mom20, 15)
        elif mom20 < -5:
            score += max(mom20, -15)

        if accel > 0:
            score += min(accel * 2, 10)

        return max(0, min(100, score))

    def _score_volume_anomaly(self, features: Dict) -> float:
        """Hacim anomalisi skoru (0-100)."""
        vol_z = features.get("volume_zscore", 0)
        vol_ratio = features.get("volume_ratio_20d", 1)

        score = 50
        if vol_z > 2:
            score += min(vol_z * 10, 40)
        elif vol_z < -1:
            score += max(vol_z * 5, -20)

        if vol_ratio > 2:
            score += min((vol_ratio - 1) * 10, 10)

        return max(0, min(100, score))

    def _score_breakout(self, features: Dict) -> float:
        """Kırılım skoru (0-100)."""
        bb_pos = features.get("bb_position", 0.5)
        near_high = features.get("near_20d_high", 0)
        near_low = features.get("near_20d_low", 0)

        score = 50
        if bb_pos > 0.9:
            score += 20
        elif bb_pos < 0.1:
            score -= 10

        if near_high:
            score += 15
        if near_low:
            score -= 10

        return max(0, min(100, score))

    def _score_volatility(self, features: Dict) -> float:
        """Volatilite skoru (0-100)."""
        vol_ratio = features.get("volatility_ratio", 1)
        atr_pct = features.get("atr_14_pct", 2)

        score = 50
        if vol_ratio > 1.5:
            score += 20
        elif vol_ratio < 0.5:
            score -= 10

        if atr_pct > 3:
            score += 10
        elif atr_pct < 1:
            score -= 10

        return max(0, min(100, score))

    def _score_relative_strength(self, features: Dict) -> float:
        """Göreceli güç skoru (0-100)."""
        mom5 = features.get("roc_5d", 0)
        mom20 = features.get("momentum_20d", 0)

        score = 50
        if mom5 > 5 and mom20 > 10:
            score += 30
        elif mom5 > 0 and mom20 > 0:
            score += 15
        elif mom5 < -5 and mom20 < -10:
            score -= 20

        return max(0, min(100, score))

    def _score_sector_divergence(self, features: Dict) -> float:
        """Sektör sapma skoru (0-100).
        Hisse kendi sektöründen pozitif sapma gösteriyorsa yüksek skor.
        Negatif sapma gösteriyorsa düşük skor.
        """
        score = 50.0

        # Sektöre göre relatif performans
        sector_rel = features.get("relative_strength_vs_sector", 0)
        sector_mom = features.get("sector_momentum", 0)
        price_vs_sma20 = features.get("price_vs_sma20", 0)
        roc_5d = features.get("roc_5d", 0)

        # Sektöre göre pozitif sapma
        if sector_rel > 3:
            score += min(sector_rel * 5, 25)
        elif sector_rel < -3:
            score += max(sector_rel * 5, -25)

        # Sektör momentumu + hisse momentumu uyumu
        if sector_mom > 0 and roc_5d > 0:
            # İkisi de pozitif → uyumlu, +10
            score += 10
        elif sector_mom < 0 and roc_5d > 0:
            # Sektör düşerken hisse çıkıyor → güçlü sapma, +15
            score += 15
        elif sector_mom > 0 and roc_5d < -3:
            # Sektör çıkarken hisse düşüyor → negatif sapma, -15
            score -= 15

        # SMA20'ye göre konum
        if price_vs_sma20 > 5:
            score += 5
        elif price_vs_sma20 < -5:
            score -= 5

        return max(0, min(100, score))

    def _score_flow_correlation(self, features: Dict) -> float:
        """Akış korelasyon skoru (0-100).
        Hacim-fiyat korelasyonunu ölçer.
        Yüksek hacim + yükseliş = pozitif akış (yüksek skor)
        Yüksek hacim + düşüş = negatşf akış (düşük skor)
        """
        score = 50.0

        vol_z = features.get("volume_zscore", 0)
        vol_ratio = features.get("volume_ratio_20d", 1)
        roc_1d = features.get("return_1d", 0)
        roc_5d = features.get("roc_5d", 0)

        # Hacim-fiyat korelasyonu
        # Pozitif korelasyon: hacim artarken fiyat da artıyor
        if vol_z > 1.5 and roc_1d > 0:
            score += min(vol_z * 8, 25)
        elif vol_z > 1.5 and roc_1d < -1:
            # Yüksek hacim + düşüş → satış baskısı
            score -= min(vol_z * 6, 20)
        elif vol_z < -1 and roc_1d > 0:
            # Düşük hacim + yükseliş → sürdürülebilir değil
            score -= 10

        # Hacim ratio + 5 günlük momentum uyumu
        if vol_ratio > 1.5 and roc_5d > 2:
            score += 10  # Hacim artıyor + momentum pozitif
        elif vol_ratio > 1.5 and roc_5d < -2:
            score -= 10  # Hacim artıyor + momentum negatif (dağıtım)
        elif vol_ratio < 0.7 and abs(roc_5d) < 1:
            score += 5   # Düşük hacim + sakin fiyat → birikim olabilir

        return max(0, min(100, score))

    def _score_liquidity(self, features: Dict) -> float:
        """Likidite skoru (0-100)."""
        vol = features.get("volume", 0)
        vol_ratio = features.get("volume_ratio_20d", 1)

        score = 50
        if vol > 1000000:
            score += 20
        elif vol < 100000:
            score -= 20

        if vol_ratio > 1.5:
            score += 10

        return max(0, min(100, score))

    # =====================================================
    # Rapor
    # =====================================================

    def get_tier_summary(self) -> Dict[str, Any]:
        """Tier bazlı özet."""
        tier_counts = {i: 0 for i in range(6)}
        for asset in self._assets.values():
            tier_counts[asset.current_tier] = tier_counts.get(asset.current_tier, 0) + 1

        return {
            "total_assets": len(self._assets),
            "tier_0_continuous": tier_counts.get(0, 0),
            "tier_1_quant": tier_counts.get(1, 0),
            "tier_2_opportunity": tier_counts.get(2, 0),
            "tier_3_deep": tier_counts.get(3, 0),
            "tier_4_gemma": tier_counts.get(4, 0),
            "tier_5_decision": tier_counts.get(5, 0),
            "regime": self._regime.regime,
            "regime_confidence": self._regime.confidence,
            "scan_count": self._scan_count,
        }

    def get_top_opportunities(self, n: int = 20) -> List[Dict]:
        """En iyi fırsatları döndür."""
        ranked = sorted(
            self._assets.values(),
            key=lambda a: a.opportunity_score,
            reverse=True,
        )

        return [{
            "ticker": a.ticker,
            "tier": a.current_tier,
            "opportunity_score": round(a.opportunity_score, 1),
            "momentum": round(a.momentum_score, 1),
            "volume_anomaly": round(a.volume_anomaly_score, 1),
            "breakout": round(a.breakout_score, 1),
            "volatility": round(a.volatility_score, 1),
            "relative_strength": round(a.relative_strength_score, 1),
            "price": a.price,
            "change_pct": round(a.price_change_pct, 2),
            "escalated": a.escalated_by_event,
        } for a in ranked[:n]]


# Singleton
tiered_scanner = TieredScanner()
