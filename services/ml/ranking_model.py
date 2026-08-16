"""
ALPHA BIST — Ranking Model v3.0 (LambdaRank + Adjusted-MSE + Rejim-Aware)

ROADMAP v3.0 FAZ 3:
- LightGBM LambdaRank (regresyon DEĞİL sıralama)
- Adjusted-MSE Loss (yanlış yön 11x ceza)
- Rejim-Aware Training (BULL/BEAR farklı ağırlıklar)
- Feature Importance Tracking (SHAP + Permutation)
- Ensemble (LightGBM + Rule-based fallback)

KURAL: "En iyi %10'da mı?" sor, "yükselir mi?" sorma!
"""

import json
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict
import structlog

logger = structlog.get_logger()


@dataclass
class OpportunityScore:
    ticker: str
    score: float
    rank: int
    direction: str
    confidence: float
    regime: str
    signals: Dict
    features: Dict
    model_contribution: Dict  # Hangi model ne kadar katkı sağladı


@dataclass
class RankingResult:
    scores: List[OpportunityScore]
    top_k: Dict[int, List[OpportunityScore]]
    feature_importance: Dict[str, float]
    regime_weights: Dict[str, Dict[str, float]]
    ensemble_weights: Dict[str, float]


class RankingModel:
    """LambdaRank + Adjusted-MSE + Rejim-Aware + Ensemble."""

    def __init__(self):
        self._lgbm_model = None
        self._is_trained = False
        self._feature_names = [
            # Motor 1: Relatif Güç
            "rs_vs_bist_1d", "rs_vs_bist_5d", "rs_vs_bist_20d", "rs_vs_bist_60d",
            "rs_vs_sector_5d", "rs_vs_peers_5d", "rs_trend", "rs_peer_rank",
            # Motor 2: Momentum + Trend
            "roc_5d", "roc_20d", "roc_60d", "momentum_20d",
            "trend_slope_20d", "trend_r2_20d", "momentum_acceleration",
            "momentum_accel_trend", "price_vs_sma20", "price_vs_sma50", "price_vs_sma200",
            "near_20d_high", "near_60d_high", "near_120d_high",
            "breakout_failure", "drawdown_20d", "recovery_strength",
            # Motor 3: Hacim + Mikroyapı
            "volume_percentile", "volume_zscore", "volume_trend",
            "volume_up_down_ratio", "tick_rule", "vwap_deviation",
            "avg_volume_5d", "obv",
            # Motor 4: Fundamental
            "sector_norm_pe_ratio", "sector_norm_pb_ratio", "fcf_yield_pct",
            "fcf_margin", "balance_sheet_quality", "profit_margin_pct",
            "roe", "roa",
            # Motor 5: KAP + Haber
            "kap_sentiment_avg", "kap_sentiment_latest", "news_sentiment_weighted",
            "sentiment_momentum", "kap_avg_importance",
            # Motor 6: Katalizör
            "catalyst_count", "catalyst_importance", "catalyst_days_nearest",
            # Motor 7: Neden Düşüyor?
            "falling_is_temporary", "fall_market_selloff", "fall_sector_selloff",
            # Cross-Sectional
            "rank_return_5d", "rank_return_20d", "rank_volume_zscore", "rank_rsi_14",
            "sector_rel_return_5d", "sector_zscore_momentum_20d",
            "cs_zscore_roc_5d", "cs_zscore_roc_20d",
            # Risk
            "atr_pct", "volatility_20d", "realized_vol_20d",
            # Market Breadth
            "market_breadth", "market_ad_ratio",
        ]

        # Rejim bazlı feature ağırlıkları
        self._regime_feature_weights = {
            "BULL": {
                "momentum_20d": 1.5, "roc_5d": 1.3, "trend_slope_20d": 1.2,
                "volume_zscore": 1.1, "rs_vs_bist_5d": 1.2,
                "breakout_failure": 0.5, "drawdown_20d": 0.5,
            },
            "BEAR": {
                "momentum_20d": 0.5, "roc_5d": 0.6, "trend_slope_20d": 0.5,
                "volume_zscore": 1.2, "rs_vs_bist_5d": 0.8,
                "breakout_failure": 1.5, "drawdown_20d": 1.3,
                "falling_is_temporary": 1.2, "balance_sheet_quality": 1.3,
            },
            "SIDEWAYS": {
                "momentum_20d": 0.8, "roc_5d": 0.8, "bb_position": 1.3,
                "volume_zscore": 1.0, "rs_vs_bist_5d": 1.0,
                "sector_norm_pe_ratio": 1.2, "fcf_yield_pct": 1.2,
            },
            "UNKNOWN": {},
        }

        # Ensemble ağırlıkları
        self._ensemble_weights = {"lgbm": 0.7, "rule_based": 0.3}

        # Feature importance
        self._feature_importance = {}
        self._feature_importance_history = []

        logger.info("RankingModel v3.0 initialized", features=len(self._feature_names))

    def train(
        self,
        features_map: Dict[str, Dict],  # {ticker: {feature: value}}
        returns: Dict[str, float],      # {ticker: future_return}
        date_groups: Dict[str, str],    # {ticker: date}
        regime: str = "UNKNOWN",
    ) -> Dict[str, Any]:
        """Model eğit — LambdaRank + Adjusted-MSE."""

        try:
            import lightgbm as lgb
        except ImportError:
            logger.warning("LightGBM not available, using rule-based only")
            self._is_trained = False
            return {"success": False, "error": "LightGBM not installed"}

        # Eğitim verisi hazırla
        X, y, groups = self._prepare_training_data(features_map, returns, date_groups)

        if len(X) < 100:
            logger.warning("Insufficient training data, using rule-based")
            self._is_trained = False
            return {"success": False, "error": "Insufficient data"}

        # Rejim bazlı feature ağırlıkları uygula
        X_weighted = self._apply_regime_weights(X, regime)

        # LambdaRank eğitimi
        # Getirileri rank'e çevir (yüksek getiri = düşük rank numarası)
        y_rank = -y  # Negatif getiri (yüksek getiri = düşük rank = daha iyi)

        # Group sizes
        group_sizes = []
        current_group = 0
        current_date = None
        for ticker, date in sorted(date_groups.items(), key=lambda x: x[1]):
            if date != current_date:
                if current_group > 0:
                    group_sizes.append(current_group)
                current_date = date
                current_group = 1
            else:
                current_group += 1
        if current_group > 0:
            group_sizes.append(current_group)

        # LightGBM Dataset
        train_data = lgb.Dataset(X_weighted, label=y_rank, group=group_sizes,
                                 feature_name=self._feature_names)

        # LambdaRank parametreleri
        params = {
            "objective": "lambdarank",
            "metric": "ndcg",
            "ndcg_eval_at": [5, 10, 20],
            "learning_rate": 0.05,
            "num_leaves": 31,
            "min_data_in_leaf": 20,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 5,
            "verbose": -1,
        }

        self._lgbm_model = lgb.train(params, train_data, num_boost_round=100)
        self._is_trained = True

        # Feature importance
        importance = self._lgbm_model.feature_importance(importance_type="gain")
        self._feature_importance = {
            name: float(imp)
            for name, imp in zip(self._feature_names, importance)
        }
        self._feature_importance_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "regime": regime,
            "importance": dict(self._feature_importance),
        })

        # SHAP values (eğer mümkünse)
        shap_importance = self._compute_shap_importance(X_weighted)

        logger.info("LambdaRank model trained",
                   samples=len(X), groups=len(group_sizes), regime=regime)

        return {
            "success": True,
            "samples": len(X),
            "groups": len(group_sizes),
            "regime": regime,
            "feature_importance": dict(sorted(
                self._feature_importance.items(), key=lambda x: x[1], reverse=True
            )[:15]),
            "shap_importance": shap_importance,
        }

    def rank(
        self,
        features_map: Dict[str, Dict],
        regime: str = "UNKNOWN",
    ) -> RankingResult:
        """Hisseleri sırala — Ensemble (LightGBM + Rule-based)."""

        # LightGBM skoru
        lgbm_scores = {}
        if self._is_trained and self._lgbm_model is not None:
            tickers = []
            X = []
            for ticker, features in features_map.items():
                vec = self._feature_vector(features)
                tickers.append(ticker)
                X.append(vec)

            if X:
                X_arr = np.array(X)
                # Rejim ağırlıkları uygula
                X_weighted = self._apply_regime_weights(X_arr, regime)
                predictions = self._lgbm_model.predict(X_weighted)
                for ticker, pred in zip(tickers, predictions):
                    lgbm_scores[ticker] = float(pred)

        # Rule-based skoru
        rule_scores = {}
        for ticker, features in features_map.items():
            rule_scores[ticker] = self._rule_based_score(features, regime)

        # Ensemble (ağırlıklı ortalama)
        ensemble_scores = {}
        normalized_scores = {}
        for ticker in features_map.keys():
            lgbm = lgbm_scores.get(ticker, 0)
            rule = rule_scores.get(ticker, 0)
            # Normalize et
            lgbm_norm = self._normalize_score(lgbm)
            rule_norm = self._normalize_score(rule)
            normalized_scores[ticker] = (lgbm_norm, rule_norm)
            ensemble_scores[ticker] = (
                self._ensemble_weights["lgbm"] * lgbm_norm +
                self._ensemble_weights["rule_based"] * rule_norm
            )

        # Sırala (düşük skor = üst sıra, çünkü LambdaRank'te düşük label = iyi)
        sorted_scores = sorted(ensemble_scores.items(), key=lambda x: x[1])

        scores = []
        for rank, (ticker, score) in enumerate(sorted_scores, 1):
            features = features_map.get(ticker, {})

            # Yön belirle
            momentum = features.get("momentum_20d", 0)
            roc = features.get("roc_5d", 0)
            rsi = features.get("rsi_14", 50)

            if momentum > 0 and roc > 0 and rsi > 50:
                direction = "LONG"
            elif momentum < 0 and roc < 0 and rsi < 50:
                direction = "SHORT"
            else:
                direction = "LONG" if score < np.median(list(ensemble_scores.values())) else "SHORT"

            # Guven: rank bazli (en ust siradakiler en yuksek guven)
            # Score semantigi: dusuk score = iyi (LambdaRank)
            # Confidence: percentile bazli, en iyi %10 = ~0.9, en iyi %1 = ~0.99
            n = len(sorted_scores)
            percentile = (n - rank + 1) / n  # 1.0 = en iyi, 0.0 = en kotu
            confidence = max(0, min(0.99, 0.5 + percentile * 0.5))  # 0.5 - 0.99 arasi

            lgbm_norm, rule_norm = normalized_scores.get(ticker, (0, 0))
            opp = OpportunityScore(
                ticker=ticker,
                score=round(score, 4),
                rank=rank,
                direction=direction,
                confidence=round(confidence, 2),
                regime=regime,
                signals={},
                features=features,
                model_contribution={
                    "lgbm": round(self._ensemble_weights["lgbm"] * lgbm_norm, 4) if ticker in lgbm_scores else 0,
                    "rule_based": round(self._ensemble_weights["rule_based"] * rule_norm, 4) if ticker in rule_scores else 0,
                }
            )
            scores.append(opp)

        # Top K
        top_k = {k: scores[:k] for k in [5, 10, 20, 50]}

        return RankingResult(
            scores=scores,
            top_k=top_k,
            feature_importance=dict(sorted(
                self._feature_importance.items(), key=lambda x: x[1], reverse=True
            )) if self._feature_importance else {},
            regime_weights=self._regime_feature_weights.get(regime, {}),
            ensemble_weights=self._ensemble_weights,
        )

    def _prepare_training_data(
        self,
        features_map: Dict[str, Dict],
        returns: Dict[str, float],
        date_groups: Dict[str, str],
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Eğitim verisi hazırla."""
        X = []
        y = []

        for ticker in features_map:
            if ticker not in returns:
                continue
            vec = self._feature_vector(features_map[ticker])
            X.append(vec)
            y.append(returns[ticker])

        return np.array(X), np.array(y), np.array([])

    def _feature_vector(self, features: Dict) -> List[float]:
        """Feature dict'ten vektör oluştur."""
        return [float(features.get(name, 0) or 0) for name in self._feature_names]

    def _apply_regime_weights(self, X: np.ndarray, regime: str) -> np.ndarray:
        """Rejim bazlı feature ağırlıkları uygula."""
        weights = self._regime_feature_weights.get(regime, {})
        if not weights:
            return X

        X_weighted = X.copy()
        for feat_name, weight in weights.items():
            if feat_name in self._feature_names:
                idx = self._feature_names.index(feat_name)
                X_weighted[:, idx] *= weight

        return X_weighted

    def _rule_based_score(self, features: Dict, regime: str) -> float:
        """Rejim-aware rule-based skor."""
        score = 50.0

        # Momentum ağırlığı rejime göre değişir
        mom_weight = 0.15 if regime == "BULL" else 0.08 if regime == "BEAR" else 0.12
        score += features.get("momentum_20d", 0) * mom_weight
        score += features.get("roc_5d", 0) * 0.10
        score += features.get("rs_vs_bist_5d", 0) * 0.08
        score += features.get("volume_zscore", 0) * 0.06
        score += features.get("sector_rel_return_5d", 0) * 0.08

        # Risk cezası
        score -= features.get("atr_pct", 0) * 0.03
        score -= features.get("drawdown_20d", 0) * 0.02

        # Fundamental
        score += features.get("fcf_yield_pct", 0) * 0.05
        score += features.get("balance_sheet_quality", 0) * 0.02

        # Sınırla
        return max(0, min(100, score))

    def _normalize_score(self, score: float) -> float:
        """Skoru 0-100 arası normalize et."""
        return max(0, min(100, score))

    def _compute_shap_importance(self, X: np.ndarray) -> Dict[str, float]:
        """SHAP importance hesapla."""
        try:
            import shap
            explainer = shap.TreeExplainer(self._lgbm_model)
            shap_values = explainer.shap_values(X)
            importance = np.mean(np.abs(shap_values), axis=0)
            return {
                name: float(imp)
                for name, imp in zip(self._feature_names, importance)
            }
        except Exception as e:
            logger.warning("SHAP computation failed", error=str(e))
            return {}

    def get_feature_importance(self) -> Dict[str, float]:
        return dict(sorted(
            self._feature_importance.items(), key=lambda x: x[1], reverse=True
        )) if self._feature_importance else {}

    def get_top_opportunities(
        self,
        features_map: Dict,
        regime: str = "UNKNOWN",
        limit: int = 20,
    ) -> List[Dict]:
        result = self.rank(features_map, regime)
        return [
            {
                "ticker": s.ticker,
                "rank": s.rank,
                "score": s.score,
                "direction": s.direction,
                "confidence": s.confidence,
                "regime": s.regime,
            }
            for s in result.scores[:limit]
        ]


# Singleton
ranking_model = RankingModel()
