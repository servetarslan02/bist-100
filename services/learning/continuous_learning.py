"""
ALPHA BIST — Continuous Learning System v1.0

ROADMAP v3.0:
- Her gün yeni veri ile modeli güncelle
- Drift tespiti (model eskimiş mi?)
- Otomatik retrain (drift varsa)
- A/B test (yeni model vs eski model)

KURAL: Sistem durmaksızın öğrenmeli!
"""

import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import deque
import structlog

logger = structlog.get_logger()

class ContinuousLearning:
    """Sürekli öğrenme motoru."""

    def __init__(
        self,
        retrain_threshold: float = 0.05,  # Drift threshold
        min_samples: int = 100,  # Minimum eğitim örneği
        max_history: int = 500,  # Maksimum geçmiş
    ):
        self._retrain_threshold = retrain_threshold
        self._min_samples = min_samples
        self._max_history = max_history

        self._predictions: deque = deque(maxlen=max_history)
        self._outcomes: deque = deque(maxlen=max_history)
        self._model_versions: List[str] = ["v1"]
        self._drift_history: List[Dict] = []

        logger.info("ContinuousLearning initialized")

    def add_prediction(
        self,
        ticker: str,
        predicted_direction: str,
        predicted_return: float,
        confidence: float,
        features: Dict[str, Any],
        timestamp: Optional[datetime] = None,
    ) -> str:
        """Yeni tahmin ekle."""

        pred_id = f"PRED_{(timestamp or datetime.now()).strftime('%Y%m%d_%H%M%S')}_{ticker}"

        self._predictions.append({
            "id": pred_id,
            "ticker": ticker,
            "predicted_direction": predicted_direction,
            "predicted_return": predicted_return,
            "confidence": confidence,
            "features": features,
            "timestamp": timestamp or datetime.now(),
            "outcome": None,
        })

        return pred_id

    def record_outcome(
        self,
        pred_id: str,
        actual_return: float,
        actual_direction: str,
    ) -> Dict[str, Any]:
        """Tahmin sonucunu kaydet."""

        # Tahmini bul
        pred = None
        for p in self._predictions:
            if p["id"] == pred_id:
                pred = p
                break

        if not pred:
            return {"error": "Tahmin bulunamadı"}

        pred["outcome"] = {
            "actual_return": actual_return,
            "actual_direction": actual_direction,
            "correct_direction": pred["predicted_direction"] == actual_direction,
            "return_error": abs(pred["predicted_return"] - actual_return),
        }

        self._outcomes.append(pred)

        return {
            "success": True,
            "prediction": pred,
        }

    def check_drift(self) -> Dict[str, Any]:
        """Model drift kontrolü."""

        if len(self._outcomes) < self._min_samples:
            return {
                "drift_detected": False,
                "reason": f"Yetersiz veri ({len(self._outcomes)}/{self._min_samples})",
            }

        # Son 100 vs ilk 100 karşılaştır
        recent = list(self._outcomes)[-100:]
        older = list(self._outcomes)[:100] if len(self._outcomes) >= 200 else list(self._outcomes)[:len(self._outcomes)//2]

        recent_accuracy = np.mean([o["outcome"]["correct_direction"] for o in recent if o["outcome"]])
        older_accuracy = np.mean([o["outcome"]["correct_direction"] for o in older if o["outcome"]])

        # Drift: Eski doğruluk - yeni doğruluk > threshold
        accuracy_drop = older_accuracy - recent_accuracy

        drift_detected = accuracy_drop > self._retrain_threshold

        result = {
            "drift_detected": drift_detected,
            "accuracy_drop": round(float(accuracy_drop), 4),
            "recent_accuracy": round(float(recent_accuracy), 4),
            "older_accuracy": round(float(older_accuracy), 4),
            "threshold": self._retrain_threshold,
            "total_outcomes": len(self._outcomes),
        }

        self._drift_history.append(result)

        if drift_detected:
            logger.warning("Model drift detected!",
                drop=accuracy_drop, recent=recent_accuracy, older=older_accuracy)

        return result

    def should_retrain(self) -> bool:
        """Retrain gerekli mi?"""
        drift = self.check_drift()
        return drift.get("drift_detected", False)

    def get_learning_stats(self) -> Dict[str, Any]:
        """Öğrenme istatistikleri."""

        if not self._outcomes:
            return {"error": "Henüz outcome yok"}

        outcomes_with_result = [o for o in self._outcomes if o["outcome"]]

        if not outcomes_with_result:
            return {"error": "Henüz sonuçlanmış tahmin yok"}

        correct = sum(1 for o in outcomes_with_result if o["outcome"]["correct_direction"])
        total = len(outcomes_with_result)

        return {
            "total_predictions": len(self._predictions),
            "resolved": total,
            "pending": len(self._predictions) - total,
            "accuracy": round(correct / total * 100, 2) if total else 0,
            "avg_return_error": round(np.mean([o["outcome"]["return_error"] for o in outcomes_with_result]), 4),
            "model_versions": self._model_versions,
            "drift_checks": len(self._drift_history),
            "last_drift": self._drift_history[-1] if self._drift_history else None,
        }

    def get_feature_drift(self) -> Dict[str, Any]:
        """Feature drift analizi."""

        if len(self._outcomes) < 50:
            return {"error": "Yetersiz veri"}

        # Feature istatistiklerini karşılaştır
        recent_features = [o["features"] for o in list(self._outcomes)[-50:]]
        older_features = [o["features"] for o in list(self._outcomes)[:50]]

        drift_report = {}

        # Tüm feature'ları kontrol et
        all_keys = set()
        for f in recent_features + older_features:
            all_keys.update(f.keys())

        for key in all_keys:
            recent_vals = [f.get(key, 0) for f in recent_features if isinstance(f.get(key), (int, float))]
            older_vals = [f.get(key, 0) for f in older_features if isinstance(f.get(key), (int, float))]

            if recent_vals and older_vals:
                recent_mean = np.mean(recent_vals)
                older_mean = np.mean(older_vals)

                if older_mean != 0:
                    change = abs(recent_mean - older_mean) / abs(older_mean)
                    if change > 0.2:  # %20+ değişim
                        drift_report[key] = {
                            "older_mean": round(older_mean, 4),
                            "recent_mean": round(recent_mean, 4),
                            "change_pct": round(change * 100, 2),
                        }

        return {
            "drifted_features": drift_report,
            "total_features_checked": len(all_keys),
            "drifted_count": len(drift_report),
        }

# Singleton
continuous_learning = ContinuousLearning()
