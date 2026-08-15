"""
ALPHA BIST — Integrated Learning System v1.0

Sistemin kendi kendine öğrenmesi:
1. Her karar → prediction kaydet
2. Sonuç geldiğinde → outcome kaydet
3. Hata analizi → hangi koşullarda hata yapıyor?
4. Model decay → ne zaman yeniden eğitim gerekli?
5. Feedback → öğrenilen bilgi gelecek kararları etkiler

Bu modül learning_loop.py'ı ana sisteme bağlar.
"""

import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta
from pathlib import Path
import structlog

logger = structlog.get_logger()

# Persistence path
LEARNING_STATE_PATH = Path("data/learning_state.json")


class IntegratedLearningSystem:
    """Ana sisteme entegre öğrenme sistemi."""

    def __init__(self):
        self._predictions: List[Dict] = []
        self._outcomes: List[Dict] = []
        self._learning_insights: Dict[str, Any] = {}
        self._accuracy_window: List[bool] = []
        self._regime_accuracy: Dict[str, Dict] = {}
        self._feature_importance_feedback: Dict[str, float] = {}

        # Persistence
        self._load_state()

    def record_decision(self, ticker: str, decision: Dict, features: Dict, regime: str):
        """Her karar anında tahmin kaydet.

        Args:
            ticker: Hisse kodu
            decision: {action, direction, composite_score, conviction, reasons, risks}
            features: Mevcut feature'lar
            regime: Mevcut piyasa rejimi
        """
        # Aynı ticker için son 24 saatte zaten tahmin var mı?
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=24)).isoformat()
        for existing in reversed(self._predictions):
            if (existing["ticker"] == ticker
                and not existing["resolved"]
                and existing.get("timestamp", "") > cutoff):
                logger.debug("Duplicate prediction skipped", ticker=ticker)
                return

        prediction = {
            "prediction_id": f"{ticker}-{now.strftime('%Y%m%d%H%M%S')}",
            "ticker": ticker,
            "timestamp": datetime.now(timezone.utc).isoformat(),

            # Tahmin
            "predicted_direction": decision.get("direction", "NEUTRAL"),
            "predicted_action": decision.get("action", "HOLD"),
            "predicted_score": decision.get("composite_score", 50),
            "predicted_conviction": decision.get("conviction", "LOW"),
            "predicted_confidence": decision.get("confidence", 0.5),

            # Bağlam
            "regime": regime,
            "feature_snapshot": {
                "price": features.get("price", 0),
                "momentum_20d": features.get("momentum_20d", 0),
                "rsi_14": features.get("rsi_14", 50),
                "volume_zscore": features.get("volume_zscore", 0),
                "realized_vol_20d": features.get("realized_vol_20d", 20),
                "bb_position": features.get("bb_position", 0.5),
                "trend_slope_20d": features.get("trend_slope_20d", 0),
            },

            # Gerekçe
            "reasons": decision.get("reasons", []),
            "risks": decision.get("risks", []),

            # Outcome henüz yok
            "outcome": None,
            "resolved": False,
        }

        self._predictions.append(prediction)
        self._save_state()

        logger.info("Prediction recorded",
                    ticker=ticker,
                    direction=prediction["predicted_direction"],
                    score=prediction["predicted_score"])

    def record_outcome(self, ticker: str, actual_price: float, entry_price: float,
                       holding_days: int = 0, outcome_type: str = "manual"):
        """Sonuç kaydet ve öğren.

        Args:
            ticker: Hisse kodu
            actual_price: Gerçekleşen fiyat
            entry_price: Giriş fiyatı
            holding_days: Tutma süresi
            outcome_type: manual | auto | timeout
        """
        actual_return = (actual_price / entry_price - 1) * 100 if entry_price > 0 else 0
        actual_direction = "LONG" if actual_return > 0 else "SHORT" if actual_return < 0 else "NEUTRAL"

        # Eşleşen tahmini bul (en son, çözülmemiş)
        matching = None
        for pred in reversed(self._predictions):
            if pred["ticker"] == ticker and not pred["resolved"]:
                matching = pred
                break

        if not matching:
            logger.warning("No matching prediction found", ticker=ticker)
            return

        # Outcome kaydet
        matching["outcome"] = {
            "actual_price": actual_price,
            "actual_return": round(actual_return, 2),
            "actual_direction": actual_direction,
            "holding_days": holding_days,
            "outcome_type": outcome_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        matching["resolved"] = True

        # Doğruluk
        is_correct = matching["predicted_direction"] == actual_direction
        self._accuracy_window.append(is_correct)
        if len(self._accuracy_window) > 200:
            self._accuracy_window = self._accuracy_window[-200:]

        # Regime bazlı doğruluk
        regime = matching.get("regime", "UNKNOWN")
        if regime not in self._regime_accuracy:
            self._regime_accuracy[regime] = {"correct": 0, "total": 0}
        self._regime_accuracy[regime]["total"] += 1
        if is_correct:
            self._regime_accuracy[regime]["correct"] += 1

        # Feature importance feedback
        self._update_feature_feedback(matching, is_correct, actual_return)

        # Öğrenme içgörüleri güncelle
        self._update_insights()

        self._save_state()

        logger.info("Outcome recorded",
                    ticker=ticker,
                    predicted=matching["predicted_direction"],
                    actual=actual_direction,
                    correct=is_correct,
                    return_pct=round(actual_return, 2))

    def _update_feature_feedback(self, prediction: Dict, is_correct: bool, actual_return: float):
        """Feature bazlı feedback — hangi feature'lar daha güvenilir?"""
        snapshot = prediction.get("feature_snapshot", {})

        for feature_name, value in snapshot.items():
            if feature_name not in self._feature_importance_feedback:
                self._feature_importance_feedback[feature_name] = 0.0

            # Doğru tahmin → bu feature'ın ağırlığını artır
            # Yanlış tahmin → azalt
            if is_correct:
                self._feature_importance_feedback[feature_name] += 0.01
            else:
                self._feature_importance_feedback[feature_name] -= 0.005

            # Sınırla [-1, 1]
            self._feature_importance_feedback[feature_name] = max(-1, min(1,
                self._feature_importance_feedback[feature_name]))

    def _update_insights(self):
        """Öğrenme içgörüleri güncelle."""
        resolved = [p for p in self._predictions if p["resolved"]]
        pending = [p for p in self._predictions if not p["resolved"]]

        # Temel metrikler her zaman güncellenmeli
        self._learning_insights["total_predictions"] = len(self._predictions)
        self._learning_insights["total_resolved"] = len(resolved)
        self._learning_insights["total_pending"] = len(pending)

        if not resolved:
            self._learning_insights["overall_accuracy"] = 0
            self._learning_insights["recent_accuracy"] = 0
            return

        # Genel doğruluk
        correct = sum(1 for p in resolved
                     if p["predicted_direction"] == p["outcome"]["actual_direction"])
        total = len(resolved)

        # Son 50 tahmin
        recent = resolved[-50:]
        recent_correct = sum(1 for p in recent
                           if p["predicted_direction"] == p["outcome"]["actual_direction"])

        # En iyi/kötü rejimler
        regime_perf = {}
        for regime, data in self._regime_accuracy.items():
            if data["total"] >= 5:
                regime_perf[regime] = round(data["correct"] / data["total"], 3)

        best_regime = max(regime_perf, key=regime_perf.get) if regime_perf else "N/A"
        worst_regime = min(regime_perf, key=regime_perf.get) if regime_perf else "N/A"

        # Hata analizi
        errors = [p for p in resolved if p["predicted_direction"] != p["outcome"]["actual_direction"]]
        error_patterns = self._analyze_errors(errors)

        self._learning_insights = {
            "total_predictions": len(self._predictions),
            "total_resolved": len(resolved),
            "overall_accuracy": round(correct / total, 4) if total > 0 else 0,
            "recent_accuracy": round(recent_correct / len(recent), 4) if recent else 0,
            "best_regime": best_regime,
            "best_regime_accuracy": regime_perf.get(best_regime, 0),
            "worst_regime": worst_regime,
            "worst_regime_accuracy": regime_perf.get(worst_regime, 0),
            "regime_performance": regime_perf,
            "error_patterns": error_patterns,
            "feature_feedback": dict(sorted(
                self._feature_importance_feedback.items(),
                key=lambda x: x[1], reverse=True
            )[:10]),
            "last_update": datetime.now(timezone.utc).isoformat(),
        }

    def _analyze_errors(self, errors: List[Dict]) -> Dict[str, Any]:
        """Hata kalıplarını analiz et."""
        if not errors:
            return {}

        # Hangi rejimde en çok hata yapılıyor?
        regime_errors = {}
        for err in errors:
            regime = err.get("regime", "UNKNOWN")
            regime_errors[regime] = regime_errors.get(regime, 0) + 1

        # Hangi score aralığında hata yapılıyor?
        score_errors = {"low": 0, "medium": 0, "high": 0}
        for err in errors:
            score = err.get("predicted_score", 50)
            if score < 50:
                score_errors["low"] += 1
            elif score < 70:
                score_errors["medium"] += 1
            else:
                score_errors["high"] += 1

        # Hangi conviction'da hata?
        conviction_errors = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
        for err in errors:
            conv = err.get("predicted_conviction", "LOW")
            conviction_errors[conv] = conviction_errors.get(conv, 0) + 1

        return {
            "total_errors": len(errors),
            "by_regime": regime_errors,
            "by_score_range": score_errors,
            "by_conviction": conviction_errors,
        }

    def get_decision_adjustment(self, ticker: str, regime: str, score: float) -> Dict[str, Any]:
        """Öğrenilen bilgiye göre karar ayarlaması öner.

        Bu, learning feedback'inin ana çıktısıdır.
        """
        adjustment = {
            "should_adjust": False,
            "confidence_modifier": 0.0,
            "warnings": [],
            "reason": "",
        }

        # Rejim bazlı performans
        regime_data = self._regime_accuracy.get(regime)
        if regime_data and regime_data["total"] >= 10:
            accuracy = regime_data["correct"] / regime_data["total"]
            if accuracy < 0.4:
                adjustment["should_adjust"] = True
                adjustment["confidence_modifier"] = -0.2
                adjustment["warnings"].append(f"Bu rejimde ({regime}) doğruluk düşük: %{accuracy*100:.0f}")
                adjustment["reason"] = f"Regime {regime} historically underperforms ({accuracy:.0%})"

        # Genel doğruluk düşükse
        if self._learning_insights.get("recent_accuracy", 0.5) < 0.45:
            adjustment["should_adjust"] = True
            adjustment["confidence_modifier"] -= 0.15
            adjustment["warnings"].append("Son tahminlerin doğruluğu düşük")

        # Yüksek skorlu tahminlerde hata yapılıyorsa
        error_patterns = self._learning_insights.get("error_patterns", {})
        high_score_errors = error_patterns.get("by_score_range", {}).get("high", 0)
        if high_score_errors > 5:
            adjustment["warnings"].append("Yüksek skorlu tahminlerde de hata yapılıyor")

        return adjustment

    def get_insights(self) -> Dict[str, Any]:
        """Öğrenme içgörüleri."""
        return dict(self._learning_insights)

    def get_prediction_history(self, limit: int = 20) -> List[Dict]:
        """Son tahmin geçmişi."""
        return self._predictions[-limit:]

    def get_pending_outcomes(self) -> List[Dict]:
        """Sonuç bekleyen tahminler."""
        return [p for p in self._predictions if not p["resolved"]]

    def _save_state(self):
        """Öğrenme durumunu diske kaydet."""
        try:
            LEARNING_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "predictions": self._predictions[-1000:],  # Son 1000 tahmin
                "regime_accuracy": self._regime_accuracy,
                "feature_importance_feedback": self._feature_importance_feedback,
                "accuracy_window": self._accuracy_window[-200:],
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(LEARNING_STATE_PATH, "w") as f:
                json.dump(state, f, default=str, indent=2)
        except Exception as e:
            logger.warning("Failed to save learning state", error=str(e))

    def _load_state(self):
        """Öğrenme durumunu diskten yükle."""
        try:
            if LEARNING_STATE_PATH.exists():
                with open(LEARNING_STATE_PATH) as f:
                    state = json.load(f)
                self._predictions = state.get("predictions", [])
                self._regime_accuracy = state.get("regime_accuracy", {})
                self._feature_importance_feedback = state.get("feature_importance_feedback", {})
                self._accuracy_window = state.get("accuracy_window", [])
                self._update_insights()
                logger.info("Learning state loaded",
                          predictions=len(self._predictions),
                          accuracy=self._learning_insights.get("overall_accuracy", 0))
        except Exception as e:
            logger.warning("Failed to load learning state", error=str(e))


# Singleton
integrated_learning = IntegratedLearningSystem()
