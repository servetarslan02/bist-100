from typing import Any
"""
ALPHA BIST — Learning Loop v2.0 (SQLite Persistence)

Kendi kendine öğrenme döngüsü:
Prediction → Outcome → Error → Attribution → Feature drift →
Regime drift → Model decay → Retrain → OOS → Champion/Reject

v2.0: SQLite tabanlı persistence — restart sonrası kaybolmaz
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog

from services.core.state_store import state_store
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
    drifted_features: list[str] = field(default_factory=list)

    # Regime performance
    regime_accuracy: dict[str, float] = field(default_factory=dict)

    # Retrain status
    last_retrain: datetime | None = None
    retrain_needed: bool = False
    retrain_reason: str = ""


class LearningLoop:
    """Otonom öğrenme döngüsü — SQLite persistence ile."""

    def __init__(self):
        """Otomatik eklendi."""
        self._state = LearningState()
        self._prediction_history: deque = deque(maxlen=5000)
        self._outcome_history: deque = deque(maxlen=5000)
        self._accuracy_window: deque = deque(maxlen=100)  # Son 100 tahmin
        self._restore_from_db()

    def _restore_from_db(self) -> Any:
        """Restart sonrası state'i SQLite'dan geri yükle."""
        try:
            saved = state_store.load_learning_state()
            if not saved:
                return

            self._state.total_predictions = int(saved.get("total_predictions", 0))
            self._state.total_outcomes = int(saved.get("total_outcomes", 0))
            self._state.correct_predictions = int(saved.get("correct_predictions", 0))
            self._state.accuracy = float(saved.get("accuracy", 0))
            self._state.recent_accuracy = float(saved.get("recent_accuracy", 0))
            self._state.accuracy_trend = float(saved.get("accuracy_trend", 0))
            self._state.retrain_needed = saved.get("retrain_needed", False) == "True"
            self._state.retrain_reason = saved.get("retrain_reason", "")

            regime_acc = saved.get("regime_accuracy", "{}")
            if isinstance(regime_acc, str):
                import orjson

                regime_acc = orjson.loads(regime_acc)
            self._state.regime_accuracy = regime_acc

            drifted = saved.get("drifted_features", "[]")
            if isinstance(drifted, str):
                import orjson

                drifted = orjson.loads(drifted)
            self._state.drifted_features = drifted

            # Son tahminleri yükle
            recent_preds = state_store.load_recent_predictions(limit=100)
            for pred in reversed(recent_preds):
                self._prediction_history.appendleft(pred)
                if pred.get("outcome"):
                    self._accuracy_window.append(pred["predicted_direction"] == pred["outcome"].get("actual_direction"))

            logger.info(
                "Learning state restored from SQLite",
                predictions=self._state.total_predictions,
                accuracy=round(self._state.accuracy, 4),
            )
        except Exception as e:
            logger.warning("Failed to restore learning state", error=str(e))

    def _persist_state(self) -> Any:
        """State'i SQLite'a kaydet (SSD dostu — batched)."""
        try:
            state_dict = {
                "total_predictions": self._state.total_predictions,
                "total_outcomes": self._state.total_outcomes,
                "correct_predictions": self._state.correct_predictions,
                "accuracy": self._state.accuracy,
                "recent_accuracy": self._state.recent_accuracy,
                "accuracy_trend": self._state.accuracy_trend,
                "retrain_needed": self._state.retrain_needed,
                "retrain_reason": self._state.retrain_reason,
                "regime_accuracy": self._state.regime_accuracy,
                "drifted_features": self._state.drifted_features,
            }
            state_store.save_learning_state(state_dict)
        except Exception as e:
            logger.warning("Failed to persist learning state", error=str(e))

    def record_prediction(
        self,
        ticker: str,
        predicted_direction: str,
        predicted_return: float,
        confidence: float,
        features: dict,
        regime: str,
    ) -> Any:
        """Tahmin kaydet."""
        self._prediction_history.append(
            {
                "ticker": ticker,
                "predicted_direction": predicted_direction,
                "predicted_return": predicted_return,
                "confidence": confidence,
                "features": features.copy(),
                "regime": regime,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._prediction_history) > 5000:
            self._prediction_history = self._prediction_history[-5000:]
        self._state.total_predictions += 1

        # SQLite'a kaydet
        state_store.save_prediction(ticker, predicted_direction, predicted_return, confidence, regime, features)

    def record_outcome(self, ticker: str, actual_return: float, actual_direction: str, timestamp: str) -> Any:
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
        self._accuracy_window.append(is_correct)  # deque(maxlen=100) auto-trims

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

        # SQLite'a kaydet
        state_store.update_prediction_outcome(ticker, matching["outcome"])
        self._persist_state()

        logger.debug(
            "Outcome recorded",
            ticker=ticker,
            correct=is_correct,
            accuracy=self._state.accuracy,
            recent_accuracy=self._state.recent_accuracy,
        )

    def _check_model_decay(self) -> Any:
        """Model bozulması kontrolü."""
        cfg = learning_settings.retrain
        if len(self._accuracy_window) < 50:
            return

        # Son 50 tahminde doğruluk eşik altına düştüyse
        if self._state.recent_accuracy < cfg.winrate_threshold:
            self._state.retrain_needed = True
            self._state.retrain_reason = (
                f"Recent accuracy dropped to {self._state.recent_accuracy:.2%} (threshold: {cfg.winrate_threshold:.2%})"
            )

        # Accuracy trendi negatifse
        if self._state.accuracy_trend < -0.1:
            self._state.retrain_needed = True
            self._state.retrain_reason = f"Accuracy trend declining: {self._state.accuracy_trend:.3f}"

    def get_state(self) -> dict:
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

    def get_worst_regimes(self) -> list[dict]:
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

    def trigger_autonomous_retrain(self, force: bool = False, tune_hyperparameters: bool = False) -> dict[str, Any]:
        """Model performansı düştüğünde veya periyodik olarak otonom yeniden eğitim döngüsünü çalıştırır.

        1. train_all_models() ile 70-feature modellerini baştan eğitir.
           - Rejim kayması veya 30 gün aşımında Optuna Bayesian aramasını otomatik devreye sokar.
        2. Modellerin kalibrasyonunu ve asimetrik ceza ağırlıklarını uygular.
        3. Yeni modelleri diskten hot-reload ile canlı tahmin hafızasına yükler.
        4. retrain_needed bayrağını sıfırlar ve last_retrain zaman damgasını günceller.
        """
        if not self._state.retrain_needed and not force:
            return {"status": "skipped", "reason": "Retrain not needed"}

        reason = self._state.retrain_reason or ("Forced retrain" if force else "Model decay")
        logger.info("autonomous_retrain_started", reason=reason)

        # Rejim değişimi veya büyük drift durumunda Optuna otomatik etkinleşsin
        should_tune = tune_hyperparameters
        lower_reason = reason.lower()
        if any(keyword in lower_reason for keyword in ["regime", "rejim", "drift", "optuna", "bayesian"]):
            should_tune = True

        try:
            from services.ml.train_all_models import train_all_models

            train_all_models(use_optuna=should_tune)

            # Modelleri canlı tarayıcıda sıcak olarak yenile (hot-reload)
            try:
                from services.scanner.bist_ml_scanner import bist_ml_scanner

                bist_ml_scanner.load_models()
                logger.info("bist_ml_scanner_models_hot_reloaded")
            except Exception as hr_err:
                logger.debug("hot_reload_scanner_notice", error=str(hr_err))

            # Durumu güncelle
            self._state.retrain_needed = False
            self._state.last_retrain = datetime.now(UTC)
            self._state.retrain_reason = ""
            self._persist_state()

            logger.info("autonomous_retrain_completed_successfully")
            return {
                "status": "success",
                "message": "Otonom yeniden eğitim ve hot-reload başarıyla tamamlandı",
                "timestamp": self._state.last_retrain.isoformat(),
                "reason": reason,
            }
        except Exception as e:
            logger.error("autonomous_retrain_failed", error=str(e))
            return {"status": "error", "error": str(e)}


# Singleton
learning_loop = LearningLoop()
