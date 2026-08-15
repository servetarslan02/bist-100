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
    features: Dict[str, Any]
    signals: Dict[str, Any]
    regime: str
    ml_score: float
    ml_confidence: float
    news_sentiment: float
    sector: str
    market_cap: float
    # YENİ: ATR bilgisi
    atr: float = 0.0
    atr_pct: float = 0.0

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

class DecisionEngine:
    """Karar motoru."""

    def __init__(self):
        self._min_confidence = 0.65
        self._min_score = 60.0
        logger.info("DecisionEngine initialized")

    def decide(self, inp: DecisionInput) -> Decision:
        """Karar ver."""

        # 1. Composite skor hesapla
        score = self._calculate_composite_score(inp)

        # 2. Eşik kontrolü
        if score < self._min_score or inp.ml_confidence < self._min_confidence:
            return Decision(
                ticker=inp.ticker,
                action="NO_ACTION",
                direction="NEUTRAL",
                confidence=inp.ml_confidence,
                score=score,
                reasons=["Skor veya güven eşiğinin altında"],
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
        )

    def _calculate_composite_score(self, inp: DecisionInput) -> float:
        """Composite skor hesapla."""
        components = {
            "ml_score": inp.ml_score * 0.30,
            "technical": self._technical_score(inp) * 0.25,
            "fundamental": self._fundamental_score(inp) * 0.15,
            "sentiment": self._sentiment_score(inp) * 0.10,
            "regime": self._regime_score(inp) * 0.10,
            "risk": self._risk_score(inp) * 0.10,
        }

        total = sum(components.values())
        return min(100, max(0, total))

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

        return min(100, max(0, score))

    def _determine_direction(self, inp: DecisionInput) -> str:
        """Yön belirle."""
        f = inp.features

        momentum = f.get("momentum_20d", 0)
        roc = f.get("roc_5d", 0)
        rsi = f.get("rsi_14", 50)

        bullish_signals = sum([
            momentum > 0,
            roc > 0,
            rsi > 55,
            inp.ml_score > 60,
        ])

        bearish_signals = sum([
            momentum < 0,
            roc < 0,
            rsi < 45,
            inp.ml_score < 40,
        ])

        if bullish_signals >= 3:
            return "LONG"
        elif bearish_signals >= 3:
            return "SHORT"

        return "LONG" if inp.ml_score > 50 else "SHORT"

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

        # ATR bazlı stop mesafesi
        if atr > 0:
            stop_distance = atr * 2.0  # 2x ATR
            stop_pct = (stop_distance / price) * 100
        elif atr_pct > 0:
            stop_pct = atr_pct * 1.5
        else:
            stop_pct = 5.0  # Fallback %5

        # Sınırla: min %3, max %10
        stop_pct = max(3.0, min(10.0, stop_pct))

        # Risk/Ödül oranı 1:2
        target_pct = stop_pct * 2.0

        if direction == "LONG":
            stop_price = price * (1 - stop_pct / 100)
            target_price = price * (1 + target_pct / 100)
        else:
            stop_price = price * (1 + stop_pct / 100)
            target_price = price * (1 - target_pct / 100)

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
        """Beklenen getiri."""
        f = inp.features

        # Basit beklenti: momentum + ROC ortalaması
        expected = (f.get("momentum_20d", 0) + f.get("roc_5d", 0)) / 2

        if direction == "SHORT":
            expected = -expected

        return round(expected, 2)

# Singleton
decision_engine = DecisionEngine()
