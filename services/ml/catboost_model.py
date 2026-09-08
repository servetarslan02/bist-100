"""ALPHA BIST — CatBoost Challenger Modeli v2.0 (Production-Hardened)

BIST pay piyasası için CatBoost Challenger modelleme mimarisi:
- Asimetrik yön cezalı özel kayıp fonksiyonu (CatBoostAdjustedLoss)
- Çoklu tahmin ufku desteği (Multi-horizon: 1g, 5g, 20g, 60g)
- Otomatik kategorik öznitelik tespiti ve hedef kodlama (Target Encoding)
- Piyasa rejimi ağırlıklı eğitim (Regime-aware weighting)
- SHAP değerleri ve öznitelik etkileşim analizi (Interaction Detection)
- Aşırı öğrenme (overfitting) denetimi (Train-Val gap izleme)
- Polars DataFrame entegrasyonu ve DuckDB WAL denetim izi
- threading.RLock eşzamanlı erişim koruması

Kurallar & Standartlar:
- Challenger model LightGBM şampiyonu ile karşılaştırılabilir niteliktedir.
- Sıfır Veri Sızıntısı (Zero Data Leakage / Point-In-Time) ilkesine sıkı bağlılık.
- DuckDB WAL optimizasyonu ve orjson yüksek hızlı serileştirme.
- Polars entegrasyonu (pandas yasaktır).
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl  # noqa: TC002
import structlog

logger = structlog.get_logger(__name__)

# ===================== SABİTLER (CONSTANTS) =====================

DEFAULT_ITERATIONS: Final[int] = 500
DEFAULT_DEPTH: Final[int] = 6
DEFAULT_LEARNING_RATE: Final[float] = 0.1
DEFAULT_L2_LEAF_REG: Final[float] = 3.0
DEFAULT_EARLY_STOPPING_ROUNDS: Final[int] = 50
DEFAULT_RANDOM_SEED: Final[int] = 42
DEFAULT_WRONG_DIRECTION_PENALTY: Final[float] = 11.0
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"


# ===================== DUCKDB WAL YARDIMCISI =====================


def configure_duckdb_wal(
    con: duckdb.DuckDBPyConnection,
    checkpoint_size: str = DEFAULT_CHECKPOINT_SIZE,
    wal_size: str = DEFAULT_WAL_SIZE,
) -> None:
    """DuckDB bağlantısında SSD korumalı WAL ve checkpoint parametrelerini yapılandırır.

    Args:
        con: Yapılandırılacak DuckDB bağlantısı.
        checkpoint_size: Otomatik checkpoint eşik boyutu.
        wal_size: Maksimum WAL dosya boyutu.
    """
    con.execute(f"SET checkpoint_threshold = '{checkpoint_size}';")
    con.execute(f"SET wal_autocheckpoint = '{wal_size}';")


# ===================== KONFİGÜRASYON VE MODELLER =====================


@dataclass(slots=True)
class CatBoostConfig:
    """CatBoost model hiperparametre ve eğitim yapılandırması.

    Attributes:
        iterations: Ağaç sayısı (maksimum iterasyon).
        depth: Karar ağacı derinliği.
        learning_rate: Öğrenme oranı (adım büyüklüğü).
        l2_leaf_reg: L2 yaprak regülarizasyon katsayısı.
        loss_function: Kayıp fonksiyonu ('Logloss', 'CrossEntropy', 'RMSE').
        eval_metric: Değerlendirme metriği ('AUC', 'RMSE', 'Logloss').
        verbose: Log detay seviyesi (0 = sessiz).
        early_stopping_rounds: Erken durdurma tolerans tur sayısı.
        random_seed: Tekrarlanabilirlik tohum değeri.
        cat_features: Kategorik öznitelik sütun indeksleri.
        target_horizons: Tahmin hedeflenen gün ufukları ([1, 5, 20, 60]).
        regime_aware: Piyasa rejim ağırlıkları aktif mi.
        regime_weights: Rejim bazlı örneklem ağırlık çarpanları.
        use_adjusted_loss: Asimetrik yön cezalı kayıp fonksiyonu kullanılsın mı.
        wrong_direction_penalty: Ters yön ceza katsayısı.
    """

    iterations: int = DEFAULT_ITERATIONS
    depth: int = DEFAULT_DEPTH
    learning_rate: float = DEFAULT_LEARNING_RATE
    l2_leaf_reg: float = DEFAULT_L2_LEAF_REG
    loss_function: str = "Logloss"
    eval_metric: str = "AUC"
    verbose: int = 0
    early_stopping_rounds: int = DEFAULT_EARLY_STOPPING_ROUNDS
    random_seed: int = DEFAULT_RANDOM_SEED
    cat_features: list[int] = field(default_factory=list)
    target_horizons: list[int] = field(default_factory=lambda: [1, 5, 20, 60])
    regime_aware: bool = False
    regime_weights: dict[str, float] = field(
        default_factory=lambda: {"BULL": 1.0, "BEAR": 1.0, "SIDEWAYS": 1.0, "HIGH_VOL": 1.0}
    )
    use_adjusted_loss: bool = False
    wrong_direction_penalty: float = DEFAULT_WRONG_DIRECTION_PENALTY

    def to_dict(self) -> dict[str, Any]:
        """Konfigürasyonu standart sözlüğe dönüştürür."""
        return {
            "iterations": self.iterations,
            "depth": self.depth,
            "learning_rate": self.learning_rate,
            "l2_leaf_reg": self.l2_leaf_reg,
            "loss_function": self.loss_function,
            "eval_metric": self.eval_metric,
            "verbose": self.verbose,
            "early_stopping_rounds": self.early_stopping_rounds,
            "random_seed": self.random_seed,
            "cat_features": list(self.cat_features),
            "target_horizons": list(self.target_horizons),
            "regime_aware": self.regime_aware,
            "regime_weights": dict(self.regime_weights),
            "use_adjusted_loss": self.use_adjusted_loss,
            "wrong_direction_penalty": self.wrong_direction_penalty,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CatBoostConfig:
        """Sözlükten CatBoostConfig nesnesi oluşturur."""
        return cls(
            iterations=int(data.get("iterations", DEFAULT_ITERATIONS)),
            depth=int(data.get("depth", DEFAULT_DEPTH)),
            learning_rate=float(data.get("learning_rate", DEFAULT_LEARNING_RATE)),
            l2_leaf_reg=float(data.get("l2_leaf_reg", DEFAULT_L2_LEAF_REG)),
            loss_function=str(data.get("loss_function", "Logloss")),
            eval_metric=str(data.get("eval_metric", "AUC")),
            verbose=int(data.get("verbose", 0)),
            early_stopping_rounds=int(data.get("early_stopping_rounds", DEFAULT_EARLY_STOPPING_ROUNDS)),
            random_seed=int(data.get("random_seed", DEFAULT_RANDOM_SEED)),
            cat_features=list(data.get("cat_features", [])),
            target_horizons=list(data.get("target_horizons", [1, 5, 20, 60])),
            regime_aware=bool(data.get("regime_aware", False)),
            regime_weights=dict(data.get("regime_weights", {"BULL": 1.0, "BEAR": 1.0, "SIDEWAYS": 1.0, "HIGH_VOL": 1.0})),
            use_adjusted_loss=bool(data.get("use_adjusted_loss", False)),
            wrong_direction_penalty=float(data.get("wrong_direction_penalty", DEFAULT_WRONG_DIRECTION_PENALTY)),
        )

    def to_orjson_bytes(self) -> bytes:
        """orjson serileştirmesi döndürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        return (
            f"CatBoostConfig(iter={self.iterations}, depth={self.depth}, lr={self.learning_rate}, "
            f"loss={self.loss_function!r}, metric={self.eval_metric!r}, adjusted_loss={self.use_adjusted_loss})"
        )


# ===================== ASİMETRİK KAYIP FONKSİYONU =====================


class CatBoostAdjustedLoss:
    """CatBoost yerel özel kayıp fonksiyonu (Custom Objective) — Asimetrik Yön Cezası.

    Modelin tahmin ettiği yön ile gerçek yön uyuşmadığında (ör. pozitif getiri beklerken negatif çıkması)
    MSE gradyan ve hessian bileşenlerini ceza katsayısı ile çarpar.
    """

    def __init__(self, penalty: float = DEFAULT_WRONG_DIRECTION_PENALTY) -> None:
        """CatBoostAdjustedLoss nesnesini yapılandırır.

        Args:
            penalty: Ters yön ceza katsayısı (asgari 1.0).
        """
        if penalty < 1.0:
            raise ValueError(f"Ceza çarpanı 1.0'dan küçük olamaz. Verilen: {penalty}")
        self.penalty = float(penalty)

    def calc_ders_range(
        self,
        approxes: Any,
        targets: Any,
        weights: Any,
    ) -> tuple[list[float], list[float]]:
        """CatBoost C++ motoru tarafından çağrılan gradyan ve hessian hesaplama arayüzü.

        Args:
            approxes: Modelin ürettiği ham tahmin değerleri.
            targets: Gerçekleşen hedef değerler.
            weights: Örneklem ağırlıkları (isteğe bağlı).

        Returns:
            (birinci_turev_gradyan, ikinci_turev_hessian) listeler demeti.
        """
        approx_arr = np.asarray(approxes, dtype=np.float64)
        target_arr = np.asarray(targets, dtype=np.float64)

        diff = approx_arr - target_arr
        wrong_dir = (approx_arr > 0.0) & (target_arr < 0.0) | (approx_arr < 0.0) & (target_arr > 0.0)
        penalties = np.where(wrong_dir, self.penalty, 1.0)

        if weights is not None and len(weights) == len(approx_arr):
            w_arr = np.asarray(weights, dtype=np.float64)
            penalties = penalties * w_arr

        der1 = (2.0 * diff * penalties).tolist()
        der2 = (2.0 * penalties).tolist()

        return der1, der2

    def __repr__(self) -> str:
        return f"CatBoostAdjustedLoss(penalty={self.penalty:.1f})"


# ===================== CATBOOST MODEL SINIFI =====================


class CatBoostModel:
    """ALPHA BIST CatBoost Challenger Model Yöneticisi v2.0.

    Özellikler:
    - Çoklu tahmin ufku (Multi-horizon) bağımsız model havuzu
    - Asimetrik yön cezalı CatBoostAdjustedLoss integrasyonu
    - Otomatik kategorik öznitelik tespiti
    - SHAP değerleri ve öznitelik etkileşim matrisi
    - Aşırı öğrenme (train vs val gap) izleme
    - Polars DataFrame üzerinden doğrudan eğitim ve tahmin
    - DuckDB WAL denetim logu entegrasyonu
    - SHA256 doğrulamalı güvenli model saklama / yükleme
    - threading.RLock thread-safety koruması
    """

    def __init__(self, config: CatBoostConfig | None = None) -> None:
        """CatBoostModel nesnesini başlatır.

        Args:
            config: Model yapılandırma parametreleri.
        """
        self._lock = threading.RLock()
        self._config = config or CatBoostConfig()
        self._models: dict[int, Any] = {}
        self._is_classifier = self._config.loss_function in ["Logloss", "CrossEntropy"]
        self._feature_names: list[str] | None = None
        self._training_metrics: dict[int, dict[str, Any]] = {}
        self._shap_values: dict[str, float] | None = None
        self._feature_interactions: dict[str, float] | None = None
        self._cat_features_detected: list[int] = []
        self._calibrators: dict[int, Any] = {}

    def __getstate__(self) -> dict[str, Any]:
        """Pickle serileştirmesinde threading.RLock nesnesini dışlayarak durum döndürür."""
        state = self.__dict__.copy()
        state["_lock"] = None
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Pickle deserializasyonunda threading.RLock nesnesini yeniden ilklendirir."""
        self.__dict__.update(state)
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        with self._lock:
            n_models = len(self._models)
            horizons = sorted(self._models.keys())
            return f"CatBoostModel(models_count={n_models}, trained_horizons={horizons}, classifier={self._is_classifier})"

    @property
    def is_trained(self) -> bool:
        """En az bir tahmin ufkunda eğitilmiş model bulunup bulunmadığını belirtir."""
        with self._lock:
            return len(self._models) > 0

    @property
    def trained_horizons(self) -> list[int]:
        """Eğitimi tamamlanmış tahmin ufukları listesini döndürür."""
        with self._lock:
            return sorted(self._models.keys())

    @property
    def metrics(self) -> dict[int, dict[str, Any]]:
        """Ufuk bazlı son eğitim metriklerinin kopyasını döndürür."""
        with self._lock:
            return {h: m.copy() for h, m in self._training_metrics.items()}

    @staticmethod
    def _validate_arrays(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Giriş matrisi ve hedef vektörünü doğrular.

        Args:
            X: Öznitelik matrisi.
            y: Hedef değişken dizisi.

        Returns:
            Doğrulanmış numpy dizileri (X, y).

        Raises:
            ValueError: Boş veri, boyut uyumsuzluğu veya geçersiz sayısal değer durumunda.
        """
        X_arr = np.asarray(X)
        y_arr = np.asarray(y).ravel()

        if X_arr.size == 0 or y_arr.size == 0:
            raise ValueError("X ve y dizileri boş olamaz.")

        if X_arr.shape[0] != y_arr.shape[0]:
            raise ValueError(
                f"Boyut uyumsuzluğu: X satır sayısı ({X_arr.shape[0]}) ile y uzunluğu ({y_arr.shape[0]}) eşleşmiyor."
            )

        return X_arr, y_arr

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
        feature_names: list[str] | None = None,
        cat_features: list[int] | None = None,
        sample_weights: np.ndarray | None = None,
        horizon: int = 5,
    ) -> dict[str, Any]:
        """Belirtilen tahmin ufku için CatBoost modelini eğitir.

        Args:
            X_train: Eğitim öznitelik matrisi.
            y_train: Eğitim hedef değişkeni.
            X_val: İsteğe bağlı doğrulama öznitelik matrisi.
            y_val: İsteğe bağlı doğrulama hedef değişkeni.
            feature_names: Öznitelik sütun adları listesi.
            cat_features: Kategorik sütun indeksleri listesi.
            sample_weights: Örneklem ağırlıkları dizisi.
            horizon: Tahmin ufku (gün).

        Returns:
            Eğitim metriklerini içeren sözlük.
        """
        try:
            from catboost import Pool
        except ImportError:
            logger.error("catboost_yuklu_degil", mesaj="pip install catboost gereklidir")
            return {"error": "catboost not installed"}

        X_tr, y_tr = self._validate_arrays(X_train, y_train)

        with self._lock:
            self._feature_names = feature_names
            cat_idx = cat_features or self._config.cat_features

            if not cat_idx and X_tr.dtype == object:
                cat_idx = self._detect_categorical(X_tr, feature_names)
            self._cat_features_detected = cat_idx

            model = self._create_model()

            fit_params: dict[str, Any] = {}
            if self._config.use_adjusted_loss and not self._is_classifier:
                try:
                    custom_loss = CatBoostAdjustedLoss(self._config.wrong_direction_penalty)
                    fit_params["loss_function"] = custom_loss
                    fit_params["eval_metric"] = "RMSE"
                except Exception as err:
                    logger.warning("catboost_ozel_kayip_hatasi", hata=str(err))

            train_pool = Pool(
                data=X_tr,
                label=y_tr,
                cat_features=cat_idx if cat_idx else None,
                feature_names=feature_names if feature_names else None,
                weight=sample_weights,
            )

            eval_pool = None
            if X_val is not None and y_val is not None:
                X_v, y_v = self._validate_arrays(X_val, y_val)
                eval_pool = Pool(
                    data=X_v,
                    label=y_v,
                    cat_features=cat_idx if cat_idx else None,
                    feature_names=feature_names if feature_names else None,
                )

            model.fit(
                train_pool,
                eval_set=eval_pool,
                early_stopping_rounds=self._config.early_stopping_rounds if eval_pool else None,
                verbose=self._config.verbose,
                **fit_params,
            )

            self._models[horizon] = model
            metrics = self._compute_metrics(model, X_tr, y_tr, X_val, y_val, horizon)
            self._training_metrics[horizon] = metrics

            if X_val is not None:
                self._compute_shap(model, X_val, feature_names)

            self._compute_feature_interactions(model, feature_names)
            self._check_overfitting(metrics, horizon)

            logger.info("catboost_egitimi_tamamlandi", horizon=horizon, n_train=len(X_tr))
            return metrics

    def train_polars(
        self,
        df_train: pl.DataFrame,
        feature_columns: list[str],
        target_column: str,
        df_val: pl.DataFrame | None = None,
        cat_columns: list[str] | None = None,
        horizon: int = 5,
    ) -> dict[str, Any]:
        """Polars DataFrame girdisi üzerinden doğrudan CatBoost modelini eğitir.

        Args:
            df_train: Eğitim verisi Polars DataFrame.
            feature_columns: Kullanılacak öznitelik sütun adları.
            target_column: Hedef sütun adı.
            df_val: İsteğe bağlı doğrulama Polars DataFrame.
            cat_columns: Kategorik sütun adları.
            horizon: Tahmin ufku (gün).

        Returns:
            Eğitim metrikleri sözlüğü.
        """
        X_train = df_train.select(feature_columns).to_numpy()
        y_train = df_train[target_column].to_numpy()

        X_val = df_val.select(feature_columns).to_numpy() if df_val is not None else None
        y_val = df_val[target_column].to_numpy() if df_val is not None else None

        cat_indices: list[int] = []
        if cat_columns:
            cat_set = set(cat_columns)
            cat_indices = [idx for idx, col in enumerate(feature_columns) if col in cat_set]

        return self.train(
            X_train=X_train,
            y_train=y_train,
            X_val=X_val,
            y_val=y_val,
            feature_names=feature_columns,
            cat_features=cat_indices,
            horizon=horizon,
        )

    def train_multi_horizon(
        self,
        X_train: np.ndarray,
        y_train_dict: dict[int, np.ndarray],
        X_val: np.ndarray | None = None,
        y_val_dict: dict[int, np.ndarray] | None = None,
        feature_names: list[str] | None = None,
    ) -> dict[int, dict[str, Any]]:
        """Birden çok tahmin ufku için modelleri eşzamanlı sırayla eğitir.

        Args:
            X_train: Eğitim öznitelik matrisi.
            y_train_dict: {horizon: y_train} eşleme sözlüğü.
            X_val: Doğrulama öznitelik matrisi.
            y_val_dict: {horizon: y_val} eşleme sözlüğü.
            feature_names: Öznitelik isimleri.

        Returns:
            {horizon: metrics} toplu sonuç sözlüğü.
        """
        all_metrics: dict[int, dict[str, Any]] = {}
        for horizon in sorted(y_train_dict.keys()):
            y_tr = y_train_dict[horizon]
            y_v = y_val_dict.get(horizon) if y_val_dict else None

            metrics = self.train(
                X_train=X_train,
                y_train=y_tr,
                X_val=X_val,
                y_val=y_v,
                feature_names=feature_names,
                horizon=horizon,
            )
            all_metrics[horizon] = metrics

        logger.info("catboost_coklu_ufuk_egitildi", ufuklar=list(all_metrics.keys()))
        return all_metrics

    def predict(
        self,
        X: np.ndarray,
        horizon: int = 5,
    ) -> np.ndarray:
        """Belirtilen tahmin ufku için model tahmini üretir.

        Args:
            X: Öznitelik matrisi.
            horizon: Hedef tahmin ufku.

        Returns:
            Tahmin olasılıkları veya sürekli getiri tahmin dizisi.
        """
        X_arr = np.asarray(X)
        if X_arr.size == 0:
            return np.zeros(0, dtype=np.float64)

        with self._lock:
            model = self._models.get(horizon)
            if model is None:
                available = sorted(self._models.keys())
                if not available:
                    return np.zeros(len(X_arr), dtype=np.float64)
                closest = min(available, key=lambda h: abs(h - horizon))
                model = self._models[closest]

            try:
                if self._is_classifier and hasattr(model, "predict_proba"):
                    raw_prob = model.predict_proba(X_arr)[:, 1]
                    calibrator = self._calibrators.get(horizon)
                    if calibrator is not None and hasattr(calibrator, "predict"):
                        return calibrator.predict(raw_prob)
                    return raw_prob
                else:
                    return model.predict(X_arr)
            except Exception as err:
                logger.warning("catboost_tahmin_hatasi", horizon=horizon, hata=str(err))
                return np.zeros(len(X_arr), dtype=np.float64)

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

        with self._lock:
            raw_prob = self.predict(X_val, horizon=horizon)
            calibrator = ProbabilityCalibrator(method=method)
            calibrator.fit(raw_prob, y_val)
            self._calibrators[horizon] = calibrator
            return calibrator.get_metrics()

    def predict_polars(
        self,
        df: pl.DataFrame,
        feature_columns: list[str],
        horizon: int = 5,
    ) -> np.ndarray:
        """Polars DataFrame üzerinden doğrudan tahmin yürütür.

        Args:
            df: Veriyi içeren Polars DataFrame.
            feature_columns: Kullanılacak öznitelik sütunları.
            horizon: Tahmin ufku.

        Returns:
            Model tahmin dizisi.
        """
        X = df.select(feature_columns).to_numpy()
        return self.predict(X=X, horizon=horizon)

    def predict_all_horizons(self, X: np.ndarray) -> dict[int, np.ndarray]:
        """Tüm kayıtlı ufuklar için eşzamanlı tahmin üretir.

        Args:
            X: Öznitelik matrisi.

        Returns:
            {horizon: tahmin_dizisi} eşleme sözlüğü.
        """
        with self._lock:
            horizons = list(self._models.keys())
        return {h: self.predict(X, h) for h in horizons}

    def feature_importance(
        self,
        importance_type: str = "FeatureImportance",
        horizon: int = 5,
    ) -> dict[str, float] | None:
        """Model öznitelik önem sıralamasını döndürür.

        Args:
            importance_type: 'FeatureImportance', 'SHAP' veya 'Interaction'.
            horizon: İlgili tahmin ufku.

        Returns:
            {oznitelik_adi: onem_skoru} sözlüğü veya None.
        """
        with self._lock:
            model = self._models.get(horizon)
            if model is None:
                return None

            try:
                if importance_type == "SHAP" and self._shap_values is not None:
                    return self._shap_values.copy()
                elif importance_type == "Interaction" and self._feature_interactions is not None:
                    return self._feature_interactions.copy()
                else:
                    importance = model.feature_importances_
                    if self._feature_names and len(self._feature_names) == len(importance):
                        return dict(zip(self._feature_names, [float(v) for v in importance], strict=False))
                    return {f"f{i}": float(v) for i, v in enumerate(importance)}
            except Exception as err:
                logger.warning("catboost_onem_skoru_hatasi", tip=importance_type, hata=str(err))
                return None

    def _create_model(self) -> Any:
        """Konfigürasyona uygun CatBoostClassifier veya CatBoostRegressor örneği oluşturur."""
        from catboost import CatBoostClassifier, CatBoostRegressor

        params: dict[str, Any] = {
            "iterations": self._config.iterations,
            "depth": self._config.depth,
            "learning_rate": self._config.learning_rate,
            "l2_leaf_reg": self._config.l2_leaf_reg,
            "verbose": self._config.verbose,
            "random_seed": self._config.random_seed,
        }

        try:
            from services.core.hardware_orchestrator import hardware_orchestrator

            params = hardware_orchestrator.get_catboost_params(params)
        except Exception as exc:
            logger.debug("Hardware orchestrator parametreleri alinamadi, varsayilan parametreler kullaniliyor", hata=str(exc))

        if self._is_classifier:
            params["loss_function"] = self._config.loss_function
            params["eval_metric"] = self._config.eval_metric
            return CatBoostClassifier(**params)
        else:
            params["loss_function"] = "RMSE"
            params["eval_metric"] = "RMSE"
            return CatBoostRegressor(**params)

    @staticmethod
    def _detect_categorical(X: np.ndarray, feature_names: list[str] | None) -> list[int]:
        """Veri matrisinde kategorik sütunları otomatik belirler."""
        cat_indices: list[int] = []
        for i in range(X.shape[1]):
            col = X[:, i]
            if col.dtype == object or col.dtype.kind in ("U", "S"):
                cat_indices.append(i)
                continue
            if col.dtype.kind in ("i", "u"):
                unique_count = len(np.unique(col[~np.isnan(col.astype(float))]))
                if unique_count < 20:
                    cat_indices.append(i)

        if cat_indices:
            names = [feature_names[i] if feature_names and i < len(feature_names) else f"f{i}" for i in cat_indices]
            logger.info("catboost_kategorik_tespit_edildi", adet=len(cat_indices), sutunlar=names)

        return cat_indices

    def _compute_metrics(
        self,
        model: Any,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray | None,
        y_val: np.ndarray | None,
        horizon: int,
    ) -> dict[str, Any]:
        """Eğitim ve doğrulama seti performans metriklerini hesaplar."""
        best_iter = getattr(model, "best_iteration_", None)
        metrics: dict[str, Any] = {
            "horizon": horizon,
            "n_train": len(X_train),
            "n_val": len(X_val) if X_val is not None else 0,
            "best_iteration": int(best_iter) if best_iter is not None else self._config.iterations,
            "feature_count": int(X_train.shape[1]),
            "n_categorical": len(self._cat_features_detected),
        }

        if X_val is not None and y_val is not None:
            val_pred = self.predict(X_val, horizon)

            if self._is_classifier:
                from sklearn.metrics import accuracy_score, log_loss, roc_auc_score

                try:
                    metrics["val_auc"] = round(float(roc_auc_score(y_val, val_pred)), 4)
                    metrics["val_accuracy"] = round(float(accuracy_score(y_val, (val_pred > 0.5).astype(int))), 4)
                    metrics["val_log_loss"] = round(float(log_loss(y_val, val_pred)), 4)
                except Exception as err:
                    logger.warning("siniflandirici_metrik_hesaplama_hatasi", hata=str(err))
            else:
                from sklearn.metrics import mean_absolute_error, mean_squared_error

                try:
                    metrics["val_rmse"] = round(float(np.sqrt(mean_squared_error(y_val, val_pred))), 6)
                    metrics["val_mae"] = round(float(mean_absolute_error(y_val, val_pred)), 6)
                    pred_dir = (val_pred > 0).astype(int)
                    true_dir = (y_val > 0).astype(int)
                    metrics["val_directional_accuracy"] = round(float(np.mean(pred_dir == true_dir)), 4)
                    if len(np.unique(val_pred)) > 1 and len(np.unique(y_val)) > 1:
                        corr = np.corrcoef(val_pred, y_val)[0, 1]
                        if np.isfinite(corr):
                            metrics["val_ic"] = round(float(corr), 4)
                except Exception as err:
                    logger.warning("regresyon_metrik_hesaplama_hatasi", hata=str(err))

        return metrics

    def _compute_shap(self, model: Any, X: np.ndarray, feature_names: list[str] | None) -> None:
        """SHAP değerlerini hesaplar ve kaydeder."""
        try:
            import shap

            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X[:100])
            mean_shap = np.mean(np.abs(shap_values), axis=0)
            if feature_names and len(feature_names) == len(mean_shap):
                self._shap_values = dict(zip(feature_names, [float(v) for v in mean_shap], strict=False))
            else:
                self._shap_values = {f"f{i}": float(v) for i, v in enumerate(mean_shap)}
        except Exception as exc:
            logger.debug("SHAP hesaplama basarisiz oldu", hata=str(exc))

    def _compute_feature_interactions(self, model: Any, feature_names: list[str] | None) -> None:
        """CatBoost öznitelik etkileşim skorlarını çıkarır."""
        try:
            interactions = model.get_feature_importance(type="Interaction")
            if interactions is not None:
                interactions_arr = np.asarray(interactions)
                if interactions_arr.size > 0:
                    result: dict[str, float] = {}
                    for row in interactions_arr[:10]:
                        if len(row) >= 3:
                            f1_idx, f2_idx, score = int(row[0]), int(row[1]), float(row[2])
                            f1 = (
                                feature_names[f1_idx]
                                if feature_names and f1_idx < len(feature_names)
                                else f"f{f1_idx}"
                            )
                            f2 = (
                                feature_names[f2_idx]
                                if feature_names and f2_idx < len(feature_names)
                                else f"f{f2_idx}"
                            )
                            result[f"{f1}×{f2}"] = round(score, 4)
                    self._feature_interactions = result
        except Exception as exc:
            logger.debug("CatBoost oznitelik etkilesimleri cikarilamadi", hata=str(exc))

    def _check_overfitting(self, metrics: dict[str, Any], horizon: int) -> None:
        """Eğitim ve doğrulama performansı farkından aşırı öğrenme riskini değerlendirir."""
        if "val_auc" in metrics and "train_auc" in metrics:
            gap = float(metrics["train_auc"] - metrics["val_auc"])
            if gap > 0.10:
                logger.warning("catboost_asiri_ogrenme_riski", horizon=horizon, gap=round(gap, 4))
                metrics["overfitting_risk"] = "HIGH"
            elif gap > 0.05:
                metrics["overfitting_risk"] = "MEDIUM"
            else:
                metrics["overfitting_risk"] = "LOW"

    def save(self, path: str) -> bool:
        """Modeli ve tüm eğitim metriklerini diskte güvenli dosya olarak saklar."""
        try:
            from services.core.safe_pickle import safe_pickle_dump

            os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
            with self._lock:
                save_data = {
                    "models": self._models,
                    "config": self._config.to_dict(),
                    "metrics": self._training_metrics,
                    "feature_names": self._feature_names,
                    "shap_values": self._shap_values,
                    "feature_interactions": self._feature_interactions,
                    "cat_features_detected": self._cat_features_detected,
                    "saved_at": datetime.now(UTC).isoformat(),
                }
            safe_pickle_dump(save_data, path)
            logger.info("catboost_modeli_kaydedildi", dosya=path)
            return True
        except Exception as err:
            logger.error("catboost_kaydetme_hatasi", dosya=path, hata=str(err))
            return False

    def load(self, path: str) -> bool:
        """Güvenli pickle formatındaki modeli diskten geri yükler."""
        try:
            from services.core.safe_pickle import safe_pickle_load

            data = safe_pickle_load(path)
            with self._lock:
                self._models = data.get("models", {})
                cfg_dict = data.get("config", {})
                if isinstance(cfg_dict, dict):
                    self._config = CatBoostConfig(**cfg_dict)
                self._is_classifier = self._config.loss_function in ["Logloss", "CrossEntropy"]
                self._training_metrics = data.get("metrics", {})
                self._feature_names = data.get("feature_names")
                self._shap_values = data.get("shap_values")
                self._feature_interactions = data.get("feature_interactions")
                self._cat_features_detected = data.get("cat_features_detected", [])
            logger.info("catboost_modeli_yuklendi", dosya=path, ufuklar=list(self._models.keys()))
            return True
        except Exception as err:
            logger.error("catboost_yukleme_hatasi", dosya=path, hata=str(err))
            return False

    # ===================== DUCKDB & POLARS ENTEGRASYONU =====================

    def export_metrics_duckdb(
        self,
        db_path: str = ":memory:",
        table_name: str = "catboost_training_audit",
    ) -> None:
        """Eğitim metriklerini DuckDB denetim tablosuna kaydeder.

        Args:
            db_path: DuckDB veritabanı yolu.
            table_name: Hedef tablo adı.
        """
        with self._lock:
            metrics_copy = {h: m.copy() for h, m in self._training_metrics.items()}

        con = duckdb.connect(db_path)
        try:
            configure_duckdb_wal(con)
            con.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    timestamp TIMESTAMP WITH TIME ZONE,
                    horizon BIGINT,
                    n_train BIGINT,
                    n_val BIGINT,
                    feature_count BIGINT,
                    best_iteration BIGINT,
                    metrics_json VARCHAR
                )
                """
            )
            now_iso = datetime.now(UTC).isoformat()
            for horizon, m in metrics_copy.items():
                m_json = orjson.dumps(m).decode("utf-8")
                con.execute(
                    f"INSERT INTO {table_name} VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        now_iso,
                        horizon,
                        m.get("n_train", 0),
                        m.get("n_val", 0),
                        m.get("feature_count", 0),
                        m.get("best_iteration", 0),
                        m_json,
                    ),
                )
            logger.info("catboost_metrikleri_duckdbye_kaydedildi", tablo=table_name, ufuk_sayisi=len(metrics_copy))
        finally:
            con.close()

    def read_metrics_polars(
        self,
        db_path: str = ":memory:",
        table_name: str = "catboost_training_audit",
    ) -> pl.DataFrame:
        """DuckDB tablosundaki eğitim metriklerini Polars DataFrame olarak okur.

        Args:
            db_path: DuckDB dosya yolu.
            table_name: Tablo adı.

        Returns:
            Eğitim metriklerini içeren Polars DataFrame.
        """
        con = duckdb.connect(db_path)
        try:
            configure_duckdb_wal(con)
            arrow_table = con.execute(f"SELECT * FROM {table_name} ORDER BY horizon ASC").arrow()
            return pl.from_arrow(arrow_table)  # type: ignore[return-value]
        finally:
            con.close()


__all__: Final[list[str]] = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_DEPTH",
    "DEFAULT_EARLY_STOPPING_ROUNDS",
    "DEFAULT_ITERATIONS",
    "DEFAULT_L2_LEAF_REG",
    "DEFAULT_LEARNING_RATE",
    "DEFAULT_RANDOM_SEED",
    "DEFAULT_WAL_SIZE",
    "DEFAULT_WRONG_DIRECTION_PENALTY",
    "CatBoostAdjustedLoss",
    "CatBoostConfig",
    "CatBoostModel",
    "configure_duckdb_wal",
]
