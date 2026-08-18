"""
ALPHA BIST — Learning Loop v1.0

Kendi kendine öğrenme döngüsü:
Prediction → Outcome → Error → Attribution → Feature drift →
Regime drift → Model decay → Retrain → OOS → Champion/Reject
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

from services.learning.config.learning_config import learning_settings

logger = structlog.get_logger()


@dataclass
class LearningState:
    """Öğrenme durumu."""
    total_predictions: int = 0
    total_outcomes: int = 0
    correct_predictions: int = 0
    accuracy: float = 0.0

    # Model decay tracking
    recent_accuracy: float = 0.0  # Son 100 tahmin
    accuracy_trend: float = 0.0  # Pozitif = iyileşiyor

    # Feature drift
    drifted_features: List[str] = field(default_factory=list)

    # Regime performance
    regime_accuracy: Dict[str, float] = field(default_factory=dict)

    # Retrain status
    last_retrain: Optional[datetime] = None
    retrain_needed: bool = False
    retrain_reason: str = ""


class LearningLoop:
    """Otonom öğrenme döngüsü."""

    def __init__(self):
        self._state = LearningState()
        self._prediction_history: List[Dict] = []
        self._outcome_history: List[Dict] = []
        self._accuracy_window: List[bool] = []  # Son 100 tahmin

    def record_prediction(self, ticker: str, predicted_direction: str,
                         predicted_return: float, confidence: float,
                         features: Dict, regime: str):
        """Tahmin kaydet."""
        self._prediction_history.append({
            "ticker": ticker,
            "predicted_direction": predicted_direction,
            "predicted_return": predicted_return,
            "confidence": confidence,
            "features": features.copy(),
            "regime": regime,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self._state.total_predictions += 1

    def record_outcome(self, ticker: str, actual_return: float,
                       actual_direction: str, timestamp: str):
        """Sonuç kaydet ve öğren."""
        # Eşleşen tahmini bul
        matching = None
        for pred in reversed(self._prediction_history):
            if pred["ticker"] == ticker and "outcome" not in pred:
                matching = pred
                break

        if not matching:
            return

        # Outcome kaydet
        matching["outcome"] = {
            "actual_return": actual_return,
            "actual_direction": actual_direction,
            "timestamp": timestamp,
        }

        # Doğruluk kontrolü
        is_correct = matching["predicted_direction"] == actual_direction
        self._accuracy_window.append(is_correct)
        if len(self._accuracy_window) > 100:
            self._accuracy_window.pop(0)

        self._state.total_outcomes += 1
        if is_correct:
            self._state.correct_predictions += 1

        # Accuracy güncelle
        self._state.accuracy = self._state.correct_predictions / self._state.total_outcomes
        self._state.recent_accuracy = sum(self._accuracy_window) / len(self._accuracy_window)

        # Trend hesapla
        if len(self._accuracy_window) >= 50:
            first_half = sum(self._accuracy_window[:50]) / 50
            second_half_len = len(self._accuracy_window[50:])
            if second_half_len > 0:
                second_half = sum(self._accuracy_window[50:]) / second_half_len
                self._state.accuracy_trend = second_half - first_half

        # Regime accuracy güncelle
        regime = matching.get("regime", "UNKNOWN")
        if regime not in self._state.regime_accuracy:
            self._state.regime_accuracy[regime] = {"correct": 0, "total": 0}
        self._state.regime_accuracy[regime]["total"] += 1
        if is_correct:
            self._state.regime_accuracy[regime]["correct"] += 1

        # Model decay kontrolü
        self._check_model_decay()

        logger.debug("Outcome recorded", ticker=ticker, correct=is_correct,
                    accuracy=self._state.accuracy, recent_accuracy=self._state.recent_accuracy)

    def _check_model_decay(self):
        """Model bozulması kontrolü."""
        cfg = learning_settings.retrain
        if len(self._accuracy_window) < 50:
            return

        # Son 50 tahminde doğruluk eşik altına düştüyse
        if self._state.recent_accuracy < cfg.winrate_threshold:
            self._state.retrain_needed = True
            self._state.retrain_reason = f"Recent accuracy dropped to {self._state.recent_accuracy:.2%} (threshold: {cfg.winrate_threshold:.2%})"

        # Accuracy trendi negatifse
        if self._state.accuracy_trend < -0.1:
            self._state.retrain_needed = True
            self._state.retrain_reason = f"Accuracy trend declining: {self._state.accuracy_trend:.3f}"

    def get_state(self) -> Dict:
        """Öğrenme durumunu döndür."""
        return {
            "total_predictions": self._state.total_predictions,
            "total_outcomes": self._state.total_outcomes,
            "accuracy": round(self._state.accuracy, 4),
            "recent_accuracy": round(self._state.recent_accuracy, 4),
            "accuracy_trend": round(self._state.accuracy_trend, 4),
            "retrain_needed": self._state.retrain_needed,
            "retrain_reason": self._state.retrain_reason,
            "regime_accuracy": {
                k: round(v["correct"] / v["total"], 4) if v["total"] > 0 else 0
                for k, v in self._state.regime_accuracy.items()
            },
            "drifted_features": self._state.drifted_features,
        }

    def get_worst_regimes(self) -> List[Dict]:
        """En kötü performans gösteren rejimler."""
        results = []
        for regime, data in self._state.regime_accuracy.items():
            if data["total"] >= 10:
                acc = data["correct"] / data["total"]
                results.append({"regime": regime, "accuracy": round(acc, 4), "count": data["total"]})
        return sorted(results, key=lambda x: x["accuracy"])[:5]

    def should_retrain(self) -> bool:
        """Yeniden eğitim gerekli mi?"""
        return self._state.retrain_needed

    def get_retrain_reason(self) -> str:
        """Yeniden eğitim sebebi."""
        return self._state.retrain_reason


# Singleton
learning_loop = LearningLoop()
