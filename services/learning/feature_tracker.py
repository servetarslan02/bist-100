"""
ALPHA BIST — Feature Importance Tracker v1.0

SHAP-based feature importance tracking:
- Günlük SHAP hesaplama
- Zaman içinde trend analizi
- Regime-specific importance
- Feature selection önerileri

KURAL: Hangi feature ne kadar önemli, trend nasıl değişiyor?
"""

import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque
import structlog

from services.learning.config.learning_config import learning_settings
from services.learning.utils.shap_helpers import SHAPHelpers

logger = structlog.get_logger()


@dataclass
class FeatureImportanceRecord:
    """Feature importance kaydı."""
    date: str
    feature: str
    importance: float
    regime: str
    model_version: str


@dataclass
class FeatureTrend:
    """Feature trend bilgisi."""
    feature: str
    avg_importance: float
    trend: str  # increasing, decreasing, stable
    volatility: float
    regime_specific: Dict[str, float]


class FeatureImportanceTracker:
    """SHAP-based feature importance tracking."""

    def __init__(self):
        self._history: deque = deque(maxlen=10000)
        self._last_importance: Dict[str, float] = {}
        self._regime_importance: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))

    def track(
        self,
        model: Any,
        feature_names: List[str],
        X: np.ndarray,
        date: str,
        regime: str = "UNKNOWN",
        model_version: str = "v1",
        sample_size: Optional[int] = None,
    ):
        """Feature importance kaydet.

        Args:
            model: Eğitilmiş model
            feature_names: Feature isimleri
            X: Feature matrix
            date: Tarih
            regime: Rejim
            model_version: Model versiyonu
            sample_size: SHAP sample boyutu
        """
        cfg = learning_settings.feature_importance
        sample_size = sample_size or cfg.shap_sample_size

        # SHAP hesapla
        result = SHAPHelpers.compute_shap_values(
            model, X, feature_names, sample_size=sample_size
        )

        # Kaydet
        for name, importance in result.feature_importance.items():
            record = FeatureImportanceRecord(
                date=date,
                feature=name,
                importance=importance,
                regime=regime,
                model_version=model_version,
            )
            self._history.append(record)
            if len(self._history) > 1000:
                self._history = self._history[-1000:]

            # Rejim bazlı
            vals = self._regime_importance[regime][name]
            vals.append(importance)
            if len(vals) > 1000:
                self._regime_importance[regime][name] = vals[-1000:]

        # Son importance
        self._last_importance = result.feature_importance

        logger.info("Feature importance tracked",
                   features=len(result.feature_importance),
                   regime=regime, date=date)

    def get_trends(
        self,
        top_n: int = 20,
        window_days: Optional[int] = None,
    ) -> Dict[str, FeatureTrend]:
        """Feature importance trendleri.

        Args:
            top_n: En önemli N feature
            window_days: Trend penceresi (config default)

        Returns:
            {feature: FeatureTrend}
        """
        cfg = learning_settings.feature_importance
        window_days = window_days or cfg.trend_window_days

        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        recent = [h for h in self._history if h.date > cutoff]

        if not recent:
            return {}

        # Feature bazlı grupla
        feature_values = defaultdict(list)
        for h in recent:
            feature_values[h.feature].append(h.importance)

        trends = {}
        for feature, values in feature_values.items():
            if len(values) < 2:
                trend = "stable"
            elif values[-1] > values[0] * 1.1:
                trend = "increasing"
            elif values[-1] < values[0] * 0.9:
                trend = "decreasing"
            else:
                trend = "stable"

            # Rejim bazlı
            regime_avg = {}
            for regime, features in self._regime_importance.items():
                if feature in features and features[feature]:
                    regime_avg[regime] = round(float(np.mean(features[feature])), 6)

            trends[feature] = FeatureTrend(
                feature=feature,
                avg_importance=round(float(np.mean(values)), 6),
                trend=trend,
                volatility=round(float(np.std(values)), 6),
                regime_specific=regime_avg,
            )

        # Top N
        sorted_trends = dict(sorted(
            trends.items(),
            key=lambda x: x[1].avg_importance,
            reverse=True,
        )[:top_n])

        return sorted_trends

    def get_regime_importance(self, regime: str) -> Dict[str, float]:
        """Rejim-specific feature importance."""
        # _regime_importance'dan veya _history'den hesapla
        if regime in self._regime_importance and self._regime_importance[regime]:
            return {
                feature: round(float(np.mean(values)), 6)
                for feature, values in self._regime_importance[regime].items()
                if values
            }

        # Fallback: _history'den hesapla
        regime_data = [h for h in self._history if h.regime == regime]
        if not regime_data:
            return {}

        feature_values = defaultdict(list)
        for h in regime_data:
            feature_values[h.feature].append(h.importance)

        return {
            feature: round(float(np.mean(values)), 6)
            for feature, values in feature_values.items()
            if values
        }

    def suggest_feature_selection(
        self,
        min_importance: Optional[float] = None,
    ) -> List[str]:
        """Düşük importance'lı feature'ları öner (çıkarılabilir)."""
        cfg = learning_settings.feature_importance
        min_importance = min_importance or cfg.min_importance_threshold

        trends = self.get_trends(top_n=200)
        return [
            feature for feature, trend in trends.items()
            if trend.avg_importance < min_importance and trend.trend == "decreasing"
        ]

    def get_report(self) -> Dict[str, Any]:
        """Feature importance raporu."""
        trends = self.get_trends(top_n=10)
        return {
            "status": "OK",
            "total_records": len(self._history),
            "unique_features": len(set(h.feature for h in self._history)),
            "top_features": {
                f: {"importance": t.avg_importance, "trend": t.trend}
                for f, t in trends.items()
            },
            "last_importance": self._last_importance,
        }


# Singleton
feature_importance_tracker = FeatureImportanceTracker()
