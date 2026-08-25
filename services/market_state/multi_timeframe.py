"""ALPHA BIST — Multi-Timeframe State Engine v2.0

Çoklu zaman ufku market state hesaplaması:
- Intraday (15 dakikalık)
- Daily (günlük)
- Weekly (haftalık)
- Monthly (aylık)

Cross-timeframe divergence detection:
- Farklı zaman ufuklarında farklı rejim → uyarı
- Alignment score (uyum skoru)
"""

import numpy as np
from typing import Dict, List, Any
from datetime import datetime, timezone
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class TimeframeState:
    """Tek bir timeframe için market state."""
    timeframe: str              # intraday / daily / weekly / monthly
    regime: str = "UNKNOWN"
    confidence: float = 0.0
    breadth_pct: float = 50.0
    momentum: float = 0.0
    volatility: float = 0.0
    risk_appetite: float = 0.5
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "regime": self.regime,
            "confidence": round(self.confidence, 4),
            "breadth_pct": round(self.breadth_pct, 2),
            "momentum": round(self.momentum, 4),
            "volatility": round(self.volatility, 4),
            "risk_appetite": round(self.risk_appetite, 4),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class MultiTimeframeResult:
    """Çoklu timeframe sonucu."""
    states: Dict[str, TimeframeState] = field(default_factory=dict)
    alignment_score: float = 1.0            # 1 = tam uyum, 0 = tam çelişki
    divergences: List[str] = field(default_factory=list)
    dominant_timeframe: str = "daily"       # En güvenilir timeframe

    def to_dict(self) -> Dict[str, Any]:
        return {
            "states": {tf: s.to_dict() for tf, s in self.states.items()},
            "alignment_score": round(self.alignment_score, 4),
            "divergences": self.divergences,
            "dominant_timeframe": self.dominant_timeframe,
        }


class MultiTimeframeEngine:
    """Çoklu zaman ufku market state engine.

    Her timeframe için ayrı state hesaplar ve
    cross-timeframe divergence tespit eder.

    Kullanım:
        engine = MultiTimeframeEngine()
        result = engine.compute_all_timeframes(data_by_timeframe)
    """

    TIMEFRAMES = ["intraday", "daily", "weekly", "monthly"]

    def compute_all_timeframes(
        self,
        data_by_timeframe: Dict[str, Dict],
    ) -> MultiTimeframeResult:
        """Her timeframe için market state hesapla.

        Args:
            data_by_timeframe: Her timeframe için veri dict'i
                {
                    "intraday": {instruments: [...], features: {...}},
                    "daily": {instruments: [...], features: {...}},
                    "weekly": {instruments: [...], features: {...}},
                    "monthly": {instruments: [...], features: {...}},
                }

        Returns:
            MultiTimeframeResult
        """
        states = {}

        for tf in self.TIMEFRAMES:
            tf_data = data_by_timeframe.get(tf)
            if tf_data:
                state = self._compute_timeframe_state(tf, tf_data)
                states[tf] = state

        # Cross-timeframe divergence
        divergences = self._detect_divergences(states)

        # Alignment score
        alignment = self._compute_alignment(states)

        # Dominant timeframe (en yüksek confidence)
        dominant = self._find_dominant(states)

        result = MultiTimeframeResult(
            states=states,
            alignment_score=alignment,
            divergences=divergences,
            dominant_timeframe=dominant,
        )

        if divergences:
            logger.warning(
                "Timeframe divergences detected",
                divergences=divergences,
                alignment=round(alignment, 3),
            )

        return result

    def _compute_timeframe_state(
        self,
        timeframe: str,
        data: Dict,
    ) -> TimeframeState:
        """Tek bir timeframe için state hesapla."""
        instruments = data.get("instruments", [])
        data.get("features", {})

        if not instruments:
            return TimeframeState(timeframe=timeframe)

        # Temel istatistikler
        changes = [s.get("change_pct", 0) for s in instruments]
        momentums = [s.get("momentum", 0) for s in instruments if s.get("momentum") is not None]
        volatilities = [s.get("volatility", 0) for s in instruments if s.get("volatility") is not None]

        breadth_pct = sum(1 for c in changes if c > 0) / max(len(changes), 1) * 100
        avg_momentum = float(np.mean(momentums)) if momentums else 0.0
        avg_volatility = float(np.mean(volatilities)) if volatilities else 0.0

        # Regime tespit (basitleştirilmiş)
        regime = self._detect_regime_simple(breadth_pct, avg_momentum, avg_volatility)

        # Confidence
        confidence = self._estimate_confidence(breadth_pct, avg_momentum, avg_volatility)

        # Risk appetite (basitleştirilmiş)
        risk_appetite = np.clip(breadth_pct / 100.0, 0, 1)

        return TimeframeState(
            timeframe=timeframe,
            regime=regime,
            confidence=confidence,
            breadth_pct=round(breadth_pct, 2),
            momentum=round(avg_momentum, 4),
            volatility=round(avg_volatility, 4),
            risk_appetite=round(float(risk_appetite), 4),
        )

    def _detect_regime_simple(
        self,
        breadth_pct: float,
        momentum: float,
        volatility: float,
    ) -> str:
        """Basit rejim tespiti (timeframe-specific)."""
        if breadth_pct > 65 and momentum > 0:
            return "BULL"
        elif breadth_pct < 35 and momentum < 0:
            return "BEAR"
        elif volatility > 30:
            return "HIGH_VOLATILITY"
        elif volatility < 12:
            return "LOW_VOLATILITY"
        elif breadth_pct > 60:
            return "RISK_ON"
        elif breadth_pct < 40:
            return "RISK_OFF"
        return "SIDEWAYS"

    def _estimate_confidence(
        self,
        breadth_pct: float,
        momentum: float,
        volatility: float,
    ) -> float:
        """Confidence tahmini — breadth'in merkezden uzaklığına göre."""
        # Breadth 50'den ne kadar uzak?
        breadth_strength = abs(breadth_pct - 50) / 50.0

        # Momentum gücü
        momentum_strength = min(abs(momentum) / 10.0, 1.0)

        # Confidence = breadth_strength * 0.6 + momentum_strength * 0.4
        confidence = breadth_strength * 0.6 + momentum_strength * 0.4

        return float(np.clip(confidence, 0.1, 1.0))

    def _detect_divergences(
        self,
        states: Dict[str, TimeframeState],
    ) -> List[str]:
        """Cross-timeframe divergence tespit.

        Örneğin: Günlük BULL ama haftalık BEAR → dikkat
        """
        divergences = []

        if len(states) < 2:
            return divergences

        # Regime'leri karşılaştır
        regimes = {tf: s.regime for tf, s in states.items()}

        # Bull/Bear çelişkisi
        bull_tfs = [tf for tf, r in regimes.items() if r in ("BULL", "RISK_ON")]
        bear_tfs = [tf for tf, r in regimes.items() if r in ("BEAR", "RISK_OFF")]

        if bull_tfs and bear_tfs:
            divergences.append(
                f"BULL/BEAR divergence: {', '.join(bull_tfs)} vs {', '.join(bear_tfs)}"
            )

        # Short-term vs long-term
        short_tf = regimes.get("intraday", regimes.get("daily"))
        long_tf = regimes.get("weekly", regimes.get("monthly"))

        if short_tf and long_tf:
            if (short_tf in ("BULL", "RISK_ON") and long_tf in ("BEAR", "RISK_OFF")) or \
               (short_tf in ("BEAR", "RISK_OFF") and long_tf in ("BULL", "RISK_ON")):
                divergences.append(
                    f"Short/Long term divergence: short={short_tf}, long={long_tf}"
                )

        return divergences

    def _compute_alignment(self, states: Dict[str, TimeframeState]) -> float:
        """Timeframe uyumu skoru [0, 1].

        1 = tüm timeframe'ler aynı rejimde
        0 = tamamen farklı rejimler
        """
        if len(states) < 2:
            return 1.0

        regimes = [s.regime for s in states.values()]
        unique_regimes = set(regimes)

        if len(unique_regimes) == 1:
            return 1.0

        # Regime grupları: bull, bear, neutral
        bull_count = sum(1 for r in regimes if r in ("BULL", "RISK_ON", "MOMENTUM_EXPANSION"))
        bear_count = sum(1 for r in regimes if r in ("BEAR", "RISK_OFF", "CRISIS", "MOMENTUM_CONTRACTION"))
        neutral_count = len(regimes) - bull_count - bear_count

        # En büyük grubun oranı
        max_group = max(bull_count, bear_count, neutral_count)
        alignment = max_group / len(regimes)

        return alignment

    def _find_dominant(self, states: Dict[str, TimeframeState]) -> str:
        """En güvenilir timeframe'i bul.

        Güvenilirlik: daily > weekly > monthly > intraday
        (daily en fazla veriye sahip, intraday gürültülü)
        """
        priority = ["daily", "weekly", "monthly", "intraday"]

        for tf in priority:
            if tf in states and states[tf].confidence > 0.3:
                return tf

        # Hiçbiri yeterli confidence'a sahip değilse
        if states:
            return max(states, key=lambda tf: states[tf].confidence)

        return "daily"
