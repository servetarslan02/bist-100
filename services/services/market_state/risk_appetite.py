"""ALPHA BIST — Risk Appetite Engine v2.0

6 faktörlü risk appetite hesaplama:
1. Breadth (0.30) — Piyasa genişliği
2. Momentum (0.20) — Piyasa gücü
3. Volatility (0.20) — Düşük vol = yüksek risk appetite
4. RSI (0.10) — Aşırı alım/satım
5. Sentiment (0.10) — Piyasa duyarlılığı
6. Macro (0.10) — Makro ortam

Çıktı: [0, 1] arası skor
0 = tam risk-off (kaçış)
1 = tam risk-on (agresif alım)
"""

import numpy as np
from typing import Dict, Optional, Any
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


class RiskAppetiteEngine:
    """6 faktörlü risk appetite hesaplama.

    Kullanım:
        engine = RiskAppetiteEngine()
        score = engine.compute(
            breadth_pct=65.0,
            momentum=2.5,
            volatility=18.0,
            rsi=55.0,
            sentiment_score=0.3,
            macro_score=0.6,
        )
    """

    def __init__(
        self,
        breadth_weight: float = 0.30,
        momentum_weight: float = 0.20,
        volatility_weight: float = 0.20,
        rsi_weight: float = 0.10,
        sentiment_weight: float = 0.10,
        macro_weight: float = 0.10,
    ):
        self._weights = {
            "breadth": breadth_weight,
            "momentum": momentum_weight,
            "volatility": volatility_weight,
            "rsi": rsi_weight,
            "sentiment": sentiment_weight,
            "macro": macro_weight,
        }

        # Normalize
        total = sum(self._weights.values())
        if total > 0:
            self._weights = {k: v / total for k, v in self._weights.items()}

    def compute(
        self,
        breadth_pct: float = 50.0,
        momentum: float = 0.0,
        volatility: float = 20.0,
        rsi: float = 50.0,
        sentiment_score: float = 0.0,
        macro_score: float = 0.5,
    ) -> float:
        """Risk appetite skoru hesapla [0, 1].

        Args:
            breadth_pct: % advancing (0-100)
            momentum: Ortalama momentum
            volatility: Ortalama volatilite (annualized %)
            rsi: Ortalama RSI (0-100)
            sentiment_score: Sentiment skoru [-1, 1]
            macro_score: Macro skoru [0, 1]

        Returns:
            Risk appetite skoru [0, 1]
        """
        # Her faktörü [0, 1]'e normalize et
        scores = {}

        # 1. Breadth: 0-100 → 0-1 (linear)
        scores["breadth"] = np.clip(breadth_pct / 100.0, 0, 1)

        # 2. Momentum: normalize ([-50, 50] → [0, 1])
        scores["momentum"] = np.clip((momentum + 50) / 100.0, 0, 1)

        # 3. Volatility: düşük vol = yüksek risk appetite
        #    annualized vol: 0-100 arası, 20 normal
        #    10 → 0.75 (risk-on), 20 → 0.5, 40 → 0.25
        if volatility > 0:
            scores["volatility"] = np.clip(1.0 - (volatility - 10) / 50.0, 0, 1)
        else:
            scores["volatility"] = 0.5

        # 4. RSI: 30-70 arası normal, extremes risk-off
        if rsi > 70:
            # Aşırı alım → risk-off (düşük risk appetite)
            scores["rsi"] = np.clip(1.0 - (rsi - 70) / 30.0, 0, 1)
        elif rsi < 30:
            # Aşırı satım → risk-on (fırsat)
            scores["rsi"] = np.clip((rsi - 10) / 20.0, 0, 1)
        else:
            # Normal bölge
            scores["rsi"] = 0.5

        # 5. Sentiment: [-1, 1] → [0, 1]
        scores["sentiment"] = np.clip((sentiment_score + 1) / 2.0, 0, 1)

        # 6. Macro: [0, 1] (zaten normalize)
        scores["macro"] = np.clip(macro_score, 0, 1)

        # Ağırlıklı toplam
        risk_appetite = sum(
            scores[factor] * weight
            for factor, weight in self._weights.items()
        )

        risk_appetite = float(np.clip(risk_appetite, 0, 1))

        logger.debug(
            "Risk appetite computed",
            risk_appetite=round(risk_appetite, 3),
            scores={k: round(v, 3) for k, v in scores.items()},
        )

        return risk_appetite

    def compute_detailed(
        self,
        breadth_pct: float = 50.0,
        momentum: float = 0.0,
        volatility: float = 20.0,
        rsi: float = 50.0,
        sentiment_score: float = 0.0,
        macro_score: float = 0.5,
    ) -> Dict[str, Any]:
        """Detaylı risk appetite hesaplama — her faktörün katkısını gösterir."""
        scores = {}

        scores["breadth"] = np.clip(breadth_pct / 100.0, 0, 1)
        scores["momentum"] = np.clip((momentum + 50) / 100.0, 0, 1)

        if volatility > 0:
            scores["volatility"] = np.clip(1.0 - (volatility - 10) / 50.0, 0, 1)
        else:
            scores["volatility"] = 0.5

        if rsi > 70:
            scores["rsi"] = np.clip(1.0 - (rsi - 70) / 30.0, 0, 1)
        elif rsi < 30:
            scores["rsi"] = np.clip((rsi - 10) / 20.0, 0, 1)
        else:
            scores["rsi"] = 0.5

        scores["sentiment"] = np.clip((sentiment_score + 1) / 2.0, 0, 1)
        scores["macro"] = np.clip(macro_score, 0, 1)

        # Katkılar
        contributions = {}
        for factor, score in scores.items():
            weight = self._weights[factor]
            contributions[factor] = {
                "raw_score": round(float(score), 4),
                "weight": round(weight, 4),
                "contribution": round(float(score * weight), 4),
            }

        total = sum(c["contribution"] for c in contributions.values())

        return {
            "risk_appetite": round(float(np.clip(total, 0, 1)), 4),
            "contributions": contributions,
            "state": self._risk_appetite_state(total),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _risk_appetite_state(self, score: float) -> str:
        """Risk appetite state belirle."""
        if score > 0.75:
            return "RISK_ON"
        elif score > 0.55:
            return "MODERATE_RISK_ON"
        elif score > 0.45:
            return "NEUTRAL"
        elif score > 0.25:
            return "MODERATE_RISK_OFF"
        return "RISK_OFF"

    def update_weights(self, weights: Dict[str, float]):
        """Ağırlıkları güncelle (backtest optimizasyonu sonrası)."""
        for factor, weight in weights.items():
            if factor in self._weights:
                self._weights[factor] = weight

        # Normalize
        total = sum(self._weights.values())
        if total > 0:
            self._weights = {k: v / total for k, v in self._weights.items()}
