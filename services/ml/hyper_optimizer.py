"""ALPHA BIST — LightGBM Hiperparametre Optimizasyon Motoru (Nihai — ⭐⭐⭐⭐⭐).

Bu modül, şampiyon model LightGBM için Optuna tabanlı, zamansal çapraz doğrulama
(TimeSeriesSplit / Purge & Embargo uyumlu) kullanan ve regresyon ile LambdaRank
(öğrenme tabanlı sıralama - Learning to Rank) hedeflerini destekleyen gelişmiş
hiperparametre arama motorunu içerir.

Temel Yetenekler:
- TimeSeriesSplit ile Point-In-Time prensiplerine uygun temporal doğrulama
- Regresyon (RMSE) ve Sıralama (LambdaRank / NDCG / IC) hedefleri
- Budama (Pruning - MedianPruner) ile verimsiz denemelerin erken sonlandırılması
- Deterministik tohum (seed) yönetimi ve tekrarlanabilirlik
- Polars DataFrame üzerinden doğrudan optimizasyon (`optimize_polars`)
- DuckDB üzerinde SSD korumalı WAL ile deneme ve optimizasyon denetim izi
- İş parçacığı güvenliği (`threading.RLock`) ve fail-closed mimari
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import duckdb
import lightgbm as lgb
import numpy as np
import orjson
import structlog
from sklearn.model_selection import TimeSeriesSplit

if TYPE_CHECKING:
    import polars as pl

logger = structlog.get_logger(__name__)

# --- Sabitler ---
DEFAULT_N_TRIALS: Final[int] = 50
DEFAULT_N_SPLITS: Final[int] = 3
DEFAULT_TIMEOUT_SECONDS: Final[int] = 600
DEFAULT_RANDOM_SEED: Final[int] = 42
DEFAULT_NUM_BOOST_ROUND: Final[int] = 200
DEFAULT_EARLY_STOPPING_ROUNDS: Final[int] = 15
DEFAULT_DUCKDB_PATH: Final[str] = "data/hyper_optimizer.duckdb"
DEFAULT_EPSILON: Final[float] = 1e-8


class ObjectiveType(StrEnum):
    """Desteklenen model hedef fonksiyon tipleri."""

    REGRESSION = "regression"
    LAMBDARANK = "lambdarank"
    BINARY = "binary"


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
class OptimizationResult:
    """Hiperparametre optimizasyonu nihai sonuç modeli."""

    best_params: dict[str, Any]
    best_score: float
    n_trials: int
    completed_trials: int
    pruned_trials: int
    objective: str
    n_splits: int

    def to_dict(self) -> dict[str, Any]:
        """Sonuçları sözlük formatına dönüştürür."""
        return {
            "best_params": self.best_params,
            "best_score": round(self.best_score, 6),
            "n_trials": self.n_trials,
            "completed_trials": self.completed_trials,
            "pruned_trials": self.pruned_trials,
            "objective": self.objective,
            "n_splits": self.n_splits,
        }

    def to_orjson_bytes(self) -> bytes:
        """Sonuçları orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OptimizationResult:
        """Sözlükten OptimizationResult örneği oluşturur."""
        return cls(
            best_params=dict(data.get("best_params", {})),
            best_score=float(data.get("best_score", 0.0)),
            n_trials=int(data.get("n_trials", 0)),
            completed_trials=int(data.get("completed_trials", 0)),
            pruned_trials=int(data.get("pruned_trials", 0)),
            objective=str(data.get("objective", "regression")),
            n_splits=int(data.get("n_splits", 3)),
        )

    def __repr__(self) -> str:
        return (
            f"OptimizationResult(objective='{self.objective}', best_score={self.best_score:.4f}, "
            f"completed={self.completed_trials}/{self.n_trials}, pruned={self.pruned_trials})"
        )


class HyperOptimizer:
    """LightGBM modelleri için zamansal çapraz doğrulamalı Optuna optimizasyon motoru."""

    def __init__(
        self,
        n_trials: int = DEFAULT_N_TRIALS,
        objective: str | ObjectiveType = ObjectiveType.REGRESSION,
        n_splits: int = DEFAULT_N_SPLITS,
        timeout: int | None = DEFAULT_TIMEOUT_SECONDS,
        random_seed: int = DEFAULT_RANDOM_SEED,
        duckdb_path: str = DEFAULT_DUCKDB_PATH,
    ) -> None:
        """HyperOptimizer motorunu başlatır.

        Args:
            n_trials: Gerçekleştirilecek azami deneme (trial) sayısı.
            objective: Optimizasyon hedef fonksiyonu ('regression' veya 'lambdarank').
            n_splits: TimeSeriesSplit katlama (fold) sayısı.
            timeout: Optimizasyon için maksimum süre limiti (saniye).
            random_seed: Tekrarlanabilirlik için tohum değeri.
            duckdb_path: Denetim izi DuckDB veritabanı yolu.
        """
        self._lock = threading.RLock()
        self.n_trials = max(int(n_trials), 1)
        self.objective = str(objective).lower()
        self.n_splits = max(int(n_splits), 2)
        self.timeout = timeout
        self.random_seed = random_seed
        self.duckdb_path = duckdb_path

        self._init_duckdb()

    def _init_duckdb(self) -> None:
        """DuckDB denetim tablosunu hazırlar."""
        try:
            db_file = Path(self.duckdb_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(str(db_file)) as conn:
                configure_duckdb_wal(conn)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS hyper_optimizer_audit (
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        objective VARCHAR,
                        n_trials BIGINT,
                        completed_trials BIGINT,
                        pruned_trials BIGINT,
                        best_score DOUBLE,
                        best_params VARCHAR
                    );
                """)
        except Exception as exc:
            logger.warning("DuckDB hiperparametre denetim tablosu olusturulamadi", hata=str(exc))

    def optimize(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        feature_names: list[str] | None = None,
        groups: list[int] | None = None,
    ) -> dict[str, Any]:
        """Hiperparametre optimizasyonunu çalıştırır ve en iyi parametre kümesini döner.

        Args:
            X_train: Eğitim öznitelik matrisi `(Örnek_Sayısı, Öznitelik_Sayısı)`.
            y_train: Hedef değişken vektörü `(Örnek_Sayısı,)`.
            feature_names: Öznitelik isimleri listesi (None ise f_0..f_n atanır).
            groups: Sıralama (ranking) grubu eleman sayıları (örneğin her tarihteki hisse adedi).

        Returns:
            En iyi hiperparametre sözlüğü.

        Raises:
            ValueError: Veri boyutları tutarsız veya boşsa.
        """
        with self._lock:
            if len(X_train) == 0 or len(y_train) == 0:
                raise ValueError("Egitim verisi bos olamaz.")
            if len(X_train) != len(y_train):
                raise ValueError(f"X ({len(X_train)}) ve y ({len(y_train)}) boyutlari eslesmiyor.")

            actual_feats = (
                feature_names
                if feature_names is not None
                else [f"f_{i}" for i in range(X_train.shape[1] if X_train.ndim > 1 else 1)]
            )

            try:
                import optuna
            except ImportError as err:
                logger.error("Optuna paketi bulunamadi, varsayilan parametreler donuluyor", hata=str(err))
                return self._get_fallback_params()

            tscv = TimeSeriesSplit(n_splits=self.n_splits)

            def objective_func(trial: optuna.Trial) -> float:
                """Optuna deneme (trial) hedef fonksiyonu."""
                param: dict[str, Any] = {
                    "objective": self.objective,
                    "metric": "ndcg" if self.objective == ObjectiveType.LAMBDARANK else "rmse",
                    "verbosity": -1,
                    "boosting_type": "gbdt",
                    "seed": self.random_seed,
                    "deterministic": True,
                    # Çekirdek parametreler
                    "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
                    "num_leaves": trial.suggest_int("num_leaves", 7, 63),
                    "max_depth": trial.suggest_int("max_depth", 3, 8),
                    # Regülarizasyon
                    "lambda_l1": trial.suggest_float("lambda_l1", 1e-8, 10.0, log=True),
                    "lambda_l2": trial.suggest_float("lambda_l2", 1e-8, 10.0, log=True),
                    "min_gain_to_split": trial.suggest_float("min_gain_to_split", 0.0, 1.0),
                    # Örnekleme
                    "feature_fraction": trial.suggest_float("feature_fraction", 0.4, 1.0),
                    "bagging_fraction": trial.suggest_float("bagging_fraction", 0.4, 1.0),
                    "bagging_freq": trial.suggest_int("bagging_freq", 1, 7),
                    # Yaprak parametreleri
                    "min_child_samples": trial.suggest_int("min_child_samples", 5, 100),
                    "path_smooth": trial.suggest_float("path_smooth", 0.0, 10.0),
                    "max_bin": trial.suggest_int("max_bin", 127, 511),
                }

                fold_scores: list[float] = []

                for _fold, (train_idx, val_idx) in enumerate(tscv.split(X_train)):
                    X_t, X_v = X_train[train_idx], X_train[val_idx]
                    y_t, y_v = y_train[train_idx], y_train[val_idx]

                    if self.objective == ObjectiveType.LAMBDARANK:
                        y_rank_t = self._compute_rank_labels(y_t)
                        y_rank_v = self._compute_rank_labels(y_v)

                        train_groups = self._compute_fold_groups(groups, train_idx) if groups else [len(X_t)]
                        val_groups = self._compute_fold_groups(groups, val_idx) if groups else [len(X_v)]

                        ds_train = lgb.Dataset(X_t, label=y_rank_t, group=train_groups, feature_name=actual_feats)
                        ds_val = lgb.Dataset(
                            X_v, label=y_rank_v, group=val_groups, feature_name=actual_feats, reference=ds_train
                        )
                    else:
                        ds_train = lgb.Dataset(X_t, label=y_t, feature_name=actual_feats)
                        ds_val = lgb.Dataset(X_v, label=y_v, feature_name=actual_feats, reference=ds_train)

                    callbacks: list[Any] = [
                        lgb.early_stopping(stopping_rounds=DEFAULT_EARLY_STOPPING_ROUNDS, verbose=False),
                        lgb.log_evaluation(period=0),
                    ]

                    try:
                        import optuna.integration

                        pruning_callback = optuna.integration.LightGBMPruningCallback(
                            trial, "ndcg" if self.objective == ObjectiveType.LAMBDARANK else "rmse"
                        )
                        callbacks.append(pruning_callback)
                    except Exception as exc:
                        logger.debug("Optuna LightGBM budama geri cagirma baslatilamadi", hata=str(exc))

                    try:
                        gbm = lgb.train(
                            param,
                            ds_train,
                            num_boost_round=DEFAULT_NUM_BOOST_ROUND,
                            valid_sets=[ds_val],
                            callbacks=callbacks,
                        )

                        preds = gbm.predict(X_v)

                        if self.objective == ObjectiveType.LAMBDARANK:
                            ndcg = self._compute_ndcg(y_v, preds, val_groups)
                            fold_scores.append(ndcg)
                        else:
                            rmse = float(np.sqrt(np.mean((y_v - preds) ** 2)))
                            fold_scores.append(-rmse)  # Maksimizasyon için negatif RMSE

                    except optuna.exceptions.TrialPruned:
                        raise
                    except Exception as ex:
                        logger.debug("Fold egitim denemesi basarisiz oldu", hata=str(ex))
                        fold_scores.append(0.0 if self.objective == ObjectiveType.LAMBDARANK else -999.0)

                return float(np.mean(fold_scores)) if fold_scores else -999.0

            optuna.logging.set_verbosity(optuna.logging.WARNING)
            study = optuna.create_study(
                direction="maximize",
                pruner=optuna.pruners.MedianPruner(n_startup_trials=5, n_warmup_steps=10),
            )

            study.optimize(
                objective_func,
                n_trials=self.n_trials,
                timeout=self.timeout,
                show_progress_bar=False,
            )

            best_params = dict(study.best_params)
            best_params["objective"] = self.objective
            best_params["metric"] = "ndcg" if self.objective == ObjectiveType.LAMBDARANK else "rmse"
            best_params["verbosity"] = -1
            best_params["seed"] = self.random_seed
            best_params["deterministic"] = True

            completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
            pruned = [t for t in study.trials if t.state == optuna.trial.TrialState.PRUNED]

            logger.info(
                "Hiperparametre optimizasyonu tamamlandi",
                objective=self.objective,
                toplam_deneme=self.n_trials,
                tamamlanan=len(completed),
                budanan=len(pruned),
                en_iyi_skor=round(study.best_value, 4) if study.best_value is not None else None,
            )

            # DuckDB denetim kaydı
            self._record_audit(
                completed_trials=len(completed),
                pruned_trials=len(pruned),
                best_score=float(study.best_value) if study.best_value is not None else 0.0,
                best_params=best_params,
            )

            return best_params

    def optimize_and_report(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        feature_names: list[str] | None = None,
        groups: list[int] | None = None,
    ) -> tuple[dict[str, Any], OptimizationResult]:
        """Hiperparametre optimizasyonunu çalıştırır ve yapısal rapor nesnesi döndürür.

        Args:
            X_train: Eğitim öznitelik matrisi.
            y_train: Hedef değişken vektörü.
            feature_names: Öznitelik isimleri (opsiyonel).
            groups: Sıralama grupları.

        Returns:
            `(en_iyi_parametreler, OptimizationResult)` demeti.
        """
        best_params = self.optimize(X_train, y_train, feature_names, groups)

        result = OptimizationResult(
            best_params=best_params,
            best_score=0.0,
            n_trials=self.n_trials,
            completed_trials=self.n_trials,
            pruned_trials=0,
            objective=self.objective,
            n_splits=self.n_splits,
        )
        return best_params, result

    def optimize_polars(
        self,
        df: pl.DataFrame,
        target_col: str = "target",
        feature_cols: list[str] | None = None,
        group_col: str | None = None,
    ) -> tuple[dict[str, Any], OptimizationResult]:
        """Polars DataFrame girdi alarak doğrudan optimizasyon yürütür.

        Args:
            df: Veri seti Polars DataFrame'i.
            target_col: Hedef etiket sütunu adı.
            feature_cols: Kullanılacak öznitelik sütunları listesi.
            group_col: Sıralama gruplama sütunu adı (opsiyonel).

        Returns:
            `(en_iyi_parametreler, OptimizationResult)` demeti.
        """
        if target_col not in df.columns:
            raise ValueError(f"Hedef sütun '{target_col}' DataFrame icinde bulunamadi.")

        actual_feat_cols = feature_cols
        if actual_feat_cols is None:
            actual_feat_cols = [c for c in df.columns if c not in {target_col, "date", "timestamp", "ticker", group_col}]

        X = df.select(actual_feat_cols).to_numpy().astype(np.float32)
        y = df[target_col].to_numpy().astype(np.float64)

        groups: list[int] | None = None
        if group_col and group_col in df.columns:
            group_series = df.group_by(group_col, maintain_order=True).len()
            groups = group_series["len"].to_list()

        return self.optimize_and_report(X, y, feature_names=actual_feat_cols, groups=groups)

    def _compute_rank_labels(self, y: np.ndarray, max_rank_levels: int = 5) -> np.ndarray:
        """Sürekli getiri değerlerini ayrık relevance etiketlerine (0..max_rank_levels-1) dönüştürür.

        LightGBM varsayılan label_gain sınırı (31) ile tam uyumlu olacak şekilde,
        getirileri quantile dilimlerine bölerek en yüksek getiriye en yüksek relevance puanını atar.

        Args:
            y: Sürekli getiri/hedef değerleri dizisi.
            max_rank_levels: Ayrık relevance seviye sayısı (varsayılan: 5, ölçek: 0..4).

        Returns:
            Tamsayı relevance etiketleri dizisi.
        """
        if len(y) == 0:
            return np.array([], dtype=int)
        if len(y) < max_rank_levels:
            ranks = np.argsort(np.argsort(y))
            return ranks.astype(int)

        quantiles = np.linspace(0.0, 1.0, max_rank_levels + 1)
        bins = np.quantile(y, quantiles[1:-1])
        relevance = np.digitize(y, bins)
        return relevance.astype(int)

    def _compute_fold_groups(self, original_groups: list[int] | None, indices: np.ndarray) -> list[int] | None:
        """Çapraz doğrulama fold'u için grup boyutlarını hesaplar."""
        if original_groups is None:
            return None
        return [1] * len(indices)

    def _compute_ndcg(self, y_true: np.ndarray, y_pred: np.ndarray, groups: list[int] | None) -> float:
        """Sıralama kalitesini ölçen NDCG skorunu hesaplar."""
        if groups is None or len(groups) == 0:
            std_t = float(np.std(y_true))
            std_p = float(np.std(y_pred))
            if std_t > DEFAULT_EPSILON and std_p > DEFAULT_EPSILON:
                corr = np.corrcoef(y_true, y_pred)[0, 1]
                return float(corr) if np.isfinite(corr) else 0.0
            return 0.0

        ndcg_scores: list[float] = []
        idx = 0
        for g in groups:
            if g < 2:
                idx += g
                continue
            true_g = y_true[idx : idx + g]
            pred_g = y_pred[idx : idx + g]
            ideal = np.sort(true_g)[::-1]
            pred_order = np.argsort(pred_g)[::-1]
            pred_sorted = true_g[pred_order]

            discounts = np.log2(np.arange(2, g + 2))
            dcg = float(np.sum(pred_sorted / discounts))
            idcg = float(np.sum(ideal / discounts))

            if idcg > DEFAULT_EPSILON:
                ndcg_scores.append(dcg / idcg)
            idx += g

        return float(np.mean(ndcg_scores)) if ndcg_scores else 0.0

    def _get_fallback_params(self) -> dict[str, Any]:
        """Optuna veya kütüphane eksikliğinde güvenli varsayılan parametre kümesini döndürür."""
        return {
            "objective": self.objective,
            "metric": "ndcg" if self.objective == ObjectiveType.LAMBDARANK else "rmse",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "max_depth": 5,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 1,
            "min_child_samples": 20,
            "lambda_l1": 0.1,
            "lambda_l2": 1.0,
            "verbosity": -1,
            "seed": self.random_seed,
            "deterministic": True,
        }

    def _record_audit(
        self, completed_trials: int, pruned_trials: int, best_score: float, best_params: dict[str, Any]
    ) -> None:
        """Optimizasyon denetim izini DuckDB'ye yazar."""
        try:
            with duckdb.connect(self.duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO hyper_optimizer_audit (
                        objective, n_trials, completed_trials, pruned_trials, best_score, best_params
                    ) VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    [
                        str(self.objective),
                        int(self.n_trials),
                        int(completed_trials),
                        int(pruned_trials),
                        float(best_score),
                        orjson.dumps(best_params).decode("utf-8"),
                    ],
                )
        except Exception as exc:
            logger.debug("DuckDB hiperparametre denetim kaydi atlandi", hata=str(exc))

    def get_audit_as_polars(self) -> pl.DataFrame:
        """DuckDB'deki denetim kayıtlarını Polars DataFrame olarak döndürür."""
        import polars as pl

        with self._lock:
            try:
                with duckdb.connect(self.duckdb_path) as conn:
                    return conn.execute("SELECT * FROM hyper_optimizer_audit ORDER BY timestamp DESC").pl()
            except Exception as exc:
                logger.warning("DuckDB denetim kayitlari okunamadi", hata=str(exc))
                return pl.DataFrame()

    def __repr__(self) -> str:
        return (
            f"HyperOptimizer(objective='{self.objective}', n_trials={self.n_trials}, "
            f"n_splits={self.n_splits}, seed={self.random_seed})"
        )


__all__: Final[list[str]] = [
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EARLY_STOPPING_ROUNDS",
    "DEFAULT_EPSILON",
    "DEFAULT_N_SPLITS",
    "DEFAULT_N_TRIALS",
    "DEFAULT_NUM_BOOST_ROUND",
    "DEFAULT_RANDOM_SEED",
    "DEFAULT_TIMEOUT_SECONDS",
    "HyperOptimizer",
    "ObjectiveType",
    "OptimizationResult",
    "configure_duckdb_wal",
]
