"""
ALPHA BIST — Feature Importance Tracker v1.0

SHAP-based feature importance tracking:
- Günlük SHAP hesaplama
- Zaman içinde trend analizi
- Regime-specific importance
- Feature selection önerileri

KURAL: Hangi feature ne kadar önemli, trend nasıl değişiyor?
"""

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
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
    regime_specific: dict[str, float]


class FeatureImportanceTracker:
    """SHAP-based feature importance tracking."""

    def __init__(self):
        """Otomatik eklendi."""
        self._history: deque = deque(maxlen=10000)
        self._last_importance: dict[str, float] = {}
        self._regime_importance: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    def track(
        self,
        model: Any,
        feature_names: list[str],
        X: np.ndarray,
        date: str,
        regime: str = "UNKNOWN",
        model_version: str = "v1",
        sample_size: int | None = None,
    ) -> Any:
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
        result = SHAPHelpers.compute_shap_values(model, X, feature_names, sample_size=sample_size)

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

        logger.info("Feature importance tracked", features=len(result.feature_importance), regime=regime, date=date)

    def get_trends(
        self,
        top_n: int = 20,
        window_days: int | None = None,
    ) -> dict[str, FeatureTrend]:
        """Feature importance trendleri.

        Args:
            top_n: En önemli N feature
            window_days: Trend penceresi (config default)

        Returns:
            {feature: FeatureTrend}
        """
        cfg = learning_settings.feature_importance
        window_days = window_days or cfg.trend_window_days

        cutoff = (datetime.now(UTC) - timedelta(days=window_days)).isoformat()
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
        sorted_trends = dict(
            sorted(
                trends.items(),
                key=lambda x: x[1].avg_importance,
                reverse=True,
            )[:top_n]
        )

        return sorted_trends

    def get_regime_importance(self, regime: str) -> dict[str, float]:
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

        return {feature: round(float(np.mean(values)), 6) for feature, values in feature_values.items() if values}

    def suggest_feature_selection(
        self,
        min_importance: float | None = None,
    ) -> list[str]:
        """Düşük importance'lı feature'ları öner (çıkarılabilir)."""
        cfg = learning_settings.feature_importance
        min_importance = min_importance or cfg.min_importance_threshold

        trends = self.get_trends(top_n=200)
        return [
            feature
            for feature, trend in trends.items()
            if trend.avg_importance < min_importance and trend.trend == "decreasing"
        ]

    def get_report(self) -> dict[str, Any]:
        """Feature importance raporu."""
        trends = self.get_trends(top_n=10)
        return {
            "status": "OK",
            "total_records": len(self._history),
            "unique_features": len(set(h.feature for h in self._history)),
            "top_features": {f: {"importance": t.avg_importance, "trend": t.trend} for f, t in trends.items()},
            "last_importance": self._last_importance,
        }

    def compute_stability_score(self, top_n: int = 20) -> dict[str, dict[str, Any]]:
        """Feature ranking stability score hesapla.

        Her feature'ın zaman içindeki ranking sırasının ne kadar stabil olduğunu ölçer.
        Yüksek skor = stabil ranking (iyi). Düşük skor = dalgalı ranking (kötü).

        Args:
            top_n: En önemli N feature

        Returns:
            {feature: {stability_score, avg_rank, rank_std, rank_trend}}
        """
        if len(self._history) < 5:
            return {}

        # Her tarih için feature ranking hesapla
        date_importances: dict[str, dict[str, float]] = defaultdict(dict)
        for h in self._history:
            date_importances[h.date][h.feature] = h.importance

        # Her tarih için ranking
        all_features = set(h.feature for h in self._history)
        date_rankings: dict[str, dict[str, int]] = {}

        for date, importances in date_importances.items():
            sorted_features = sorted(importances.items(), key=lambda x: x[1], reverse=True)
            date_rankings[date] = {f: rank for rank, (f, _) in enumerate(sorted_features)}

        # Her feature için ranking istatistikleri
        stability_scores = {}
        for feature in all_features:
            ranks = []
            for date_ranking in date_rankings.values():
                if feature in date_ranking:
                    ranks.append(date_ranking[feature])

            if len(ranks) < 3:
                continue

            avg_rank = float(np.mean(ranks))
            rank_std = float(np.std(ranks))

            # Stability score: 1 / (1 + rank_std) — düşük std = yüksek stabilite
            stability = 1.0 / (1.0 + rank_std)

            # Rank trend (son 3 vs ilk 3)
            if len(ranks) >= 6:
                recent_rank = np.mean(ranks[-3:])
                older_rank = np.mean(ranks[:3])
                if recent_rank < older_rank - 2:
                    rank_trend = "improving"  # Sıralama yükseldi (daha iyi)
                elif recent_rank > older_rank + 2:
                    rank_trend = "declining"  # Sıralama düştü (kötü)
                else:
                    rank_trend = "stable"
            else:
                rank_trend = "insufficient_data"

            stability_scores[feature] = {
                "stability_score": round(stability, 4),
                "avg_rank": round(avg_rank, 1),
                "rank_std": round(rank_std, 2),
                "rank_trend": rank_trend,
                "n_observations": len(ranks),
            }

        # Top N (avg_rank'a göre sırala)
        sorted_scores = dict(
            sorted(
                stability_scores.items(),
                key=lambda x: x[1]["avg_rank"],
            )[:top_n]
        )

        return sorted_scores

    def suggest_feature_selection_detailed(
        self,
        min_importance: float | None = None,
        min_stability: float = 0.3,
    ) -> dict[str, Any]:
        """Detaylı feature selection önerileri.

        Feature'ları 4 kategoriye ayırır:
        - KEEP: Yüksek importance + yüksek stabilite
        - MONITOR: Düşük importance ama stabil (potansiyel faydalı)
        - CONSIDER_DROPPING: Düşük importance + düşük stabilite
        - INVESTIGATE: Yüksek importance ama düşük stabilite (overfitting riski)

        Args:
            min_importance: Minimum importance eşiği
            min_stability: Minimum stabilite eşiği

        Returns:
            {keep: [...], monitor: [...], consider_dropping: [...], investigate: [...]}
        """
        cfg = learning_settings.feature_importance
        min_importance = min_importance or cfg.min_importance_threshold

        trends = self.get_trends(top_n=200)
        stability = self.compute_stability_score(top_n=200)

        keep = []
        monitor = []
        consider_dropping = []
        investigate = []

        for feature, trend in trends.items():
            stab = stability.get(feature, {}).get("stability_score", 0.5)
            avg_imp = trend.avg_importance

            if avg_imp >= min_importance and stab >= min_stability:
                keep.append(feature)
            elif avg_imp < min_importance and stab >= min_stability:
                monitor.append(feature)
            elif avg_imp < min_importance and stab < min_stability:
                consider_dropping.append(feature)
            else:  # avg_imp >= min_importance and stab < min_stability
                investigate.append(feature)

        return {
            "keep": keep,
            "monitor": monitor,
            "consider_dropping": consider_dropping,
            "investigate": investigate,
            "summary": {
                "total_features": len(trends),
                "keep_count": len(keep),
                "monitor_count": len(monitor),
                "consider_dropping_count": len(consider_dropping),
                "investigate_count": len(investigate),
            },
        }

    def save_history(self, path: str) -> None:
        """Feature importance geçmişini dosyaya kaydet (debounced — SSD dostu)."""
        from pathlib import Path

        import orjson

        from services.core.debounce import should_save
        if not should_save("feature_tracker_history", 120):
            return

        data = []
        for h in self._history:
            data.append(
                {
                    "date": h.date,
                    "feature": h.feature,
                    "importance": h.importance,
                    "regime": h.regime,
                    "model_version": h.model_version,
                }
            )

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2, default=str))

        logger.info("Feature history saved", path=path, records=len(data))

    def load_history(self, path: str) -> None:
        """Feature importance geçmişini dosyadan yükle (orjson)."""
        import orjson

        try:
            with open(path, "rb") as f:
                data = orjson.loads(f.read())

            for entry in data:
                record = FeatureImportanceRecord(
                    date=entry["date"],
                    feature=entry["feature"],
                    importance=entry["importance"],
                    regime=entry.get("regime", "UNKNOWN"),
                    model_version=entry.get("model_version", "v1"),
                )
                self._history.append(record)

            logger.info("Feature history loaded", path=path, records=len(data))
        except FileNotFoundError:
            logger.warning("Feature history file not found", path=path)
        except Exception as e:
            logger.error("Failed to load feature history", path=path, error=str(e))


# Singleton
feature_importance_tracker = FeatureImportanceTracker()
