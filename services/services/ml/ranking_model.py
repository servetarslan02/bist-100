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
        # LightGBM eğitilmemişse tamamen rule-based kullan
        has_lgbm = self._is_trained and self._lgbm_model is not None and lgbm_scores
        ensemble_scores = {}
        normalized_scores = {}
        for ticker in features_map.keys():
            rule = rule_scores.get(ticker, 0)
            rule_norm = self._normalize_score(rule)
            if has_lgbm:
                lgbm = lgbm_scores.get(ticker, 0)
                lgbm_norm = self._normalize_score(lgbm)
                normalized_scores[ticker] = (lgbm_norm, rule_norm)
                ensemble_scores[ticker] = (
                    self._ensemble_weights["lgbm"] * lgbm_norm +
                    self._ensemble_weights["rule_based"] * rule_norm
                )
            else:
                normalized_scores[ticker] = (0, rule_norm)
                ensemble_scores[ticker] = rule_norm

        # Sırala (yüksek skor = üst sıra — label: future return, yüksek = iyi)
        sorted_scores = sorted(ensemble_scores.items(), key=lambda x: x[1], reverse=True)

        scores = []
        for rank, (ticker, score) in enumerate(sorted_scores, 1):
            features = features_map.get(ticker, {})

            # Yön belirle (scalar'a çevir — numpy array gelebilir)
            momentum = self._scalar(features.get("momentum_20d", 0))
            roc = self._scalar(features.get("roc_5d", 0))
            rsi = self._scalar(features.get("rsi_14", 50))

            if momentum > 0 and roc > 0 and rsi > 50:
                direction = "LONG"
            elif momentum < 0 and roc < 0 and rsi < 50:
                direction = "SHORT"
            else:
                direction = "LONG" if score > np.median(list(ensemble_scores.values())) else "SHORT"

            # Guven: rank bazli (en ust siradakiler en yuksek guven)
            # Score semantigi: dusuk score = iyi (LambdaRank)
            # Confidence: percentile bazli, en iyi %10 = ~0.9, en iyi %1 = ~0.99
            n = len(sorted_scores)
            percentile = (n - rank + 1) / n  # 1.0 = en iyi, 0.0 = en kotu
            confidence = max(0, min(0.99, 0.5 + percentile * 0.5))  # 0.5 - 0.99 arasi

            lgbm_norm, rule_norm = normalized_scores.get(ticker, (0, 0))
            opp = OpportunityScore(
                ticker=ticker,
                score=round(float(score), 4),
                rank=rank,
                direction=direction,
                confidence=round(float(confidence), 2),
                regime=regime,
                signals={},
                features=features,
                model_contribution={
                    "lgbm": round(float(self._ensemble_weights["lgbm"] * lgbm_norm), 4) if ticker in lgbm_scores else 0,
                    "rule_based": round(float(self._ensemble_weights["rule_based"] * rule_norm), 4) if ticker in rule_scores else 0,
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

    @staticmethod
    def _scalar(val) -> float:
        """numpy array veya scalar değerden float elde et."""
        if isinstance(val, np.ndarray):
            return float(val.flat[0]) if val.size > 0 else 0.0
        return float(val)

    def _rule_based_score(self, features: Dict, regime: str) -> float:
        """Rejim-aware rule-based skor.

        Rejime göre strateji ağırlıkları:
        - BULL: momentum ağırlıklı, trend takibi
        - BEAR: defansif, kalite, mean reversion
        - SIDEWAYS: değer, mean reversion
        - HIGH_VOL: defansif, düşük volatilite tercihi
        """
        _s = self._scalar  # shorthand

        # === REJİM BAZLI STRATEJİ AĞIRLIKLARI ===
        if regime == "BULL":
            w_mom, w_roc, w_rs, w_vol, w_sector = 0.20, 0.12, 0.10, 0.08, 0.10
            w_risk, w_dd, w_fund, w_quality = -0.02, -0.01, 0.03, 0.01
            w_trend, w_rev = 0.05, 0.00
        elif regime == "BEAR":
            w_mom, w_roc, w_rs, w_vol, w_sector = 0.05, 0.05, 0.05, 0.08, 0.05
            w_risk, w_dd, w_fund, w_quality = -0.05, -0.05, 0.05, 0.03
            w_trend, w_rev = 0.02, 0.08
        elif regime in ("HIGH_VOL", "HIGH_VOLATILITY"):
            w_mom, w_roc, w_rs, w_vol, w_sector = 0.08, 0.06, 0.06, 0.05, 0.06
            w_risk, w_dd, w_fund, w_quality = -0.06, -0.04, 0.04, 0.03
            w_trend, w_rev = 0.03, 0.06
        else:  # SIDEWAYS, UNKNOWN, vb.
            w_mom, w_roc, w_rs, w_vol, w_sector = 0.12, 0.08, 0.08, 0.06, 0.08
            w_risk, w_dd, w_fund, w_quality = -0.03, -0.02, 0.04, 0.02
            w_trend, w_rev = 0.04, 0.04

        score = 50.0

        # === TEMEL SİNYALLER ===
        score += _s(features.get("momentum_20d", 0)) * w_mom
        score += _s(features.get("roc_5d", 0)) * w_roc
        score += _s(features.get("rs_vs_bist_5d", 0)) * w_rs
        score += _s(features.get("volume_zscore", 0)) * w_vol
        score += _s(features.get("sector_rel_return_5d", 0)) * w_sector

        # === RİSK CEZASI ===
        score -= _s(features.get("atr_pct", 0)) * abs(w_risk)
        score -= _s(features.get("drawdown_20d", 0)) * abs(w_dd)

        # === FUNDAMENTAL (Motor 4 bağlandığında otomatik çalışacak) ===
        fcf = _s(features.get("fcf_yield_pct", 0))
        bsq = _s(features.get("balance_sheet_quality", 0))
        if fcf != 0:
            score += fcf * w_fund
        if bsq != 0:
            score += bsq * w_quality * 0.01

        # === TREND KALİTESİ ===
        trend_slope = _s(features.get("trend_slope_20d", 0))
        trend_r2 = _s(features.get("trend_r2_20d", 0))
        # Güçlü trend (yüksek R² + pozitif eğim) bonus
        if trend_r2 > 0.5 and trend_slope > 0:
            score += trend_slope * w_trend * trend_r2
        elif trend_r2 > 0.5 and trend_slope < 0:
            score += trend_slope * w_trend * trend_r2 * 0.5

        # === MEAN REVERSION (BEAR/SIDEWAYS'de ağırlıklı) ===
        rsi = _s(features.get("rsi_14", 50))
        if rsi < 30:
            score += (30 - rsi) * w_rev * 0.3  # Aşırı satım bonus
        elif rsi > 70:
            score -= (rsi - 70) * w_rev * 0.3  # Aşırı alım cezası

        # === DÜŞÜŞ ANALİZİ (Motor 7) ===
        falling_temp = _s(features.get("falling_is_temporary", 0.5))
        if falling_temp > 0.7 and regime in ("BEAR", "HIGH_VOL", "HIGH_VOLATILITY"):
            score += 3.0  # Geçici düşüş + kötü rejim = fırsat

        # === Sınırla ===
        return max(0.0, min(100.0, float(score)))

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


# =====================================================
# ML Modül Bağlantıları
# =====================================================
def get_ml_ensemble() -> Dict[str, Any]:
    """Tüm ML modüllerini ensemble olarak getir."""
    models = {}
    try:
        from .xgboost_model import xgboost_model
        models["xgboost"] = xgboost_model
    except ImportError:
        pass
    except Exception:
        pass
    try:
        from .lstm_model import lstm_model
        models["lstm"] = lstm_model
    except ImportError:
        pass
    except Exception:
        pass
    try:
        from .transformer_model import transformer_model
        models["transformer"] = transformer_model
    except ImportError:
        pass
    except Exception:
        pass
    try:
        from .ensemble import ensemble_model
        models["ensemble"] = ensemble_model
    except ImportError:
        pass
    except Exception:
        pass
    try:
        from .model_comparator import model_comparator
        models["comparator"] = model_comparator
    except ImportError:
        pass
    except Exception:
        pass
    try:
        from .finrl_bist import finrl_env
        models["finrl"] = finrl_env
    except ImportError:
        pass
    except Exception:
        pass
    try:
        from .fingpt import fingpt_sentiment
        models["fingpt"] = fingpt_sentiment
    except ImportError:
        pass
    except Exception:
        pass
    try:
        from .hybrid_model import hybrid_predict
        models["hybrid"] = hybrid_predict
    except ImportError:
        pass
    except Exception:
        pass
    try:
        from .rl_agent import train_rl_agent
        models["rl_agent"] = train_rl_agent
    except ImportError:
        pass
    except Exception:
        pass
    try:
        from .walk_forward import WalkForwardEngine
        models["walk_forward"] = WalkForwardEngine
    except ImportError:
        pass
    except Exception:
        pass
    return models
