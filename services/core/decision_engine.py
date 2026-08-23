"""
ALPHA BIST — Decision Engine v2.0 (Düzeltilmiş)

ATR field'ı eklendi.
Stop-loss ve target hesaplaması ATR bazlı.

FAZ 8: Decision Engine
"""

import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import structlog

logger = structlog.get_logger()

class Action(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    NO_ACTION = "NO_ACTION"

@dataclass
class DecisionInput:
    """Karar motoru girdisi (ATR eklendi)."""
    ticker: str
    price: float
    features: Dict[str, Any] = field(default_factory=dict)
    signals: Dict[str, Any] = field(default_factory=dict)
    regime: str = "UNKNOWN"
    ml_score: float = 50.0
    ml_confidence: float = 0.5
    news_sentiment: float = 0.0
    sector: str = ""
    market_cap: float = 0.0
    # ATR bilgisi
    atr: float = 0.0
    atr_pct: float = 0.0
    # Agent sistemi
    agent_direction: str = "NEUTRAL"
    agent_confidence: float = 0.0
    agent_score: float = 50.0
    # Macro sistemi
    macro_regime: str = "UNKNOWN"
    macro_stance: float = 0.0  # -1.0 (negatif) ile +1.0 (pozitif)
    macro_confidence: float = 0.0
    macro_impact: float = 0.0  # Sektör bazlı makro etki
    # Geriye uyumlu ek alanlar (test_phase10_13)
    ml_return_5d: float = 0.0
    ml_return_20d: float = 0.0
    spec_score: float = 0.0
    world_alignment: float = 0.0
    sim_expected_return: float = 0.0
    sim_var_95: float = 0.0
    sim_prob_positive: float = 0.0
    ai_direction: str = "NEUTRAL"
    ai_confidence: float = 0.0
    max_position_pct: float = 10.0
    current_position_pct: float = 0.0
    portfolio_drawdown: float = 0.0
    avg_volume: float = 0.0
    spread_pct: float = 0.0

@dataclass
class Decision:
    """Karar çıktısı."""
    ticker: str
    action: str  # BUY, SELL, HOLD, NO_ACTION
    direction: str  # LONG, SHORT
    confidence: float
    score: float
    reasons: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    target_price: float = 0.0
    stop_price: float = 0.0
    position_size: float = 0.0
    time_horizon: str = "1-5D"
    expected_return: float = 0.0
    conviction: str = "LOW"  # Geriye uyumlu
    # LLM Ajan Türkçe Açıklama
    llm_narrative: str = ""  # LLM Agent tarafından üretilen karar özeti

class DecisionEngine:
    """Karar motoru."""

    # ATR olmadığında kullanılacak varsayılan stop yüzdesi
    DEFAULT_STOP_FALLBACK = 6.5  # %6.5 — BIST ortalaması için makul

    def __init__(self):
        self._min_confidence = 0.65
        self._min_score = 60.0
        logger.info("DecisionEngine initialized")

    def _get_dynamic_thresholds(self, regime: str) -> tuple[float, float]:
        """Piyasa rejimine göre dinamik skor ve güven eşikleri."""
        regime_upper = (regime or "").upper()
        if "BEAR" in regime_upper or "PANIC" in regime_upper or "CRASH" in regime_upper:
            return 68.0, 0.70  # Ayı piyasasında katı eşik (sermaye koruma)
        elif "VOLATILE" in regime_upper or "HIGH_VOL" in regime_upper or "SIDEWAYS" in regime_upper:
            return 63.0, 0.65  # Yatay/oynak piyasada seçici
        elif "BULL" in regime_upper or "TREND" in regime_upper:
            return 58.0, 0.60  # Boğa piyasasında trend takip
        return self._min_score, self._min_confidence

    def decide(self, inp: DecisionInput) -> Decision:
        """Karar ver."""

        # 1. Composite skor hesapla
        score = self._calculate_composite_score(inp)

        # 2. Rejime duyarlı dinamik eşik kontrolü
        min_score, min_conf = self._get_dynamic_thresholds(inp.regime)
        if score < min_score or inp.ml_confidence < min_conf:
            return Decision(
                ticker=inp.ticker,
                action="NO_ACTION",
                direction="NEUTRAL",
                confidence=inp.ml_confidence,
                score=score,
                reasons=[f"Skor ({score:.1f} < {min_score}) veya güven ({inp.ml_confidence:.2f} < {min_conf}) rejim eşiğinin altında ({inp.regime})"],
            )

        # 3. Yön belirle
        direction = self._determine_direction(inp)

        # 4. Action belirle
        action = self._determine_action(inp, direction)

        # 5. Stop ve target hesapla (ATR bazlı)
        stop_price, target_price = self._calculate_stop_and_target(inp, direction)

        # 6. Risk kontrolü
        risks = self._assess_risks(inp)

        # 7. Nedenler
        reasons = self._generate_reasons(inp, score)

        # Conviction belirle
        if score >= 80 and inp.ml_confidence >= 0.8:
            conviction = "HIGH"
        elif score >= 60 and inp.ml_confidence >= 0.65:
            conviction = "MEDIUM"
        else:
            conviction = "LOW"

        return Decision(
            ticker=inp.ticker,
            action=action,
            direction=direction,
            confidence=inp.ml_confidence,
            score=score,
            reasons=reasons,
            risks=risks,
            target_price=target_price,
            stop_price=stop_price,
            expected_return=self._calculate_expected_return(inp, direction),
            conviction=conviction,
        )

    def _calculate_composite_score(self, inp: DecisionInput) -> float:
        """Composite skor hesapla.

        Düzeltmeler (v2.1):
        1. max() yerine güven-ağırlıklı ortalama (optimistic bias kaldırıldı)
        2. ML return sinyalleri simetrik (pozitif VE negatif)
        3. Ağırlıklar toplamı = 1.0 garantisi
        """
        # ML skor: max() yerine güven-ağırlıklı ortalama
        # max() kullanmak systematic bullish bias yaratıyordu:
        # ml_score=40 (bearish) + spec_score=60 (bullish) → max(40, 54) = 54
        # Oysa her iki sinyal de dikkate alınmalı
        if inp.spec_score > 0:
            # Güven ağırlıklı ortalama: ml_confidence yüksekse ml_score'a daha çok güven
            ml_weight = max(inp.ml_confidence, 0.5)
            spec_weight = 1.0 - ml_weight
            ml_component = inp.ml_score * ml_weight + (inp.spec_score * 0.9) * spec_weight
        else:
            ml_component = inp.ml_score

        # Agent skor: agent_confidence > 0.5 ise ağırlık ver
        agent_component = inp.agent_score if inp.agent_confidence > 0.5 else 50.0

        components = {
            "ml_score": ml_component * 0.20,
            "agent": agent_component * 0.12,
            "technical": self._technical_score(inp) * 0.16,
            "fundamental": self._fundamental_score(inp) * 0.12,
            "sentiment": self._sentiment_score(inp) * 0.07,
            "regime": self._regime_score(inp) * 0.07,
            "macro": self._macro_score(inp) * 0.09,
            "risk": self._risk_score(inp) * 0.09,
            "monte_carlo": self._monte_carlo_score(inp) * 0.08,
        }

        total = sum(components.values())

        # ML return sinyalleri — SİMETRİK (pozitif VE negatif)
        # Eski kod sadece pozitif return'ler için bonus veriyordu → BUY bias
        if inp.ml_return_5d > 3:
            total += 5
        elif inp.ml_return_5d < -3:
            total -= 5

        if inp.ml_return_20d > 8:
            total += 5
        elif inp.ml_return_20d < -8:
            total -= 5

        # Monte Carlo bonus/ceza: sim_expected_return ve sim_prob_positive
        if inp.sim_expected_return > 0 and inp.sim_prob_positive > 0.6:
            total += 3  # Pozitif MC beklentisi bonus
        elif inp.sim_expected_return < 0 and inp.sim_prob_positive < 0.4:
            total -= 3  # Negatif MC beklentisi ceza

        return min(100, max(0, total))

    def _monte_carlo_score(self, inp: DecisionInput) -> float:
        """Monte Carlo simülasyon skoru.

        Düşük VaR (düşük risk) = yüksek skor, yüksek VaR = düşük skor.
        Pozitif expected return ve yüksek prob_positive bonus.
        """
        score = 50.0

        # sim_var_95: negatif getiri yüzdesi (örn -12.5 = %12.5 kayıp riski)
        # Daha düşük (daha az negatif) VaR = daha iyi
        if inp.sim_var_95 != 0:
            # VaR negatif gelir (kayıp); mutlak değeri ne kadar küçükse o kadar iyi
            var_abs = abs(inp.sim_var_95)
            if var_abs < 5:
                score += 15  # Düşük risk
            elif var_abs < 10:
                score += 5
            elif var_abs > 20:
                score -= 15  # Yüksek risk
            elif var_abs > 15:
                score -= 10

        # Expected return
        if inp.sim_expected_return > 3:
            score += 10
        elif inp.sim_expected_return > 0:
            score += 5
        elif inp.sim_expected_return < -3:
            score -= 10
        elif inp.sim_expected_return < 0:
            score -= 5

        # Prob positive
        if inp.sim_prob_positive > 0.7:
            score += 10
        elif inp.sim_prob_positive > 0.55:
            score += 5
        elif inp.sim_prob_positive < 0.3:
            score -= 10
        elif inp.sim_prob_positive < 0.45:
            score -= 5

        return min(100, max(0, score))

    def _technical_score(self, inp: DecisionInput) -> float:
        """Teknik skor."""
        f = inp.features
        score = 50.0

        momentum = f.get("momentum_20d", 0)
        roc = f.get("roc_5d", 0)
        rsi = f.get("rsi_14", 50)
        volume = f.get("volume_zscore", 0)
        bb = f.get("bb_position", 0.5)

        score += momentum * 0.3
        score += roc * 0.3
        score += (rsi - 50) * 0.2
        score += volume * 0.1
        score += (bb - 0.5) * 20

        return min(100, max(0, score))

    def _fundamental_score(self, inp: DecisionInput) -> float:
        """Fundamental skor."""
        f = inp.features
        score = 50.0

        fundamental = f.get("fundamental_score", 0)
        pe = f.get("pe_ratio", 15)
        pb = f.get("pb_ratio", 1.5)
        roe = f.get("roe", 0)

        score += fundamental * 0.4
        score += (20 - pe) * 1.0  # Düşük PE iyi
        score += (2 - pb) * 10.0  # Düşük PB iyi
        score += roe * 0.2

        return min(100, max(0, score))

    def _sentiment_score(self, inp: DecisionInput) -> float:
        """Sentiment skor."""
        sentiment = inp.news_sentiment
        return 50 + sentiment * 50  # -1 to 1 → 0 to 100

    def _regime_score(self, inp: DecisionInput) -> float:
        """Rejim skoru."""
        regime_scores = {
            "BULL": 80,
            "BULL_VOLATILE": 70,
            "BEAR": 30,
            "BEAR_VOLATILE": 25,
            "SIDEWAYS": 50,
            "SIDEWAYS_VOLATILE": 45,
            "RECOVERY": 65,
            "DISTRIBUTION": 35,
            "ACCUMULATION": 70,
            "CRASH": 20,
        }
        return regime_scores.get(inp.regime, 50)

    def _risk_score(self, inp: DecisionInput) -> float:
        """Risk skoru (yüksek = düşük risk = yüksek skor)."""
        f = inp.features
        score = 50.0

        # ATR bazlı risk (düşük ATR = düşük risk = yüksek skor)
        atr_pct = f.get("atr_pct", inp.atr_pct)
        if atr_pct > 0:
            score -= atr_pct * 2  # Yüksek volatilite = düşük skor

        # ADX (trend gücü)
        adx = f.get("adx", 25)
        score += (adx - 25) * 0.5

        # Volume (yüksek hacim = likidite = iyi)
        volume = f.get("volume_zscore", 0)
        score += volume * 0.5

        # Monte Carlo VaR_95 (düşük VaR = düşük risk = yüksek skor)
        if inp.sim_var_95 != 0:
            var_abs = abs(inp.sim_var_95)
            # VaR yüzdesi ne kadar düşükse risk o kadar düşük
            score += max(-15, min(10, (10 - var_abs) * 0.8))

        return min(100, max(0, score))

    def _macro_score(self, inp: DecisionInput) -> float:
        """Macro skor — makro rejim ve etki."""
        score = 50.0

        # Macro stance (pozitif = yukarı, negatif = aşağı)
        if inp.macro_stance != 0:
            score += inp.macro_stance * 20  # -20 ile +20 arası

        # Macro confidence (yüksek güven = daha güçlü sinyal)
        if inp.macro_confidence > 0.5:
            score += inp.macro_stance * 10  # Güvenli sinyalleri güçlendir

        # Macro impact (sektör bazlı etki)
        if inp.macro_impact != 0:
            score += inp.macro_impact * 15  # Düzeltme: 100→15, aşırı skor bozulması önlendi

        # Macro regime bonusları
        regime_bonuses = {
            "EXPANSION": 5,
            "RISK_ON": 5,
            "CONTRACTION": -5,
            "STAGFLATION": -10,
            "RISK_OFF": -8,
            "REFLATION": 0,
        }
        score += regime_bonuses.get(inp.macro_regime, 0)

        return min(100, max(0, score))

    def _determine_direction(self, inp: DecisionInput) -> str:
        """Yön belirle.

        Düzeltme (v2.1): Eşikler simetrik yapıldı.
        Eski: RSI > 55 / < 45 (10 puan gap), ML > 60 / < 40 (20 puan gap)
        Yeni: RSI > 52 / < 48 (4 puan gap), ML > 55 / < 45 (10 puan gap)
        Neden: Asimetrik eşikler BUY bias yaratıyordu.
        """
        f = inp.features

        momentum = f.get("momentum_20d", 0)
        roc = f.get("roc_5d", 0)
        rsi = f.get("rsi_14", 50)

        # SİMETRİK eşikler (BUY bias kaldırıldı)
        bullish_signals = sum([
            momentum > 0,
            roc > 0,
            rsi > 52,   # Eski: 55 → Yeni: 52 (simetrik)
            inp.ml_score > 55,  # Eski: 60 → Yeni: 55 (simetrik)
        ])

        bearish_signals = sum([
            momentum < 0,
            roc < 0,
            rsi < 48,   # Eski: 45 → Yeni: 48 (simetrik)
            inp.ml_score < 45,  # Eski: 40 → Yeni: 45 (simetrik)
        ])

        if bullish_signals >= 3:
            return "LONG"
        elif bearish_signals >= 3:
            return "SHORT"

        return "HOLD"

    def _determine_action(self, inp: DecisionInput, direction: str) -> str:
        """Action belirle."""
        if inp.ml_confidence < self._min_confidence:
            return "NO_ACTION"

        if direction == "LONG":
            return "BUY"
        elif direction == "SHORT":
            return "SELL"

        return "HOLD"

    def _calculate_stop_and_target(self, inp: DecisionInput, direction: str) -> tuple:
        """Stop ve target hesapla (ATR bazlı)."""
        price = inp.price
        atr = inp.atr
        atr_pct = inp.atr_pct

        if price <= 0:
            return 0, 0

        # ATR bazlı stop mesafesi (Canonical Strateji Parametreleri: frozen_strategy_engine.py ile senkronize)
        if atr > 0:
            stop_distance = atr * 2.5  # Canonical: 2.5x ATR
            stop_pct = (stop_distance / price) * 100
        elif atr_pct > 0:
            stop_pct = atr_pct * 1.5
        else:
            stop_pct = self.DEFAULT_STOP_FALLBACK  # Config'den okunabilir

        # Sınırla: min %4.0 (min_atr_pct), max %10.0
        stop_pct = max(4.0, min(10.0, stop_pct))

        # Risk/Ödül oranı 1:2
        target_pct = stop_pct * 2.0

        if direction == "LONG":
            stop_price = price * (1 - stop_pct / 100)
            target_price = price * (1 + target_pct / 100)
        elif direction == "SHORT":
            stop_price = price * (1 + stop_pct / 100)
            target_price = price * (1 - target_pct / 100)
        else:
            return 0.0, 0.0

        return round(stop_price, 2), round(target_price, 2)

    def _assess_risks(self, inp: DecisionInput) -> List[str]:
        """Risk değerlendirmesi."""
        risks = []
        f = inp.features

        if f.get("atr_pct", inp.atr_pct) > 5:
            risks.append("Yüksek volatilite")

        if f.get("rsi_14", 50) > 80 or f.get("rsi_14", 50) < 20:
            risks.append("Aşırı alım/satım (RSI)")

        if inp.news_sentiment < -0.5:
            risks.append("Negatif haber sentimenti")

        if inp.ml_confidence < 0.75:
            risks.append("Düşük model güveni")

        # Monte Carlo risk metrikleri
        if inp.sim_var_95 != 0 and abs(inp.sim_var_95) > 15:
            risks.append(f"MC VaR yüksek: %{abs(inp.sim_var_95):.1f}")

        if inp.sim_prob_positive < 0.35:
            risks.append(f"MC olasılık düşük: %{inp.sim_prob_positive * 100:.0f}")

        if inp.sim_expected_return < -5:
            risks.append(f"MC beklenen getiri negatif: %{inp.sim_expected_return:.1f}")

        if not risks:
            risks.append("Düşük risk profili")

        return risks

    def _generate_reasons(self, inp: DecisionInput, score: float) -> List[str]:
        """Karar nedenleri."""
        reasons = []
        f = inp.features

        if f.get("momentum_20d", 0) > 5:
            reasons.append("Güçlü momentum")

        if f.get("roc_5d", 0) > 3:
            reasons.append("Pozitif kısa vadeli getiri")

        if f.get("volume_zscore", 0) > 1:
            reasons.append("Yüksek hacim onayı")

        if inp.news_sentiment > 0.3:
            reasons.append("Pozitif haber sentimenti")

        if score > 80:
            reasons.append("Çok yüksek composite skor")

        if not reasons:
            reasons.append("Teknik ve temel göstergeler uyumlu")

        return reasons

    def _calculate_expected_return(self, inp: DecisionInput, direction: str) -> float:
        """Çok kaynaklı harmanlanmış beklenen getiri hesapla."""
        if direction not in ("LONG", "SHORT"):
            return 0.0

        f = inp.features
        raw_momentum = (f.get("momentum_20d", 0) + f.get("roc_5d", 0)) / 2.0

        # Eğer ML ve Monte Carlo modelleri tahmin üretmişse bunları ağırlıklandır
        if inp.ml_return_5d != 0 or inp.sim_expected_return != 0:
            expected = (raw_momentum * 0.3) + (inp.ml_return_5d * 0.4) + (inp.sim_expected_return * 0.3)
        else:
            expected = raw_momentum

        if direction == "SHORT":
            expected = -abs(expected) if expected > 0 else expected
        elif direction == "LONG":
            expected = abs(expected) if expected < 0 and raw_momentum > 0 else expected

        return round(float(expected), 2)

    def decide_from_canonical(self, score, price: float = 0):
        """CanonicalScore'tan karar üret.

        Bu, tek canonical karar noktasıdır.
        Ranking, scoring, risk burada birleşir.

        Args:
            score: CanonicalScore instance
            price: Güncel fiyat (stop/target hesaplama için)
        """
        from services.core.canonical_scoring import CanonicalScore

        if not isinstance(score, CanonicalScore):
            raise TypeError(f"Expected CanonicalScore, got {type(score)}")

        # Eşik kontrolü
        if score.confidence < self._min_confidence:
            return Decision(
                ticker=score.ticker,
                action="NO_ACTION",
                direction="NEUTRAL",
                confidence=score.confidence,
                score=score.opportunity_score,
                reasons=[f"Confidence çok düşük: {score.confidence:.2f} < {self._min_confidence}"],
            )

        if score.opportunity_score < self._min_score:
            return Decision(
                ticker=score.ticker,
                action="NO_ACTION",
                direction="NEUTRAL",
                confidence=score.confidence,
                score=score.opportunity_score,
                reasons=[f"Skor eşik altında: {score.opportunity_score:.1f} < {self._min_score}"],
            )

        # Yön ve action
        direction = score.direction
        if direction == "NEUTRAL":
            action = "HOLD"
        elif direction == "LONG":
            action = "BUY"
        else:
            action = "SELL"

        # Risk kontrolü — risk_score düşükse pozisyon küçült veya engelle
        if score.risk_score < 30:
            if action in ("BUY", "SELL"):
                action = "HOLD"  # Çok riskli — pozisyon açma
                direction = "NEUTRAL"

        # Stop ve Target hesaplama (price verilmişse)
        stop_price = 0.0
        target_price = 0.0
        if price > 0 and action in ("BUY", "SELL"):
            stop_pct = self.DEFAULT_STOP_FALLBACK
            target_pct = stop_pct * 2.0
            if direction == "LONG":
                stop_price = round(price * (1 - stop_pct / 100), 2)
                target_price = round(price * (1 + target_pct / 100), 2)
            elif direction == "SHORT":
                stop_price = round(price * (1 + stop_pct / 100), 2)
                target_price = round(price * (1 - target_pct / 100), 2)

        # Conviction
        if score.opportunity_score >= 80 and score.confidence >= 0.8:
            conviction = "HIGH"
        elif score.opportunity_score >= 65 and score.confidence >= 0.65:
            conviction = "MEDIUM"
        else:
            conviction = "LOW"

        # Nedenler
        reasons = []
        v = score.vector
        if v.momentum > 65:
            reasons.append(f"Momentum güçlü: {v.momentum:.0f}")
        if v.relative_strength > 65:
            reasons.append(f"Relatif güç yüksek: {v.relative_strength:.0f}")
        if v.fundamental > 65:
            reasons.append(f"Fundamental pozitif: {v.fundamental:.0f}")
        if v.news_sentiment > 65:
            reasons.append(f"Sentiment olumlu: {v.news_sentiment:.0f}")
        if v.catalyst > 65:
            reasons.append(f"Katalizör var: {v.catalyst:.0f}")
        if v.mean_reversion > 65:
            reasons.append(f"Mean reversion fırsatı: {v.mean_reversion:.0f}")
        if not reasons:
            reasons.append("Genel skor eşiği aşıldı")

        # Riskler
        risks = []
        if v.risk < 40:
            risks.append(f"Yüksek risk: {v.risk:.0f}")
        if v.data_quality < 60:
            risks.append(f"Düşük veri kalitesi: {v.data_quality:.0f}")
        if v.momentum < 35:
            risks.append(f"Momentum zayıf: {v.momentum:.0f}")
        if not risks:
            risks.append("Belirgin risk tespit edilmedi")

        return Decision(
            ticker=score.ticker,
            action=action,
            direction=direction,
            confidence=score.confidence,
            score=score.opportunity_score,
            reasons=reasons,
            risks=risks,
            stop_price=stop_price,
            target_price=target_price,
            conviction=conviction,
        )


# Singleton
decision_engine = DecisionEngine()
