"""
ALPHA BIST — Ranking Model v2.0 (Düzeltilmiş)

Feature isimleri feature_store ile senkronize.
LightGBM + Rule-based hybrid.

FAZ 6: ML Ranking
"""

import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timezone
from collections import defaultdict
import structlog

logger = structlog.get_logger()

@dataclass
class OpportunityScore:
    ticker: str
    score: float
    direction: str
    confidence: float
    regime: str
    signals: Dict
    features: Dict

class RankingModel:
    """Hisse sıralama modeli."""

    def __init__(self):
        self._model = None
        self._is_trained = False
        self._feature_names = [
            "roc_5d", "roc_20d", "momentum_20d", "rsi_14",
            "volume_zscore", "volume_trend", "bb_position",
            "price_vs_sma20", "price_vs_sma50", "adx",
            "sentiment_score", "sentiment_momentum",
            "fundamental_score", "pe_ratio", "pb_ratio",
            "debt_to_equity", "roe", "profit_margin",
            "atr_14", "atr_pct",
        ]

        # Feature isimleri SENKRONIZE (feature_store ile aynı)
        self._rule_weights = {
            # Teknik göstergeler (feature_store'daki isimlerle eşleşiyor)
            "roc_5d": 0.12,
            "roc_20d": 0.08,
            "momentum_20d": 0.15,
            "rsi_14": 0.10,
            "volume_zscore": 0.08,
            "volume_trend": 0.06,
            "bb_position": 0.08,
            "price_vs_sma20": 0.06,
            "price_vs_sma50": 0.05,
            "adx": 0.04,

            # Sentiment
            "sentiment_score": 0.06,
            "sentiment_momentum": 0.04,

            # Fundamental
            "fundamental_score": 0.05,
            "pe_ratio": 0.02,
            "pb_ratio": 0.02,
            "debt_to_equity": 0.02,
            "roe": 0.02,
            "profit_margin": 0.02,

            # Risk
            "atr_14": -0.03,  # Yüksek ATR = düşük skor
            "atr_pct": -0.02,
        }

        logger.info("RankingModel initialized", features=len(self._feature_names))

    def train(self, training_data: List[Dict]):
        """Model eğit."""
        logger.info("Training ranking model...")

        try:
            import lightgbm as lgb

            # Basit eğitim (gerçek veri ile değiştirilecek)
            X = []
            y = []

            for sample in training_data:
                features = []
                for name in self._feature_names:
                    features.append(sample.get(name, 0))
                X.append(features)
                y.append(sample.get("target", 0))

            if len(X) < 10:
                logger.warning("Insufficient training data, using rule-based")
                self._is_trained = False
                return

            train_data = lgb.Dataset(X, label=y, feature_name=self._feature_names)

            params = {
                "objective": "regression",
                "metric": "rmse",
                "boosting_type": "gbdt",
                "num_leaves": 31,
                "learning_rate": 0.05,
                "feature_fraction": 0.9,
                "bagging_fraction": 0.8,
                "bagging_freq": 5,
                "verbose": -1,
            }

            self._model = lgb.train(params, train_data, num_boost_round=100)
            self._is_trained = True

            # Feature importance
            importance = self._model.feature_importance(importance_type="gain")
            self._feature_importance = {
                name: float(imp)
                for name, imp in zip(self._feature_names, importance)
            }

            logger.info("Model trained successfully")

        except ImportError:
            logger.warning("LightGBM not available, using rule-based")
            self._is_trained = False
        except Exception as e:
            logger.error("Training failed", error=str(e))
            self._is_trained = False

    def rank(self, features_map: Dict, regime: str) -> List[OpportunityScore]:
        """Hisseleri sırala."""
        scores = []

        for ticker, features in features_map.items():
            try:
                score, direction, confidence = self._calculate_score(features, regime)

                opp = OpportunityScore(
                    ticker=ticker,
                    score=score,
                    direction=direction,
                    confidence=confidence,
                    regime=regime,
                    signals={},
                    features=features,
                )
                scores.append(opp)

            except Exception as e:
                logger.warning(f"Scoring failed for {ticker}", error=str(e))

        # Sırala
        scores.sort(key=lambda x: x.score, reverse=True)
        return scores

    def _calculate_score(self, features: Dict, regime: str) -> tuple:
        """Skor hesapla."""

        if self._is_trained and self._model:
            # ML skoru
            x = [features.get(name, 0) for name in self._feature_names]
            ml_score = self._model.predict([x])[0]
        else:
            # Rule-based skor
            ml_score = self._rule_based_score(features)

        # Regime ayarı
        regime_multiplier = self._regime_multiplier(regime)
        adjusted_score = ml_score * regime_multiplier

        # Yön belirle
        momentum = features.get("momentum_20d", 0)
        roc = features.get("roc_5d", 0)
        rsi = features.get("rsi_14", 50)

        if momentum > 0 and roc > 0 and rsi > 50:
            direction = "LONG"
        elif momentum < 0 and roc < 0 and rsi < 50:
            direction = "SHORT"
        else:
            direction = "LONG" if adjusted_score > 50 else "SHORT"

        # Güven
        confidence = min(adjusted_score, 100)

        return adjusted_score, direction, confidence

    def _rule_based_score(self, features: Dict) -> float:
        """Kural bazlı skor hesapla."""
        score = 50.0  # Başlangıç

        for feature_name, weight in self._rule_weights.items():
            value = features.get(feature_name, 0)

            # Normalize et
            if feature_name in ["rsi_14"]:
                # RSI: 30-70 arası normalize
                normalized = (value - 30) / 40 * 100
                normalized = max(0, min(100, normalized))
            elif feature_name in ["pe_ratio", "pb_ratio", "debt_to_equity"]:
                # Düşük değerler iyi
                normalized = max(0, 100 - value * 10)
            elif feature_name in ["atr_14", "atr_pct"]:
                # Düşük volatilite iyi
                normalized = max(0, 100 - value * 5)
            else:
                # Diğerleri: -100 to 100 arası
                normalized = max(-100, min(100, value))
                normalized = (normalized + 100) / 2  # 0-100 arası

            score += normalized * weight

        # Sınırla
        score = max(0, min(100, score))

        return score

    def _regime_multiplier(self, regime: str) -> float:
        """Rejim çarpanı."""
        multipliers = {
            "BULL": 1.2,
            "BULL_VOLATILE": 1.1,
            "BEAR": 0.7,
            "BEAR_VOLATILE": 0.6,
            "SIDEWAYS": 0.9,
            "SIDEWAYS_VOLATILE": 0.8,
            "RECOVERY": 1.0,
            "DISTRIBUTION": 0.7,
            "ACCUMULATION": 1.1,
            "CRASH": 0.5,
            "UNKNOWN": 1.0,
        }
        return multipliers.get(regime, 1.0)

    def get_feature_importance(self) -> Dict[str, float]:
        """Feature importance."""
        if self._is_trained:
            return dict(self._feature_importance)

        # Rule-based importance
        return dict(self._rule_weights)

    def get_top_opportunities(self, features_map: Dict, regime: str, limit: int = 20) -> List[Dict]:
        """En iyi fırsatları getir."""
        scores = self.rank(features_map, regime)

        return [
            {
                "ticker": s.ticker,
                "score": round(s.score, 1),
                "direction": s.direction,
                "confidence": round(s.confidence, 1),
                "regime": s.regime,
            }
            for s in scores[:limit]
        ]

# Singleton
ranking_model = RankingModel()
