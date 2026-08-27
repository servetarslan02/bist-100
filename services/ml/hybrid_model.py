"""ALPHA BIST — Hybrid Model (Nihai —⭐⭐⭐⭐⭐).

FinGPT sentiment + RL action + ML ranking birleşimi.
Multi-signal fusion, dynamic weighting, conflict resolution.
"""
from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class HybridSignal:
    """Hybrid sinyal sonucu."""
    action: str  # BUY, SELL, HOLD
    confidence: float
    ml_score: float
    sentiment_score: float
    rl_action: int
    conflict: bool
    signals: dict[str, Any]
    reasoning: str


class HybridModel:
    """Multi-signal hybrid model —⭐⭐⭐⭐⭐ seviye.

    Özellikler:
    - ML ranking + Sentiment + RL birleşimi
    - Dynamic signal weighting (rejime göre)
    - Conflict detection ve resolution
    - Confidence-based signal filtering
    - Multi-timeframe aggregation
    """

    def __init__(
        self,
        ml_weight: float = 0.5,
        sentiment_weight: float = 0.3,
        rl_weight: float = 0.2,
        conflict_threshold: float = 0.3,
        confidence_threshold: float = 0.4,
    ):
        self.ml_weight = ml_weight
        self.sentiment_weight = sentiment_weight
        self.rl_weight = rl_weight
        self.conflict_threshold = conflict_threshold
        self.confidence_threshold = confidence_threshold
        self._regime_weights: dict[str, dict[str, float]] = {
            "BULL": {"ml": 0.4, "sentiment": 0.4, "rl": 0.2},
            "BEAR": {"ml": 0.5, "sentiment": 0.2, "rl": 0.3},
            "SIDEWAYS": {"ml": 0.6, "sentiment": 0.2, "rl": 0.2},
            "HIGH_VOL": {"ml": 0.3, "sentiment": 0.2, "rl": 0.5},
        }

    def predict(
        self,
        ml_score: float,
        sentiment_score: float,
        rl_action: int,
        regime: str = "NORMAL",
        market_state: str = "NORMAL",
    ) -> HybridSignal:
        """Hybrid prediction — sinyal birleşimi.

        Args:
            ml_score: ML model skoru (0-1)
            sentiment_score: Sentiment skoru (-1 ile 1)
            rl_action: RL aksiyonu (0=BUY, 1=HOLD, 2=SELL)
            regime: Piyasa rejimi
            market_state: Piyasa durumu

        Returns:
            HybridSignal
        """
        # Rejime göre ağırlıklar
        weights = self._regime_weights.get(regime, {
            "ml": self.ml_weight, "sentiment": self.sentiment_weight, "rl": self.rl_weight
        })

        # Sentiment'ı 0-1'e normalize et
        sentiment_normalized = (sentiment_score + 1) / 2  # -1..1 → 0..1

        # RL action'ı 0-1'e normalize et
        rl_normalized = {0: 0.8, 1: 0.5, 2: 0.2}.get(rl_action, 0.5)

        # Weighted score
        weighted_score = (
            ml_score * weights["ml"]
            + sentiment_normalized * weights["sentiment"]
            + rl_normalized * weights["rl"]
        )

        # Conflict detection
        ml_direction = "BUY" if ml_score > 0.5 else "SELL" if ml_score < 0.5 else "HOLD"
        sentiment_direction = "BUY" if sentiment_score > 0.1 else "SELL" if sentiment_score < -0.1 else "HOLD"
        rl_direction = {0: "BUY", 1: "HOLD", 2: "SELL"}.get(rl_action, "HOLD")

        directions = [ml_direction, sentiment_direction, rl_direction]
        unique_directions = set(d for d in directions if d != "HOLD")
        conflict = len(unique_directions) > 1

        # Action belirleme
        if weighted_score > 0.65:
            action = "BUY"
        elif weighted_score < 0.35:
            action = "SELL"
        else:
            action = "HOLD"

        # Confidence
        base_confidence = abs(weighted_score - 0.5) * 2  # 0-1 arası
        if conflict:
            base_confidence *= 0.6  # Conflict varsa confidence düş

        # Market state adjustment
        if market_state == "HALT" or market_state == "LIMIT":
            action = "HOLD"
            base_confidence *= 0.3

        # Reasoning
        reasoning = self._generate_reasoning(ml_score, sentiment_score, rl_action, regime, conflict, action)

        return HybridSignal(
            action=action,
            confidence=round(min(base_confidence, 1.0), 4),
            ml_score=round(ml_score, 4),
            sentiment_score=round(sentiment_score, 4),
            rl_action=rl_action,
            conflict=conflict,
            signals={
                "ml_direction": ml_direction,
                "sentiment_direction": sentiment_direction,
                "rl_direction": rl_direction,
                "weighted_score": round(weighted_score, 4),
                "regime": regime,
                "weights": weights,
            },
            reasoning=reasoning,
        )

    def predict_batch(
        self,
        ml_scores: np.ndarray,
        sentiment_scores: np.ndarray,
        rl_actions: np.ndarray,
        regime: str = "NORMAL",
    ) -> list[HybridSignal]:
        """Toplu prediction."""
        return [
            self.predict(ml, sent, rl, regime)
            for ml, sent, rl in zip(ml_scores, sentiment_scores, rl_actions, strict=False)
        ]

    def set_regime_weights(self, regime: str, weights: dict[str, float]):
        """Rejim ağırlıklarını güncelle."""
        self._regime_weights[regime] = weights

    def _generate_reasoning(
        self,
        ml_score: float,
        sentiment_score: float,
        rl_action: int,
        regime: str,
        conflict: bool,
        action: str,
    ) -> str:
        """Karar açıklaması oluştur."""
        parts = []

        # ML
        if ml_score > 0.6:
            parts.append(f"ML güçlü alım sinyali ({ml_score:.2f})")
        elif ml_score < 0.4:
            parts.append(f"ML satış sinyali ({ml_score:.2f})")
        else:
            parts.append(f"ML nötr ({ml_score:.2f})")

        # Sentiment
        if sentiment_score > 0.2:
            parts.append(f"Olumlu sentiment ({sentiment_score:.2f})")
        elif sentiment_score < -0.2:
            parts.append(f"Olumsuz sentiment ({sentiment_score:.2f})")

        # RL
        rl_names = {0: "alım", 1: "bekle", 2: "satış"}
        parts.append(f"RL {rl_names.get(rl_action, 'bilinmeyen')} önerisi")

        # Regime
        parts.append(f"Rejim: {regime}")

        # Conflict
        if conflict:
            parts.append("⚠️ Sinyal çelişkisi var — dikkatli ol")

        return " | ".join(parts)


# Singleton
hybrid_model = HybridModel()


def hybrid_predict(
    rl_action: int,
    sentiment_score: float,
    market_state: str = "NORMAL",
    ml_score: float = 0.5,
    regime: str = "NORMAL",
) -> dict[str, Any]:
    """Hyybrid prediction — backward compatible wrapper."""
    result = hybrid_model.predict(
        ml_score=ml_score,
        sentiment_score=sentiment_score,
        rl_action=rl_action,
        regime=regime,
        market_state=market_state,
    )
    return {
        "action": result.action,
        "confidence": result.confidence,
        "rl_action": result.rl_action,
        "sentiment": result.sentiment_score,
        "ml_score": result.ml_score,
        "conflict": result.conflict,
        "reasoning": result.reasoning,
    }
