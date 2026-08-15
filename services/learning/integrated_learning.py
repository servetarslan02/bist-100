"""
ALPHA BIST — Integrated Learning System v2.0

Prediction → Outcome → Feedback döngüsü.
Regime bazlı doğruluk, feature importance, model drift tespiti.

FAZ 10: Learning System (Güncellenmiş)
"""

import json
import hashlib
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import structlog

logger = structlog.get_logger()

@dataclass
class Prediction:
    """Tahmin kaydı."""
    prediction_id: str
    ticker: str
    timestamp: datetime
    regime: str
    predicted_direction: str  # UP, DOWN
    confidence: float
    horizon: str  # 1-5D, 1-4W, 1-6M, 6-24M
    feature_snapshot: Dict[str, Any]
    model_version: str = "v1"

    # Outcome (daha sonra doldurulur)
    actual_direction: Optional[str] = None
    actual_return: Optional[float] = None
    outcome: Optional[str] = None  # TP, SL, EXPIRED
    outcome_timestamp: Optional[datetime] = None

class IntegratedLearningSystem:
    """Entegre öğrenme sistemi."""

    def __init__(self):
        self._predictions: List[Prediction] = []
        self._outcomes: List[Dict] = []
        self._regime_accuracy: Dict[str, Dict] = defaultdict(
            lambda: {"correct": 0, "total": 0}
        )
        self._feature_importance: Dict[str, float] = {}
        self._model_versions: List[str] = ["v1"]
        self._feedback_buffer: List[Dict] = []

        logger.info("IntegratedLearningSystem initialized")

    # ===================== PREDICTION =====================

    def record_prediction(
        self,
        ticker: str,
        regime: str,
        predicted_direction: str,
        confidence: float,
        horizon: str = "1-5D",
        feature_snapshot: Dict = None,
    ) -> str:
        """Yeni tahmin kaydet."""
        pred_id = f"PRED_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{ticker}"

        pred = Prediction(
            prediction_id=pred_id,
            ticker=ticker,
            timestamp=datetime.now(timezone.utc),
            regime=regime,
            predicted_direction=predicted_direction,
            confidence=confidence,
            horizon=horizon,
            feature_snapshot=feature_snapshot or {},
            model_version=self._model_versions[-1],
        )

        self._predictions.append(pred)

        logger.debug("Prediction recorded",
            ticker=ticker, direction=predicted_direction,
            confidence=confidence, regime=regime)

        return pred_id

    # ===================== OUTCOME (YENİ EKLENEN) =====================

    def record_outcome(
        self,
        ticker: str,
        actual_price: float,
        entry_price: float,
        holding_days: int = 0,
        outcome_type: str = "auto",
    ) -> Dict[str, Any]:
        """Tahmin sonucunu kaydet.

        Bu method outcome_tracker tarafından çağrılır.
        """
        # İlgili tahmini bul
        matching_preds = [
            p for p in self._predictions
            if p.ticker == ticker and p.outcome is None
        ]

        if not matching_preds:
            logger.warning("No matching prediction found", ticker=ticker)
            return {"success": False, "error": "Eşleşen tahmin bulunamadı"}

        # En son tahmini kullan
        pred = matching_preds[-1]

        # Gerçek getiri
        if entry_price and entry_price > 0:
            actual_return = (actual_price / entry_price - 1) * 100
        else:
            actual_return = 0.0

        # Yön belirle
        actual_direction = "UP" if actual_return > 0 else "DOWN"

        # Outcome belirle
        if actual_return > 5:
            outcome = "TP"  # Take Profit
        elif actual_return < -5:
            outcome = "SL"  # Stop Loss
        else:
            outcome = "EXPIRED"

        # Tahmini güncelle
        pred.actual_direction = actual_direction
        pred.actual_return = actual_return
        pred.outcome = outcome
        pred.outcome_timestamp = datetime.now(timezone.utc)

        # Doğruluk kontrolü
        correct = pred.predicted_direction == actual_direction

        # Regime bazlı doğruluk güncelle
        self._regime_accuracy[pred.regime]["total"] += 1
        if correct:
            self._regime_accuracy[pred.regime]["correct"] += 1

        # Outcome kaydet
        outcome_record = {
            "prediction_id": pred.prediction_id,
            "ticker": ticker,
            "predicted_direction": pred.predicted_direction,
            "actual_direction": actual_direction,
            "actual_return": round(actual_return, 2),
            "outcome": outcome,
            "correct": correct,
            "regime": pred.regime,
            "confidence": pred.confidence,
            "holding_days": holding_days,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._outcomes.append(outcome_record)

        logger.info("Outcome recorded",
            ticker=ticker,
            predicted=pred.predicted_direction,
            actual=actual_direction,
            correct=correct,
            return_pct=round(actual_return, 2))

        return {
            "success": True,
            "outcome": outcome_record,
        }

    def get_pending_outcomes(self, limit: int = 50) -> List[Dict]:
        """Sonuç bekleyen tahminleri getir.

        Bu method API handler tarafından çağrılır.
        """
        pending = [
            {
                "prediction_id": p.prediction_id,
                "ticker": p.ticker,
                "predicted_direction": p.predicted_direction,
                "confidence": p.confidence,
                "regime": p.regime,
                "horizon": p.horizon,
                "timestamp": p.timestamp.isoformat(),
                "days_elapsed": (datetime.now(timezone.utc) - p.timestamp).days,
            }
            for p in self._predictions
            if p.outcome is None
        ]

        return pending[-limit:]

    # ===================== DECISION (MEVCUT) =====================

    def record_decision(
        self,
        ticker: str,
        action: str,
        direction: str,
        confidence: float,
        features: Dict,
        signals: Dict,
        regime: str,
    ) -> str:
        """Karar kaydet."""
        decision_id = hashlib.sha256(
            f"{ticker}:{action}:{datetime.now(timezone.utc).isoformat()}".encode()
        ).hexdigest()[:16]

        logger.debug("Decision recorded",
            ticker=ticker, action=action,
            direction=direction, confidence=confidence)

        return decision_id

    def record_feedback(
        self,
        ticker: str,
        prediction_id: str,
        feedback: str,
        actual_outcome: str,
    ):
        """Manuel feedback kaydet."""
        self._feedback_buffer.append({
            "ticker": ticker,
            "prediction_id": prediction_id,
            "feedback": feedback,
            "actual_outcome": actual_outcome,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        logger.info("Feedback recorded", ticker=ticker, feedback=feedback)

    # ===================== STATS =====================

    def get_stats(self) -> Dict[str, Any]:
        """Öğrenme istatistikleri."""
        total = len(self._outcomes)
        if total == 0:
            return {
                "total_predictions": len(self._predictions),
                "resolved": 0,
                "accuracy": 0,
                "regime_accuracy": {},
                "avg_return": 0,
                "model_version": self._model_versions[-1],
            }

        correct = sum(1 for o in self._outcomes if o.get("correct"))
        accuracy = (correct / total) * 100

        avg_return = sum(o.get("actual_return", 0) for o in self._outcomes) / total

        # Regime bazlı doğruluk
        regime_stats = {}
        for regime, stats in self._regime_accuracy.items():
            if stats["total"] > 0:
                regime_stats[regime] = {
                    "correct": stats["correct"],
                    "total": stats["total"],
                    "accuracy": round((stats["correct"] / stats["total"]) * 100, 1),
                }

        return {
            "total_predictions": len(self._predictions),
            "resolved": total,
            "pending": len(self._predictions) - total,
            "accuracy": round(accuracy, 1),
            "regime_accuracy": regime_stats,
            "avg_return": round(avg_return, 2),
            "model_version": self._model_versions[-1],
        }

    def get_recent_predictions(self, limit: int = 20) -> List[Dict]:
        """Son tahminleri getir."""
        recent = self._predictions[-limit:]
        return [
            {
                "prediction_id": p.prediction_id,
                "ticker": p.ticker,
                "predicted_direction": p.predicted_direction,
                "actual_direction": p.actual_direction,
                "confidence": p.confidence,
                "regime": p.regime,
                "outcome": p.outcome,
                "timestamp": p.timestamp.isoformat(),
            }
            for p in reversed(recent)
        ]

    def get_regime_accuracy(self) -> Dict[str, Any]:
        """Regime bazlı doğruluk."""
        return dict(self._regime_accuracy)

    def get_feature_importance(self) -> Dict[str, float]:
        """Feature importance."""
        return dict(self._feature_importance)

    def check_model_drift(self) -> Dict[str, Any]:
        """Model drift kontrolü."""
        if len(self._outcomes) < 20:
            return {"drift_detected": False, "reason": "Yetersiz veri"}

        # Son 20 outcome'un doğruluğu
        recent = self._outcomes[-20:]
        recent_accuracy = sum(1 for o in recent if o.get("correct")) / len(recent)

        # Tüm zamanların doğruluğu
        all_accuracy = sum(1 for o in self._outcomes if o.get("correct")) / len(self._outcomes)

        drift = recent_accuracy < all_accuracy * 0.8

        return {
            "drift_detected": drift,
            "recent_accuracy": round(recent_accuracy * 100, 1),
            "overall_accuracy": round(all_accuracy * 100, 1),
            "threshold": round(all_accuracy * 0.8 * 100, 1),
        }

    def suggest_retrain(self) -> bool:
        """Yeniden eğitim önerisi."""
        drift = self.check_model_drift()
        return drift.get("drift_detected", False)

# Singleton
learning_system = IntegratedLearningSystem()
