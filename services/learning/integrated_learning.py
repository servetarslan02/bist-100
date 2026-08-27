"""
ALPHA BIST — Integrated Learning System v2.0

Prediction → Outcome → Feedback döngüsü.
Regime bazlı doğruluk, feature importance, model drift tespiti.

FAZ 10: Learning System (Güncellenmiş)
"""

import hashlib
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import orjson
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
    feature_snapshot: dict[str, Any]
    model_version: str = "v1"

    # Outcome (daha sonra doldurulur)
    actual_direction: str | None = None
    actual_return: float | None = None
    outcome: str | None = None  # TP, SL, EXPIRED
    outcome_timestamp: datetime | None = None


@dataclass
class Outcome:
    """Sonuç kaydı."""
    prediction_id: str
    ticker: str
    predicted_direction: str
    actual_direction: str
    actual_return: float
    outcome: str
    correct: bool
    regime: str
    confidence: float
    holding_days: int
    timestamp: str


class IntegratedLearningSystem:
    """Entegre öğrenme sistemi."""

    def __init__(self):
        self._predictions: deque = deque(maxlen=5000)
        self._outcomes: deque = deque(maxlen=5000)
        self._regime_accuracy: dict[str, dict] = defaultdict(
            lambda: {"correct": 0, "total": 0}
        )
        self._feature_importance: dict[str, float] = {}
        self._model_versions: list[str] = ["v1"]
        self._feedback_buffer: deque = deque(maxlen=1000)

        logger.info("IntegratedLearningSystem initialized")

    # ===================== PREDICTION =====================

    def record_prediction(
        self,
        ticker: str,
        regime: str,
        predicted_direction: str,
        confidence: float,
        horizon: str = "1-5D",
        feature_snapshot: dict = None,
    ) -> str:
        """Yeni tahmin kaydet."""
        pred_id = f"PRED_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{ticker}"

        pred = Prediction(
            prediction_id=pred_id,
            ticker=ticker,
            timestamp=datetime.now(UTC),
            regime=regime,
            predicted_direction=predicted_direction,
            confidence=confidence,
            horizon=horizon,
            feature_snapshot=feature_snapshot or {},
            model_version=self._model_versions[-1],
        )

        self._predictions.append(pred)
        if len(self._predictions) > 5000:
            self._predictions = self._predictions[-5000:]

        logger.debug("Prediction recorded",
            ticker=ticker, direction=predicted_direction,
            confidence=confidence, regime=regime)

        # PREDICTION_CREATED event
        try:
            from services.core.event_bus import publish_event
            from services.core.event_schema import CanonicalEvent, EventType
            pred_event = CanonicalEvent(
                event_type=EventType.PREDICTION_CREATED,
                payload={
                    "ticker": ticker,
                    "prediction_type": predicted_direction,
                    "predicted_value": confidence,
                    "confidence": confidence,
                },
            )
            publish_event(pred_event, key=ticker)
        except Exception as e:
            logger.debug("prediction_event_publish_failed", ticker=ticker, error=str(e))

        return pred_id

    # ===================== OUTCOME (YENİ EKLENEN) =====================

    def record_outcome(
        self,
        ticker: str,
        actual_price: float,
        entry_price: float,
        holding_days: int = 0,
        outcome_type: str = "auto",
    ) -> dict[str, Any]:
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
        actual_return = (actual_price / entry_price - 1) * 100 if entry_price and entry_price > 0 else 0.0

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
        pred.outcome_timestamp = datetime.now(UTC)

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
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._outcomes.append(outcome_record)
        if len(self._outcomes) > 5000:
            self._outcomes = self._outcomes[-5000:]

        # Feature importance güncelle — doğru tahmin eden feature'ları ağırlıklandır
        if pred.feature_snapshot:
            weight = 1.0 if correct else -0.5
            for feat_name, feat_val in pred.feature_snapshot.items():
                if isinstance(feat_val, (int, float)) and feat_val == feat_val:  # NaN check
                    self._feature_importance[feat_name] = self._feature_importance.get(feat_name, 0) + weight

        logger.info("Outcome recorded",
            ticker=ticker,
            predicted=pred.predicted_direction,
            actual=actual_direction,
            correct=correct,
            return_pct=round(actual_return, 2))

        # OUTCOME_CREATED event
        try:
            from services.core.event_bus import publish_event
            from services.core.event_schema import CanonicalEvent, EventType
            out_event = CanonicalEvent(
                event_type=EventType.OUTCOME_CREATED,
                payload={
                    "ticker": ticker,
                    "actual_value": actual_return,
                    "prediction_id": pred.prediction_id,
                },
            )
            publish_event(out_event, key=ticker)
        except Exception as e:
            logger.debug("outcome_event_publish_failed", ticker=ticker, error=str(e))

        return {
            "success": True,
            "outcome": outcome_record,
        }

    def get_pending_outcomes(self, limit: int = 50) -> list[dict]:
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
                "days_elapsed": (datetime.now(UTC) - p.timestamp).days,
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
        features: dict,
        signals: dict,
        regime: str,
    ) -> str:
        """Karar kaydet."""
        decision_id = hashlib.sha256(
            f"{ticker}:{action}:{datetime.now(UTC).isoformat()}".encode()
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
            "timestamp": datetime.now(UTC).isoformat(),
        })
        if len(self._feedback_buffer) > 1000:
            self._feedback_buffer = self._feedback_buffer[-1000:]

        logger.info("Feedback recorded", ticker=ticker, feedback=feedback)

    # ===================== STATS =====================

    def get_stats(self) -> dict[str, Any]:
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

    def get_recent_predictions(self, limit: int = 20) -> list[dict]:
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

    def get_regime_accuracy(self, regime: str | None = None) -> Any:
        """Regime bazlı doğruluk."""
        if regime is not None:
            stats = self._regime_accuracy.get(str(regime), {})
            if isinstance(stats, dict) and stats.get("total", 0) > 0:
                return float(stats["correct"] / stats["total"])
            return 0.5
        return dict(self._regime_accuracy)

    def get_feature_importance(self) -> dict[str, float]:
        """Feature importance."""
        return dict(self._feature_importance)

    def check_model_drift(self) -> dict[str, Any]:
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

    def save(self, path: str = "data/integrated_learning.json"):
        """Learning state'i dosyaya kaydet."""
        data = {
            "predictions": [
                {"prediction_id": p.prediction_id, "ticker": p.ticker,
                 "timestamp": p.timestamp.isoformat(), "regime": p.regime,
                 "predicted_direction": p.predicted_direction, "confidence": p.confidence,
                 "horizon": p.horizon, "model_version": p.model_version}
                for p in self._predictions
            ],
            "outcomes": [
                {"prediction_id": o.prediction_id, "actual_return": o.actual_return,
                 "actual_direction": o.actual_direction, "correct": o.correct,
                 "regime": o.regime, "timestamp": o.timestamp.isoformat()}
                for o in self._outcomes
            ],
            "regime_accuracy": dict(self._regime_accuracy),
            "model_versions": self._model_versions,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2).decode())
        logger.info("Integrated learning saved", path=path, predictions=len(self._predictions), outcomes=len(self._outcomes))

    def load(self, path: str = "data/integrated_learning.json"):
        """Learning state'i dosyadan yükle."""
        if not Path(path).exists():
            return
        try:
            with open(path) as f:
                data = orjson.loads(f.read())
            for p in data.get("predictions", []):
                p["timestamp"] = datetime.fromisoformat(p["timestamp"])
                self._predictions.append(Prediction(**p))
            for o in data.get("outcomes", []):
                o["timestamp"] = datetime.fromisoformat(o["timestamp"])
                self._outcomes.append(Outcome(**o))
            for regime, acc in data.get("regime_accuracy", {}).items():
                self._regime_accuracy[regime] = acc
            if data.get("model_versions"):
                self._model_versions = data["model_versions"]
            logger.info("Integrated learning loaded", path=path, predictions=len(self._predictions), outcomes=len(self._outcomes))
        except Exception as e:
            logger.warning("Failed to load integrated learning", path=path, error=str(e))

# Singleton
learning_system = IntegratedLearningSystem()
