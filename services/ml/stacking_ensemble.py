"""ALPHA BIST — Yığınlama Topluluğu (Stacking Ensemble v3.0) (Nihai — ⭐⭐⭐⭐⭐).

Bu modül; temel modellerin (Base Models: LightGBM, XGBoost, CatBoost vb.) tahminlerini girdi alan
ve nihai meta-tahmini üreten çok katmanlı meta-öğrenici (Meta-Learner) mimarisini uygular.

Temel Yetenekler:
- Zaman Serisi Çapraz Doğrulamalı Yığınlama (TimeSeriesSplit ile Sıfır Veri Sızıntısı)
- Rejim Duyarlı Meta-Öğreniciler ve Dinamik Model Ağırlıklandırması (BULL, BEAR, SIDEWAYS, HIGH_VOL)
- Model Uzlaşısı ve Güven Skoru (Model Agreement Confidence)
- Model Çeşitlilik Puanlaması (Model Diversity Scoring)
- Rejim Geçiş Yumuşatması (Regime Transition Smoothing)
- DuckDB SSD Korumalı WAL ile Eğitim ve Karar Denetim İzi (Audit Trail)
- Polars DataFrame Desteği (`predict_polars`)
- İş Parçacığı Güvenliği (`threading.RLock`) ve Kesin Tip Belirteçleri
"""

from __future__ import annotations

import copy
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import duckdb
import numpy as np
import orjson
import structlog
from scipy.stats import spearmanr
from sklearn.linear_model import ElasticNet, LinearRegression, LogisticRegression, Ridge
from sklearn.model_selection import TimeSeriesSplit

if TYPE_CHECKING:
    import polars as pl

logger = structlog.get_logger(__name__)

# --- Sabitler ---
DEFAULT_MIN_SAMPLES_PER_REGIME: Final[int] = 30
DEFAULT_MAX_POSSIBLE_STD: Final[float] = 0.5
DEFAULT_EPSILON: Final[float] = 1e-8
DEFAULT_DUCKDB_PATH: Final[str] = "data/stacking_ensemble.duckdb"
DEFAULT_MAX_TRAINING_HISTORY: Final[int] = 1000


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
class StackingConfig:
    """Stacking ensemble konfigürasyonu ve hiperparametreleri."""

    meta_learner_type: str = "ridge"  # ridge, logistic, linear, elastic_net
    cv_folds: int = 5
    use_proba: bool = True
    passthrough: bool = False  # Orijinal öznitelikleri de meta-learner'a aktar
    regime_aware: bool = True
    regime_meta_learners: bool = True  # Her rejim için ayrı meta-öğrenici
    min_diversity_score: float = 0.1  # Asgari model çeşitliliği
    online_adaptation: bool = True
    adaptation_rate: float = 0.1  # Ağırlık adaptasyon katsayısı

    def to_dict(self) -> dict[str, Any]:
        """Konfigürasyonu sözlük yapısına dönüştürür."""
        return asdict(self)

    def to_orjson_bytes(self) -> bytes:
        """Konfigürasyonu orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StackingConfig:
        """Sözlükten StackingConfig nesnesi oluşturur."""
        return cls(
            meta_learner_type=str(data.get("meta_learner_type", "ridge")),
            cv_folds=int(data.get("cv_folds", 5)),
            use_proba=bool(data.get("use_proba", True)),
            passthrough=bool(data.get("passthrough", False)),
            regime_aware=bool(data.get("regime_aware", True)),
            regime_meta_learners=bool(data.get("regime_meta_learners", True)),
            min_diversity_score=float(data.get("min_diversity_score", 0.1)),
            online_adaptation=bool(data.get("online_adaptation", True)),
            adaptation_rate=float(data.get("adaptation_rate", 0.1)),
        )

    def __repr__(self) -> str:
        """Özet metin gösterimini oluşturur."""
        return f"StackingConfig(meta='{self.meta_learner_type}', folds={self.cv_folds}, regime_aware={self.regime_aware})"


@dataclass(slots=True)
class StackingPredictionResult:
    """Tekil tahmin detayı modeli."""

    prediction: float
    confidence: float
    model_predictions: dict[str, float]
    model_weights: dict[str, float]
    regime: str
    agreement_score: float
    diversity_score: float

    def to_dict(self) -> dict[str, Any]:
        """Modeli sözlüğe dönüştürür."""
        return asdict(self)

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StackingPredictionResult:
        """Sözlükten StackingPredictionResult nesnesi oluşturur."""
        return cls(
            prediction=float(data.get("prediction", 0.0)),
            confidence=float(data.get("confidence", 0.0)),
            model_predictions=dict(data.get("model_predictions", {})),
            model_weights=dict(data.get("model_weights", {})),
            regime=str(data.get("regime", "UNKNOWN")),
            agreement_score=float(data.get("agreement_score", 0.0)),
            diversity_score=float(data.get("diversity_score", 0.0)),
        )

    def __repr__(self) -> str:
        """Özet metin gösterimi."""
        return (
            f"StackingPredictionResult(pred={self.prediction:.4f}, conf={self.confidence:.2f}, "
            f"agreement={self.agreement_score:.2f}, regime='{self.regime}')"
        )


class StackingEnsemble:
    """Çoklu Model Yığınlama Topluluğu ve Rejim Duyarlı Meta-Öğrenici."""

    def __init__(
        self,
        config: StackingConfig | None = None,
        duckdb_path: str = DEFAULT_DUCKDB_PATH,
    ) -> None:
        """StackingEnsemble bileşenini başlatır.

        Args:
            config: Yığınlama konfigürasyonu nesnesi.
            duckdb_path: Denetim kaydı için DuckDB veritabanı yolu.
        """
        self._config: StackingConfig = config or StackingConfig()
        self._duckdb_path: str = duckdb_path
        self._lock: threading.RLock = threading.RLock()

        self._base_models: dict[str, Any] = {}
        self._meta_learner: Any = None
        self._regime_meta_learners: dict[str, Any] = {}
        self._model_weights: dict[str, float] = {}
        self._regime_weights: dict[str, dict[str, float]] = {}
        self._is_fitted: bool = False
        self._training_history: list[dict[str, Any]] = []
        self._diversity_scores: dict[str, float] = {}

        self._init_duckdb()
        logger.info("StackingEnsemble v3.0 baslatildi", meta_learner=self._config.meta_learner_type)

    def _init_duckdb(self) -> None:
        """DuckDB denetim tablosunu güvenle oluşturur."""
        try:
            db_dir = Path(self._duckdb_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS stacking_ensemble_audit (
                        timestamp TIMESTAMPTZ NOT NULL,
                        operation VARCHAR NOT NULL,
                        base_model_count BIGINT NOT NULL,
                        val_ic DOUBLE NOT NULL,
                        val_rank_ic DOUBLE NOT NULL,
                        details VARCHAR NOT NULL
                    );
                    """
                )
        except Exception as exc:
            logger.warning("DuckDB stacking_ensemble_audit tablosu ilklendirilemedi", hata=str(exc))

    def _record_audit_event(
        self,
        operation: str,
        base_model_count: int,
        val_ic: float,
        val_rank_ic: float,
        details: dict[str, Any],
    ) -> None:
        """Denetim kaydını DuckDB tablosuna işler."""
        try:
            now_iso = datetime.now(UTC).isoformat()
            details_json = orjson.dumps(details).decode()
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO stacking_ensemble_audit
                    (timestamp, operation, base_model_count, val_ic, val_rank_ic, details)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    [now_iso, operation, base_model_count, val_ic, val_rank_ic, details_json],
                )
        except Exception as exc:
            logger.warning("DuckDB stacking_ensemble denetim kaydi basarisiz", hata=str(exc))

    def add_model(self, name: str, model: Any, weight: float = 1.0) -> None:
        """Topluluğa yeni bir temel (base) model ekler.

        Args:
            name: Modelin benzersiz adı.
            model: fit ve predict / predict_proba metodlarına sahip model nesnesi.
            weight: Başlangıç ağırlığı.
        """
        with self._lock:
            self._base_models[name] = model
            self._model_weights[name] = float(weight)
            logger.info("Temel model topluluga eklendi", model=name, weight=weight)

    def fit(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        regimes_train: np.ndarray | None = None,
        regimes_val: np.ndarray | None = None,
    ) -> dict[str, Any]:
        """Zaman serisi TimeSeriesSplit çapraz doğrulama ile meta-öğreniciyi ve modelleri eğitir.

        Args:
            X_train: Eğitim öznitelik matrisi.
            y_train: Eğitim hedef vektörü.
            X_val: Doğrulama öznitelik matrisi.
            y_val: Doğrulama hedef vektörü.
            regimes_train: Eğitim rejim etiketleri (opsiyonel).
            regimes_val: Doğrulama rejim etiketleri (opsiyonel).

        Returns:
            Eğitim ve doğrulama metriklerini içeren sözlük.
        """
        with self._lock:
            if len(self._base_models) < 2:
                logger.error("Yetersiz temel model", mevcut=len(self._base_models))
                return {"error": "En az 2 temel model gereklidir"}

            # Cross-validated stacking (TimeSeriesSplit — veri sızıntısını önler)
            n_splits = min(self._config.cv_folds, max(2, len(X_train) // 10))
            kf = TimeSeriesSplit(n_splits=n_splits)
            meta_features_train = np.zeros((len(X_train), len(self._base_models)), dtype=np.float64)

            for fold_idx, (train_idx, val_idx) in enumerate(kf.split(X_train)):
                X_tr, X_vl = X_train[train_idx], X_train[val_idx]
                y_tr = y_train[train_idx]

                for model_idx, (name, model) in enumerate(self._base_models.items()):
                    try:
                        fold_model = copy.deepcopy(model)
                        if hasattr(fold_model, "fit"):
                            fold_model.fit(X_tr, y_tr)

                        if self._config.use_proba and hasattr(fold_model, "predict_proba"):
                            probs = fold_model.predict_proba(X_vl)
                            meta_features_train[val_idx, model_idx] = (
                                probs[:, 1] if probs.shape[1] > 1 else probs[:, 0]
                            )
                        else:
                            meta_features_train[val_idx, model_idx] = fold_model.predict(X_vl)
                    except Exception as exc:
                        logger.warning("Katman fold egitimi basarisiz", model=name, fold=fold_idx, hata=str(exc))
                        meta_features_train[val_idx, model_idx] = 0.5

            # Orijinal öznitelik geçişi (Passthrough)
            if self._config.passthrough:
                meta_features_train = np.hstack([meta_features_train, X_train])

            # Ana meta-öğrenici eğitimi
            self._meta_learner = self._create_meta_learner()
            self._meta_learner.fit(meta_features_train, y_train)

            # Rejime özgü meta-öğreniciler
            if self._config.regime_aware and self._config.regime_meta_learners and regimes_train is not None:
                self._fit_regime_meta_learners(meta_features_train, y_train, regimes_train)

            # Temel modelleri tüm eğitim verisi üzerinde yeniden eğit
            for name, model in self._base_models.items():
                try:
                    if hasattr(model, "fit"):
                        model.fit(X_train, y_train)
                except Exception as exc:
                    logger.warning("Temel model tam egitimi basarisiz", model=name, hata=str(exc))

            self._is_fitted = True

            # Model çeşitlilik puanlaması
            self._compute_diversity(X_val)

            # Rejim bazlı ağırlık hesaplaması
            if regimes_val is not None:
                self._compute_regime_weights(X_val, y_val, regimes_val)

            # Doğrulama metrikleri
            metrics = self._compute_validation_metrics(X_val, y_val)

            self._training_history.append(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "metrics": metrics,
                    "n_base_models": len(self._base_models),
                    "diversity_scores": self._diversity_scores,
                }
            )
            if len(self._training_history) > DEFAULT_MAX_TRAINING_HISTORY:
                self._training_history = self._training_history[-DEFAULT_MAX_TRAINING_HISTORY:]

            self._record_audit_event(
                operation="FIT",
                base_model_count=len(self._base_models),
                val_ic=metrics.get("val_ic", 0.0),
                val_rank_ic=metrics.get("val_rank_ic", 0.0),
                details=metrics,
            )

            logger.info("Stacking ensemble basariyla egitildi", **metrics)
            return metrics

    def predict(
        self,
        X: np.ndarray,
        regime: str | None = None,
    ) -> np.ndarray:
        """Topluluk tahminini hesaplar.

        Args:
            X: Girdi öznitelik matrisi.
            regime: Aktif piyasa rejimi (None ise genel meta-öğrenici kullanılır).

        Returns:
            Tahmin dizisi (N,).
        """
        with self._lock:
            if not self._is_fitted:
                return np.zeros(len(X), dtype=np.float64)

            meta_features = self._get_meta_features(X)

            if regime and regime in self._regime_meta_learners:
                meta_learner = self._regime_meta_learners[regime]
            else:
                meta_learner = self._meta_learner

            try:
                if hasattr(meta_learner, "predict_proba"):
                    probs = meta_learner.predict_proba(meta_features)
                    return probs[:, 1] if probs.shape[1] > 1 else probs[:, 0]
                return meta_learner.predict(meta_features)
            except Exception as exc:
                logger.warning("Meta ogrenici tahmini basarisiz, agirlikli ortalamaya geciliyor", hata=str(exc))
                return self._weighted_average_predict(X, regime=regime)

    def _weighted_average_predict(self, X: np.ndarray, regime: str | None = None) -> np.ndarray:
        """Meta-learner başarısız olduğunda güvenli ağırlıklı ortalama fallback'i uygular."""
        weights = self.get_model_weights(regime)
        preds_list: list[np.ndarray] = []
        w_list: list[float] = []

        for name, model in self._base_models.items():
            try:
                if self._config.use_proba and hasattr(model, "predict_proba"):
                    p = model.predict_proba(X)[:, 1]
                else:
                    p = model.predict(X)
                preds_list.append(p)
                w_list.append(weights.get(name, 1.0))
            except Exception:
                continue

        if not preds_list:
            return np.zeros(len(X), dtype=np.float64)

        total_w = sum(w_list) or 1.0
        norm_w = [w / total_w for w in w_list]
        return np.sum([p * w for p, w in zip(preds_list, norm_w, strict=False)], axis=0)

    def predict_with_confidence(
        self,
        X: np.ndarray,
        regime: str | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Tahmin ve model uzlaşı güven skorunu (0.0-1.0) birlikte üretir.

        Args:
            X: Öznitelik matrisi.
            regime: Aktif rejim adı.

        Returns:
            (predictions, confidence) demeti.
        """
        with self._lock:
            if not self._is_fitted:
                return np.zeros(len(X), dtype=np.float64), np.zeros(len(X), dtype=np.float64)

            all_preds: list[np.ndarray] = []
            for _name, model in self._base_models.items():
                try:
                    if self._config.use_proba and hasattr(model, "predict_proba"):
                        probs = model.predict_proba(X)
                        preds = probs[:, 1] if probs.shape[1] > 1 else probs[:, 0]
                    else:
                        preds = model.predict(X)
                    all_preds.append(preds)
                except Exception as exc:
                    logger.debug("Model tahmin uretim hatasi", hata=str(exc))

            if not all_preds:
                return np.zeros(len(X), dtype=np.float64), np.zeros(len(X), dtype=np.float64)

            preds_matrix = np.asarray(all_preds, dtype=np.float64)

            # Güven: 1 - normalize standart sapma
            pred_std = np.std(preds_matrix, axis=0)
            confidence = 1.0 - (pred_std / DEFAULT_MAX_POSSIBLE_STD)
            confidence = np.clip(np.nan_to_num(confidence, nan=0.5), 0.0, 1.0)

            weighted_pred = self.predict(X, regime=regime)
            return weighted_pred, confidence

    def predict_with_details(
        self,
        X: np.ndarray,
        regime: str | None = None,
    ) -> StackingPredictionResult:
        """Detaylı model tahmin ve katkı dökümünü üretir.

        Args:
            X: Öznitelik matrisi (ilk satır analiz edilir).
            regime: Aktif rejim adı.

        Returns:
            StackingPredictionResult nesnesi.
        """
        with self._lock:
            X_sample = X[:1]
            model_preds: dict[str, float] = {}

            for name, model in self._base_models.items():
                try:
                    if self._config.use_proba and hasattr(model, "predict_proba"):
                        probs = model.predict_proba(X_sample)
                        p_val = float(probs[0, 1] if probs.shape[1] > 1 else probs[0, 0])
                    else:
                        p_val = float(model.predict(X_sample)[0])
                    model_preds[name] = p_val
                except Exception as exc:
                    logger.warning("Detayli tahmin hatasi", model=name, hata=str(exc))
                    model_preds[name] = 0.5

            pred_arr, conf_arr = self.predict_with_confidence(X_sample, regime=regime)
            pred = float(pred_arr[0]) if len(pred_arr) > 0 else 0.5
            conf = float(conf_arr[0]) if len(conf_arr) > 0 else 0.0

            preds_list = list(model_preds.values())
            above_half = sum(1 for p in preds_list if p > 0.5)
            agreement = max(above_half, len(preds_list) - above_half) / max(len(preds_list), 1)

            avg_diversity = (
                float(np.mean(list(self._diversity_scores.values()))) if self._diversity_scores else 0.0
            )

            return StackingPredictionResult(
                prediction=round(pred, 4),
                confidence=round(conf, 4),
                model_predictions=model_preds,
                model_weights=self.get_model_weights(regime),
                regime=regime or "UNKNOWN",
                agreement_score=round(agreement, 4),
                diversity_score=round(avg_diversity, 4),
            )

    def predict_polars(
        self,
        df: pl.DataFrame,
        feature_cols: list[str],
        regime: str | None = None,
    ) -> pl.DataFrame:
        """Polars DataFrame girdisi üzerinde tahmin yürüterek sonuç sütunlarını ekler.

        Args:
            df: Veri satırlarını içeren Polars DataFrame.
            feature_cols: Model girdi öznitelik sütunları.
            regime: Aktif piyasa rejimi.

        Returns:
            'stacking_pred' ve 'stacking_confidence' sütunları eklenmiş Polars DataFrame.
        """
        import polars as pl

        if df.is_empty():
            return df.with_columns(
                pl.lit(0.0).alias("stacking_pred"),
                pl.lit(0.0).alias("stacking_confidence"),
            )

        X = df.select(feature_cols).fill_null(0.0).to_numpy()
        preds, confs = self.predict_with_confidence(X, regime=regime)

        cols = [
            pl.Series("stacking_pred", preds),
            pl.Series("stacking_prediction", preds),
            pl.Series("stacking_confidence", confs),
            pl.Series("confidence", confs),
        ]
        if regime:
            cols.append(pl.lit(regime).alias("regime"))

        return df.with_columns(cols)

    def predict_detailed(
        self,
        X: np.ndarray,
        regime: str | None = None,
    ) -> list[StackingPredictionResult]:
        """Ayrıntılı tahmin çıktısı ve model uzlaşısı (predict_with_details sarmalayıcısı)."""
        return self.predict_with_details(X, regime=regime)

    def evaluate_by_regime(
        self,
        X_val: np.ndarray,
        y_val: np.ndarray,
        regimes_val: np.ndarray,
    ) -> dict[str, dict[str, Any]]:
        """Rejim bazlı performans raporu (get_regime_performance_report sarmalayıcısı)."""
        return self.get_regime_performance_report(X_val, y_val, regimes_val)

    def get_model_weights(self, regime: str | None = None) -> dict[str, float]:
        """Piyasa rejimine veya genel modele göre göreli model katsayılarını döndürür."""
        with self._lock:
            if regime and regime in self._regime_weights:
                return self._regime_weights[regime]

            if self._meta_learner is None or not hasattr(self._meta_learner, "coef_"):
                return self._model_weights

            try:
                coefs = self._meta_learner.coef_
                if coefs.ndim > 1:
                    coefs = coefs[0]
                n_models = len(self._base_models)
                if len(coefs) >= n_models:
                    model_coefs = coefs[:n_models]
                    total = sum(abs(c) for c in model_coefs)
                    if total > 0:
                        return {
                            name: round(float(abs(c) / total), 4)
                            for (name, _), c in zip(self._base_models.items(), model_coefs, strict=False)
                        }
            except Exception as exc:
                logger.debug("Model agirlik hesaplama bildirimi", hata=str(exc))

            return self._model_weights

    def get_regime_weights(self) -> dict[str, dict[str, float]]:
        """Tüm rejim ağırlıkları sözlüğünü döndürür."""
        with self._lock:
            return dict(self._regime_weights)

    def get_diversity_scores(self) -> dict[str, float]:
        """Modeller arası çeşitlilik skorlarını döndürür."""
        with self._lock:
            return dict(self._diversity_scores)

    def get_training_history(self) -> list[dict[str, Any]]:
        """Eğitim geçmiş kayıtlarını döndürür."""
        with self._lock:
            return list(self._training_history)

    def _get_meta_features(self, X: np.ndarray) -> np.ndarray:
        """Temel modellerin tahminlerini meta-öğrenici girdi matrisine dönüştürür."""
        meta_features = np.zeros((len(X), len(self._base_models)), dtype=np.float64)
        for model_idx, (model_name, model) in enumerate(self._base_models.items()):
            try:
                if self._config.use_proba and hasattr(model, "predict_proba"):
                    probs = model.predict_proba(X)
                    meta_features[:, model_idx] = probs[:, 1] if probs.shape[1] > 1 else probs[:, 0]
                else:
                    meta_features[:, model_idx] = model.predict(X)
            except Exception as exc:
                logger.warning("Meta feature uretimi basarisiz", model=model_name, hata=str(exc))
                meta_features[:, model_idx] = 0.5

        if self._config.passthrough:
            meta_features = np.hstack([meta_features, X])

        return meta_features

    def _create_meta_learner(self) -> Any:
        """Konfigürasyona uygun sklearn regresyon/sınıflandırıcı meta-öğrenicisini oluşturur."""
        m_type = self._config.meta_learner_type
        if m_type == "ridge":
            return Ridge(alpha=1.0)
        if m_type == "logistic":
            return LogisticRegression(max_iter=1000)
        if m_type == "elastic_net":
            return ElasticNet(alpha=1.0, l1_ratio=0.5)
        return LinearRegression()

    def _fit_regime_meta_learners(
        self,
        meta_features: np.ndarray,
        y: np.ndarray,
        regimes: np.ndarray,
    ) -> None:
        """Her rejim için ayrı bir meta-öğrenici eğitir."""
        unique_regimes = np.unique(regimes)
        for regime in unique_regimes:
            mask = regimes == regime
            if np.sum(mask) < DEFAULT_MIN_SAMPLES_PER_REGIME:
                continue

            try:
                learner = self._create_meta_learner()
                learner.fit(meta_features[mask], y[mask])
                self._regime_meta_learners[str(regime)] = learner
                logger.info("Rejime ozgu meta ogrenici egitildi", regime=str(regime), samples=int(np.sum(mask)))
            except Exception as exc:
                logger.warning("Rejim meta ogrenici egitimi basarisiz", regime=str(regime), hata=str(exc))

    def _compute_diversity(self, X: np.ndarray) -> None:
        """Modeller arası ikili korelasyonu hesaplayarak çeşitlilik puanını belirler."""
        all_preds: list[tuple[str, np.ndarray]] = []
        for name, model in self._base_models.items():
            try:
                if self._config.use_proba and hasattr(model, "predict_proba"):
                    probs = model.predict_proba(X)
                    preds = probs[:, 1] if probs.shape[1] > 1 else probs[:, 0]
                else:
                    preds = model.predict(X)
                all_preds.append((name, preds))
            except Exception as exc:
                logger.debug("Cesitlilik tahmin hatasi", model=name, hata=str(exc))

        if len(all_preds) < 2:
            return

        names = [n for n, _ in all_preds]
        preds_matrix = np.asarray([p for _, p in all_preds], dtype=np.float64)

        for i, name_i in enumerate(names):
            correlations: list[float] = []
            for j, _name_j in enumerate(names):
                if i != j:
                    std_i = np.std(preds_matrix[i])
                    std_j = np.std(preds_matrix[j])
                    if std_i > DEFAULT_EPSILON and std_j > DEFAULT_EPSILON:
                        corr = np.corrcoef(preds_matrix[i], preds_matrix[j])[0, 1]
                        if np.isfinite(corr):
                            correlations.append(abs(corr))

            avg_corr = float(np.mean(correlations)) if correlations else 1.0
            self._diversity_scores[name_i] = round(1.0 - avg_corr, 4)

    def _compute_regime_weights(
        self,
        X: np.ndarray,
        y: np.ndarray,
        regimes: np.ndarray,
    ) -> None:
        """Her rejim kesiti için modellerin korelasyon (IC) performansına göre ağırlıklarını hesaplar."""
        unique_regimes = np.unique(regimes)

        for regime in unique_regimes:
            mask = regimes == regime
            if np.sum(mask) < DEFAULT_MIN_SAMPLES_PER_REGIME:
                continue

            try:
                regime_scores: dict[str, float] = {}
                for name, model in self._base_models.items():
                    try:
                        if self._config.use_proba and hasattr(model, "predict_proba"):
                            probs = model.predict_proba(X[mask])
                            preds = probs[:, 1] if probs.shape[1] > 1 else probs[:, 0]
                        else:
                            preds = model.predict(X[mask])

                        std_p = np.std(preds)
                        std_y = np.std(y[mask])
                        if std_p > DEFAULT_EPSILON and std_y > DEFAULT_EPSILON:
                            ic = np.corrcoef(preds, y[mask])[0, 1]
                            ic_val = abs(float(ic)) if np.isfinite(ic) else 0.0
                        else:
                            ic_val = 0.0

                        regime_scores[name] = ic_val
                    except Exception as exc:
                        logger.warning("Rejim skoru hesabi basarisiz", model=name, regime=str(regime), hata=str(exc))
                        regime_scores[name] = 0.0

                total = sum(regime_scores.values())
                if total > 0:
                    self._regime_weights[str(regime)] = {
                        name: round(score / total, 4) for name, score in regime_scores.items()
                    }
                else:
                    self._regime_weights[str(regime)] = {
                        name: round(1.0 / len(self._base_models), 4) for name in self._base_models
                    }
            except Exception as exc:
                logger.warning("Rejim agirligi hesaplama hatasi", regime=str(regime), hata=str(exc))

    def _compute_validation_metrics(self, X_val: np.ndarray, y_val: np.ndarray) -> dict[str, Any]:
        """Doğrulama kümesi üzerinde IC, Rank IC ve yön doğruluğu metriklerini hesaplar."""
        val_pred = self.predict(X_val)

        # IC (Information Coefficient)
        std_p = np.std(val_pred)
        std_y = np.std(y_val)
        if std_p > DEFAULT_EPSILON and std_y > DEFAULT_EPSILON:
            ic_corr = np.corrcoef(val_pred, y_val)[0, 1]
            ic = float(ic_corr) if np.isfinite(ic_corr) else 0.0
        else:
            ic = 0.0

        # Yön Doğruluğu (Directional Accuracy)
        try:
            pred_sign = np.sign(val_pred)
            true_sign = np.sign(y_val)
            directional_accuracy = float(np.mean(pred_sign == true_sign))
        except Exception:
            directional_accuracy = 0.0

        # Spearman Rank IC
        try:
            rank_ic, _ = spearmanr(val_pred, y_val)
            rank_ic = float(rank_ic) if np.isfinite(rank_ic) else 0.0
        except Exception:
            rank_ic = 0.0

        avg_div = float(np.mean(list(self._diversity_scores.values()))) if self._diversity_scores else 0.0

        return {
            "n_base_models": len(self._base_models),
            "cv_folds": self._config.cv_folds,
            "meta_learner": self._config.meta_learner_type,
            "val_ic": round(ic, 4),
            "val_rank_ic": round(rank_ic, 4),
            "val_directional_accuracy": round(directional_accuracy, 4),
            "diversity_score": round(avg_div, 4),
            "n_regime_meta_learners": len(self._regime_meta_learners),
            "n_regime_weights": len(self._regime_weights),
        }

    def predict_with_regime_smoothing(
        self,
        X: np.ndarray,
        current_regime: str,
        previous_regime: str | None = None,
        smoothing_factor: float = 0.3,
    ) -> np.ndarray:
        """Ani rejim geçişlerinde tahmin sıçramalarını yumuşatır (Smoothing).

        Args:
            X: Öznitelik matrisi.
            current_regime: Aktif piyasa rejimi.
            previous_regime: Önceki adımın piyasa rejimi.
            smoothing_factor: Yeni rejimin ağırlığı [0.0-1.0].

        Returns:
            Yumuşatılmış tahmin dizisi.
        """
        if previous_regime is None or previous_regime == current_regime:
            return self.predict(X, regime=current_regime)

        pred_current = self.predict(X, regime=current_regime)
        pred_previous = self.predict(X, regime=previous_regime)

        alpha = float(np.clip(smoothing_factor, 0.0, 1.0))
        return alpha * pred_current + (1.0 - alpha) * pred_previous

    def get_regime_performance_report(
        self,
        X_val: np.ndarray,
        y_val: np.ndarray,
        regimes: np.ndarray,
    ) -> dict[str, dict[str, float]]:
        """Her rejimdeki topluluk performans dökümünü oluşturur."""
        report: dict[str, dict[str, float]] = {}
        unique_regimes = np.unique(regimes)

        for regime in unique_regimes:
            mask = regimes == regime
            n = int(np.sum(mask))
            if n < 10:
                continue

            preds = self.predict(X_val[mask], regime=str(regime))
            y_regime = y_val[mask]

            finite_mask = np.isfinite(preds) & np.isfinite(y_regime)
            if np.sum(finite_mask) < 5:
                continue

            p_fin = preds[finite_mask]
            y_fin = y_regime[finite_mask]

            if np.std(p_fin) > DEFAULT_EPSILON and np.std(y_fin) > DEFAULT_EPSILON:
                ic_val = float(np.corrcoef(p_fin, y_fin)[0, 1])
                ic = ic_val if np.isfinite(ic_val) else 0.0
            else:
                ic = 0.0

            try:
                rank_ic, _ = spearmanr(p_fin, y_fin)
                rank_ic = float(rank_ic) if np.isfinite(rank_ic) else 0.0
            except Exception:
                rank_ic = 0.0

            dir_acc = float(np.mean(np.sign(p_fin) == np.sign(y_fin)))

            report[str(regime)] = {
                "ic": round(ic, 4),
                "rank_ic": round(rank_ic, 4),
                "direction_accuracy": round(dir_acc, 4),
                "n_samples": n,
            }

        return report

    @property
    def is_fitted(self) -> bool:
        """Modelin başarıyla eğitilip eğitilmediğini döndürür."""
        with self._lock:
            return self._is_fitted

    @property
    def base_model_names(self) -> list[str]:
        """Kayıtlı temel model adlarının listesini döndürür."""
        with self._lock:
            return list(self._base_models.keys())

    def get_audit_as_polars(self) -> pl.DataFrame:
        """DuckDB denetim tablosunu Polars DataFrame olarak döndürür."""
        import polars as pl

        with self._lock:
            try:
                with duckdb.connect(self._duckdb_path) as conn:
                    configure_duckdb_wal(conn)
                    return conn.execute("SELECT * FROM stacking_ensemble_audit ORDER BY timestamp ASC").pl()
            except Exception as exc:
                logger.warning("DuckDB denetim izi okunamadi", hata=str(exc))
                return pl.DataFrame()

    def __repr__(self) -> str:
        """StackingEnsemble özet metin gösterimini oluşturur."""
        with self._lock:
            return (
                f"StackingEnsemble(is_fitted={self._is_fitted}, "
                f"base_models={list(self._base_models.keys())}, meta='{self._config.meta_learner_type}')"
            )


__all__: Final[list[str]] = [
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EPSILON",
    "DEFAULT_MAX_POSSIBLE_STD",
    "DEFAULT_MAX_TRAINING_HISTORY",
    "DEFAULT_MIN_SAMPLES_PER_REGIME",
    "StackingConfig",
    "StackingEnsemble",
    "StackingPredictionResult",
    "configure_duckdb_wal",
]
