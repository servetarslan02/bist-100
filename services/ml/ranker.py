"""ALPHA BIST — Sıralama Öğrenimi Modeli (Learning-to-Rank) (Nihai — ⭐⭐⭐⭐⭐).

Bu modül; regresyon veya mutlak fiyat kestirimi yerine BIST hisselerini kesitsel (cross-sectional)
olarak bağıl getiri potansiyellerine göre sıralar (LambdaMART / LightGBM Ranker).
Piyasadaki en güçlü hisseleri tespit etmek için normalize edilmiş teknik, temel, sektörel ve
duyarlılık özniteliklerini LambdaRank hedefiyle optimize eder.

Temel Yetenekler:
- LightGBM LGBMRanker (LambdaMART / NDCG@k Optimizasyonu) ile Hisse Sıralama
- Kesitsel Tarih Gruplama (Cross-Sectional Date Grouping) ve Otomatik Veri Hazırlama
- Polars Native Vektörize Sıralama Desteği (`rank_polars`)
- Eğitilmemiş veya Model Yokluğunda Çok Faktörlü Güvenli Kural Tabanlı Fallback
- DuckDB SSD Korumalı WAL ile Sıralama ve Eğitim Denetim İzi (Audit Trail)
- İş Parçacığı Güvenliği (`threading.RLock`) ve Kesin Tip Belirteçleri
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

logger = structlog.get_logger(__name__)

# --- Sabitler ---
DEFAULT_DUCKDB_PATH: Final[str] = "data/ranker.duckdb"
DEFAULT_EPSILON: Final[float] = 1e-8

# Fallback Ağırlıkları
DEFAULT_WEIGHT_MOMENTUM_20D: Final[float] = 0.30
DEFAULT_WEIGHT_ROC_5D: Final[float] = 0.20
DEFAULT_WEIGHT_VOLUME_ZSCORE: Final[float] = 0.10
DEFAULT_WEIGHT_SECTOR_ZSCORE: Final[float] = 0.20
DEFAULT_WEIGHT_FUNDAMENTAL: Final[float] = 0.10
DEFAULT_WEIGHT_SENTIMENT: Final[float] = 0.10

DEFAULT_FEATURE_NAMES: Final[list[str]] = [
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
    # Kesitsel (Cross-sectional)
    "momentum_20d_sector_zscore",
    "momentum_20d_bist_pct",
    "roc_5d_sector_ratio",
    "avg_peer_correlation",
    # Zamansal
    "trend_slope",
    "trend_r2",
    "momentum_acceleration",
    "volatility_trend",
    "volume_trend_pct",
    # Temel (Fundamental)
    "fundamental_score",
    "pe_ratio",
    "pb_ratio",
    "roe",
    # Duyarlılık (Sentiment)
    "sentiment_score",
    "sentiment_momentum",
]


class RankDirection(StrEnum):
    """Sıralama yönü (Long / Short)."""

    LONG = "LONG"
    SHORT = "SHORT"


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
class RankItem:
    """Tekil hisse sıralama çıktı modeli."""

    ticker: str
    rank: int
    score: float
    direction: str

    def to_dict(self) -> dict[str, Any]:
        """Sıralama öğesini sözlüğe dönüştürür."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RankItem:
        """Sözlükten RankItem nesnesi üretir."""
        return cls(
            ticker=str(data["ticker"]),
            rank=int(data["rank"]),
            score=float(data["score"]),
            direction=str(data["direction"]),
        )

    def to_orjson_bytes(self) -> bytes:
        """Sıralama öğesini orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        """Özet metin gösterimi."""
        return f"RankItem(ticker='{self.ticker}', rank={self.rank}, score={self.score:.4f}, dir={self.direction})"


@dataclass(slots=True)
class RankerTrainResult:
    """Sıralama modeli eğitim sonucu modeli."""

    success: bool
    samples: int
    groups: int
    feature_importance: dict[str, float]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Eğitim sonucunu standart sözlük yapısına dönüştürür."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RankerTrainResult:
        """Sözlükten RankerTrainResult nesnesi üretir."""
        return cls(
            success=bool(data.get("success", False)),
            samples=int(data.get("samples", 0)),
            groups=int(data.get("groups", 0)),
            feature_importance=dict(data.get("feature_importance", {})),
            error=data.get("error"),
        )

    def to_orjson_bytes(self) -> bytes:
        """Eğitim sonucunu orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        """Özet metin gösterimi."""
        return f"RankerTrainResult(success={self.success}, samples={self.samples}, groups={self.groups})"


class LearningToRankModel:
    """LightGBM LGBMRanker ile hisse bağıl sıralama motoru."""

    def __init__(
        self,
        feature_names: list[str] | None = None,
        duckdb_path: str = DEFAULT_DUCKDB_PATH,
    ) -> None:
        """LearningToRankModel sınıfını başlatır.

        Args:
            feature_names: Kullanılacak öznitelik isim listesi.
            duckdb_path: Denetim kayıtları için DuckDB dosya yolu.
        """
        self._feature_names: list[str] = list(feature_names) if feature_names is not None else list(DEFAULT_FEATURE_NAMES)
        self._duckdb_path: str = duckdb_path
        self._lock: threading.RLock = threading.RLock()
        self._model: Any = None
        self._is_trained: bool = False
        self._feature_importance: dict[str, float] = {}

        self._init_duckdb()
        logger.info("LearningToRankModel basariyla ilklendirildi", features_count=len(self._feature_names))

    def _init_duckdb(self) -> None:
        """DuckDB denetim tablosunu güvenle oluşturur."""
        try:
            db_dir = Path(self._duckdb_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ranker_audit (
                        timestamp TIMESTAMPTZ NOT NULL,
                        operation VARCHAR NOT NULL,
                        samples BIGINT NOT NULL,
                        group_count BIGINT NOT NULL,
                        top_ticker VARCHAR NOT NULL,
                        top_score DOUBLE NOT NULL,
                        details VARCHAR NOT NULL
                    );
                    """
                )
        except Exception as exc:
            logger.warning("DuckDB ranker denetim tablosu ilklendirilemedi", hata=str(exc))

    def _record_audit_event(
        self,
        operation: str,
        samples: int,
        group_count: int,
        top_ticker: str,
        top_score: float,
        details: dict[str, Any],
    ) -> None:
        """Sıralama olayını DuckDB'ye kaydeder."""
        try:
            now_iso = datetime.now(UTC).isoformat()
            details_json = orjson.dumps(details, default=str).decode("utf-8")
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO ranker_audit
                    (timestamp, operation, samples, group_count, top_ticker, top_score, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    [now_iso, operation, samples, group_count, top_ticker, top_score, details_json],
                )
        except Exception as exc:
            logger.warning("DuckDB ranker denetim kaydi basarisiz", hata=str(exc))

    def prepare_training_data(
        self,
        features_map: dict[str, dict[str, Any]],
        returns: dict[str, float],
        date_groups: dict[str, str],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Tarih kesitlerine göre gruplanmış LambdaMART eğitim verisini hazırlar.

        Args:
            features_map: {ticker: {feature_name: value}} sözlüğü.
            returns: {ticker: forward_return} sözlüğü.
            date_groups: {ticker: iso_date} sözlüğü.

        Returns:
            (X matrisi, y hedef dizisi, groups dizi boyutları).
        """
        with self._lock:
            X_list: list[list[float]] = []
            y_list: list[float] = []
            groups_list: list[int] = []

            # Tarih bazlı hisseleri grupla
            date_tickers: defaultdict[str, list[str]] = defaultdict(list)
            for ticker, date_str in date_groups.items():
                date_tickers[date_str].append(ticker)

            for _date_str, tickers in sorted(date_tickers.items()):
                group_size = 0
                for ticker in tickers:
                    if ticker not in features_map or ticker not in returns:
                        continue

                    feat_dict = features_map[ticker]
                    vector: list[float] = []
                    for name in self._feature_names:
                        val = feat_dict.get(name)
                        try:
                            f_val = float(val) if val is not None and np.isfinite(val) else 0.0
                        except (ValueError, TypeError):
                            f_val = 0.0
                        vector.append(f_val)

                    ret = returns[ticker]
                    try:
                        ret_val = float(ret) if ret is not None and np.isfinite(ret) else 0.0
                    except (ValueError, TypeError):
                        ret_val = 0.0

                    X_list.append(vector)
                    y_list.append(ret_val)
                    group_size += 1

                if group_size > 0:
                    groups_list.append(group_size)

            X_arr = np.asarray(X_list, dtype=np.float64) if X_list else np.empty((0, len(self._feature_names)))
            y_arr = np.asarray(y_list, dtype=np.float64) if y_list else np.empty((0,))
            groups_arr = np.asarray(groups_list, dtype=np.int32) if groups_list else np.empty((0,), dtype=np.int32)

            return X_arr, y_arr, groups_arr

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        groups: np.ndarray,
    ) -> dict[str, Any]:
        """LambdaRank hedefiyle LightGBM Ranker modelini eğitir.

        Args:
            X: Öznitelik matrisi (N, F).
            y: Gerçek getiri dizisi (N,).
            groups: Her tarih kesitindeki hisse adedi dizisi.

        Returns:
            Eğitim başarı durumunu ve öznitelik önem düzeylerini içeren sözlük.
        """
        with self._lock:
            if len(X) == 0 or len(y) == 0 or len(groups) == 0:
                logger.error("Ranker egitimi icin bos veri iletildi")
                return {"success": False, "error": "Veri setleri bos olamaz"}

            try:
                import lightgbm as lgb

                # LambdaRank: Yüksek getiri = Daha yüksek tam sayı ilgi derecesi (relevance gain)
                # Her tarih grubundaki hisseleri getirilerine göre 0..N-1 tam sayı ilgililik derecesine dönüştür
                y_labels = np.zeros(len(y), dtype=np.int32)
                idx_start = 0
                for g_size in groups:
                    idx_end = idx_start + int(g_size)
                    group_y = np.asarray(y[idx_start:idx_end], dtype=np.float64)
                    group_ranks = np.argsort(np.argsort(group_y)).astype(np.int32)
                    y_labels[idx_start:idx_end] = group_ranks
                    idx_start = idx_end

                model = lgb.LGBMRanker(
                    objective="lambdarank",
                    metric="ndcg",
                    eval_at=[5, 10, 20],
                    learning_rate=0.05,
                    num_leaves=31,
                    min_data_in_leaf=max(1, min(len(X), max(1, len(X) // max(len(groups), 1)))),
                    feature_fraction=0.8,
                    bagging_fraction=0.8,
                    bagging_freq=5,
                    verbose=-1,
                )

                model.fit(X, y_labels, group=groups)
                self._model = model
                self._is_trained = True

                importance = model.feature_importances_
                self._feature_importance = {
                    name: float(imp) for name, imp in zip(self._feature_names, importance, strict=False)
                }

                top_importances = dict(
                    sorted(self._feature_importance.items(), key=lambda item: item[1], reverse=True)[:10]
                )

                self._record_audit_event(
                    operation="TRAIN",
                    samples=len(X),
                    group_count=len(groups),
                    top_ticker="MODEL_TRAINED",
                    top_score=0.0,
                    details={"top_importance": top_importances},
                )

                logger.info(
                    "Ranker basariyla egitildi",
                    samples=len(X),
                    groups=len(groups),
                )

                return {
                    "success": True,
                    "samples": len(X),
                    "groups": len(groups),
                    "feature_importance": top_importances,
                }

            except ImportError:
                logger.warning("LightGBM kutuphanesi yuklu degil, fallback moduna gecilecek")
                return {"success": False, "error": "LightGBM yuklu degil"}
            except Exception as exc:
                logger.error("Ranker egitimi basarisiz", hata=str(exc))
                return {"success": False, "error": str(exc)}

    def train_result(self, X: np.ndarray, y: np.ndarray, groups: np.ndarray) -> RankerTrainResult:
        """Eğitim sonucunu tip güvenli dataclass olarak döndürür."""
        res = self.train(X, y, groups)
        return RankerTrainResult(
            success=bool(res.get("success", False)),
            samples=int(res.get("samples", 0)),
            groups=int(res.get("groups", 0)),
            feature_importance=res.get("feature_importance", {}),
            error=res.get("error"),
        )

    def rank(self, features_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Verilen hisselerin özniteliklerine göre bağıl sıralamasını üretir.

        Args:
            features_map: {ticker: {feature_name: value}} sözlüğü.

        Returns:
            Sıralanmış hisseler listesi (1. sıra en güçlü).
        """
        with self._lock:
            if not features_map:
                return []

            if not self._is_trained or self._model is None:
                logger.warning("Model henuz egitilmemis, kural tabanli fallback siralamaya geciliyor")
                return self._fallback_rank(features_map)

            tickers: list[str] = []
            X_list: list[list[float]] = []

            for ticker, feat_dict in features_map.items():
                vector: list[float] = []
                for name in self._feature_names:
                    val = feat_dict.get(name)
                    try:
                        f_val = float(val) if val is not None and np.isfinite(val) else 0.0
                    except (ValueError, TypeError):
                        f_val = 0.0
                    vector.append(f_val)

                tickers.append(ticker)
                X_list.append(vector)

            if not X_list:
                return []

            X_arr = np.asarray(X_list, dtype=np.float64)
            predictions = self._model.predict(X_arr)
            predictions = np.nan_to_num(predictions, nan=0.0, posinf=1e6, neginf=-1e6)

            # Yüksek tahmin skoru = Daha üst sıra (Rank 1)
            ranked_pairs = sorted(zip(tickers, predictions, strict=False), key=lambda item: item[1], reverse=True)
            median_pred = float(np.median(predictions)) if len(predictions) > 0 else 0.0

            result: list[dict[str, Any]] = [
                {
                    "ticker": t,
                    "rank": idx + 1,
                    "score": round(float(p), 4),
                    "direction": RankDirection.LONG.value if p >= median_pred else RankDirection.SHORT.value,
                }
                for idx, (t, p) in enumerate(ranked_pairs)
            ]

            if result:
                self._record_audit_event(
                    operation="RANK",
                    samples=len(result),
                    group_count=1,
                    top_ticker=result[0]["ticker"],
                    top_score=result[0]["score"],
                    details={"count": len(result)},
                )

            return result

    def rank_objects(self, features_map: dict[str, dict[str, Any]]) -> list[RankItem]:
        """Sıralama sonucunu tip güvenli RankItem nesneleri olarak döndürür."""
        raw = self.rank(features_map)
        return [
            RankItem(ticker=r["ticker"], rank=r["rank"], score=r["score"], direction=r["direction"])
            for r in raw
        ]

    def rank_polars(self, df: pl.DataFrame, ticker_col: str = "ticker") -> pl.DataFrame:
        """Polars DataFrame girdi alarak sıralanmış yeni Polars DataFrame döndürür.

        Args:
            df: Hisse ve öznitelik satırlarını içeren Polars DataFrame.
            ticker_col: Hisse sembol sütun adı.

        Returns:
            'rank', 'score' ve 'direction' sütunları eklenmiş ve sıralanmış Polars DataFrame.
        """
        if df.is_empty():
            return df.with_columns(
                pl.lit(None).cast(pl.Int64).alias("rank"),
                pl.lit(None).cast(pl.Float64).alias("score"),
                pl.lit(None).cast(pl.Utf8).alias("direction"),
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

        ranked_items = self.rank(features_map)
        if not ranked_items:
            return df

        ranked_df = pl.DataFrame(ranked_items)
        return df.join(ranked_df, on=ticker_col, how="left").sort("rank")

    def _fallback_rank(self, features_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Model yokluğunda çok faktörlü kural tabanlı sıralama üretir."""
        scores: list[tuple[str, float]] = []

        for ticker, features in features_map.items():
            score = 0.0

            def _get_float(feat_dict: dict[str, Any], key: str) -> float:
                v = feat_dict.get(key)
                try:
                    return float(v) if v is not None and np.isfinite(v) else 0.0
                except (ValueError, TypeError):
                    return 0.0

            # Momentum
            score += _get_float(features, "momentum_20d") * DEFAULT_WEIGHT_MOMENTUM_20D
            score += _get_float(features, "roc_5d") * DEFAULT_WEIGHT_ROC_5D

            # Volume
            score += _get_float(features, "volume_zscore") * DEFAULT_WEIGHT_VOLUME_ZSCORE

            # Cross-sectional
            score += _get_float(features, "momentum_20d_sector_zscore") * DEFAULT_WEIGHT_SECTOR_ZSCORE

            # Fundamental
            score += _get_float(features, "fundamental_score") * DEFAULT_WEIGHT_FUNDAMENTAL

            # Sentiment
            score += _get_float(features, "sentiment_score") * DEFAULT_WEIGHT_SENTIMENT

            if not np.isfinite(score):
                score = 0.0

            scores.append((ticker, score))

        scores.sort(key=lambda item: item[1], reverse=True)

        return [
            {
                "ticker": t,
                "rank": idx + 1,
                "score": round(sc, 4),
                "direction": RankDirection.LONG.value if sc > 0 else RankDirection.SHORT.value,
            }
            for idx, (t, sc) in enumerate(scores)
        ]

    def get_feature_importance(self) -> dict[str, float]:
        """Model öznitelik önem sıralamasını döndürür."""
        with self._lock:
            if self._is_trained:
                return dict(sorted(self._feature_importance.items(), key=lambda item: item[1], reverse=True))
            return {}

    def __repr__(self) -> str:
        """LearningToRankModel özet metin gösterimini oluşturur."""
        with self._lock:
            return f"LearningToRankModel(is_trained={self._is_trained}, features_count={len(self._feature_names)})"


ranker_model: Final[LearningToRankModel] = LearningToRankModel()

__all__: Final[list[str]] = [
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EPSILON",
    "DEFAULT_FEATURE_NAMES",
    "DEFAULT_WEIGHT_FUNDAMENTAL",
    "DEFAULT_WEIGHT_MOMENTUM_20D",
    "DEFAULT_WEIGHT_ROC_5D",
    "DEFAULT_WEIGHT_SECTOR_ZSCORE",
    "DEFAULT_WEIGHT_SENTIMENT",
    "DEFAULT_WEIGHT_VOLUME_ZSCORE",
    "LearningToRankModel",
    "RankDirection",
    "RankItem",
    "RankerTrainResult",
    "configure_duckdb_wal",
    "ranker_model",
]
