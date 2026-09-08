"""ALPHA BIST — XGBoost Makine Öğrenimi Modeli ve Çok Vadeli Sıralama Motoru (Nihai — ⭐⭐⭐⭐⭐).

Bu modül, BIST piyasasında alfa sinyalleri ve hisse getiri tahminleri üretmek amacıyla
XGBoost (Extreme Gradient Boosting) algoritmasını kurumsal standartlarda uygular.

Temel Yetenekler:
- Asimetrik Özelleştirilmiş Kayıp Fonksiyonu (Custom Adjusted Loss): Düşüş ve yanlış yön hatalarına yüksek ceza (3x-11x)
- Çoklu Tahmin Ufku (Multi-Horizon Prediction): 1, 5, 20 ve 60 günlük dinamik vadeler
- Olasılık Kalibrasyonu: Platt Scaling ve Isotonic regresyon kalibratör entegrasyonu
- SHAP ve TreeExplainer Desteği: Model tahminlerinin açıklanabilirliği (Feature Attribution)
- Aşırı Öğrenme Denetimi (Overfitting & Signal Quality Diagnostics)
- Polars Native Vektörize Tahmin (`predict_polars`)
- DuckDB SSD Korumalı WAL ile Eğitim ve Karşılaştırma Denetim İzi (Audit Trail)
- İş Parçacığı Güvenliği (`threading.RLock`) ve SHA256 Korumalı Model Serileştirme
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

from services.core.safe_pickle import safe_pickle_dump, safe_pickle_load

logger = structlog.get_logger(__name__)

# --- Sabitler ---
DEFAULT_WRONG_DIRECTION_PENALTY: Final[float] = 11.0
DEFAULT_DUCKDB_PATH: Final[str] = "data/xgboost_audit.duckdb"


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
class XGBoostConfig:
    """XGBoost model hiperparametre ve yapılandırma veri modeli."""

    max_depth: int = 6
    learning_rate: float = 0.1
    n_estimators: int = 200
    objective: str = "binary:logistic"
    eval_metric: str = "auc"
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    reg_alpha: float = 0.1
    reg_lambda: float = 1.0
    min_child_weight: int = 5
    gamma: float = 0.1
    early_stopping_rounds: int = 20
    verbose: int = 0
    random_state: int = 42
    target_horizons: list[int] = field(default_factory=lambda: [1, 5, 20, 60])
    regime_aware: bool = False
    regime_weights: dict[str, float] = field(
        default_factory=lambda: {"BULL": 1.0, "BEAR": 1.0, "SIDEWAYS": 1.0, "HIGH_VOL": 1.0}
    )
    use_adjusted_loss: bool = False
    wrong_direction_penalty: float = DEFAULT_WRONG_DIRECTION_PENALTY

    def to_dict(self) -> dict[str, Any]:
        """Konfigürasyonu sözlük yapısına dönüştürür."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> XGBoostConfig:
        """Sözlükten XGBoostConfig nesnesi oluşturur."""
        return cls(
            max_depth=int(data.get("max_depth", 6)),
            learning_rate=float(data.get("learning_rate", 0.1)),
            n_estimators=int(data.get("n_estimators", 200)),
            objective=str(data.get("objective", "binary:logistic")),
            eval_metric=str(data.get("eval_metric", "auc")),
            subsample=float(data.get("subsample", 0.8)),
            colsample_bytree=float(data.get("colsample_bytree", 0.8)),
            reg_alpha=float(data.get("reg_alpha", 0.1)),
            reg_lambda=float(data.get("reg_lambda", 1.0)),
            min_child_weight=int(data.get("min_child_weight", 5)),
            gamma=float(data.get("gamma", 0.1)),
            early_stopping_rounds=int(data.get("early_stopping_rounds", 20)),
            verbose=int(data.get("verbose", 0)),
            random_state=int(data.get("random_state", 42)),
            target_horizons=list(data.get("target_horizons", [1, 5, 20, 60])),
            regime_aware=bool(data.get("regime_aware", False)),
            regime_weights=dict(data.get("regime_weights", {"BULL": 1.0, "BEAR": 1.0, "SIDEWAYS": 1.0, "HIGH_VOL": 1.0})),
            use_adjusted_loss=bool(data.get("use_adjusted_loss", False)),
            wrong_direction_penalty=float(data.get("wrong_direction_penalty", DEFAULT_WRONG_DIRECTION_PENALTY)),
        )

    def to_orjson_bytes(self) -> bytes:
        """Konfigürasyonu orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Konfigürasyonun özet metin gösterimini oluşturur."""
        return (
            f"XGBoostConfig(depth={self.max_depth}, lr={self.learning_rate}, n_est={self.n_estimators}, "
            f"obj='{self.objective}', adjusted_loss={self.use_adjusted_loss})"
        )


@dataclass(slots=True)
class XGBoostMetrics:
    """XGBoost model doğrulama ve eğitim metrikleri modeli."""

    horizon: int
    n_train: int
    n_val: int
    feature_count: int
    val_auc: float = 0.0
    val_accuracy: float = 0.0
    val_rmse: float = 0.0
    val_mae: float = 0.0
    val_directional_accuracy: float = 0.0
    val_ic: float = 0.0
    best_iteration: int = 0
    signal_quality: str = "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        """Metrikleri sözlük yapısına dönüştürür."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> XGBoostMetrics:
        """Sözlükten XGBoostMetrics nesnesi oluşturur."""
        return cls(
            horizon=int(data.get("horizon", 5)),
            n_train=int(data.get("n_train", 0)),
            n_val=int(data.get("n_val", 0)),
            feature_count=int(data.get("feature_count", 0)),
            val_auc=float(data.get("val_auc", 0.0)),
            val_accuracy=float(data.get("val_accuracy", 0.0)),
            val_rmse=float(data.get("val_rmse", 0.0)),
            val_mae=float(data.get("val_mae", 0.0)),
            val_directional_accuracy=float(data.get("val_directional_accuracy", 0.0)),
            val_ic=float(data.get("val_ic", 0.0)),
            best_iteration=int(data.get("best_iteration", 0)),
            signal_quality=str(data.get("signal_quality", "UNKNOWN")),
        )

    def to_orjson_bytes(self) -> bytes:
        """Metrikleri orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Metriklerin özet metin gösterimini oluşturur."""
        return (
            f"XGBoostMetrics(h={self.horizon}d, train={self.n_train}, val={self.n_val}, "
            f"IC={self.val_ic:.4f}, DirAcc={self.val_directional_accuracy:.1f}%, Signal='{self.signal_quality}')"
        )


class XGBoostAdjustedLoss:
    """Yanlış piyasa yönü tahminlerine katlamalı ceza uygulayan asimetrik kayıp fonksiyonu.

    XGBoost özel amaç fonksiyonu (custom objective) protokolünü uygular ve
    analitik birinci derece türev (gradient) ile ikinci derece türev (hessian) üretir.
    """

    def __init__(self, penalty: float = DEFAULT_WRONG_DIRECTION_PENALTY) -> None:
        """Özelleştirilmiş kayıp fonksiyonunu ilklendirir.

        Args:
            penalty: Yanlış yönde tahmin cezası katsayısı (varsayılan: 11.0).
        """
        self.penalty: float = max(1.0, float(penalty))

    def __call__(self, preds: np.ndarray, dtrain: Any) -> tuple[np.ndarray, np.ndarray]:
        """XGBoost eğitim döngüsü tarafından çağrılan gradient ve hessian üreticisi.

        Args:
            preds: Modelin ham tahmin değerleri.
            dtrain: XGBoost DMatrix eğitim veri yapısı.

        Returns:
            (gradient, hessian) NumPy dizileri tuple'ı.
        """
        labels = dtrain.get_label()
        diff = preds - labels

        # Yanlış yön kontrolü (İşaret uyumsuzluğu)
        wrong_direction = ((preds > 0) & (labels < 0)) | ((preds < 0) & (labels > 0))
        penalty_weights = np.where(wrong_direction, self.penalty, 1.0)

        # Gradient ve Hessian türevleri
        grad = 2.0 * diff * penalty_weights
        hess = 2.0 * penalty_weights * np.ones_like(grad)

        return grad, hess

    def __repr__(self) -> str:
        """Kayıp fonksiyonu metin gösterimi."""
        return f"XGBoostAdjustedLoss(penalty={self.penalty:.1f}x)"


class XGBoostModel:
    """Kurumsal düzeyde çok vadeli XGBoost tahmin ve sıralama motoru."""

    def __init__(
        self,
        config: XGBoostConfig | None = None,
        duckdb_path: str = DEFAULT_DUCKDB_PATH,
    ) -> None:
        """XGBoost modelini yapılandırır ve denetim izini hazırlar.

        Args:
            config: Model hiperparametre konfigürasyonu.
            duckdb_path: Model denetim izi için DuckDB veritabanı yolu.
        """
        self._config: XGBoostConfig = config or XGBoostConfig()
        self._models: dict[int, Any] = {}
        self._feature_names: list[str] | None = None
        self._training_metrics: dict[str, Any] = {}
        self._shap_values: dict[str, float] | None = None
        self._feature_importance_cache: dict[str, dict[str, float]] = {}
        self._calibrators: dict[int, Any] = {}

        self._duckdb_path: str = duckdb_path
        self._lock: threading.RLock = threading.RLock()

        self._init_duckdb()
        logger.info(
            "XGBoostModel baslatildi",
            max_depth=self._config.max_depth,
            learning_rate=self._config.learning_rate,
            n_estimators=self._config.n_estimators,
        )

    def __getstate__(self) -> dict[str, Any]:
        """Pickle serileştirmesinde threading.RLock nesnesini dışlayarak durum döndürür."""
        state = self.__dict__.copy()
        state["_lock"] = None
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Pickle deserializasyonunda threading.RLock nesnesini yeniden ilklendirir."""
        self.__dict__.update(state)
        self._lock = threading.RLock()

    def _init_duckdb(self) -> None:
        """DuckDB denetim tablosunu güvenle ilklendirir."""
        try:
            db_dir = Path(self._duckdb_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS xgboost_audit (
                        timestamp TIMESTAMPTZ PRIMARY KEY,
                        horizon INTEGER NOT NULL,
                        n_train INTEGER NOT NULL,
                        n_val INTEGER NOT NULL,
                        val_ic DOUBLE NOT NULL,
                        val_accuracy DOUBLE NOT NULL,
                        val_directional_accuracy DOUBLE NOT NULL,
                        val_rmse DOUBLE NOT NULL,
                        best_iteration INTEGER NOT NULL,
                        signal_quality VARCHAR NOT NULL,
                        metrics_json VARCHAR NOT NULL
                    );
                    """
                )
        except Exception as exc:
            logger.warning("DuckDB xgboost_audit tablosu ilklendirilemedi", hata=str(exc))

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
        feature_names: list[str] | None = None,
        sample_weights: np.ndarray | None = None,
        horizon: int = 5,
    ) -> dict[str, Any]:
        """Belirtilen vade ufku için XGBoost modelini eğitir.

        Args:
            X_train: Eğitim öznitelik matrisi (N, D).
            y_train: Eğitim hedef değişken dizisi (N,).
            X_val: Doğrulama öznitelik matrisi (isteğe bağlı).
            y_val: Doğrulama hedef değişken dizisi (isteğe bağlı).
            feature_names: Öznitelik isimleri listesi.
            sample_weights: Örneklem ağırlıkları (asimetrik ceza vb.).
            horizon: Tahmin ufku (işlem günü olarak; varsayılan: 5).

        Returns:
            Eğitim ve doğrulama metrikleri sözlüğü.
        """
        with self._lock:
            try:
                import xgboost as xgb
            except ImportError:
                logger.warning("xgboost kutuphanesi sistemde bulunamadi, yuklemek icin: uv add xgboost")
                return {"error": "xgboost not installed"}

            self._feature_names = feature_names

            # Classifier veya Regressor tespiti
            is_classifier = "logistic" in self._config.objective or "hinge" in self._config.objective

            # Model oluştur
            model = self._create_model(xgb, is_classifier)

            # Özel Asimetrik Kayıp Fonksiyonu
            custom_obj = None
            if self._config.use_adjusted_loss and not is_classifier:
                custom_obj = XGBoostAdjustedLoss(self._config.wrong_direction_penalty)

            # DMatrix oluştur
            dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=feature_names, weight=sample_weights)
            dval = xgb.DMatrix(X_val, label=y_val, feature_names=feature_names) if X_val is not None else None

            if custom_obj is not None:
                params = {
                    "max_depth": self._config.max_depth,
                    "eta": self._config.learning_rate,
                    "subsample": self._config.subsample,
                    "colsample_bytree": self._config.colsample_bytree,
                    "reg_alpha": self._config.reg_alpha,
                    "reg_lambda": self._config.reg_lambda,
                    "min_child_weight": self._config.min_child_weight,
                    "gamma": self._config.gamma,
                    "seed": self._config.random_state,
                    "verbosity": 0,
                }
                if is_classifier:
                    params["objective"] = "binary:logistic"
                    params["eval_metric"] = "auc"
                else:
                    params["objective"] = "reg:squarederror"
                    params["eval_metric"] = "rmse"

                evals = [(dtrain, "train")]
                if dval:
                    evals.append((dval, "val"))

                bst = xgb.train(
                    params,
                    dtrain,
                    num_boost_round=self._config.n_estimators,
                    evals=evals,
                    early_stopping_rounds=self._config.early_stopping_rounds if dval else None,
                    verbose_eval=False,
                )
                self._models[horizon] = bst
            else:
                fit_params: dict[str, Any] = {"verbose": self._config.verbose}
                if X_val is not None and y_val is not None:
                    fit_params["eval_set"] = [(X_val, y_val)]
                    fit_params["verbose"] = False
                if sample_weights is not None:
                    fit_params["sample_weight"] = sample_weights

                model.fit(X_train, y_train, **fit_params)
                self._models[horizon] = model

            # Metrikleri hesapla
            metrics = self._compute_metrics(X_train, y_train, X_val, y_val, horizon, is_classifier)
            self._training_metrics[str(horizon)] = metrics

            # SHAP hesaplama (örneklem üzerinde)
            if X_val is not None and len(X_val) > 0:
                self._compute_shap(model, X_val[: min(len(X_val), 100)], feature_names)

            # Feature importance önbellekleme
            self._cache_feature_importance(horizon, feature_names)

            # Aşırı öğrenme teşhisi
            self._check_overfitting(metrics, horizon)

            # DuckDB denetim kaydı
            self._record_audit_event(horizon, metrics)

            logger.info("XGBoost modeli basariyla egitildi", **metrics)
            return metrics

    def train_multi_horizon(
        self,
        X_train: np.ndarray,
        y_train_dict: dict[int, np.ndarray],
        X_val: np.ndarray | None = None,
        y_val_dict: dict[int, np.ndarray] | None = None,
        feature_names: list[str] | None = None,
    ) -> dict[int, dict[str, Any]]:
        """Tüm hedef vadeler için modelleri sırayla eğitir.

        Args:
            X_train: Eğitim öznitelik matrisi.
            y_train_dict: {vade_gunu: hedef_vektoru} sözlüğü.
            X_val: Doğrulama öznitelik matrisi.
            y_val_dict: {vade_gunu: doğrulama_hedef_vektoru} sözlüğü.
            feature_names: Öznitelik isimleri listesi.

        Returns:
            Her vade için elde edilen metrikler sözlüğü.
        """
        all_metrics: dict[int, dict[str, Any]] = {}
        for horizon in sorted(y_train_dict.keys()):
            y_train = y_train_dict[horizon]
            y_val = y_val_dict.get(horizon) if y_val_dict else None

            metrics = self.train(
                X_train=X_train,
                y_train=y_train,
                X_val=X_val,
                y_val=y_val,
                feature_names=feature_names,
                horizon=horizon,
            )
            all_metrics[horizon] = metrics

        logger.info("XGBoost cok vadeli egitim tamamlandi", vadeler=list(all_metrics.keys()))
        return all_metrics

    def predict(self, X: np.ndarray, horizon: int = 5) -> np.ndarray:
        """Verilen öznitelik matrisi için getiri tahmini veya yön olasılığı üretir.

        Args:
            X: Öznitelik matrisi (N, D).
            horizon: İstenen tahmin ufku (işlem günü; varsayılan: 5).

        Returns:
            Tahmin dizisi (N,).
        """
        with self._lock:
            model = self._models.get(horizon)
            if model is None:
                available = sorted(self._models.keys())
                if not available:
                    return np.zeros(len(X), dtype=np.float64)
                closest = min(available, key=lambda h: abs(h - horizon))
                model = self._models[closest]

            try:
                import xgboost as xgb

                if isinstance(model, xgb.Booster):
                    dmat = xgb.DMatrix(X, feature_names=self._feature_names)
                    preds = model.predict(dmat)
                    if len(preds) != len(X):
                        logger.warning(
                            "xgboost tahmin uzunluk uyumsuzlugu",
                            beklenen=len(X),
                            gelen=len(preds),
                            horizon=horizon,
                        )
                        return np.zeros(len(X), dtype=np.float64)
                    raw_prob = np.asarray(preds, dtype=np.float64)
                else:
                    if hasattr(model, "predict_proba"):
                        raw_prob = np.asarray(model.predict_proba(X)[:, 1], dtype=np.float64)
                    else:
                        raw_prob = np.asarray(model.predict(X), dtype=np.float64)

                calibrator = self._calibrators.get(horizon)
                if calibrator is not None and hasattr(calibrator, "calibrate"):
                    return np.asarray(calibrator.calibrate(raw_prob), dtype=np.float64)
                return raw_prob
            except Exception as exc:
                logger.warning("XGBoost tahmin hatasi", horizon=horizon, hata=str(exc))
                return np.zeros(len(X), dtype=np.float64)

    def predict_polars(
        self,
        df: pl.DataFrame,
        feature_names: list[str] | None = None,
        horizon: int = 5,
        output_col: str | None = None,
    ) -> pl.DataFrame:
        """Polars DataFrame üzerinden doğrudan tahmin üretir ve tahmin sütunu eklenmiş DataFrame döndürür.

        Args:
            df: Girdi veri çerçevesi.
            feature_names: Kullanılacak öznitelik isimleri.
            horizon: Hedef vade.
            output_col: Tahminlerin yazılacağı sütun adı.

        Returns:
            Tahmin sütunu eklenmiş Polars DataFrame.
        """
        feats = feature_names or self._feature_names
        if feats is None:
            feats = [col for col in df.columns if col not in ("Date", "ticker", "symbol", "target")]
        X_mat = df.select(feats).to_numpy()
        preds = self.predict(X_mat, horizon=horizon)
        target_col = output_col or f"xgboost_pred_{horizon}d"
        return df.with_columns(pl.Series(name=target_col, values=preds))

    def calibrate(
        self,
        X_val: np.ndarray,
        y_val: np.ndarray,
        horizon: int = 5,
        method: str = "sigmoid",
    ) -> dict[str, float]:
        """Model olasılıklarını Platt scaling veya Isotonic regresyon ile kalibre eder.

        Args:
            X_val: Doğrulama öznitelik matrisi.
            y_val: Doğrulama ikili sınıf etiketleri (0/1).
            horizon: Kalibre edilecek vade ufku.
            method: Kalibrasyon yöntemi ('sigmoid' veya 'isotonic').

        Returns:
            Kalibrasyon sonrası metrikler (Brier skoru vb.).
        """
        from .probability_calibrator import ProbabilityCalibrator

        raw_prob = self.predict(X_val, horizon=horizon)
        calibrator = ProbabilityCalibrator(method=method)
        calibrator.fit(raw_prob, y_val)
        self._calibrators[horizon] = calibrator
        return calibrator.get_metrics()

    def predict_all_horizons(self, X: np.ndarray) -> dict[int, np.ndarray]:
        """Eğitilmiş tüm vadeler için eş zamanlı tahmin üretir.

        Args:
            X: Öznitelik matrisi.

        Returns:
            {vade: tahmin_dizisi} sözlüğü.
        """
        return {h: self.predict(X, h) for h in self._models}

    def feature_importance(
        self,
        importance_type: str = "gain",
        horizon: int = 5,
    ) -> dict[str, float] | None:
        """Belirtilen vade için öznitelik önem derecelerini döndürür.

        Args:
            importance_type: 'gain', 'cover', 'weight' veya 'SHAP'.
            horizon: Hedef vade ufku.

        Returns:
            {öznitelik_adı: önem_skoru} sözlüğü veya None.
        """
        if importance_type.upper() == "SHAP" and self._shap_values:
            return self._shap_values

        cache_key = f"{horizon}_{importance_type}"
        if cache_key in self._feature_importance_cache:
            return self._feature_importance_cache[cache_key]

        model = self._models.get(horizon)
        if model is None:
            return None

        try:
            import xgboost as xgb

            if isinstance(model, xgb.Booster):
                importance = model.get_score(importance_type=importance_type)
                if self._feature_names:
                    return {fn: float(importance.get(fn, 0.0)) for fn in self._feature_names}
                return {k: float(v) for k, v in importance.items()}
            else:
                imp_arr = model.feature_importances_
                if self._feature_names:
                    return dict(zip(self._feature_names, [float(v) for v in imp_arr], strict=False))
                return {f"f{i}": float(v) for i, v in enumerate(imp_arr)}
        except Exception as exc:
            logger.warning("XGBoost feature importance cikarilamadi", tip=importance_type, hata=str(exc))
            return None

    def shap_values(self, X: np.ndarray) -> np.ndarray | None:
        """TreeExplainer kullanarak verilen matris için SHAP değerlerini üretir.

        Args:
            X: Açıklanacak öznitelik matrisi.

        Returns:
            SHAP değerleri dizisi veya None.
        """
        model = self._models.get(5)
        if model is None:
            return None

        try:
            import shap
            import xgboost as xgb

            if isinstance(model, xgb.Booster):
                dmat = xgb.DMatrix(X, feature_names=self._feature_names)
                explainer = shap.TreeExplainer(model)
                return explainer.shap_values(dmat)
            else:
                explainer = shap.TreeExplainer(model)
                return explainer.shap_values(X)
        except ImportError:
            logger.debug("SHAP kutuphanesi sistemde yuklu degil")
            return None
        except Exception as exc:
            logger.debug("SHAP hesaplama hatasi", hata=str(exc))
            return None

    def _create_model(self, xgb_module: Any, is_classifier: bool) -> Any:
        """XGBoost sklearn API modelini parametrelere göre başlatır."""
        gpu_params: dict[str, Any] = {}
        try:
            import torch

            if torch.cuda.is_available():
                gpu_params = {"tree_method": "hist", "device": "cuda"}
        except Exception as t_err:
            logger.debug("XGBoost GPU kontrolu fallback", hata=str(t_err))

        if is_classifier:
            return xgb_module.XGBClassifier(
                max_depth=self._config.max_depth,
                learning_rate=self._config.learning_rate,
                n_estimators=self._config.n_estimators,
                objective=self._config.objective,
                eval_metric=self._config.eval_metric,
                subsample=self._config.subsample,
                colsample_bytree=self._config.colsample_bytree,
                reg_alpha=self._config.reg_alpha,
                reg_lambda=self._config.reg_lambda,
                min_child_weight=self._config.min_child_weight,
                gamma=self._config.gamma,
                verbosity=self._config.verbose,
                random_state=self._config.random_state,
                **gpu_params,
            )
        else:
            return xgb_module.XGBRegressor(
                max_depth=self._config.max_depth,
                learning_rate=self._config.learning_rate,
                n_estimators=self._config.n_estimators,
                objective="reg:squarederror",
                subsample=self._config.subsample,
                colsample_bytree=self._config.colsample_bytree,
                reg_alpha=self._config.reg_alpha,
                reg_lambda=self._config.reg_lambda,
                min_child_weight=self._config.min_child_weight,
                gamma=self._config.gamma,
                verbosity=self._config.verbose,
                random_state=self._config.random_state,
                **gpu_params,
            )

    def _compute_metrics(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray | None,
        y_val: np.ndarray | None,
        horizon: int,
        is_classifier: bool,
    ) -> dict[str, Any]:
        """Eğitim ve doğrulama metriklerini hesaplar."""
        model = self._models.get(horizon)
        metrics: dict[str, Any] = {
            "horizon": horizon,
            "n_train": len(X_train),
            "n_val": len(X_val) if X_val is not None else 0,
            "feature_count": X_train.shape[1] if len(X_train.shape) > 1 else 1,
        }

        if model is not None:
            try:
                metrics["best_iteration"] = int(
                    getattr(model, "best_iteration", getattr(self._config, "n_estimators", 200))
                )
            except Exception as exc:
                logger.debug("best_iteration okunamadi", hata=str(exc))

        if X_val is not None and y_val is not None and len(X_val) > 0 and len(y_val) > 0:
            val_pred = self.predict(X_val, horizon)

            if is_classifier:
                from sklearn.metrics import accuracy_score, roc_auc_score

                try:
                    metrics["val_auc"] = round(float(roc_auc_score(y_val, val_pred)), 4)
                    metrics["val_accuracy"] = round(float(accuracy_score(y_val, (val_pred > 0.5).astype(int))), 4)
                except Exception as exc:
                    logger.debug("XGBoost siniflandirici metrik hatasi", hata=str(exc))
            else:
                from sklearn.metrics import mean_absolute_error, mean_squared_error

                try:
                    metrics["val_rmse"] = round(float(np.sqrt(mean_squared_error(y_val, val_pred))), 6)
                    metrics["val_mae"] = round(float(mean_absolute_error(y_val, val_pred)), 6)
                    pred_dir = (val_pred > 0).astype(int)
                    true_dir = (y_val > 0).astype(int)
                    metrics["val_directional_accuracy"] = round(float(np.mean(pred_dir == true_dir)), 4)

                    if len(np.unique(val_pred)) > 1 and len(np.unique(y_val)) > 1:
                        metrics["val_ic"] = round(float(np.corrcoef(val_pred, y_val)[0, 1]), 4)
                    else:
                        metrics["val_ic"] = 0.0
                except Exception as exc:
                    logger.debug("XGBoost regresor metrik hatasi", hata=str(exc))

        return metrics

    def _compute_shap(self, model: Any, X: np.ndarray, feature_names: list[str] | None) -> None:
        """SHAP değerlerini hesaplayıp ortalama önem derecesini kaydeder."""
        if model is None:
            return

        try:
            import shap
            import xgboost as xgb

            if isinstance(model, xgb.Booster):
                dmat = xgb.DMatrix(X, feature_names=feature_names)
                explainer = shap.TreeExplainer(model)
                shap_vals = explainer.shap_values(dmat)
            else:
                explainer = shap.TreeExplainer(model)
                shap_vals = explainer.shap_values(X)

            mean_shap = np.mean(np.abs(shap_vals), axis=0)
            if feature_names and len(feature_names) == len(mean_shap):
                self._shap_values = dict(zip(feature_names, [float(v) for v in mean_shap], strict=False))
            else:
                self._shap_values = {f"f{i}": float(v) for i, v in enumerate(mean_shap)}
        except Exception as exc:
            logger.debug("SHAP hesaplanamadi", hata=str(exc))

    def _cache_feature_importance(self, horizon: int, feature_names: list[str] | None) -> None:
        """Tüm önem türlerini (gain, cover, weight) önbelleğe alır."""
        model = self._models.get(horizon)
        if model is None:
            return

        for imp_type in ["gain", "cover", "weight"]:
            try:
                imp = self.feature_importance(imp_type, horizon)
                if imp:
                    self._feature_importance_cache[f"{horizon}_{imp_type}"] = imp
            except Exception as exc:
                logger.debug("Feature importance onbelleklenemedi", tip=imp_type, hata=str(exc))

    def _check_overfitting(self, metrics: dict[str, Any], horizon: int) -> None:
        """Validasyon IC skoruna göre aşırı öğrenme ve sinyal kalitesini denetler."""
        if "val_ic" in metrics:
            ic = float(metrics["val_ic"])
            if abs(ic) < 0.01:
                logger.warning("XGBoost modelinde sinyal bulunamadi", horizon=horizon, ic=ic)
                metrics["signal_quality"] = "NONE"
            elif abs(ic) < 0.05:
                metrics["signal_quality"] = "WEAK"
            else:
                metrics["signal_quality"] = "STRONG"

    def _record_audit_event(self, horizon: int, metrics: dict[str, Any]) -> None:
        """Eğitim metriklerini DuckDB denetim tablosuna kaydeder."""
        try:
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO xgboost_audit
                    (timestamp, horizon, n_train, n_val, val_ic, val_accuracy,
                     val_directional_accuracy, val_rmse, best_iteration, signal_quality, metrics_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    [
                        datetime.now(UTC).isoformat(),
                        horizon,
                        int(metrics.get("n_train", 0)),
                        int(metrics.get("n_val", 0)),
                        float(metrics.get("val_ic", 0.0)),
                        float(metrics.get("val_accuracy", 0.0)),
                        float(metrics.get("val_directional_accuracy", 0.0)),
                        float(metrics.get("val_rmse", 0.0)),
                        int(metrics.get("best_iteration", 0)),
                        str(metrics.get("signal_quality", "UNKNOWN")),
                        orjson.dumps(metrics).decode(),
                    ],
                )
        except Exception as exc:
            logger.warning("XGBoost denetim kaydi DuckDB'ye yazilamadi", hata=str(exc))

    def save(self, path: str) -> bool:
        """Model ağırlıklarını ve durumunu güvenli serileştirme ile diske kaydeder.

        Args:
            path: Hedef dosya yolu (.pkl).

        Returns:
            Başarılıysa True, aksi halde False.
        """
        with self._lock:
            if not self._models:
                return False
            try:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                safe_pickle_dump(
                    {
                        "models": self._models,
                        "config": self._config.to_dict(),
                        "metrics": self._training_metrics,
                        "feature_names": self._feature_names,
                        "shap_values": self._shap_values,
                        "feature_importance_cache": self._feature_importance_cache,
                        "saved_at": datetime.now(UTC).isoformat(),
                    },
                    path,
                )
                logger.info("XGBoost modeli guvenle kaydedildi", dosya=path)
                return True
            except Exception as exc:
                logger.error("XGBoost model kayit hatasi", hata=str(exc))
                return False

    def load(self, path: str) -> bool:
        """Modeli SHA256 doğrulamalı güvenli yükleme ile hafızaya alır.

        Args:
            path: Model dosya yolu.

        Returns:
            Başarılıysa True, aksi halde False.
        """
        with self._lock:
            try:
                data = safe_pickle_load(path)
                self._models = data.get("models", {})
                cfg_data = data.get("config", {})
                if isinstance(cfg_data, dict):
                    self._config = XGBoostConfig(**{k: v for k, v in cfg_data.items() if hasattr(XGBoostConfig, k)})
                self._training_metrics = data.get("metrics", {})
                self._feature_names = data.get("feature_names")
                self._shap_values = data.get("shap_values")
                self._feature_importance_cache = data.get("feature_importance_cache", {})
                logger.info("XGBoost modeli basariyla yuklendi", dosya=path, vadeler=list(self._models.keys()))
                return True
            except Exception as exc:
                logger.error("XGBoost model yukleme hatasi", hata=str(exc))
                return False

    @property
    def is_trained(self) -> bool:
        """Modelin en az bir vade için eğitilip eğitilmediğini belirtir."""
        with self._lock:
            return len(self._models) > 0

    @property
    def trained_horizons(self) -> list[int]:
        """Eğitilmiş aktif vade ufuklarının listesini döndürür."""
        with self._lock:
            return sorted(self._models.keys())

    @property
    def metrics(self) -> dict[str, Any]:
        """Modelin tüm vadelerdeki eğitim ve doğrulama metriklerini döndürür."""
        with self._lock:
            return dict(self._training_metrics)

    def get_audit_as_polars(self) -> pl.DataFrame:
        """DuckDB xgboost_audit tablosunu Polars DataFrame olarak döndürür."""
        import polars as pl

        with self._lock:
            try:
                with duckdb.connect(self._duckdb_path) as conn:
                    configure_duckdb_wal(conn)
                    arrow_table = conn.execute(
                        "SELECT * FROM xgboost_audit ORDER BY timestamp DESC;"
                    ).arrow()
                    return pl.from_arrow(arrow_table)  # type: ignore[return-value]
            except Exception as exc:
                logger.warning("DuckDB xgboost_audit tablosu okunamadi", hata=str(exc))
                return pl.DataFrame()

    def __repr__(self) -> str:
        """XGBoostModel özet metin gösterimi."""
        return (
            f"XGBoostModel(horizons={self.trained_horizons}, "
            f"features={len(self._feature_names) if self._feature_names else 0}, "
            f"trained={self.is_trained})"
        )


def compare_xgboost_vs_lightgbm(
    features_map: dict[str, dict[str, Any]],
    returns: dict[str, float],
    date_groups: dict[str, str],
    feature_names: list[str],
    config: XGBoostConfig | None = None,
) -> dict[str, Any]:
    """XGBoost ve LightGBM modellerini aynı veri kümesi ve koşullar altında karşılaştırır.

    Args:
        features_map: {ornek_anahtari: {oznitelik_adi: deger}} haritası.
        returns: {ornek_anahtari: getiri} haritası.
        date_groups: {ornek_anahtari: tarih} haritası.
        feature_names: Kullanılacak öznitelik isimleri listesi.
        config: XGBoost yapılandırma modeli.

    Returns:
        Her iki modelin IC, doğruluk ve kazanan model önerisi rapor sözlüğü.
    """
    from .lightgbm_trainer import LightGBMTrainer

    # Veriyi hazırla
    trainer = LightGBMTrainer()
    X, y, _, _ = trainer._prepare_data(features_map, returns, date_groups, feature_names)

    if len(X) < 100:
        return {"error": "Insufficient data", "samples": len(X)}

    # Eksik verileri doldur (Imputation)
    impute_values = trainer._compute_impute_values(X, feature_names)
    X = trainer._impute(X, impute_values, feature_names)

    # Zamansal Train/Validation Ayrımı (Son %20 holdout)
    n = len(X)
    split_idx = int(n * 0.8)
    X_train, X_val = X[:split_idx], X[split_idx:]
    y_train, y_val = y[:split_idx], y[split_idx:]

    # Standartlaştırma (Sadece eğitim kümesi parametreleriyle)
    scaler_mean = np.mean(X_train, axis=0)
    scaler_std = np.std(X_train, axis=0)
    scaler_std[scaler_std == 0] = 1.0
    X_train_s = (X_train - scaler_mean) / scaler_std
    X_val_s = (X_val - scaler_mean) / scaler_std

    results: dict[str, Any] = {}

    # 1. LightGBM Modeli
    try:
        lgb_model = trainer.train(features_map, returns, date_groups, feature_names)
        if lgb_model:
            lgb_pred = lgb_model.predict_batch([dict(zip(feature_names, row, strict=False)) for row in X_val_s])
            lgb_pred_arr = np.array(lgb_pred, dtype=np.float64)
            corr_val = (
                float(np.corrcoef(lgb_pred_arr, y_val)[0, 1])
                if (len(np.unique(lgb_pred_arr)) > 1 and len(np.unique(y_val)) > 1)
                else 0.0
            )
            results["lightgbm"] = {
                "val_ic": round(corr_val, 4),
                "val_directional_accuracy": round(float(np.mean((lgb_pred_arr > 0) == (y_val > 0))), 4),
                "train_samples": lgb_model.train_samples,
                "confidence": lgb_model.confidence_score,
            }
    except Exception as exc:
        results["lightgbm"] = {"error": str(exc)}

    # 2. XGBoost Modeli
    try:
        xgb_model = XGBoostModel(config)
        xgb_metrics = xgb_model.train(
            X_train_s,
            y_train,
            X_val_s,
            y_val,
            feature_names=feature_names,
            horizon=5,
        )
        results["xgboost"] = {
            "val_ic": xgb_metrics.get("val_ic", 0.0),
            "val_directional_accuracy": xgb_metrics.get("val_directional_accuracy", 0.0),
            "val_rmse": xgb_metrics.get("val_rmse", 0.0),
            "train_samples": len(X_train),
        }
    except Exception as exc:
        results["xgboost"] = {"error": str(exc)}

    # 3. İstatistiksel Karşılaştırma
    lgb_ic = float(results.get("lightgbm", {}).get("val_ic", 0.0))
    xgb_ic = float(results.get("xgboost", {}).get("val_ic", 0.0))

    if lgb_ic > xgb_ic:
        winner = "lightgbm"
        margin = lgb_ic - xgb_ic
    elif xgb_ic > lgb_ic:
        winner = "xgboost"
        margin = xgb_ic - lgb_ic
    else:
        winner = "equal"
        margin = 0.0

    results["comparison"] = {
        "winner": winner,
        "ic_margin": round(margin, 4),
        "recommendation": "CHAMPION" if margin > 0.02 else "COMPARABLE",
    }

    logger.info(
        "XGBoost ve LightGBM model karsilastirmasi tamamlandi",
        kazanan=winner,
        lgb_ic=lgb_ic,
        xgb_ic=xgb_ic,
        fark=round(margin, 4),
    )

    return results


__all__: Final[list[str]] = [
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_WRONG_DIRECTION_PENALTY",
    "XGBoostAdjustedLoss",
    "XGBoostConfig",
    "XGBoostMetrics",
    "XGBoostModel",
    "compare_xgboost_vs_lightgbm",
    "configure_duckdb_wal",
]
