"""
ALPHA BIST â€” Decision Engine v2.0 (DÃ¼zeltilmiÅŸ)

ATR field'Ä± eklendi.
Stop-loss ve target hesaplamasÄ± ATR bazlÄ±.

FAZ 8: Decision Engine
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


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
    features: dict[str, Any] = field(default_factory=dict)
    signals: dict[str, Any] = field(default_factory=dict)
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
    macro_impact: float = 0.0  # SektÃ¶r bazlÄ± makro etki
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
    """Karar Ã§Ä±ktÄ±sÄ±."""

    ticker: str
    action: str  # BUY, SELL, HOLD, NO_ACTION
    direction: str  # LONG, SHORT
    confidence: float
    score: float
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    target_price: float = 0.0
    stop_price: float = 0.0
    position_size: float = 0.0
    time_horizon: str = "1-5D"
    expected_return: float = 0.0
    conviction: str = "LOW"  # Geriye uyumlu
    # LLM Ajan TÃ¼rkÃ§e AÃ§Ä±klama
    llm_narrative: str = ""  # LLM Agent tarafÄ±ndan Ã¼retilen karar Ã¶zeti


class DecisionEngine:
    """Karar motoru."""

    # ATR olmadÄ±ÄŸÄ±nda kullanÄ±lacak varsayÄ±lan stop yÃ¼zdesi
    DEFAULT_STOP_FALLBACK = 6.5  # %6.5 â€” BIST ortalamasÄ± iÃ§in makul

    def __init__(self):
        self._min_confidence = 0.65
        self._min_score = 60.0
        logger.info("DecisionEngine initialized")

    def _get_dynamic_thresholds(self, regime: str) -> tuple[float, float]:
        """Piyasa rejimine gÃ¶re dinamik skor ve gÃ¼ven eÅŸikleri."""
        regime_upper = (regime or "").upper()
        if "BEAR" in regime_upper or "PANIC" in regime_upper or "CRASH" in regime_upper:
            return 68.0, 0.70  # AyÄ± piyasasÄ±nda katÄ± eÅŸik (sermaye koruma)
        elif "VOLATILE" in regime_upper or "HIGH_VOL" in regime_upper or "SIDEWAYS" in regime_upper:
            return 63.0, 0.65  # Yatay/oynak piyasada seÃ§ici
        elif "BULL" in regime_upper or "TREND" in regime_upper:
            return 58.0, 0.60  # BoÄŸa piyasasÄ±nda trend takip
        return self._min_score, self._min_confidence

    def decide(self, inp: DecisionInput) -> Decision:
        """Karar ver."""

        # 1. Composite skor hesapla
        score = self._calculate_composite_score(inp)

        # 2. Rejime duyarlÄ± dinamik eÅŸik kontrolÃ¼
        min_score, min_conf = self._get_dynamic_thresholds(inp.regime)
        if score < min_score or inp.ml_confidence < min_conf:
            return Decision(
                ticker=inp.ticker,
                action="NO_ACTION",
                direction="NEUTRAL",
                confidence=inp.ml_confidence,
                score=score,
                reasons=[
                    f"Skor ({score:.1f} < {min_score}) veya gÃ¼ven ({inp.ml_confidence:.2f} < {min_conf}) rejim eÅŸiÄŸinin altÄ±nda ({inp.regime})"
                ],
            )

        # 3. YÃ¶n belirle
        direction = self._determine_direction(inp)

        # 4. Action belirle
        action = self._determine_action(inp, direction)

        # 5. Stop ve target hesapla (ATR bazlÄ±)
        stop_price, target_price = self._calculate_stop_and_target(inp, direction)

        # 6. Risk kontrolÃ¼
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

        DÃ¼zeltmeler (v2.1):
        1. max() yerine gÃ¼ven-aÄŸÄ±rlÄ±klÄ± ortalama (optimistic bias kaldÄ±rÄ±ldÄ±)
        2. ML return sinyalleri simetrik (pozitif VE negatif)
        3. AÄŸÄ±rlÄ±klar toplamÄ± = 1.0 garantisi
        """
        # ML skor: max() yerine gÃ¼ven-aÄŸÄ±rlÄ±klÄ± ortalama
        # max() kullanmak systematic bullish bias yaratÄ±yordu:
        # ml_score=40 (bearish) + spec_score=60 (bullish) â†’ max(40, 54) = 54
        # Oysa her iki sinyal de dikkate alÄ±nmalÄ±
        if inp.spec_score > 0:
            # GÃ¼ven aÄŸÄ±rlÄ±klÄ± ortalama: ml_confidence yÃ¼ksekse ml_score'a daha Ã§ok gÃ¼ven
            ml_weight = max(inp.ml_confidence, 0.5)
            spec_weight = 1.0 - ml_weight
            ml_component = inp.ml_score * ml_weight + (inp.spec_score * 0.9) * spec_weight
        else:
            ml_component = inp.ml_score

        # Agent skor: agent_confidence > 0.5 ise aÄŸÄ±rlÄ±k ver
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

        # ML return sinyalleri â€” SÄ°METRÄ°K (pozitif VE negatif)
        # Eski kod sadece pozitif return'ler iÃ§in bonus veriyordu â†’ BUY bias
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
        """Monte Carlo simÃ¼lasyon skoru.

        DÃ¼ÅŸÃ¼k VaR (dÃ¼ÅŸÃ¼k risk) = yÃ¼ksek skor, yÃ¼ksek VaR = dÃ¼ÅŸÃ¼k skor.
        Pozitif expected return ve yÃ¼ksek prob_positive bonus.
        """
        score = 50.0

        # sim_var_95: negatif getiri yÃ¼zdesi (Ã¶rn -12.5 = %12.5 kayÄ±p riski)
        # Daha dÃ¼ÅŸÃ¼k (daha az negatif) VaR = daha iyi
        if inp.sim_var_95 != 0:
            # VaR negatif gelir (kayÄ±p); mutlak deÄŸeri ne kadar kÃ¼Ã§Ã¼kse o kadar iyi
            var_abs = abs(inp.sim_var_95)
            if var_abs < 5:
                score += 15  # DÃ¼ÅŸÃ¼k risk
            elif var_abs < 10:
                score += 5
            elif var_abs > 20:
                score -= 15  # YÃ¼ksek risk
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
        score += (20 - pe) * 1.0  # DÃ¼ÅŸÃ¼k PE iyi
        score += (2 - pb) * 10.0  # DÃ¼ÅŸÃ¼k PB iyi
        score += roe * 0.2

        return min(100, max(0, score))

    def _sentiment_score(self, inp: DecisionInput) -> float:
        """Sentiment skor."""
        sentiment = inp.news_sentiment
        return 50 + sentiment * 50  # -1 to 1 â†’ 0 to 100

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
        """Risk skoru (yÃ¼ksek = dÃ¼ÅŸÃ¼k risk = yÃ¼ksek skor)."""
        f = inp.features
        score = 50.0

        # ATR bazlÄ± risk (dÃ¼ÅŸÃ¼k ATR = dÃ¼ÅŸÃ¼k risk = yÃ¼ksek skor)
        atr_pct = f.get("atr_pct", inp.atr_pct)
        if atr_pct > 0:
            score -= atr_pct * 2  # YÃ¼ksek volatilite = dÃ¼ÅŸÃ¼k skor

        # ADX (trend gÃ¼cÃ¼)
        adx = f.get("adx", 25)
        score += (adx - 25) * 0.5

        # Volume (yÃ¼ksek hacim = likidite = iyi)
        volume = f.get("volume_zscore", 0)
        score += volume * 0.5

        # Monte Carlo VaR_95 (dÃ¼ÅŸÃ¼k VaR = dÃ¼ÅŸÃ¼k risk = yÃ¼ksek skor)
        if inp.sim_var_95 != 0:
            var_abs = abs(inp.sim_var_95)
            # VaR yÃ¼zdesi ne kadar dÃ¼ÅŸÃ¼kse risk o kadar dÃ¼ÅŸÃ¼k
            score += max(-15, min(10, (10 - var_abs) * 0.8))

        return min(100, max(0, score))

    def _macro_score(self, inp: DecisionInput) -> float:
        """Macro skor â€” makro rejim ve etki."""
        score = 50.0

        # Macro stance (pozitif = yukarÄ±, negatif = aÅŸaÄŸÄ±)
        if inp.macro_stance != 0:
            score += inp.macro_stance * 20  # -20 ile +20 arasÄ±

        # Macro confidence (yÃ¼ksek gÃ¼ven = daha gÃ¼Ã§lÃ¼ sinyal)
        if inp.macro_confidence > 0.5:
            score += inp.macro_stance * 10  # GÃ¼venli sinyalleri gÃ¼Ã§lendir

        # Macro impact (sektÃ¶r bazlÄ± etki)
        if inp.macro_impact != 0:
            score += inp.macro_impact * 15  # DÃ¼zeltme: 100â†’15, aÅŸÄ±rÄ± skor bozulmasÄ± Ã¶nlendi

        # Macro regime bonuslarÄ±
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
        """YÃ¶n belirle.

        DÃ¼zeltme (v2.1): EÅŸikler simetrik yapÄ±ldÄ±.
        Eski: RSI > 55 / < 45 (10 puan gap), ML > 60 / < 40 (20 puan gap)
        Yeni: RSI > 52 / < 48 (4 puan gap), ML > 55 / < 45 (10 puan gap)
        Neden: Asimetrik eÅŸikler BUY bias yaratÄ±yordu.
        """
        f = inp.features

        momentum = f.get("momentum_20d", 0)
        roc = f.get("roc_5d", 0)
        rsi = f.get("rsi_14", 50)

        # SÄ°METRÄ°K eÅŸikler (BUY bias kaldÄ±rÄ±ldÄ±)
        bullish_signals = sum(
            [
                momentum > 0,
                roc > 0,
                rsi > 52,  # Eski: 55 â†’ Yeni: 52 (simetrik)
                inp.ml_score > 55,  # Eski: 60 â†’ Yeni: 55 (simetrik)
            ]
        )

        bearish_signals = sum(
            [
                momentum < 0,
                roc < 0,
                rsi < 48,  # Eski: 45 â†’ Yeni: 48 (simetrik)
                inp.ml_score < 45,  # Eski: 40 â†’ Yeni: 45 (simetrik)
            ]
        )

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
        """Stop ve target hesapla (ATR bazlÄ±)."""
        price = inp.price
        atr = inp.atr
        atr_pct = inp.atr_pct

        if price <= 0:
            return 0, 0

        # ATR bazlÄ± stop mesafesi (Canonical Strateji Parametreleri: frozen_strategy_engine.py ile senkronize)
        if atr > 0:
            stop_distance = atr * 2.5  # Canonical: 2.5x ATR
            stop_pct = (stop_distance / price) * 100
        elif atr_pct > 0:
            stop_pct = atr_pct * 1.5
        else:
            stop_pct = self.DEFAULT_STOP_FALLBACK  # Config'den okunabilir

        # SÄ±nÄ±rla: min %4.0 (min_atr_pct), max %10.0
        stop_pct = max(4.0, min(10.0, stop_pct))

        # Risk/Ã–dÃ¼l oranÄ± 1:2
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

    def _assess_risks(self, inp: DecisionInput) -> list[str]:
        """Risk deÄŸerlendirmesi."""
        risks = []
        f = inp.features

        if f.get("atr_pct", inp.atr_pct) > 5:
            risks.append("YÃ¼ksek volatilite")

        if f.get("rsi_14", 50) > 80 or f.get("rsi_14", 50) < 20:
            risks.append("AÅŸÄ±rÄ± alÄ±m/satÄ±m (RSI)")

        if inp.news_sentiment < -0.5:
            risks.append("Negatif haber sentimenti")

        if inp.ml_confidence < 0.75:
            risks.append("DÃ¼ÅŸÃ¼k model gÃ¼veni")

        # Monte Carlo risk metrikleri
        if inp.sim_var_95 != 0 and abs(inp.sim_var_95) > 15:
            risks.append(f"MC VaR yÃ¼ksek: %{abs(inp.sim_var_95):.1f}")

        if inp.sim_prob_positive < 0.35:
            risks.append(f"MC olasÄ±lÄ±k dÃ¼ÅŸÃ¼k: %{inp.sim_prob_positive * 100:.0f}")

        if inp.sim_expected_return < -5:
            risks.append(f"MC beklenen getiri negatif: %{inp.sim_expected_return:.1f}")

        if not risks:
            risks.append("DÃ¼ÅŸÃ¼k risk profili")

        return risks

    def _generate_reasons(self, inp: DecisionInput, score: float) -> list[str]:
        """Karar nedenleri."""
        reasons = []
        f = inp.features

        if f.get("momentum_20d", 0) > 5:
            reasons.append("GÃ¼Ã§lÃ¼ momentum")

        if f.get("roc_5d", 0) > 3:
            reasons.append("Pozitif kÄ±sa vadeli getiri")

        if f.get("volume_zscore", 0) > 1:
            reasons.append("YÃ¼ksek hacim onayÄ±")

        if inp.news_sentiment > 0.3:
            reasons.append("Pozitif haber sentimenti")

        if score > 80:
            reasons.append("Ã‡ok yÃ¼ksek composite skor")

        if not reasons:
            reasons.append("Teknik ve temel gÃ¶stergeler uyumlu")

        return reasons

    def _calculate_expected_return(self, inp: DecisionInput, direction: str) -> float:
        """Ã‡ok kaynaklÄ± harmanlanmÄ±ÅŸ beklenen getiri hesapla."""
        if direction not in ("LONG", "SHORT"):
            return 0.0

        f = inp.features
        raw_momentum = (f.get("momentum_20d", 0) + f.get("roc_5d", 0)) / 2.0

        # EÄŸer ML ve Monte Carlo modelleri tahmin Ã¼retmiÅŸse bunlarÄ± aÄŸÄ±rlÄ±klandÄ±r
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
        """CanonicalScore'tan karar Ã¼ret.

        Bu, tek canonical karar noktasÄ±dÄ±r.
        Ranking, scoring, risk burada birleÅŸir.

        Args:
            score: CanonicalScore instance
            price: GÃ¼ncel fiyat (stop/target hesaplama iÃ§in)
        """
        from services.core.canonical_scoring import CanonicalScore

        if not isinstance(score, CanonicalScore):
            raise TypeError(f"Expected CanonicalScore, got {type(score)}")

        # EÅŸik kontrolÃ¼
        if score.confidence < self._min_confidence:
            return Decision(
                ticker=score.ticker,
                action="NO_ACTION",
                direction="NEUTRAL",
                confidence=score.confidence,
                score=score.opportunity_score,
                reasons=[f"Confidence Ã§ok dÃ¼ÅŸÃ¼k: {score.confidence:.2f} < {self._min_confidence}"],
            )

        if score.opportunity_score < self._min_score:
            return Decision(
                ticker=score.ticker,
                action="NO_ACTION",
                direction="NEUTRAL",
                confidence=score.confidence,
                score=score.opportunity_score,
                reasons=[f"Skor eÅŸik altÄ±nda: {score.opportunity_score:.1f} < {self._min_score}"],
            )

        # YÃ¶n ve action
        direction = score.direction
        if direction == "NEUTRAL":
            action = "HOLD"
        elif direction == "LONG":
            action = "BUY"
        else:
            action = "SELL"

        # Risk kontrolÃ¼ â€” risk_score dÃ¼ÅŸÃ¼kse pozisyon kÃ¼Ã§Ã¼lt veya engelle
        if score.risk_score < 30 and action in ("BUY", "SELL"):
            action = "HOLD"  # Ã‡ok riskli â€” pozisyon aÃ§ma
            direction = "NEUTRAL"

        # Stop ve Target hesaplama (price verilmiÅŸse â€” ATR bazlÄ±)
        stop_price = 0.0
        target_price = 0.0
        if price > 0 and action in ("BUY", "SELL"):
            # ATR varsa kullan, yoksa fallback
            atr = score.vector.__dict__.get("atr", 0) if hasattr(score.vector, "__dict__") else 0
            atr_pct = score.vector.__dict__.get("atr_pct", 0) if hasattr(score.vector, "__dict__") else 0
            if atr and atr > 0:
                stop_distance = atr * 2.5
                stop_pct = (stop_distance / price) * 100
            elif atr_pct and atr_pct > 0:
                stop_pct = atr_pct * 1.5
            else:
                stop_pct = self.DEFAULT_STOP_FALLBACK
            stop_pct = max(4.0, min(10.0, stop_pct))
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
            reasons.append(f"Momentum gÃ¼Ã§lÃ¼: {v.momentum:.0f}")
        if v.relative_strength > 65:
            reasons.append(f"Relatif gÃ¼Ã§ yÃ¼ksek: {v.relative_strength:.0f}")
        if v.fundamental > 65:
            reasons.append(f"Fundamental pozitif: {v.fundamental:.0f}")
        if v.news_sentiment > 65:
            reasons.append(f"Sentiment olumlu: {v.news_sentiment:.0f}")
        if v.catalyst > 65:
            reasons.append(f"KatalizÃ¶r var: {v.catalyst:.0f}")
        if v.mean_reversion > 65:
            reasons.append(f"Mean reversion fÄ±rsatÄ±: {v.mean_reversion:.0f}")
        if not reasons:
            reasons.append("Genel skor eÅŸiÄŸi aÅŸÄ±ldÄ±")

        # Riskler
        risks = []
        if v.risk < 40:
            risks.append(f"YÃ¼ksek risk: {v.risk:.0f}")
        if v.data_quality < 60:
            risks.append(f"DÃ¼ÅŸÃ¼k veri kalitesi: {v.data_quality:.0f}")
        if v.momentum < 35:
            risks.append(f"Momentum zayÄ±f: {v.momentum:.0f}")
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

