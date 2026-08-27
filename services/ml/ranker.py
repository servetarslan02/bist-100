"""
ALPHA BIST — Learning-to-Rank Model v1.0

ROADMAP v3.0: Regresyon değil sıralama!
- LightGBM Ranker kullan (LGBMRanker)
- Her gün hisseleri sırala, en üsttekini al
- Bu tek başına +0.44 Sharpe katkısı

KURAL: En iyi hisseyi bul, fiyat tahmini yapma!
"""

from collections import defaultdict
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


class LearningToRankModel:
    """LightGBM Ranker ile hisse sıralama."""

    def __init__(self):
        self._model = None
        self._is_trained = False
        self._feature_names = [
            # Teknik
            "roc_5d",
            "roc_20d",
            "momentum_20d",
            "rsi_14",
            "volume_zscore",
            "volume_trend",
            "bb_position",
            "price_vs_sma20",
            "price_vs_sma50",
            "adx",
            "stoch_k",
            "stoch_d",
            "atr_pct",
            # Cross-sectional
            "momentum_20d_sector_zscore",
            "momentum_20d_bist_pct",
            "roc_5d_sector_ratio",
            "avg_peer_correlation",
            # Temporal
            "trend_slope",
            "trend_r2",
            "momentum_acceleration",
            "volatility_trend",
            "volume_trend_pct",
            # Fundamental
            "fundamental_score",
            "pe_ratio",
            "pb_ratio",
            "roe",
            # Sentiment
            "sentiment_score",
            "sentiment_momentum",
        ]
        logger.info("LearningToRankModel initialized")

    def prepare_training_data(
        self,
        features_map: dict[str, dict],
        returns: dict[str, float],  # Gelecek dönem getirileri
        date_groups: dict[str, str],  # Her hissenin tarihi (group için)
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Eğitim verisi hazırla."""

        X = []
        y = []
        groups = []

        # Tarih bazlı grupla
        date_tickers = defaultdict(list)
        for ticker, date in date_groups.items():
            date_tickers[date].append(ticker)

        for date, tickers in date_tickers.items():
            group_size = 0

            for ticker in tickers:
                if ticker not in features_map or ticker not in returns:
                    continue

                features = features_map[ticker]
                feature_vector = []

                for name in self._feature_names:
                    val = features.get(name, 0)
                    if val is None:
                        val = 0
                    feature_vector.append(float(val))

                X.append(feature_vector)
                y.append(returns[ticker])  # Getiri (rank target)
                group_size += 1

            if group_size > 0:
                groups.append(group_size)

        return np.array(X), np.array(y), np.array(groups)

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        groups: np.ndarray,
    ) -> dict[str, Any]:
        """Model eğit."""

        try:
            import lightgbm as lgb

            # Getirileri rank'e çevir (yüksek getiri = düşük rank numarası)
            # LightGBM ranker: düşük label = daha iyi (daha üst sıra)
            # Yani yüksek getiriyi düşük label yap
            y_rank = -y  # Negatif getiri (yüksek getiri = düşük rank)

            self._model = lgb.LGBMRanker(
                objective="lambdarank",
                metric="ndcg",
                ndcg_at=[5, 10, 20],
                learning_rate=0.05,
                num_leaves=31,
                min_data_in_leaf=20,
                feature_fraction=0.8,
                bagging_fraction=0.8,
                bagging_freq=5,
                verbose=-1,
            )

            self._model.fit(X, y_rank, group=groups)
            self._is_trained = True

            # Feature importance
            importance = self._model.feature_importances_
            self._feature_importance = {
                name: float(imp) for name, imp in zip(self._feature_names, importance, strict=False)
            }

            logger.info("Ranker trained successfully", samples=len(X), groups=len(groups))

            return {
                "success": True,
                "samples": len(X),
                "groups": len(groups),
                "feature_importance": dict(
                    sorted(self._feature_importance.items(), key=lambda x: x[1], reverse=True)[:10]
                ),
            }

        except ImportError:
            logger.warning("LightGBM not available")
            return {"success": False, "error": "LightGBM not installed"}
        except Exception as e:
            logger.error("Training failed", error=str(e))
            return {"success": False, "error": str(e)}

    def rank(
        self,
        features_map: dict[str, dict],
    ) -> list[dict[str, Any]]:
        """Hisseleri sırala."""

        if not self._is_trained or self._model is None:
            logger.warning("Model not trained, using fallback")
            return self._fallback_rank(features_map)

        tickers = []
        X = []

        for ticker, features in features_map.items():
            feature_vector = []
            for name in self._feature_names:
                val = features.get(name, 0)
                if val is None:
                    val = 0
                feature_vector.append(float(val))

            tickers.append(ticker)
            X.append(feature_vector)

        if not X:
            return []

        # Tahmin (düşük değer = daha iyi rank)
        predictions = self._model.predict(np.array(X))

        # Sırala (düşük tahmin = üst sıra)
        ranked = sorted(zip(tickers, predictions, strict=False), key=lambda x: x[1])

        return [
            {
                "ticker": ticker,
                "rank": i + 1,
                "score": round(float(pred), 4),
                "direction": "LONG" if pred < np.median(predictions) else "SHORT",
            }
            for i, (ticker, pred) in enumerate(ranked)
        ]

    def _fallback_rank(self, features_map: dict[str, dict]) -> list[dict[str, Any]]:
        """Model yoksa rule-based fallback."""

        scores = []
        for ticker, features in features_map.items():
            score = 0

            # Momentum
            score += features.get("momentum_20d", 0) * 0.3
            score += features.get("roc_5d", 0) * 0.2

            # Volume
            score += features.get("volume_zscore", 0) * 0.1

            # Cross-sectional
            score += features.get("momentum_20d_sector_zscore", 0) * 0.2

            # Fundamental
            score += features.get("fundamental_score", 0) * 0.1

            # Sentiment
            score += features.get("sentiment_score", 0) * 0.1

            scores.append((ticker, score))

        scores.sort(key=lambda x: x[1], reverse=True)

        return [
            {
                "ticker": ticker,
                "rank": i + 1,
                "score": round(score, 4),
                "direction": "LONG" if score > 0 else "SHORT",
            }
            for i, (ticker, score) in enumerate(scores)
        ]

    def get_feature_importance(self) -> dict[str, float]:
        """Feature importance."""
        if self._is_trained:
            return dict(sorted(self._feature_importance.items(), key=lambda x: x[1], reverse=True))
        return {}


# Singleton
ranker_model = LearningToRankModel()
