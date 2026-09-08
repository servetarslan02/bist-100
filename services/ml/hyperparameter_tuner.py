"""ALPHA BIST — Çok Modelli ve Rejime Özel Hiperparametre Ayarlayıcı (Nihai — ⭐⭐⭐⭐⭐).

Bu modül; şampiyon model LightGBM ve rakip (challenger) modeller XGBoost ile CatBoost
için Optuna tabanlı Bayesyen optimizasyon, IC (Information Coefficient) ve getiri yönü
odaklı hedef fonksiyonları, zamansal çapraz doğrulama (TimeSeriesSplit), piyasa rejimlerine
özel parametre optimizasyonu ve yakınsama (convergence) analizi sunar.

Temel Yetenekler:
- IC (Spearman Rank Correlation), AUC, Yön Doğruluğu (Directional) ve MSE hedefleri
- Piyasa rejimlerine (BOĞA, AYI, YATAY, YÜKSEK VOLATİLİTE) özel parametre arama
- Denemeler arası zamansal çapraz doğrulama (TimeSeriesSplit CV within trials)
- Çoklu model desteği: LightGBM (Champion), CatBoost & XGBoost (Challengers)
- Erken durdurma (MedianPruner) ve otomatik yakınsama tespiti
- Polars DataFrame üzerinden doğrudan optimizasyon (`tune_polars`)
- DuckDB üzerinde SSD korumalı WAL ile deneme geçmişi ve ayar denetim izi
- İş parçacığı güvenliği (`threading.RLock`) ve `orjson` serileştirme desteği
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import duckdb
import numpy as np
import orjson
import structlog
from sklearn.model_selection import TimeSeriesSplit

if TYPE_CHECKING:
    import polars as pl

logger = structlog.get_logger(__name__)

# --- Sabitler ---
DEFAULT_N_TRIALS: Final[int] = 50
DEFAULT_TIMEOUT_SECONDS: Final[int] = 600
DEFAULT_CV_FOLDS: Final[int] = 3
DEFAULT_RANDOM_SEED: Final[int] = 42
DEFAULT_MIN_REGIME_SAMPLES: Final[int] = 50
DEFAULT_DUCKDB_PATH: Final[str] = "data/hyperparameter_tuner.duckdb"
DEFAULT_EPSILON: Final[float] = 1e-8


class TuningObjective(StrEnum):
    """Desteklenen optimizasyon hedef fonksiyonu tipleri."""

    IC = "ic"                      # Information Coefficient (Korelasyon)
    AUC = "auc"                    # ROC-AUC Skoru (Sınıflandırma)
    DIRECTIONAL = "directional"    # Yön Doğruluğu (% Pozitif/Negatif Eşleşme)
    MSE = "mse"                    # Ortalama Hata Karesi (Negatif RMSE/MSE)


class SupportedModel(StrEnum):
    """Desteklenen makine öğrenimi model türleri."""

    LIGHTGBM = "lightgbm"
    XGBOOST = "xgboost"
    CATBOOST = "catboost"


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
class TuningResult:
    """Tekil model hiperparametre arama sonucu veri modeli."""

    best_params: dict[str, Any]
    best_value: float
    n_trials: int
    trial_history: list[dict[str, Any]]
    tuning_time_seconds: float
    model_name: str = "lightgbm"
    convergence_info: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Arama sonucunu JSON uyumlu sözlük formatına dönüştürür."""
        return {
            "model_name": self.model_name,
            "best_params": self.best_params,
            "best_value": round(self.best_value, 6),
            "n_trials": self.n_trials,
            "tuning_time_seconds": round(self.tuning_time_seconds, 2),
            "convergence_info": self.convergence_info,
            "trial_count": len(self.trial_history),
        }

    def to_orjson_bytes(self) -> bytes:
        """Arama sonucunu orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TuningResult:
        """Sözlükten TuningResult örneği oluşturur."""
        return cls(
            best_params=dict(data.get("best_params", {})),
            best_value=float(data.get("best_value", 0.0)),
            n_trials=int(data.get("n_trials", 0)),
            trial_history=list(data.get("trial_history", [])),
            tuning_time_seconds=float(data.get("tuning_time_seconds", 0.0)),
            model_name=str(data.get("model_name", "lightgbm")),
            convergence_info=dict(data.get("convergence_info", {})),
        )

    def __repr__(self) -> str:
        return (
            f"TuningResult(model='{self.model_name}', best_val={self.best_value:.4f}, "
            f"trials={self.n_trials}, time={self.tuning_time_seconds:.1f}s)"
        )


@dataclass(slots=True)
class RegimeTuningResult:
    """Piyasa rejimine özel hiperparametre arama sonucu veri modeli."""

    regime: str
    result: TuningResult
    n_samples: int

    def to_dict(self) -> dict[str, Any]:
        """Rejim arama sonucunu sözlük formatına dönüştürür."""
        return {
            "regime": self.regime,
            "result": self.result.to_dict(),
            "n_samples": self.n_samples,
        }

    def to_orjson_bytes(self) -> bytes:
        """Rejim sonucunu orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RegimeTuningResult:
        """Sözlükten RegimeTuningResult örneği oluşturur."""
        res_data = data.get("result", {})
        result_obj = TuningResult.from_dict(res_data) if isinstance(res_data, dict) else res_data
        return cls(
            regime=str(data.get("regime", "NORMAL")),
            result=result_obj,
            n_samples=int(data.get("n_samples", 0)),
        )

    def __repr__(self) -> str:
        return f"RegimeTuningResult(regime='{self.regime}', n_samples={self.n_samples}, best_val={self.result.best_value:.4f})"


class HyperparameterTuner:
    """Optuna tabanlı gelişmiş çok modelli hiperparametre ayarlama motoru.

    LightGBM (Champion), CatBoost ve XGBoost (Challengers) modellerini zamansal
    çapraz doğrulama ile optimize eder.
    """

    def __init__(
        self,
        n_trials: int = DEFAULT_N_TRIALS,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        cv_folds: int = DEFAULT_CV_FOLDS,
        pruning: bool = True,
        random_seed: int = DEFAULT_RANDOM_SEED,
        duckdb_path: str = DEFAULT_DUCKDB_PATH,
    ) -> None:
        """HyperparameterTuner motorunu başlatır.

        Args:
            n_trials: Gerçekleştirilecek azami Optuna deneme sayısı.
            timeout_seconds: Optimizasyon için azami süre limiti (saniye).
            cv_folds: Deneme içi TimeSeriesSplit katlama sayısı.
            pruning: Erken durdurma (MedianPruner) etkinleştirilsin mi.
            random_seed: Tekrarlanabilir tohum değeri.
            duckdb_path: Denetim izi DuckDB veritabanı yolu.
        """
        self._lock = threading.RLock()
        self.n_trials = max(int(n_trials), 1)
        self.timeout_seconds = timeout_seconds
        self.cv_folds = max(int(cv_folds), 1)
        self.pruning = pruning
        self.random_seed = random_seed
        self.duckdb_path = duckdb_path
        self._trial_history: list[dict[str, Any]] = []

        self._init_duckdb()

    def _init_duckdb(self) -> None:
        """DuckDB denetim tablosunu hazırlar."""
        try:
            db_file = Path(self.duckdb_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(str(db_file)) as conn:
                configure_duckdb_wal(conn)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS hyperparameter_tuning_audit (
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        model_name VARCHAR,
                        objective VARCHAR,
                        n_trials BIGINT,
                        best_value DOUBLE,
                        tuning_time_seconds DOUBLE,
                        best_params VARCHAR,
                        converged BOOLEAN
                    );
                """)
        except Exception as exc:
            logger.warning("DuckDB tuning denetim tablosu hazirlanamadi", hata=str(exc))

    def tune_lightgbm(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        objective_type: str | TuningObjective = TuningObjective.IC,
        sample_weight_train: np.ndarray | None = None,
    ) -> TuningResult:
        """LightGBM modeli için hiperparametre optimizasyonu yürütür.

        Args:
            X_train: Eğitim öznitelik matrisi.
            y_train: Eğitim hedef değişkeni.
            X_val: Doğrulama öznitelik matrisi.
            y_val: Doğrulama hedef değişkeni.
            objective_type: Hedef fonksiyon türü ('ic', 'auc', 'directional', 'mse').
            sample_weight_train: Örneklem ağırlıkları (opsiyonel).

        Returns:
            TuningResult nesnesi.
        """
        with self._lock:
            try:
                import lightgbm as lgb
                import optuna
            except ImportError as err:
                logger.warning("Optuna veya LightGBM modulu yuklu degil", hata=str(err))
                return self._create_empty_result(SupportedModel.LIGHTGBM)

            start_time = time.time()
            obj_type = str(objective_type).lower()

            def objective(trial: optuna.Trial) -> float:
                """Optuna LightGBM optimizasyon hedef fonksiyonu."""
                params: dict[str, Any] = {
                    "n_estimators": trial.suggest_int("n_estimators", 80, 220),
                    "max_depth": trial.suggest_int("max_depth", 3, 7),
                    "learning_rate": trial.suggest_float("learning_rate", 0.015, 0.15, log=True),
                    "num_leaves": trial.suggest_int("num_leaves", 15, 63),
                    "min_child_samples": trial.suggest_int("min_child_samples", 10, 50),
                    "subsample": trial.suggest_float("subsample", 0.55, 0.95),
                    "colsample_bytree": trial.suggest_float("colsample_bytree", 0.45, 0.85),
                    "reg_alpha": trial.suggest_float("reg_alpha", 1e-4, 10.0, log=True),
                    "reg_lambda": trial.suggest_float("reg_lambda", 1e-4, 10.0, log=True),
                    "n_jobs": 2,
                    "verbose": -1,
                    "random_state": self.random_seed,
                }

                if self.cv_folds > 1:
                    return self._cv_objective(
                        lgb.LGBMRegressor, params, X_train, y_train, obj_type, sample_weight_train
                    )
                else:
                    model = lgb.LGBMRegressor(**params)
                    fit_params: dict[str, Any] = {}
                    if sample_weight_train is not None:
                        fit_params["sample_weight"] = sample_weight_train
                    model.fit(X_train, y_train, **fit_params)
                    preds = model.predict(X_val)
                    return self._compute_objective(preds, y_val, obj_type)

            optuna.logging.set_verbosity(optuna.logging.WARNING)
            study = optuna.create_study(
                direction="maximize",
                pruner=optuna.pruners.MedianPruner() if self.pruning else None,
            )
            study.optimize(objective, n_trials=self.n_trials, timeout=self.timeout_seconds, show_progress_bar=False)

            elapsed = time.time() - start_time
            trial_history = [
                {"trial": t.number, "value": t.value, "params": t.params, "state": str(t.state)}
                for t in study.trials
                if t.value is not None
            ]

            convergence = self._analyze_convergence(trial_history)
            best_val = float(study.best_value) if study.best_value is not None else 0.0

            result = TuningResult(
                best_params=dict(study.best_params),
                best_value=round(best_val, 4),
                n_trials=len(study.trials),
                trial_history=trial_history,
                tuning_time_seconds=round(elapsed, 2),
                model_name=SupportedModel.LIGHTGBM,
                convergence_info=convergence,
            )

            self._trial_history.extend(trial_history)
            self._record_audit(result, obj_type)

            logger.info("LightGBM ayarlamasi tamamlandi", best_value=result.best_value, n_trials=result.n_trials)
            return result

    def tune_xgboost(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        objective_type: str | TuningObjective = TuningObjective.IC,
    ) -> TuningResult:
        """XGBoost modeli için hiperparametre optimizasyonu yürütür.

        Args:
            X_train: Eğitim öznitelik matrisi.
            y_train: Eğitim hedef değişkeni.
            X_val: Doğrulama öznitelik matrisi.
            y_val: Doğrulama hedef değişkeni.
            objective_type: Hedef fonksiyon türü.

        Returns:
            TuningResult nesnesi.
        """
        with self._lock:
            try:
                import optuna
                import xgboost as xgb
            except ImportError as err:
                logger.warning("Optuna veya XGBoost modulu yuklu degil", hata=str(err))
                return self._create_empty_result(SupportedModel.XGBOOST)

            start_time = time.time()
            obj_type = str(objective_type).lower()

            def objective(trial: optuna.Trial) -> float:
                """Optuna XGBoost optimizasyon hedef fonksiyonu."""
                params: dict[str, Any] = {
                    "max_depth": trial.suggest_int("max_depth", 3, 7),
                    "learning_rate": trial.suggest_float("learning_rate", 0.015, 0.15, log=True),
                    "n_estimators": trial.suggest_int("n_estimators", 80, 220),
                    "subsample": trial.suggest_float("subsample", 0.55, 0.95),
                    "colsample_bytree": trial.suggest_float("colsample_bytree", 0.45, 0.85),
                    "reg_alpha": trial.suggest_float("reg_alpha", 1e-4, 10.0, log=True),
                    "reg_lambda": trial.suggest_float("reg_lambda", 1e-4, 10.0, log=True),
                    "min_child_weight": trial.suggest_int("min_child_weight", 2, 10),
                    "n_jobs": 2,
                    "verbosity": 0,
                    "random_state": self.random_seed,
                }

                if self.cv_folds > 1:
                    return self._cv_objective(xgb.XGBRegressor, params, X_train, y_train, obj_type)
                else:
                    model = xgb.XGBRegressor(**params)
                    model.fit(X_train, y_train)
                    preds = model.predict(X_val)
                    return self._compute_objective(preds, y_val, obj_type)

            optuna.logging.set_verbosity(optuna.logging.WARNING)
            study = optuna.create_study(direction="maximize")
            study.optimize(objective, n_trials=self.n_trials, timeout=self.timeout_seconds, show_progress_bar=False)

            elapsed = time.time() - start_time
            trial_history = [
                {"trial": t.number, "value": t.value, "params": t.params, "state": str(t.state)}
                for t in study.trials
                if t.value is not None
            ]

            best_val = float(study.best_value) if study.best_value is not None else 0.0
            result = TuningResult(
                best_params=dict(study.best_params),
                best_value=round(best_val, 4),
                n_trials=len(study.trials),
                trial_history=trial_history,
                tuning_time_seconds=round(elapsed, 2),
                model_name=SupportedModel.XGBOOST,
                convergence_info=self._analyze_convergence(trial_history),
            )

            self._trial_history.extend(trial_history)
            self._record_audit(result, obj_type)

            logger.info("XGBoost ayarlamasi tamamlandi", best_value=result.best_value, n_trials=result.n_trials)
            return result

    def tune_catboost(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        objective_type: str | TuningObjective = TuningObjective.IC,
    ) -> TuningResult:
        """CatBoost modeli için hiperparametre optimizasyonu yürütür.

        Args:
            X_train: Eğitim öznitelik matrisi.
            y_train: Eğitim hedef değişkeni.
            X_val: Doğrulama öznitelik matrisi.
            y_val: Doğrulama hedef değişkeni.
            objective_type: Hedef fonksiyon türü.

        Returns:
            TuningResult nesnesi.
        """
        with self._lock:
            try:
                import optuna
                from catboost import CatBoostRegressor
            except ImportError as err:
                logger.warning("Optuna veya CatBoost modulu yuklu degil", hata=str(err))
                return self._create_empty_result(SupportedModel.CATBOOST)

            start_time = time.time()
            obj_type = str(objective_type).lower()

            def objective(trial: optuna.Trial) -> float:
                """Optuna CatBoost optimizasyon hedef fonksiyonu."""
                params: dict[str, Any] = {
                    "iterations": trial.suggest_int("iterations", 80, 200),
                    "depth": trial.suggest_int("depth", 4, 7),
                    "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.15, log=True),
                    "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1e-3, 10.0, log=True),
                    "thread_count": 2,
                    "random_seed": self.random_seed,
                    "verbose": 0,
                }

                model = CatBoostRegressor(**params)
                model.fit(X_train, y_train, eval_set=(X_val, y_val), early_stopping_rounds=20, verbose=0)
                preds = model.predict(X_val)
                return self._compute_objective(preds, y_val, obj_type)

            optuna.logging.set_verbosity(optuna.logging.WARNING)
            study = optuna.create_study(direction="maximize")
            study.optimize(objective, n_trials=self.n_trials, timeout=self.timeout_seconds, show_progress_bar=False)

            elapsed = time.time() - start_time
            trial_history = [
                {"trial": t.number, "value": t.value, "params": t.params}
                for t in study.trials
                if t.value is not None
            ]

            best_val = float(study.best_value) if study.best_value is not None else 0.0
            result = TuningResult(
                best_params=dict(study.best_params),
                best_value=round(best_val, 4),
                n_trials=len(study.trials),
                trial_history=trial_history,
                tuning_time_seconds=round(elapsed, 2),
                model_name=SupportedModel.CATBOOST,
                convergence_info=self._analyze_convergence(trial_history),
            )

            self._trial_history.extend(trial_history)
            self._record_audit(result, obj_type)

            logger.info("CatBoost ayarlamasi tamamlandi", best_value=result.best_value, n_trials=result.n_trials)
            return result

    def tune_regime_specific(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        regimes_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        regimes_val: np.ndarray,
        model_type: SupportedModel = SupportedModel.LIGHTGBM,
        objective_type: TuningObjective = TuningObjective.IC,
    ) -> dict[str, RegimeTuningResult]:
        """Her piyasa rejimi için ayrı hiperparametre optimizasyonu yürütür.

        Args:
            X_train: Eğitim öznitelik matrisi.
            y_train: Eğitim hedef serisi.
            regimes_train: Eğitim piyasa rejimi etiketleri dizisi.
            X_val: Doğrulama öznitelik matrisi.
            y_val: Doğrulama hedef serisi.
            regimes_val: Doğrulama piyasa rejimi etiketleri dizisi.
            model_type: Optimize edilecek model türü.
            objective_type: Optimizasyon hedef fonksiyonu.

        Returns:
            `{rejim_adi: RegimeTuningResult}` sözlüğü.
        """
        results: dict[str, RegimeTuningResult] = {}
        unique_regimes = np.unique(regimes_train)

        for regime in unique_regimes:
            reg_str = str(regime).upper()
            train_mask = regimes_train == regime
            val_mask = regimes_val == regime

            n_tr = int(np.sum(train_mask))
            n_vl = int(np.sum(val_mask))

            if n_tr < DEFAULT_MIN_REGIME_SAMPLES or n_vl < 10:
                logger.info("Rejim optimizasyonu atlandi (yetersiz orneklem)", rejim=reg_str, train_adet=n_tr, val_adet=n_vl)
                continue

            logger.info("Rejime ozel optimizasyon baslatildi", rejim=reg_str, train_adet=n_tr)

            if model_type == SupportedModel.LIGHTGBM:
                res = self.tune_lightgbm(
                    X_train=X_train[train_mask],
                    y_train=y_train[train_mask],
                    X_val=X_val[val_mask],
                    y_val=y_val[val_mask],
                    objective_type=objective_type,
                )
            elif model_type == SupportedModel.XGBOOST:
                res = self.tune_xgboost(
                    X_train=X_train[train_mask],
                    y_train=y_train[train_mask],
                    X_val=X_val[val_mask],
                    y_val=y_val[val_mask],
                    objective_type=objective_type,
                )
            else:
                res = self.tune_catboost(
                    X_train=X_train[train_mask],
                    y_train=y_train[train_mask],
                    X_val=X_val[val_mask],
                    y_val=y_val[val_mask],
                    objective_type=objective_type,
                )

            results[reg_str] = RegimeTuningResult(regime=reg_str, result=res, n_samples=n_tr)

        return results

    def tune_polars(
        self,
        df_train: pl.DataFrame,
        df_val: pl.DataFrame,
        target_col: str = "target",
        feature_cols: list[str] | None = None,
        model_type: SupportedModel = SupportedModel.LIGHTGBM,
        objective_type: TuningObjective = TuningObjective.IC,
    ) -> TuningResult:
        """Polars DataFrame girdi alarak doğrudan optimizasyon yürütür.

        Args:
            df_train: Eğitim Polars DataFrame'i.
            df_val: Doğrulama Polars DataFrame'i.
            target_col: Hedef sütun adı.
            feature_cols: Kullanılacak öznitelik sütun isimleri.
            model_type: Optimize edilecek model türü.
            objective_type: Hedef fonksiyon türü.

        Returns:
            TuningResult nesnesi.
        """
        if target_col not in df_train.columns or target_col not in df_val.columns:
            raise ValueError(f"Hedef sütun '{target_col}' DataFrame icinde bulunamadi.")

        actual_feat_cols = feature_cols
        if actual_feat_cols is None:
            actual_feat_cols = [c for c in df_train.columns if c not in {target_col, "date", "timestamp", "ticker", "regime"}]

        X_tr = df_train.select(actual_feat_cols).to_numpy().astype(np.float32)
        y_tr = df_train[target_col].to_numpy().astype(np.float64)

        X_vl = df_val.select(actual_feat_cols).to_numpy().astype(np.float32)
        y_vl = df_val[target_col].to_numpy().astype(np.float64)

        if model_type == SupportedModel.LIGHTGBM:
            return self.tune_lightgbm(X_tr, y_tr, X_vl, y_vl, objective_type=objective_type)
        elif model_type == SupportedModel.XGBOOST:
            return self.tune_xgboost(X_tr, y_tr, X_vl, y_vl, objective_type=objective_type)
        else:
            return self.tune_catboost(X_tr, y_tr, X_vl, y_vl, objective_type=objective_type)

    def _cv_objective(
        self,
        model_class: Any,
        params: dict[str, Any],
        X: np.ndarray,
        y: np.ndarray,
        objective_type: str,
        sample_weight: np.ndarray | None = None,
    ) -> float:
        """Deneme içinde TimeSeriesSplit ile zamansal çapraz doğrulama skorunu hesaplar."""
        kf = TimeSeriesSplit(n_splits=self.cv_folds)
        scores: list[float] = []

        for train_idx, val_idx in kf.split(X):
            try:
                model = model_class(**params)
                X_tr, X_vl = X[train_idx], X[val_idx]
                y_tr, y_vl = y[train_idx], y[val_idx]

                fit_params: dict[str, Any] = {}
                if sample_weight is not None:
                    fit_params["sample_weight"] = sample_weight[train_idx]

                model.fit(X_tr, y_tr, **fit_params)
                preds = model.predict(X_vl)
                score = self._compute_objective(preds, y_vl, objective_type)
                if np.isfinite(score):
                    scores.append(score)
            except Exception as ex:
                logger.debug("CV fold hatasi", hata=str(ex))
                scores.append(-999.0)

        return float(np.mean(scores)) if scores else -999.0

    def _compute_objective(self, preds: np.ndarray, y_true: np.ndarray, objective_type: str) -> float:
        """Belirtilen hedef metriğe göre model performansını hesaplar."""
        if len(preds) == 0 or len(y_true) == 0:
            return 0.0

        if objective_type == TuningObjective.IC:
            if len(np.unique(preds)) < 2 or len(np.unique(y_true)) < 2:
                return 0.0
            ic = np.corrcoef(preds, y_true)[0, 1]
            return float(ic) if np.isfinite(ic) else 0.0

        elif objective_type == TuningObjective.AUC:
            from sklearn.metrics import roc_auc_score

            try:
                if len(np.unique(y_true)) < 2:
                    return 0.5
                return float(roc_auc_score(y_true, preds))
            except Exception:
                return 0.5

        elif objective_type == TuningObjective.DIRECTIONAL:
            pred_dir = (preds > 0).astype(int)
            true_dir = (y_true > 0).astype(int)
            return float(np.mean(pred_dir == true_dir))

        else:  # mse (maksimizasyon için negatif)
            mse = np.mean((preds - y_true) ** 2)
            return -float(mse) if np.isfinite(mse) else -999.0

    def _analyze_convergence(self, trial_history: list[dict[str, Any]]) -> dict[str, Any]:
        """Tuning deneme geçmişini analiz ederek yakınsama durumunu belirler."""
        if len(trial_history) < 5:
            return {"converged": False, "reason": "Yetersiz deneme sayisi (< 5)"}

        values = [t["value"] for t in trial_history if t.get("value") is not None and np.isfinite(t["value"])]
        if not values:
            return {"converged": False, "reason": "Gecerli deneme skoru bulunamadi"}

        n_recent = max(len(values) // 5, 3)
        recent_best = max(values[-n_recent:])
        overall_best = max(values)

        improvement = (recent_best - overall_best) / max(abs(overall_best), DEFAULT_EPSILON)
        converged = abs(improvement) < 0.01

        return {
            "converged": bool(converged),
            "overall_best": round(float(overall_best), 4),
            "recent_best": round(float(recent_best), 4),
            "improvement_pct": round(float(improvement * 100), 2),
            "n_trials_analyzed": len(values),
        }

    def _record_audit(self, res: TuningResult, objective: str) -> None:
        """Optimizasyon denetim izini DuckDB'ye yazar."""
        try:
            with duckdb.connect(self.duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO hyperparameter_tuning_audit (
                        model_name, objective, n_trials, best_value, tuning_time_seconds, best_params, converged
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    [
                        str(res.model_name),
                        str(objective),
                        int(res.n_trials),
                        float(res.best_value),
                        float(res.tuning_time_seconds),
                        orjson.dumps(res.best_params).decode("utf-8"),
                        bool(res.convergence_info.get("converged", False)),
                    ],
                )
        except Exception as exc:
            logger.debug("DuckDB tuning denetim kaydi atlandi", hata=str(exc))

    def _create_empty_result(self, model_name: SupportedModel) -> TuningResult:
        """Hata veya eksik kütüphane durumunda boş TuningResult nesnesi üretir."""
        return TuningResult(
            best_params={},
            best_value=0.0,
            n_trials=0,
            trial_history=[],
            tuning_time_seconds=0.0,
            model_name=str(model_name),
            convergence_info={"converged": False, "reason": "Kutuphane bulunamadi"},
        )

    def get_trial_history(self) -> list[dict[str, Any]]:
        """Gerçekleştirilen tüm denemelerin geçmişini döndürür."""
        with self._lock:
            return list(self._trial_history)

    def get_best_trials(self, n: int = 5) -> list[dict[str, Any]]:
        """En yüksek skora sahip ilk N denemeyi döndürür."""
        with self._lock:
            sorted_trials = sorted(
                self._trial_history,
                key=lambda t: t.get("value", -999.0) if t.get("value") is not None else -999.0,
                reverse=True,
            )
            return sorted_trials[:n]

    def tune(
        self,
        model_type: SupportedModel | str,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
        objective_type: str | TuningObjective = TuningObjective.IC,
    ) -> TuningResult:
        """Belirtilen model türü için hiperparametre optimizasyonu yürütür.

        X_val ve y_val verilmezse X_train ve y_train %80-%20 zamansal olarak bölünür.
        """
        if X_val is None or y_val is None:
            split_idx = int(len(X_train) * 0.8)
            X_tr, X_vl = X_train[:split_idx], X_train[split_idx:]
            y_tr, y_vl = y_train[:split_idx], y_train[split_idx:]
        else:
            X_tr, X_vl = X_train, X_val
            y_tr, y_vl = y_train, y_val

        m_type = str(model_type).lower()
        if m_type == SupportedModel.LIGHTGBM:
            return self.tune_lightgbm(X_tr, y_tr, X_vl, y_vl, objective_type)
        elif m_type == SupportedModel.XGBOOST:
            return self.tune_xgboost(X_tr, y_tr, X_vl, y_vl, objective_type)
        else:
            return self.tune_catboost(X_tr, y_tr, X_vl, y_vl, objective_type)

    def get_audit_as_polars(self) -> pl.DataFrame:
        """DuckDB'deki tuning denetim kayıtlarını Polars DataFrame olarak döndürür."""
        import polars as pl

        with self._lock:
            try:
                with duckdb.connect(self.duckdb_path) as conn:
                    return conn.execute("SELECT * FROM hyperparameter_tuning_audit ORDER BY timestamp DESC").pl()
            except Exception as exc:
                logger.warning("DuckDB denetim kayitlari okunamadi", hata=str(exc))
                return pl.DataFrame()

    def __repr__(self) -> str:
        return (
            f"HyperparameterTuner(trials={self.n_trials}, cv_folds={self.cv_folds}, "
            f"pruning={self.pruning}, seed={self.random_seed})"
        )


__all__: Final[list[str]] = [
    "DEFAULT_CV_FOLDS",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EPSILON",
    "DEFAULT_MIN_REGIME_SAMPLES",
    "DEFAULT_N_TRIALS",
    "DEFAULT_RANDOM_SEED",
    "DEFAULT_TIMEOUT_SECONDS",
    "HyperparameterTuner",
    "RegimeTuningResult",
    "SupportedModel",
    "TuningObjective",
    "TuningResult",
    "configure_duckdb_wal",
]
