"""ALPHA BIST — Çok Faktörlü Hisse Sıralama Modeli (Ranking Model v3.0) (Nihai — ⭐⭐⭐⭐⭐).

Bu modül; mutlak fiyat veya getiri kestirimi yapmak yerine ("yükselir mi?" sorusu yerine),
BIST hisse evrenindeki hisseleri birbirlerine göre bağıl üstünlüklerine göre sıralar
("en iyi %10'da mı?" sorusuna odaklanır).

Temel Yetenekler:
- LightGBM LambdaRank (NDCG@k Hedefli Sıralama Optimizasyonu)
- Rejim Farkındalığı (BULL, BEAR, SIDEWAYS ve HIGH_VOL rejimlerine özgü dinamik öznitelik ağırlıklandırması)
- Çok Faktörlü Ensemble: LambdaRank + Kanıtlanmış Kural Tabanlı (Rule-based) Ağırlık Birleşimi
- 70 Kanonik Öznitelik (Momentum, Trend, Hacim, Temel, Sektör, Duyarlılık, Fiyat Hareketi)
- DuckDB SSD Korumalı WAL ile Sıralama ve Model Karar Denetim İzi (Audit Trail)
- Polars Native Sıralama Desteği (`rank_polars`)
- İş Parçacığı Güvenliği (`threading.RLock`) ve Kesin Tip Belirteçleri
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

logger = structlog.get_logger(__name__)

# --- Sabitler ---
DEFAULT_DUCKDB_PATH: Final[str] = "data/ranking_model.duckdb"
DEFAULT_EPSILON: Final[float] = 1e-8
DEFAULT_MODEL_PATH: Final[str] = "models/lightgbm_lambdarank.pkl"
DEFAULT_MIN_SAMPLES_FOR_TRAIN: Final[int] = 100


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısına SSD ömrünü ve WAL boyutunu koruma direktiflerini uygular.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute("PRAGMA checkpoint_threshold = '4MB';")
        conn.execute("PRAGMA wal_autocheckpoint = '2MB';")
    except Exception as exc:
        logger.warning("DuckDB WAL pragma yapilandirmasi basarisiz", hata=str(exc))


@dataclass(slots=True)
class OpportunityScore:
    """Tekil bir hissenin sıralama skoru, yönü ve güven seviyesi modeli."""

    ticker: str
    score: float
    rank: int
    direction: str
    confidence: float
    regime: str
    signals: dict[str, Any]
    features: dict[str, Any]
    model_contribution: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        """Modeli standart sözlük yapısına dönüştürür."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpportunityScore:
        """Sözlükten OpportunityScore nesnesi üretir."""
        return cls(
            ticker=str(data["ticker"]),
            score=float(data["score"]),
            rank=int(data["rank"]),
            direction=str(data["direction"]),
            confidence=float(data.get("confidence", 0.5)),
            regime=str(data.get("regime", "UNKNOWN")),
            signals=dict(data.get("signals", {})),
            features=dict(data.get("features", {})),
            model_contribution=dict(data.get("model_contribution", {})),
        )

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        """Özet metin gösterimini oluşturur."""
        return (
            f"OpportunityScore(ticker='{self.ticker}', rank={self.rank}, "
            f"score={self.score:.4f}, dir={self.direction}, conf={self.confidence:.2f})"
        )


@dataclass(slots=True)
class RankingResult:
    """Evren sıralama operasyonunun kümülatif sonuç modeli."""

    scores: list[OpportunityScore]
    top_k: dict[int, list[OpportunityScore]]
    feature_importance: dict[str, float]
    regime_weights: dict[str, float]
    ensemble_weights: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        """Sıralama sonucunu sözlük yapısına dönüştürür."""
        return {
            "scores": [s.to_dict() for s in self.scores],
            "top_k": {str(k): [s.to_dict() for s in v] for k, v in self.top_k.items()},
            "feature_importance": self.feature_importance,
            "regime_weights": self.regime_weights,
            "ensemble_weights": self.ensemble_weights,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RankingResult:
        """Sözlükten RankingResult nesnesi üretir."""
        scores = [OpportunityScore.from_dict(s) for s in data.get("scores", [])]
        raw_top_k = data.get("top_k", {})
        top_k = {
            int(k): [OpportunityScore.from_dict(s) for s in v]
            for k, v in raw_top_k.items()
        }
        return cls(
            scores=scores,
            top_k=top_k,
            feature_importance=dict(data.get("feature_importance", {})),
            regime_weights=dict(data.get("regime_weights", {})),
            ensemble_weights=dict(data.get("ensemble_weights", {})),
        )

    def to_orjson_bytes(self) -> bytes:
        """Sıralama sonucunu orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict(), default=str, option=orjson.OPT_NON_STR_KEYS)

    def __repr__(self) -> str:
        """Özet metin gösterimi."""
        return f"RankingResult(total_ranked={len(self.scores)}, top_10_count={len(self.top_k.get(10, []))})"


class RankingModel:
    """LambdaRank + Rejim Duyarlı Çok Faktörlü Hisse Sıralama Motoru."""

    def __init__(self, duckdb_path: str = DEFAULT_DUCKDB_PATH) -> None:
        """RankingModel bileşenini başlatır ve kanonik 70 özniteliği tanımlar.

        Args:
            duckdb_path: Denetim kayıtları için DuckDB dosya yolu.
        """
        self._duckdb_path: str = duckdb_path
        self._lock: threading.RLock = threading.RLock()
        self._lgbm_model: Any = None
        self._is_trained: bool = False

        # Kanonik 70 Öznitelik Listesi
        self._feature_names: list[str] = [
            # Motor 1: Relatif Güç
            "rs_vs_bist_1d",
            "rs_vs_bist_5d",
            "rs_vs_bist_20d",
            "rs_vs_bist_60d",
            "rs_vs_sector_5d",
            "rs_vs_peers_5d",
            "rs_trend",
            "rs_peer_rank",
            # Motor 2: Momentum + Trend
            "roc_5d",
            "roc_20d",
            "roc_60d",
            "momentum_20d",
            "trend_slope_20d",
            "trend_r2_20d",
            "momentum_acceleration",
            "momentum_accel_trend",
            "price_vs_sma20",
            "price_vs_sma50",
            "price_vs_sma200",
            "near_20d_high",
            "near_60d_high",
            "near_120d_high",
            "breakout_failure",
            "drawdown_20d",
            "recovery_strength",
            # Motor 3: Hacim + Mikroyapı
            "volume_percentile",
            "volume_zscore",
            "volume_trend",
            "volume_up_down_ratio",
            "tick_rule",
            "vwap_deviation",
            "avg_volume_5d",
            "obv",
            # Motor 4: Temel Analiz (Fundamental)
            "sector_norm_pe_ratio",
            "sector_norm_pb_ratio",
            "fcf_yield_pct",
            "fcf_margin",
            "balance_sheet_quality",
            "profit_margin_pct",
            "roe",
            "roa",
            # Motor 5: KAP + Haber Duyarlılığı
            "kap_sentiment_avg",
            "kap_sentiment_latest",
            "news_sentiment_weighted",
            "sentiment_momentum",
            "kap_avg_importance",
            # Motor 6: Katalizör
            "catalyst_count",
            "catalyst_importance",
            "catalyst_days_nearest",
            # Motor 7: Düşüş Analizi (Neden Düşüyor?)
            "falling_is_temporary",
            "fall_market_selloff",
            "fall_sector_selloff",
            # Kesitsel Faktörler (Cross-Sectional)
            "rank_return_5d",
            "rank_return_20d",
            "rank_volume_zscore",
            "rank_rsi_14",
            "sector_rel_return_5d",
            "sector_zscore_momentum_20d",
            "cs_zscore_roc_5d",
            "cs_zscore_roc_20d",
            # Risk
            "atr_pct",
            "volatility_20d",
            "realized_vol_20d",
            # Piyasa Genişliği (Market Breadth)
            "market_breadth",
            "market_ad_ratio",
            # Fiyat Hareketi ve Mum Analizi
            "buyer_pressure_pct",
            "candle_score",
            "has_bullish_pattern",
            "has_fvg",
            "vol_adj_mom",
        ]

        # Rejim bazlı öznitelik ağırlıkları
        self._regime_feature_weights: dict[str, dict[str, float]] = {
            "BULL": {
                "volume_trend": 1.6,
                "sector_rel_return_5d": 1.5,
                "vol_adj_mom": 1.4,
                "momentum_20d": 1.4,
                "buyer_pressure_pct": 1.3,
                "has_bullish_pattern": 1.2,
                "roc_5d": 1.2,
                "trend_r2_20d": 1.2,
                "trend_slope_20d": 1.2,
                "volume_zscore": 1.2,
                "rs_vs_bist_5d": 1.3,
                "breakout_failure": 0.5,
                "drawdown_20d": 0.5,
            },
            "BEAR": {
                "trend_r2_20d": 1.5,
                "balance_sheet_quality": 1.4,
                "falling_is_temporary": 1.3,
                "momentum_20d": 0.5,
                "roc_5d": 0.6,
                "trend_slope_20d": 0.5,
                "volume_zscore": 1.2,
                "rs_vs_bist_5d": 0.8,
                "breakout_failure": 1.5,
                "drawdown_20d": 1.4,
            },
            "SIDEWAYS": {
                "rs_vs_bist_5d": 1.3,
                "roc_5d": 1.2,
                "momentum_20d": 0.9,
                "bb_position": 1.3,
                "volume_zscore": 1.1,
                "buyer_pressure_pct": 1.2,
                "sector_norm_pe_ratio": 1.2,
                "fcf_yield_pct": 1.2,
            },
            "UNKNOWN": {},
        }

        # Ensemble ağırlıkları (LightGBM eğitildiğinde lgbm=0.7, rule_based=0.3)
        self._ensemble_weights: dict[str, float] = {"lgbm": 0.7, "rule_based": 0.3}

        # Öznitelik önem düzeyleri
        self._feature_importance: dict[str, float] = {}
        self._feature_importance_history: list[dict[str, Any]] = []

        self._init_duckdb()
        self._try_load_pretrained()

        logger.info("RankingModel v3.0 basariyla ilklendirildi", features=len(self._feature_names), is_trained=self._is_trained)

    def _init_duckdb(self) -> None:
        """DuckDB denetim tablosunu güvenle oluşturur."""
        try:
            db_dir = Path(self._duckdb_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ranking_model_audit (
                        timestamp TIMESTAMPTZ NOT NULL,
                        operation VARCHAR NOT NULL,
                        ticker_count BIGINT NOT NULL,
                        regime VARCHAR NOT NULL,
                        top_ticker VARCHAR NOT NULL,
                        top_score DOUBLE NOT NULL,
                        details VARCHAR NOT NULL
                    );
                    """
                )
        except Exception as exc:
            logger.warning("DuckDB ranking_model_audit tablosu ilklendirilemedi", hata=str(exc))

    def _record_audit_event(
        self,
        operation: str,
        ticker_count: int,
        regime: str,
        top_ticker: str,
        top_score: float,
        details: dict[str, Any],
    ) -> None:
        """Sıralama operasyonunu DuckDB denetim tablosuna yazar."""
        try:
            now_iso = datetime.now(UTC).isoformat()
            details_json = orjson.dumps(details, default=str).decode("utf-8")
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO ranking_model_audit
                    (timestamp, operation, ticker_count, regime, top_ticker, top_score, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    [now_iso, operation, ticker_count, regime, top_ticker, top_score, details_json],
                )
        except Exception as exc:
            logger.warning("DuckDB ranking_model denetim kaydi basarisiz", hata=str(exc))

    def _try_load_pretrained(self) -> None:
        """Disk üzerinde önceden eğitilmiş LambdaRank modeli varsa güvenle yükler."""
        with self._lock:
            try:
                from services.core.safe_pickle import safe_pickle_load

                p = Path(DEFAULT_MODEL_PATH)
                if p.exists():
                    loaded = safe_pickle_load(str(p))
                    if hasattr(loaded, "model") and loaded.model is not None:
                        self._lgbm_model = loaded.model
                        self._is_trained = True
                    elif loaded is not None:
                        self._lgbm_model = loaded
                        self._is_trained = True

                    if self._is_trained:
                        logger.info("Onceden egitilmis LambdaRank modeli diskten yuklendi", path=str(p))
            except Exception as exc:
                logger.debug("On egitimli LambdaRank modeli yukleme bilgisi", hata=str(exc))

    def train(
        self,
        features_map: dict[str, dict[str, Any]],
        returns: dict[str, float],
        date_groups: dict[str, str],
        regime: str = "UNKNOWN",
        min_samples: int = DEFAULT_MIN_SAMPLES_FOR_TRAIN,
    ) -> dict[str, Any]:
        """LambdaRank hedefiyle LightGBM sıralama modelini eğitir.

        Args:
            features_map: {ticker: {feature_name: value}} sözlüğü.
            returns: {ticker: future_return} sözlüğü.
            date_groups: {ticker: iso_date} sözlüğü.
            regime: Piyasa rejimi ('BULL', 'BEAR', vb.).
            min_samples: Eğitim için gereken asgari örnek sayısı.

        Returns:
            Eğitim başarı durumunu ve öznitelik önem derecelerini içeren sözlük.
        """
        with self._lock:
            try:
                import lightgbm as lgb
            except ImportError:
                logger.warning("LightGBM kutuphanesi yuklu degil, yalnizca kural tabanli mod devrede")
                self._is_trained = False
                return {"success": False, "error": "LightGBM yuklu degil"}

            X, y, groups = self._prepare_training_data(features_map, returns, date_groups)

            if len(X) < min_samples:
                logger.warning("Yetersiz egitim verisi, kural tabanli siralamaya devam edilecek", ornek_sayisi=len(X))
                self._is_trained = False
                return {"success": False, "error": "Yetersiz orneklem"}

            X_weighted = self._apply_regime_weights(X, regime)

            # LambdaRank: Yüksek getiri = Daha yüksek tam sayı ilgi derecesi (relevance gain)
            y_labels = np.zeros(len(y), dtype=np.int32)
            idx_start = 0
            for g_size in groups:
                idx_end = idx_start + int(g_size)
                group_y = np.asarray(y[idx_start:idx_end], dtype=np.float64)
                group_ranks = np.argsort(np.argsort(group_y)).astype(np.int32)
                y_labels[idx_start:idx_end] = group_ranks
                idx_start = idx_end

            group_sizes = groups.tolist()

            train_data = lgb.Dataset(X_weighted, label=y_labels, group=group_sizes, feature_name=self._feature_names)

            params = {
                "objective": "lambdarank",
                "metric": "ndcg",
                "ndcg_eval_at": [5, 10, 20],
                "learning_rate": 0.05,
                "num_leaves": 31,
                "min_data_in_leaf": max(1, min(len(X), max(1, len(X) // max(len(groups), 1)))),
                "feature_fraction": 0.8,
                "bagging_fraction": 0.8,
                "bagging_freq": 5,
                "verbose": -1,
            }

            self._lgbm_model = lgb.train(params, train_data, num_boost_round=100)
            self._is_trained = True

            importance = self._lgbm_model.feature_importance(importance_type="gain")
            self._feature_importance = {
                name: float(imp) for name, imp in zip(self._feature_names, importance, strict=False)
            }
            self._feature_importance_history.append(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "regime": regime,
                    "importance": dict(self._feature_importance),
                }
            )
            if len(self._feature_importance_history) > 1000:
                self._feature_importance_history = self._feature_importance_history[-1000:]

            shap_importance = self._compute_shap_importance(X_weighted)

            top_importances = dict(
                sorted(self._feature_importance.items(), key=lambda item: item[1], reverse=True)[:15]
            )

            self._record_audit_event(
                operation="TRAIN",
                ticker_count=len(X),
                regime=regime,
                top_ticker="MODEL_TRAINED",
                top_score=0.0,
                details={"top_importance": top_importances},
            )

            logger.info("LambdaRank modeli basariyla egitildi", samples=len(X), groups=len(group_sizes), regime=regime)

            return {
                "success": True,
                "samples": len(X),
                "groups": len(group_sizes),
                "regime": regime,
                "feature_importance": top_importances,
                "shap_importance": shap_importance,
            }

    def rank(
        self,
        features_map: dict[str, dict[str, Any]],
        regime: str = "UNKNOWN",
    ) -> RankingResult:
        """Hisseleri LambdaRank ve kural tabanlı ensemble motoruyla sıralar.

        Args:
            features_map: {ticker: {feature_name: value}} sözlüğü.
            regime: Aktif piyasa rejimi ('BULL', 'BEAR', 'SIDEWAYS', vb.).

        Returns:
            Tüm sıralama sonuçlarını içeren RankingResult nesnesi.
        """
        with self._lock:
            if not features_map:
                return RankingResult(
                    scores=[],
                    top_k={},
                    feature_importance={},
                    regime_weights=self._regime_feature_weights.get(regime, {}),
                    ensemble_weights=self._ensemble_weights,
                )

            # 1. LightGBM Skorları
            lgbm_scores: dict[str, float] = {}
            if self._is_trained and self._lgbm_model is not None:
                tickers: list[str] = []
                X: list[list[float]] = []
                for ticker, features in features_map.items():
                    vec = self._feature_vector(features)
                    tickers.append(ticker)
                    X.append(vec)

                if X:
                    X_arr = np.asarray(X, dtype=np.float64)
                    X_weighted = self._apply_regime_weights(X_arr, regime)
                    predictions = self._lgbm_model.predict(X_weighted)
                    predictions = np.nan_to_num(predictions, nan=0.0, posinf=100.0, neginf=-100.0)
                    for ticker, pred in zip(tickers, predictions, strict=False):
                        lgbm_scores[ticker] = float(pred)

            # 2. Kural Tabanlı Skorlar
            rule_scores: dict[str, float] = {}
            for ticker, features in features_map.items():
                rule_scores[ticker] = self._rule_based_score(features, regime)

            # 3. Ensemble (Ağırlıklı Bileşim)
            has_lgbm = bool(self._is_trained and self._lgbm_model is not None and lgbm_scores)
            ensemble_scores: dict[str, float] = {}
            normalized_scores: dict[str, tuple[float, float]] = {}

            # LightGBM skorlarını 0..100 aralığına min-max ölçekle
            lgbm_scaled: dict[str, float] = {}
            if lgbm_scores:
                l_vals = list(lgbm_scores.values())
                min_l = min(l_vals)
                max_l = max(l_vals)
                diff_l = max_l - min_l
                for t, v in lgbm_scores.items():
                    if diff_l > DEFAULT_EPSILON:
                        lgbm_scaled[t] = ((v - min_l) / diff_l) * 100.0
                    else:
                        lgbm_scaled[t] = 50.0

            for ticker in features_map:
                rule = rule_scores.get(ticker, 0.0)
                rule_norm = self._normalize_score(rule)
                if has_lgbm:
                    lgbm_norm = lgbm_scaled.get(ticker, 50.0)
                    normalized_scores[ticker] = (lgbm_norm, rule_norm)
                    ensemble_scores[ticker] = (
                        self._ensemble_weights["lgbm"] * lgbm_norm + self._ensemble_weights["rule_based"] * rule_norm
                    )
                else:
                    normalized_scores[ticker] = (0.0, rule_norm)
                    ensemble_scores[ticker] = rule_norm

            sorted_scores = sorted(ensemble_scores.items(), key=lambda item: item[1], reverse=True)
            n_total = len(sorted_scores)

            median_score = (
                float(np.median(list(ensemble_scores.values()))) if ensemble_scores else 50.0
            )

            scores: list[OpportunityScore] = []
            for rank_idx, (ticker, score) in enumerate(sorted_scores, 1):
                feat_dict = features_map.get(ticker, {})

                momentum = self._scalar(feat_dict.get("momentum_20d", 0.0))
                roc = self._scalar(feat_dict.get("roc_5d", 0.0))
                rsi = self._scalar(feat_dict.get("rsi_14", 50.0))

                if momentum > 0 and roc > 0 and rsi > 50:
                    direction = "LONG"
                elif momentum < 0 and roc < 0 and rsi < 50:
                    direction = "SHORT"
                else:
                    direction = "LONG" if score >= median_score else "SHORT"

                percentile = (n_total - rank_idx + 1) / max(n_total, 1)
                confidence = max(0.10, min(0.99, 0.5 + percentile * 0.5))

                lgbm_norm, rule_norm = normalized_scores.get(ticker, (0.0, 0.0))
                opp = OpportunityScore(
                    ticker=ticker,
                    score=round(float(score), 4),
                    rank=rank_idx,
                    direction=direction,
                    confidence=round(float(confidence), 2),
                    regime=regime,
                    signals={},
                    features=feat_dict,
                    model_contribution={
                        "lgbm": round(float(self._ensemble_weights["lgbm"] * lgbm_norm), 4) if ticker in lgbm_scores else 0.0,
                        "rule_based": round(float(self._ensemble_weights["rule_based"] * rule_norm), 4)
                        if ticker in rule_scores
                        else 0.0,
                    },
                )
                scores.append(opp)

            top_k = {k: scores[:k] for k in [5, 10, 20, 50]}

            if scores:
                self._record_audit_event(
                    operation="RANK",
                    ticker_count=len(scores),
                    regime=regime,
                    top_ticker=scores[0].ticker,
                    top_score=scores[0].score,
                    details={"top_5": [s.ticker for s in scores[:5]]},
                )

            return RankingResult(
                scores=scores,
                top_k=top_k,
                feature_importance=dict(sorted(self._feature_importance.items(), key=lambda item: item[1], reverse=True))
                if self._feature_importance
                else {},
                regime_weights=self._regime_feature_weights.get(regime, {}),
                ensemble_weights=self._ensemble_weights,
            )

    def rank_polars(self, df: pl.DataFrame, ticker_col: str = "ticker", regime: str = "UNKNOWN") -> pl.DataFrame:
        """Polars DataFrame girdi alarak sıralanmış yeni Polars DataFrame döndürür.

        Args:
            df: Hisse ve öznitelik satırlarını içeren Polars DataFrame.
            ticker_col: Hisse sembol sütun adı.
            regime: Aktif rejim adı.

        Returns:
            'rank', 'score', 'direction' ve 'confidence' sütunları eklenmiş ve sıralanmış Polars DataFrame.
        """
        if df.is_empty():
            return df.with_columns(
                pl.lit(None).cast(pl.Int64).alias("rank"),
                pl.lit(None).cast(pl.Float64).alias("score"),
                pl.lit(None).cast(pl.Utf8).alias("direction"),
                pl.lit(None).cast(pl.Float64).alias("confidence"),
            )

        if ticker_col not in df.columns:
            logger.warning("Polars DataFrame icinde ticker kolonu bulunamadi", ticker_col=ticker_col)
            return df

        valid_df = df.filter(pl.col(ticker_col).is_not_null())
        if valid_df.is_empty():
            return df

        rows = valid_df.to_dicts()
        features_map: dict[str, dict[str, Any]] = {
            str(row[ticker_col]): row for row in rows if row.get(ticker_col) is not None
        }

        ranking_result = self.rank(features_map, regime=regime)
        ranked_items = [
            {
                ticker_col: s.ticker,
                "rank": s.rank,
                "score": s.score,
                "direction": s.direction,
                "confidence": s.confidence,
            }
            for s in ranking_result.scores
        ]

        ranked_df = pl.DataFrame(ranked_items)
        return df.join(ranked_df, on=ticker_col, how="left").sort("rank")

    def _prepare_training_data(
        self,
        features_map: dict[str, dict[str, Any]],
        returns: dict[str, float],
        date_groups: dict[str, str],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Tarih kesitlerine göre gruplanmış LambdaMART eğitim verisini hazırlar."""
        X: list[list[float]] = []
        y: list[float] = []
        groups: list[int] = []

        sorted_tickers = sorted(
            [t for t in features_map if t in returns and t in date_groups], key=lambda t: date_groups[t]
        )

        current_date = None
        current_group = 0
        for ticker in sorted_tickers:
            vec = self._feature_vector(features_map[ticker])
            X.append(vec)
            y.append(float(returns[ticker]))

            date = date_groups[ticker]
            if date != current_date:
                if current_group > 0:
                    groups.append(current_group)
                current_date = date
                current_group = 1
            else:
                current_group += 1

        if current_group > 0:
            groups.append(current_group)

        X_arr = np.asarray(X, dtype=np.float64) if X else np.empty((0, len(self._feature_names)))
        y_arr = np.asarray(y, dtype=np.float64) if y else np.empty((0,))
        groups_arr = np.asarray(groups, dtype=np.int32) if groups else np.empty((0,), dtype=np.int32)

        return X_arr, y_arr, groups_arr

    def _feature_vector(self, features: dict[str, Any]) -> list[float]:
        """Öznitelik sözlüğünden 70 elemanlı sıralı öznitelik vektörü üretir."""
        _FALLBACKS: Final[dict[str, list[str]]] = {
            "volume_percentile": ["volume_percentile_20d", "volume_percentile_5d"],
            "volume_up_down_ratio": ["volume_up_down_ratio_20d"],
            "tick_rule": ["tick_rule_20d"],
            "vwap_deviation": ["vwap_deviation_20d"],
            "breakout_failure": ["breakout_failure_20d"],
            "recovery_strength": ["recovery_strength_20d"],
            "rs_peer_rank": ["rs_peer_rank_5d"],
            "fall_market_selloff": ["fall_market_selloff_5d"],
            "fall_sector_selloff": ["fall_sector_selloff_5d"],
            "roe": ["raw_roe"],
            "roa": ["raw_roa"],
            "profit_margin_pct": ["raw_profit_margin"],
        }
        vals: list[float] = []
        for name in self._feature_names:
            val = features.get(name)
            if val is None:
                for fallback_name in _FALLBACKS.get(name, []):
                    val = features.get(fallback_name)
                    if val is not None:
                        break
            try:
                f_val = float(val) if val is not None and np.isfinite(val) else 0.0
            except (ValueError, TypeError):
                f_val = 0.0
            vals.append(f_val)
        return vals

    def _apply_regime_weights(self, X: np.ndarray, regime: str) -> np.ndarray:
        """Öznitelik matrisine rejim katsayılarını uygular."""
        weights = self._regime_feature_weights.get(regime, {})
        if not weights or len(X) == 0:
            return X

        X_weighted = X.copy()
        for feat_name, weight in weights.items():
            if feat_name in self._feature_names:
                idx = self._feature_names.index(feat_name)
                X_weighted[:, idx] *= weight

        return X_weighted

    @staticmethod
    def _scalar(val: Any) -> float:
        """numpy dizisi veya skaler değerden güvenli float elde eder."""
        if isinstance(val, np.ndarray):
            return float(val.flat[0]) if val.size > 0 else 0.0
        try:
            return float(val) if val is not None and np.isfinite(val) else 0.0
        except (ValueError, TypeError):
            return 0.0

    def _rule_based_score(self, features: dict[str, Any], regime: str) -> float:
        """Piyasa rejimine duyarlı kural tabanlı fırsat puanı hesaplar."""
        _s = self._scalar

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
        else:  # SIDEWAYS, UNKNOWN vb.
            w_mom, w_roc, w_rs, w_vol, w_sector = 0.12, 0.08, 0.08, 0.06, 0.08
            w_risk, w_dd, w_fund, w_quality = -0.03, -0.02, 0.04, 0.02
            w_trend, w_rev = 0.04, 0.04

        score = 50.0

        score += _s(features.get("momentum_20d", 0.0)) * w_mom
        score += _s(features.get("roc_5d", 0.0)) * w_roc
        score += _s(features.get("rs_vs_bist_5d", 0.0)) * w_rs
        score += _s(features.get("volume_zscore", 0.0)) * w_vol
        score += _s(features.get("sector_rel_return_5d", 0.0)) * w_sector

        score -= _s(features.get("atr_pct", 0.0)) * abs(w_risk)
        score -= _s(features.get("drawdown_20d", 0.0)) * abs(w_dd)

        fcf = _s(features.get("fcf_yield_pct", 0.0))
        bsq = _s(features.get("balance_sheet_quality", 0.0))
        if fcf != 0:
            score += fcf * w_fund
        if bsq != 0:
            score += bsq * w_quality * 0.01

        trend_slope = _s(features.get("trend_slope_20d", 0.0))
        trend_r2 = _s(features.get("trend_r2_20d", 0.0))
        if trend_r2 > 0.5 and trend_slope > 0:
            score += trend_slope * w_trend * trend_r2
        elif trend_r2 > 0.5 and trend_slope < 0:
            score += trend_slope * w_trend * trend_r2 * 0.5

        rsi = _s(features.get("rsi_14", 50.0))
        if rsi < 30:
            score += (30 - rsi) * w_rev * 0.3
        elif rsi > 70:
            score -= (rsi - 70) * w_rev * 0.3

        falling_temp = _s(features.get("falling_is_temporary", 0.5))
        if falling_temp > 0.7 and regime in ("BEAR", "HIGH_VOL", "HIGH_VOLATILITY"):
            score += 3.0

        buyer_pressure = _s(features.get("buyer_pressure_pct", 50.0))
        candle_score = _s(features.get("candle_score", 50.0))
        has_bull_pat = bool(features.get("has_bullish_pattern", False))
        has_fvg = bool(features.get("has_fvg", False))

        if buyer_pressure >= 55.0:
            score += (buyer_pressure - 50.0) * 0.15
        elif buyer_pressure <= 40.0:
            score -= (50.0 - buyer_pressure) * 0.15

        if candle_score >= 60.0:
            score += (candle_score - 50.0) * 0.10

        if has_bull_pat:
            score += 4.0
        if has_fvg:
            score += 3.0

        vol_adj = _s(features.get("vol_adj_mom", 0.0))
        if vol_adj != 0:
            score += float(np.clip(vol_adj, -3.0, 3.0)) * 1.5

        return max(0.0, min(100.0, float(score)))

    def _normalize_score(self, score: float) -> float:
        """Skoru [0.0, 100.0] aralığına normalize eder."""
        return max(0.0, min(100.0, float(score)))

    def _compute_shap_importance(self, X: np.ndarray) -> dict[str, float]:
        """SHAP önem değerlerini hesaplar."""
        try:
            import shap

            explainer = shap.TreeExplainer(self._lgbm_model)
            shap_values = explainer.shap_values(X)
            importance = np.mean(np.abs(shap_values), axis=0)
            return {name: float(imp) for name, imp in zip(self._feature_names, importance, strict=False)}
        except Exception as exc:
            logger.warning("SHAP onem hesabi basarisiz", hata=str(exc))
            return {}

    def get_feature_importance(self) -> dict[str, float]:
        """Model öznitelik önem değerlerini azalan sırada döndürür."""
        with self._lock:
            return (
                dict(sorted(self._feature_importance.items(), key=lambda item: item[1], reverse=True))
                if self._feature_importance
                else {}
            )

    def get_top_opportunities(
        self,
        features_map: dict[str, dict[str, Any]],
        regime: str = "UNKNOWN",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """En yüksek fırsat puanına sahip hisseleri liste halinde döndürür."""
        result = self.rank(features_map, regime=regime)
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

    def get_top_opportunities_polars(
        self,
        features_map: dict[str, dict[str, Any]],
        regime: str = "UNKNOWN",
        limit: int = 20,
    ) -> pl.DataFrame:
        """En yüksek fırsat puanına sahip hisseleri Polars DataFrame olarak döndürür."""
        items = self.get_top_opportunities(features_map, regime=regime, limit=limit)
        if not items:
            return pl.DataFrame(
                schema={
                    "ticker": pl.Utf8,
                    "rank": pl.Int64,
                    "score": pl.Float64,
                    "direction": pl.Utf8,
                    "confidence": pl.Float64,
                    "regime": pl.Utf8,
                }
            )
        return pl.DataFrame(items)

    @property
    def feature_names(self) -> list[str]:
        """Kanonik 70 öznitelik listesini döndürür."""
        return list(self._feature_names)

    def __repr__(self) -> str:
        """RankingModel özet metin gösterimini oluşturur."""
        with self._lock:
            return f"RankingModel(is_trained={self._is_trained}, features_count={len(self._feature_names)})"


ranking_model: Final[RankingModel] = RankingModel()


def get_ml_ensemble() -> dict[str, Any]:
    """Tüm ML modüllerini topluluk (ensemble) olarak döndürür."""
    models: dict[str, Any] = {}
    try:
        from .xgboost_model import xgboost_model

        models["xgboost"] = xgboost_model
    except Exception as exc:
        logger.debug("xgboost_model yuklenemedi", hata=str(exc))

    try:
        from .lstm_model import lstm_model

        models["lstm"] = lstm_model
    except Exception as exc:
        logger.debug("lstm_model yuklenemedi", hata=str(exc))

    try:
        from .transformer_model import transformer_model

        models["transformer"] = transformer_model
    except Exception as exc:
        logger.debug("transformer_model yuklenemedi", hata=str(exc))

    try:
        from .ensemble import ensemble_model

        models["ensemble"] = ensemble_model
    except Exception as exc:
        logger.debug("ensemble_model yuklenemedi", hata=str(exc))

    try:
        from .model_comparator import model_comparator

        models["comparator"] = model_comparator
    except Exception as exc:
        logger.debug("model_comparator yuklenemedi", hata=str(exc))

    try:
        from .finrl_bist import finrl_env

        models["finrl"] = finrl_env
    except Exception as exc:
        logger.debug("finrl_bist yuklenemedi", hata=str(exc))

    try:
        from .fingpt import fingpt_sentiment

        models["fingpt"] = fingpt_sentiment
    except Exception as exc:
        logger.debug("fingpt yuklenemedi", hata=str(exc))

    try:
        from .hybrid_model import hybrid_predict

        models["hybrid"] = hybrid_predict
    except Exception as exc:
        logger.debug("hybrid_model yuklenemedi", hata=str(exc))

    try:
        from .rl_agent import train_rl_agent

        models["rl_agent"] = train_rl_agent
    except Exception as exc:
        logger.debug("rl_agent yuklenemedi", hata=str(exc))

    try:
        from .walk_forward import WalkForwardEngine

        models["walk_forward"] = WalkForwardEngine
    except Exception as exc:
        logger.debug("walk_forward yuklenemedi", hata=str(exc))

    return models


__all__: Final[list[str]] = [
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EPSILON",
    "DEFAULT_MIN_SAMPLES_FOR_TRAIN",
    "DEFAULT_MODEL_PATH",
    "OpportunityScore",
    "RankingModel",
    "RankingResult",
    "configure_duckdb_wal",
    "get_ml_ensemble",
    "ranking_model",
]
