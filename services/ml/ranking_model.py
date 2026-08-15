"""
ALPHA BIST — Ranking Model v1.0

LightGBM Ranker + Adjusted-MSE Loss + Regime-Aware + Feature Importance

Kaynaklar:
- Du (2026): Adjusted-MSE loss, wrong direction 11x penalty
- Oxford (2023): Spatio-temporal combined model
- Huang (2026): Non-linear factor aggregation via LightGBM

Hedef: Cross-sectional ranking (regresyon değil)
"""

import numpy as np
import json
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import structlog

logger = structlog.get_logger()

try:
    import lightgbm as lgb
    HAS_LGBM = True
except ImportError:
    HAS_LGBM = False
    logger.warning("LightGBM not installed, using rule-based fallback")


@dataclass
class RankingPrediction:
    """Ranking model çıktısı."""
    ticker: str
    rank_score: float           # 0-1 arası (0=en kötü, 1=en iyi)
    predicted_direction: str    # LONG / SHORT / NEUTRAL
    confidence: float           # 0-1
    feature_importance: Dict[str, float]
    model_source: str           # lightgbm | rule_based
    regime: str


@dataclass
class ModelMetrics:
    """Model performans metrikleri."""
    precision_at_5: float
    precision_at_10: float
    precision_at_20: float
    ic: float                   # Information Coefficient
    hit_rate: float
    sharpe: float
    max_drawdown: float
    turnover: float
    total_predictions: int


class AdjustedMSELoss:
    """Adjusted-MSE Loss: Yanlış yön cezası 11x.

    Kaynak: Du (2026) — Chinese A-share

    Normal MSE: (predicted - actual)²
    Adjusted MSE: (predicted - actual)² × penalty_multiplier

    penalty_multiplier:
    - Aynı yön: 1×
    - Farklı yön: 11× (Du 2026'da 11× kullanmış)
    """

    WRONG_DIRECTION_PENALTY = 11.0

    @staticmethod
    def compute(predictions: np.ndarray, actuals: np.ndarray) -> float:
        """Adjusted MSE hesapla."""
        errors = predictions - actuals
        penalties = np.ones(len(errors))

        # Yanlış yön tespiti
        pred_positive = predictions > 0
        actual_positive = actuals > 0
        wrong_direction = pred_positive != actual_positive
        penalties[wrong_direction] = AdjustedMSELoss.WRONG_DIRECTION_PENALTY

        adjusted_mse = np.mean((errors ** 2) * penalties)
        return float(adjusted_mse)

    @staticmethod
    def compute_lgbm_objective(predictions: np.ndarray, dataset) -> Tuple[np.ndarray, np.ndarray]:
        """LightGBM custom objective (adjusted MSE gradient)."""
        actuals = dataset.get_label()
        errors = predictions - actuals

        # Penalties
        penalties = np.ones(len(errors))
        wrong_dir = (predictions > 0) != (actuals > 0)
        penalties[wrong_dir] = AdjustedMSELoss.WRONG_DIRECTION_PENALTY

        # Gradient: d/d_pred = 2 * error * penalty
        grad = 2 * errors * penalties
        # Hessian: d²/d_pred² = 2 * penalty
        hess = 2 * penalties

        return grad, hess


class FeatureImportanceTracker:
    """Feature importance takibi."""

    def __init__(self):
        self._importance_history: Dict[str, List[float]] = {}
        self._regime_importance: Dict[str, Dict[str, List[float]]] = {}

    def record(self, importance: Dict[str, float], regime: str = "UNKNOWN"):
        """Feature importance kaydet."""
        for feat, imp in importance.items():
            if feat not in self._importance_history:
                self._importance_history[feat] = []
            self._importance_history[feat].append(imp)

            # Regime bazlı
            if regime not in self._regime_importance:
                self._regime_importance[regime] = {}
            if feat not in self._regime_importance[regime]:
                self._regime_importance[regime][feat] = []
            self._regime_importance[regime][feat].append(imp)

    def get_top_features(self, n: int = 20) -> List[Tuple[str, float]]:
        """En önemli N feature."""
        avg_importance = {}
        for feat, values in self._importance_history.items():
            avg_importance[feat] = np.mean(values[-100:])  # Son 100 model
        return sorted(avg_importance.items(), key=lambda x: x[1], reverse=True)[:n]

    def get_regime_importance(self, regime: str) -> Dict[str, float]:
        """Belirli rejimdeki feature importance."""
        regime_data = self._regime_importance.get(regime, {})
        return {feat: float(np.mean(values[-50:])) for feat, values in regime_data.items() if values}

    def get_stability_score(self) -> float:
        """Feature importance stabilitesi (0-1)."""
        if len(self._importance_history) < 10:
            return 0.0

        # Son 10 model arasındaki korelasyon
        recent_importances = []
        for feat, values in self._importance_history.items():
            if len(values) >= 10:
                recent_importances.append(values[-10:])

        if len(recent_importances) < 5:
            return 0.0

        # Ortalama korelasyon
        correlations = []
        arr = np.array(recent_importances)
        for i in range(len(arr)):
            for j in range(i + 1, min(len(arr), i + 5)):
                if np.std(arr[i]) > 0 and np.std(arr[j]) > 0:
                    corr = np.corrcoef(arr[i], arr[j])[0, 1]
                    if not np.isnan(corr):
                        correlations.append(corr)

        return float(np.mean(correlations)) if correlations else 0.0


class LightGBMRanker:
    """LightGBM Ranker modeli."""

    def __init__(self):
        self._model: Optional[Any] = None
        self._feature_names: List[str] = []
        self._is_trained = False
        self._train_metrics: Optional[ModelMetrics] = None

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        groups: List[int],
        feature_names: List[str],
        params: Optional[Dict] = None,
    ) -> ModelMetrics:
        """Modeli eğit.

        Args:
            X: Feature matrix (n_samples × n_features)
            y: Target (cross-sectional rank, 0-1)
            groups: Her query grubundaki sample sayısı (her gün için)
            feature_names: Feature isimleri
        """
        if not HAS_LGBM:
            logger.warning("LightGBM not available, skipping training")
            return ModelMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0)

        self._feature_names = feature_names

        # Dataset oluştur
        # lambdarank integer label gerektirir, regression kullanıp
        # sonra cross-sectional rank'a çeviriyoruz
        train_data = lgb.Dataset(X, label=y, feature_name=feature_names)

        # Parametreler (regression — ranking için daha esnek)
        default_params = {
            "objective": "regression",
            "metric": "rmse",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "max_depth": 6,
            "min_child_samples": 20,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.1,
            "reg_lambda": 0.1,
            "verbose": -1,
            "seed": 42,
        }

        if params:
            default_params.update(params)

        # Eğit
        self._model = lgb.train(
            default_params,
            train_data,
            num_boost_round=500,
            valid_sets=[train_data],
            callbacks=[lgb.log_evaluation(0)],  # Sessiz
        )

        self._is_trained = True

        # Feature importance
        importance = self._model.feature_importance(importance_type="gain")
        feat_imp = dict(zip(feature_names, importance.tolist()))

        logger.info("LightGBM Ranker trained",
                    features=len(feature_names),
                    rounds=self._model.num_trees())

        return ModelMetrics(
            precision_at_5=0, precision_at_10=0, precision_at_20=0,
            ic=0, hit_rate=0, sharpe=0, max_drawdown=0, turnover=0,
            total_predictions=len(y),
        )

    def predict(self, X: np.ndarray, feature_names: Optional[List[str]] = None) -> np.ndarray:
        """Tahmin yap."""
        if not self._is_trained or self._model is None:
            return np.zeros(X.shape[0])

        try:
            predictions = self._model.predict(X)
            # 0-1 arası normalize
            if len(predictions) > 1:
                min_p = np.min(predictions)
                max_p = np.max(predictions)
                if max_p > min_p:
                    predictions = (predictions - min_p) / (max_p - min_p)
            return predictions
        except Exception as e:
            logger.error("Prediction failed", error=str(e))
            return np.zeros(X.shape[0])

    def get_feature_importance(self) -> Dict[str, float]:
        """Feature importance döndür."""
        if not self._is_trained or self._model is None:
            return {}

        importance = self._model.feature_importance(importance_type="gain")
        total = np.sum(importance)
        if total > 0:
            return dict(zip(self._feature_names, (importance / total).tolist()))
        return {}


class RuleBasedRanker:
    """Kural tabanlı ranking (LightGBM yokken fallback)."""

    # Feature ağırlıkları (rejime göre değişebilir)
    DEFAULT_WEIGHTS = {
        "rs_vs_bist_5d": 0.15,
        "rs_vs_bist_20d": 0.10,
        "momentum_acceleration": 0.10,
        "trend_slope_20d": 0.10,
        "volume_percentile": 0.08,
        "tick_rule": 0.07,
        "raw_pe_ratio": -0.05,  # Negatif: düşük P/E tercih edilir
        "balance_sheet_quality": 0.08,
        "kap_sentiment_avg": 0.07,
        "catalyst_importance": 0.05,
        "drawdown_20d": -0.05,  # Negatif: düşük drawdown tercih edilir
        "why_falling": -0.10,   # Negatif: düşen hisse cezalandır
    }

    REGIME_WEIGHTS = {
        "BULL": {"momentum_acceleration": 0.15, "rs_vs_bist_5d": 0.20, "why_falling": -0.05},
        "BEAR": {"balance_sheet_quality": 0.15, "drawdown_20d": -0.10, "why_falling": -0.15},
        "HIGH-VOLATILITY": {"volume_percentile": 0.12, "tick_rule": 0.10, "drawdown_20d": -0.08},
    }

    def predict(
        self,
        features_list: List[Dict[str, float]],
        regime: str = "UNKNOWN",
    ) -> List[RankingPrediction]:
        """Kural tabanlı ranking."""
        weights = dict(self.DEFAULT_WEIGHTS)
        regime_overrides = self.REGIME_WEIGHTS.get(regime, {})
        weights.update(regime_overrides)

        # Önce ham skorları hesapla
        raw_scores = []
        for features in features_list:
            ticker = features.get("ticker", "UNKNOWN")
            score = 0.0

            for feat_name, weight in weights.items():
                value = features.get(feat_name, 0)
                if value is not None:
                    score += value * weight

            raw_scores.append((ticker, score, features))

        # Cross-sectional normalize (0-1 arası)
        if raw_scores:
            scores = [s[1] for s in raw_scores]
            min_score = min(scores)
            max_score = max(scores)
            range_score = max_score - min_score if max_score > min_score else 1
        else:
            min_score = 0
            range_score = 1

        predictions = []
        for ticker, raw_score, features in raw_scores:
            # 0-1 arası normalize
            rank_score = (raw_score - min_score) / range_score
            rank_score = max(0, min(1, rank_score))

            # Yön belirle
            if rank_score > 0.6:
                direction = "LONG"
            elif rank_score < 0.4:
                direction = "SHORT"
            else:
                direction = "NEUTRAL"

            predictions.append(RankingPrediction(
                ticker=ticker,
                rank_score=round(rank_score, 4),
                predicted_direction=direction,
                confidence=round(abs(rank_score - 0.5) * 2, 4),
                feature_importance={k: abs(v) for k, v in weights.items()},
                model_source="rule_based",
                regime=regime,
            ))

        # Rank'a göre sırala
        predictions.sort(key=lambda p: p.rank_score, reverse=True)
        return predictions


class RankingModel:
    """Ana ranking modeli — LightGBM + Rule-based ensemble."""

    def __init__(self):
        self._lgbm = LightGBMRanker()
        self._rule_based = RuleBasedRanker()
        self._importance_tracker = FeatureImportanceTracker()
        self._model_path = Path("ml/ranking_model")
        self._model_path.mkdir(parents=True, exist_ok=True)

    def train(
        self,
        feature_matrix: np.ndarray,
        labels: np.ndarray,
        groups: List[int],
        feature_names: List[str],
        regime: str = "UNKNOWN",
    ) -> ModelMetrics:
        """Modeli eğit."""
        metrics = self._lgbm.train(feature_matrix, labels, groups, feature_names)

        # Feature importance kaydet
        importance = self._lgbm.get_feature_importance()
        if importance:
            self._importance_tracker.record(importance, regime)

        # Modeli kaydet
        self._save_model()

        return metrics

    def predict(
        self,
        features_list: List[Dict[str, float]],
        regime: str = "UNKNOWN",
    ) -> List[RankingPrediction]:
        """Tahmin yap."""
        if self._lgbm._is_trained:
            # LightGBM ile tahmin
            feature_names = self._lgbm._feature_names
            X = np.array([[f.get(name, 0) for name in feature_names] for f in features_list])
            raw_predictions = self._lgbm.predict(X)

            predictions = []
            for i, features in enumerate(features_list):
                ticker = features.get("ticker", "UNKNOWN")
                rank_score = float(raw_predictions[i])

                if rank_score > 0.6:
                    direction = "LONG"
                elif rank_score < 0.4:
                    direction = "SHORT"
                else:
                    direction = "NEUTRAL"

                predictions.append(RankingPrediction(
                    ticker=ticker,
                    rank_score=round(rank_score, 4),
                    predicted_direction=direction,
                    confidence=round(abs(rank_score - 0.5) * 2, 4),
                    feature_importance=self._lgbm.get_feature_importance(),
                    model_source="lightgbm",
                    regime=regime,
                ))

            predictions.sort(key=lambda p: p.rank_score, reverse=True)
            return predictions
        else:
            # Rule-based fallback
            return self._rule_based.predict(features_list, regime)

    def get_feature_importance(self, regime: Optional[str] = None) -> Dict[str, float]:
        """Feature importance."""
        if regime:
            return self._importance_tracker.get_regime_importance(regime)
        return dict(self._importance_tracker.get_top_features(20))

    def get_model_status(self) -> Dict[str, Any]:
        """Model durumu."""
        return {
            "lightgbm_trained": self._lgbm._is_trained,
            "feature_count": len(self._lgbm._feature_names),
            "importance_stability": self._importance_tracker.get_stability_score(),
            "top_features": dict(self._importance_tracker.get_top_features(10)),
        }

    def _save_model(self):
        """Modeli diske kaydet."""
        try:
            if self._lgbm._model:
                self._lgbm._model.save_model(str(self._model_path / "model.txt"))
                with open(self._model_path / "features.json", "w") as f:
                    json.dump(self._lgbm._feature_names, f)
                logger.info("Model saved", path=str(self._model_path))
        except Exception as e:
            logger.warning("Model save failed", error=str(e))

    def load_model(self) -> bool:
        """Modeli diskten yükle."""
        try:
            model_file = self._model_path / "model.txt"
            features_file = self._model_path / "features.json"

            if model_file.exists() and features_file.exists() and HAS_LGBM:
                self._lgbm._model = lgb.Booster(model_file=str(model_file))
                with open(features_file) as f:
                    self._lgbm._feature_names = json.load(f)
                self._lgbm._is_trained = True
                logger.info("Model loaded", features=len(self._lgbm._feature_names))
                return True
        except Exception as e:
            logger.warning("Model load failed", error=str(e))
        return False


# Singleton
ranking_model = RankingModel()
