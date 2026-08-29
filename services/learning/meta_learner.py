"""
ALPHA BIST — Meta Learner v1.0

Rejim-specific model selection ve ensemble optimization:
- Hangi model hangi rejimde daha iyi?
- Dynamic ensemble weights
- Model decay prediction
- Factor-based model routing

KURAL: Rejim değişince model seçimi de değişmeli.
"""

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

from services.learning.config.learning_config import learning_settings

logger = structlog.get_logger()


@dataclass
class ModelPerformance:
    """Model performans kaydı."""

    model_id: str
    regime: str
    sharpe: float
    win_rate: float
    ic: float
    timestamp: str


class MetaLearner:
    """Rejim-specific model selection ve ensemble optimization."""

    def __init__(self):
        """Otomatik eklendi."""
        self._regime_performance: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        self._model_history: deque = deque(maxlen=5000)
        self._current_regime: str = "UNKNOWN"

    def record_performance(
        self,
        model_id: str,
        regime: str,
        metrics: dict[str, float],
    ) -> Any:
        """Rejim bazlı performans kaydet."""
        scores = self._regime_performance[regime][model_id]
        scores.append(metrics.get("sharpe", 0))
        if len(scores) > 500:
            self._regime_performance[regime][model_id] = scores[-500:]
        self._current_regime = regime

        self._model_history.append(
            ModelPerformance(
                model_id=model_id,
                regime=regime,
                sharpe=metrics.get("sharpe", 0),
                win_rate=metrics.get("win_rate", 0),
                ic=metrics.get("ic", 0),
                timestamp=datetime.now(UTC).isoformat(),
            )
        )

    def select_best_model(self, regime: str) -> str | None:
        """Rejim için en iyi modeli seç."""
        if regime not in self._regime_performance:
            return None

        best_model = None
        best_score = -float("inf")
        cfg = learning_settings.meta_learning

        for model_id, scores in self._regime_performance[regime].items():
            if scores:
                recent = scores[-cfg.regime_performance_window :]
                avg_score = np.mean(recent)
                if avg_score > best_score:
                    best_score = avg_score
                    best_model = model_id

        return best_model

    def calculate_ensemble_weights(
        self,
        models: list[str],
        regime: str,
    ) -> dict[str, float]:
        """Dynamic ensemble weights — rejime göre."""
        weights = {}
        total_score = 0
        cfg = learning_settings.meta_learning

        for model in models:
            if regime in self._regime_performance and model in self._regime_performance[regime]:
                scores = self._regime_performance[regime][model]
                recent = scores[-cfg.regime_performance_window :]
                avg_sharpe = np.mean(recent) if recent else 0
            else:
                avg_sharpe = 0

            score = max(avg_sharpe, 0.01)
            weights[model] = score
            total_score += score

        if total_score <= 0:
            # Eşit ağırlık
            return {m: round(1.0 / len(models), 4) for m in models}

        return {m: round(w / total_score, 4) for m, w in weights.items()}

    def predict_decay(self, model_id: str) -> dict[str, Any]:
        """Model decay prediction — ne zaman retrain gerekli?"""
        cfg = learning_settings.meta_learning

        # Son performansları al
        recent_perfs = [p for p in self._model_history if p.model_id == model_id][-60:]

        if len(recent_perfs) < 30:
            return {"decay_predicted": False, "reason": "Insufficient data"}

        sharpes = [p.sharpe for p in recent_perfs]
        trend = float(np.polyfit(range(len(sharpes)), sharpes, 1)[0])

        if trend < cfg.decay_trend_threshold:
            current_sharpe = sharpes[-1]
            days_to_threshold = max(0, (current_sharpe - 0.3) / abs(trend)) if trend != 0 else 999

            return {
                "decay_predicted": True,
                "trend": round(trend, 6),
                "current_sharpe": round(current_sharpe, 4),
                "estimated_days_to_retrain": int(days_to_threshold),
            }

        return {"decay_predicted": False, "trend": round(trend, 6)}

    def get_regime_summary(self) -> dict[str, Any]:
        """Rejim özet raporu."""
        summary = {}
        for regime, models in self._regime_performance.items():
            model_avgs = {}
            for model_id, scores in models.items():
                if scores:
                    model_avgs[model_id] = {
                        "avg_sharpe": round(float(np.mean(scores)), 4),
                        "count": len(scores),
                        "trend": "improving" if len(scores) > 1 and scores[-1] > scores[0] else "declining",
                    }
            summary[regime] = model_avgs
        return summary

    def get_report(self) -> dict[str, Any]:
        """Rapor."""
        return {
            "current_regime": self._current_regime,
            "regime_count": len(self._regime_performance),
            "total_records": len(self._model_history),
            "regime_summary": self.get_regime_summary(),
        }


# Singleton
meta_learner = MetaLearner()
