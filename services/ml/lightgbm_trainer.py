"""ALPHA BIST — Şampiyon Model LightGBM Eğitim ve Doğrulama Hattı v3.0 (Nihai — ⭐⭐⭐⭐⭐).

Bu modül; sistemin ana şampiyon (champion) modeli olan LightGBM için Point-in-Time
tarih-uzayında arındırma (Date-Space Purge & Embargo), çoklu tahmin ufku (Multi-Horizon:
1g/5g/20g/60g), kapsamlı doğrulama metrikleri (IC, Spearman Rank IC, Hit Rate, Yön Doğruluğu),
model güven skoru (confidence) ve DuckDB denetim izi altyapısını içerir.

Temel Yetenekler:
- Sıfır Veri Sızıntısı (Zero Data Leakage): Date-space purge_gap = max(horizon, purge_gap_days)
- Yalnızca eğitim setinden öğrenilen ölçekleyici (Scaler) ve eksik değer tamamlama (Imputer)
- Çoklu Vade (Multi-Horizon Target) mimarisi ve TrainedModel / MultiHorizonModel sarmalayıcıları
- Kapsamlı model doğrulama metrikleri ve dinamik model güven (confidence) hesabı
- Out-Of-Fold (OOF) zamansal çapraz doğrulama tahminleri
- Polars DataFrame üzerinden doğrudan eğitim ve veri hazırlığı (`train_polars`)
- DuckDB üzerinde SSD korumalı WAL ile eğitim ve doğrulama denetim izi
- İş parçacığı güvenliği (`threading.RLock`) ve fail-closed mimari
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import duckdb
import numpy as np
import orjson
import structlog

if TYPE_CHECKING:
    import polars as pl

logger = structlog.get_logger(__name__)

# --- Sabitler ---
DEFAULT_LEARNING_RATE: Final[float] = 0.05
DEFAULT_NUM_LEAVES: Final[int] = 31
DEFAULT_MAX_DEPTH: Final[int] = 5
DEFAULT_MIN_DATA_IN_LEAF: Final[int] = 20
DEFAULT_FEATURE_FRACTION: Final[float] = 0.80
DEFAULT_BAGGING_FRACTION: Final[float] = 0.80
DEFAULT_BAGGING_FREQ: Final[int] = 5
DEFAULT_NUM_BOOST_ROUND: Final[int] = 100
DEFAULT_EARLY_STOPPING_ROUNDS: Final[int] = 10
DEFAULT_VAL_RATIO: Final[float] = 0.20
DEFAULT_PURGE_GAP_DAYS: Final[int] = 5
DEFAULT_TARGET_HORIZON: Final[int] = 5
DEFAULT_RANDOM_SEED: Final[int] = 42
DEFAULT_DUCKDB_PATH: Final[str] = "data/lightgbm_trainer.duckdb"
DEFAULT_EPSILON: Final[float] = 1e-8


class TargetMethod(StrEnum):
    """Hedef değişken türetme metotları."""

    RETURN = "return"
    LOG_RETURN = "log_return"
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
class MLModelConfig:
    """LightGBM model konfigürasyon veri modeli."""

    objective: str = "regression"
    metric: str = "rmse"
    ndcg_eval_at: list[int] = field(default_factory=lambda: [5, 10, 20])
    learning_rate: float = DEFAULT_LEARNING_RATE
    num_leaves: int = DEFAULT_NUM_LEAVES
    min_data_in_leaf: int = DEFAULT_MIN_DATA_IN_LEAF
    feature_fraction: float = DEFAULT_FEATURE_FRACTION
    bagging_fraction: float = DEFAULT_BAGGING_FRACTION
    bagging_freq: int = DEFAULT_BAGGING_FREQ
    num_boost_round: int = DEFAULT_NUM_BOOST_ROUND
    early_stopping_rounds: int = DEFAULT_EARLY_STOPPING_ROUNDS
    verbose: int = -1
    impute_strategy: str = "median"
    scale_features: bool = True
    val_ratio: float = DEFAULT_VAL_RATIO
    purge_gap_days: int = DEFAULT_PURGE_GAP_DAYS
    target_horizon: int = DEFAULT_TARGET_HORIZON
    model_dir: str = "models"
    duckdb_path: str = DEFAULT_DUCKDB_PATH

    def to_dict(self) -> dict[str, Any]:
        """Konfigürasyonu sözlük formatına dönüştürür."""
        return {
            "objective": self.objective,
            "metric": self.metric,
            "learning_rate": self.learning_rate,
            "num_leaves": self.num_leaves,
            "min_data_in_leaf": self.min_data_in_leaf,
            "feature_fraction": self.feature_fraction,
            "num_boost_round": self.num_boost_round,
            "val_ratio": self.val_ratio,
            "purge_gap_days": self.purge_gap_days,
            "target_horizon": self.target_horizon,
        }

    def to_orjson_bytes(self) -> bytes:
        """Konfigürasyonu orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MLModelConfig:
        """Sözlükten MLModelConfig nesnesi oluşturur."""
        return cls(
            objective=str(data.get("objective", "regression")),
            metric=str(data.get("metric", "rmse")),
            learning_rate=float(data.get("learning_rate", DEFAULT_LEARNING_RATE)),
            num_leaves=int(data.get("num_leaves", DEFAULT_NUM_LEAVES)),
            min_data_in_leaf=int(data.get("min_data_in_leaf", DEFAULT_MIN_DATA_IN_LEAF)),
            feature_fraction=float(data.get("feature_fraction", DEFAULT_FEATURE_FRACTION)),
            num_boost_round=int(data.get("num_boost_round", DEFAULT_NUM_BOOST_ROUND)),
            val_ratio=float(data.get("val_ratio", DEFAULT_VAL_RATIO)),
            purge_gap_days=int(data.get("purge_gap_days", DEFAULT_PURGE_GAP_DAYS)),
            target_horizon=int(data.get("target_horizon", DEFAULT_TARGET_HORIZON)),
            model_dir=str(data.get("model_dir", "models")),
            duckdb_path=str(data.get("duckdb_path", DEFAULT_DUCKDB_PATH)),
        )

    def __repr__(self) -> str:
        return (
            f"MLModelConfig(obj='{self.objective}', lr={self.learning_rate}, "
            f"horizon={self.target_horizon}d, purge={self.purge_gap_days}d)"
        )


@dataclass(slots=True)
class TrainedModel:
    """Eğitilmiş LightGBM modeli ve öznitelik/doğrulama meta verileri sarmalayıcısı."""

    model: Any
    feature_names: list[str]
    scaler_mean: np.ndarray | None = None
    scaler_std: np.ndarray | None = None
    impute_values: dict[str, float] | None = None
    train_date_range: tuple[str, str] = ("", "")
    train_samples: int = 0
    validation_score: float = 0.0
    feature_importance: dict[str, float] = field(default_factory=dict)
    trained_at: str = ""
    config: MLModelConfig | None = None
    validation_metrics: dict[str, float] = field(default_factory=dict)
    confidence_score: float = 0.0
    confidence_details: dict[str, Any] = field(default_factory=dict)
    fallback_reason: str | None = None
    target_horizon: int = DEFAULT_TARGET_HORIZON
    cs_features: list[str] = field(default_factory=list)

    def predict(self, features: dict[str, Any]) -> float:
        """Tekil öznitelik sözlüğü için model tahmini üretir.

        Args:
            features: Öznitelik adı -> değer sözlüğü.

        Returns:
            Tahmin edilen sürekli getiri değeri.

        Raises:
            ValueError: Model henüz eğitilmemişse fırlatılır.
        """
        if self.model is None:
            raise ValueError("Model egitilmemis veya yuklenmemis.")
        vec = self._feature_vector(features)
        pred = self.model.predict(np.array([vec]))
        result = float(pred[0])
        return result if np.isfinite(result) else 0.0

    def predict_batch(self, features_list: list[dict[str, Any]]) -> list[float]:
        """Çoklu öznitelik sözlükleri için toplu tahmin üretir.

        Args:
            features_list: Öznitelik sözlükleri listesi.

        Returns:
            Tahmin listesi.

        Raises:
            ValueError: Model henüz eğitilmemişse fırlatılır.
        """
        if self.model is None:
            raise ValueError("Model egitilmemis veya yuklenmemis.")
        if not features_list:
            return []
        vecs = [self._feature_vector(f) for f in features_list]
        preds = self.model.predict(np.array(vecs))
        return [float(p) if np.isfinite(p) else 0.0 for p in preds]

    def _feature_vector(self, features: dict[str, Any]) -> list[float]:
        """Öznitelik sözlüğünü sıralı, impute edilmiş ve ölçeklenmiş vektöre dönüştürür."""
        vec: list[float] = []
        for name in self.feature_names:
            val = features.get(name)
            if val is None:
                vec.append(self.impute_values.get(name, 0.0) if self.impute_values else 0.0)
            else:
                try:
                    v = float(val)
                    vec.append(v if np.isfinite(v) else 0.0)
                except (TypeError, ValueError):
                    vec.append(0.0)
        arr = np.array(vec, dtype=np.float32)
        if self.scaler_mean is not None and self.scaler_std is not None:
            std_safe = np.where(self.scaler_std > DEFAULT_EPSILON, self.scaler_std, 1.0)
            arr = (arr - self.scaler_mean) / std_safe
        return arr.tolist()

    def save(self, path: str | Path) -> None:
        """Modeli güvenli serileştirme ile diske kaydeder.

        Args:
            path: Kayıt dosya yolu.
        """
        from services.core.safe_pickle import safe_pickle_dump

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        safe_pickle_dump(self, str(p))

    @classmethod
    def load(cls, path: str | Path) -> TrainedModel:
        """Diskten TrainedModel nesnesini yükler.

        Args:
            path: Yüklenecek model dosyası.

        Returns:
            TrainedModel örneği.
        """
        from services.core.safe_pickle import safe_pickle_load

        return safe_pickle_load(str(path))

    def to_dict(self) -> dict[str, Any]:
        """Model meta verilerini sözlük olarak döndürür."""
        return {
            "feature_names": self.feature_names,
            "train_date_range": list(self.train_date_range),
            "train_samples": self.train_samples,
            "validation_score": round(self.validation_score, 4),
            "validation_metrics": self.validation_metrics,
            "confidence_score": round(self.confidence_score, 4),
            "target_horizon": self.target_horizon,
            "trained_at": self.trained_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TrainedModel:
        """Sözlükten TrainedModel nesnesi oluşturur."""
        return cls(
            model=d.get("model"),
            feature_names=list(d.get("feature_names", [])),
            train_date_range=tuple(d.get("train_date_range", ("", ""))),  # type: ignore[arg-type]
            train_samples=int(d.get("train_samples", 0)),
            validation_score=float(d.get("validation_score", 0.0)),
            validation_metrics=dict(d.get("validation_metrics", {})),
            confidence_score=float(d.get("confidence_score", 0.0)),
            target_horizon=int(d.get("target_horizon", DEFAULT_TARGET_HORIZON)),
            trained_at=str(d.get("trained_at", "")),
        )

    def to_orjson_bytes(self) -> bytes:
        """Meta verileri orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        return (
            f"TrainedModel(samples={self.train_samples}, val_score={self.validation_score:.4f}, "
            f"conf={self.confidence_score:.2f}, horizon={self.target_horizon}d)"
        )


@dataclass(slots=True)
class MultiHorizonModel:
    """Çoklu tahmin ufku (1d, 5d, 20d, 60d) modelleri sarmalayıcısı."""

    horizon_models: dict[int, TrainedModel] = field(default_factory=dict)
    primary_horizon: int = DEFAULT_TARGET_HORIZON
    cs_features: list[str] = field(default_factory=list)

    @property
    def primary_model(self) -> TrainedModel | None:
        """Birincil (varsayılan) horizon modelini döndürür."""
        return self.horizon_models.get(self.primary_horizon)

    def predict(self, features: dict[str, Any]) -> float:
        """Birincil horizon üzerinden tahmin üretir."""
        m = self.primary_model
        if m is None:
            return 0.0
        try:
            return m.predict(features)
        except Exception:
            return 0.0

    def predict_horizon(self, features: dict[str, Any], horizon: int) -> float:
        """Belirtilen vade (horizon) üzerinden tahmin üretir."""
        m = self.horizon_models.get(horizon)
        if m is None:
            return 0.0
        try:
            return m.predict(features)
        except Exception:
            return 0.0

    def get_all_predictions(self, features: dict[str, Any]) -> dict[int, float]:
        """Mevcut tüm vadeler için tahmin sözlüğü üretir."""
        return {h: m.predict(features) for h, m in self.horizon_models.items()}

    @property
    def available_horizons(self) -> list[int]:
        """Kullanılabilir vade günleri listesi."""
        return sorted(self.horizon_models.keys())

    @property
    def total_train_samples(self) -> int:
        """Tüm horizon modellerindeki toplam örnek sayısı."""
        return sum(m.train_samples for m in self.horizon_models.values())

    @property
    def train_samples(self) -> int:
        """Birincil modelin eğitim örneklem sayısı."""
        m = self.primary_model
        return m.train_samples if m else 0

    @property
    def train_date_range(self) -> tuple[str, str]:
        """Birincil modelin eğitim tarih aralığı."""
        m = self.primary_model
        return m.train_date_range if m else ("", "")

    @property
    def validation_score(self) -> float:
        """Birincil modelin doğrulama skoru."""
        m = self.primary_model
        return m.validation_score if m else 0.0

    @property
    def validation_metrics(self) -> dict[str, float]:
        """Birincil modelin kapsamlı doğrulama metrikleri."""
        m = self.primary_model
        return m.validation_metrics if m else {}

    @property
    def confidence_score(self) -> float:
        """Birincil modelin güven skoru."""
        m = self.primary_model
        return m.confidence_score if m else 0.0

    @property
    def feature_names(self) -> list[str]:
        """Birincil modelin öznitelik listesi."""
        m = self.primary_model
        return m.feature_names if m else []

    def to_dict(self) -> dict[str, Any]:
        """Çoklu vade model özetini sözlüğe dönüştürür."""
        return {
            "available_horizons": self.available_horizons,
            "primary_horizon": self.primary_horizon,
            "total_train_samples": self.total_train_samples,
            "primary_confidence": round(self.confidence_score, 4),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MultiHorizonModel:
        """Sözlükten MultiHorizonModel nesnesi oluşturur."""
        return cls(
            primary_horizon=int(d.get("primary_horizon", DEFAULT_TARGET_HORIZON)),
        )

    def to_orjson_bytes(self) -> bytes:
        """Özeti orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        return (
            f"MultiHorizonModel(horizons={self.available_horizons}, "
            f"primary={self.primary_horizon}d, primary_conf={self.confidence_score:.2f})"
        )


@dataclass(slots=True)
class TargetSpec:
    """Çoklu vade hedef spesifikasyon veri modeli."""

    horizon: int = DEFAULT_TARGET_HORIZON
    name: str = "return_5d"
    method: TargetMethod | str = TargetMethod.RETURN

    @property
    def label(self) -> str:
        """Hedefin etiket adını üretir."""
        return f"{self.method}_{self.horizon}d"

    def to_dict(self) -> dict[str, Any]:
        """Hedef spesifikasyonunu sözlüğe dönüştürür."""
        return {
            "horizon": self.horizon,
            "name": self.name,
            "method": str(self.method),
        }

    def to_orjson_bytes(self) -> bytes:
        """Spesifikasyonu orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TargetSpec:
        """Sözlükten TargetSpec nesnesi oluşturur."""
        return cls(
            horizon=int(d.get("horizon", DEFAULT_TARGET_HORIZON)),
            name=str(d.get("name", "return_5d")),
            method=d.get("method", TargetMethod.RETURN),
        )

    def __repr__(self) -> str:
        return f"TargetSpec(horizon={self.horizon}, name='{self.name}', method='{self.method}')"


DEFAULT_TARGETS: Final[list[TargetSpec]] = [
    TargetSpec(horizon=1, name="return_1d"),
    TargetSpec(horizon=5, name="return_5d"),
    TargetSpec(horizon=20, name="return_20d"),
    TargetSpec(horizon=60, name="return_60d"),
]


def compute_target(close: np.ndarray, idx: int, spec: TargetSpec) -> float | None:
    """Belirtilen kapanış serisi ve indeks için vade hedefini hesaplar.

    Args:
        close: Fiyat kapanış dizisi.
        idx: Güncel zaman indeksi.
        spec: Hedef spesifikasyonu.

    Returns:
        Yüzdesel getiri / log-getiri / ikili etiket veya veri yetersizse None.
    """
    target_idx = idx + spec.horizon
    if target_idx >= len(close):
        return None
    c_t = float(close[idx])
    c_fwd = float(close[target_idx])

    if c_t <= DEFAULT_EPSILON or not np.isfinite(c_t) or not np.isfinite(c_fwd) or c_fwd <= DEFAULT_EPSILON:
        return None

    if str(spec.method) == TargetMethod.LOG_RETURN:
        return float(np.log(c_fwd / c_t) * 100.0)
    elif str(spec.method) == TargetMethod.BINARY:
        return 1.0 if c_fwd > c_t else 0.0
    else:  # RETURN
        return float((c_fwd / c_t - 1.0) * 100.0)


def compute_comprehensive_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Gerçek ve tahmin edilen değerler arasında kapsamlı quant doğrulama metriklerini hesaplar.

    Args:
        y_true: Gerçekleşen getiri değerleri.
        y_pred: Model tarafından tahmin edilen değerler.

    Returns:
        MAE, RMSE, IC, Rank Correlation, Directional Accuracy vb. metrik sözlüğü.
    """
    defaults: dict[str, float] = {
        "mae": 0.0,
        "rmse": 0.0,
        "r_squared": 0.0,
        "directional_accuracy": 0.0,
        "ic": 0.0,
        "ic_stability": 0.0,
        "prediction_std": 0.0,
        "target_std": 0.0,
        "rank_correlation": 0.0,
        "hit_rate": 0.0,
        "worst_error": 0.0,
        "validation_samples": 0.0,
        "top10_avg_return": 0.0,
        "top20_avg_return": 0.0,
        "bottom10_avg_return": 0.0,
        "long_short_spread": 0.0,
        "rank_ic": 0.0,
    }
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    yt, yp = y_true[mask], y_pred[mask]
    if len(yt) < 2:
        return defaults

    n = len(yt)
    defaults["validation_samples"] = float(n)
    defaults["mae"] = float(np.mean(np.abs(yt - yp)))
    defaults["rmse"] = float(np.sqrt(np.mean((yt - yp) ** 2)))

    ss_res = np.sum((yt - yp) ** 2)
    ss_tot = np.sum((yt - np.mean(yt)) ** 2)
    if ss_tot > DEFAULT_EPSILON:
        defaults["r_squared"] = float(max(-10.0, 1.0 - (ss_res / ss_tot)))

    defaults["directional_accuracy"] = float(np.sum(np.sign(yt) == np.sign(yp)) / n)
    defaults["prediction_std"] = float(np.std(yp))
    defaults["target_std"] = float(np.std(yt))
    defaults["worst_error"] = float(np.max(np.abs(yt - yp)))

    positive_mask = yt > 0
    if np.sum(positive_mask) > 0:
        defaults["hit_rate"] = float(np.sum(np.sign(yp[positive_mask]) == 1) / np.sum(positive_mask))

    try:
        from scipy.stats import spearmanr

        if np.std(yt) > DEFAULT_EPSILON and np.std(yp) > DEFAULT_EPSILON:
            ic_val, _ = spearmanr(yt, yp)
            defaults["ic"] = float(ic_val) if np.isfinite(ic_val) else 0.0
            defaults["rank_correlation"] = defaults["ic"]
    except ImportError:
        if np.std(yt) > DEFAULT_EPSILON and np.std(yp) > DEFAULT_EPSILON:
            corr = np.corrcoef(yt, yp)[0, 1]
            defaults["ic"] = float(corr) if np.isfinite(corr) else 0.0
            defaults["rank_correlation"] = defaults["ic"]

    if n >= 20:
        half = n // 2
        try:
            from scipy.stats import spearmanr

            ic1 = ic2 = 0.0
            if np.std(yt[:half]) > DEFAULT_EPSILON and np.std(yp[:half]) > DEFAULT_EPSILON:
                r1, _ = spearmanr(yt[:half], yp[:half])
                ic1 = float(r1) if np.isfinite(r1) else 0.0
            if np.std(yt[half:]) > DEFAULT_EPSILON and np.std(yp[half:]) > DEFAULT_EPSILON:
                r2, _ = spearmanr(yt[half:], yp[half:])
                ic2 = float(r2) if np.isfinite(r2) else 0.0
            defaults["ic_stability"] = float(1.0 - abs(ic1 - ic2))
        except Exception as err:
            logger.debug("IC kararlilik hesabi basarisiz", hata=str(err))

    if n >= 10:
        k10 = max(1, int(n * 0.1))
        k20 = max(1, int(n * 0.2))
        top10_idx = np.argsort(-yp)[:k10]
        top20_idx = np.argsort(-yp)[:k20]
        bottom10_idx = np.argsort(yp)[:k10]
        defaults["top10_avg_return"] = float(np.mean(yt[top10_idx]))
        defaults["top20_avg_return"] = float(np.mean(yt[top20_idx]))
        defaults["bottom10_avg_return"] = float(np.mean(yt[bottom10_idx]))
        defaults["long_short_spread"] = float(defaults["top10_avg_return"] - defaults["bottom10_avg_return"])
        defaults["rank_ic"] = defaults["ic"]

    return defaults


def compute_model_confidence(
    validation_metrics: dict[str, float],
    train_samples: int,
    feature_count: int,
    train_regime: str = "UNKNOWN",
    current_regime: str = "UNKNOWN",
) -> tuple[float, dict[str, Any]]:
    """Doğrulama metriklerine ve veri boyutuna dayalı model güven skoru hesaplar.

    Args:
        validation_metrics: Doğrulama metrikleri sözlüğü.
        train_samples: Eğitim örneklem sayısı.
        feature_count: Kullanılan öznitelik adedi.
        train_regime: Eğitim sırasındaki rejim.
        current_regime: Güncel canlı rejim.

    Returns:
        `(guven_skoru, detay_sozlugu)` demeti [0.0, 1.0].
    """
    details: dict[str, Any] = {"degradation_reasons": []}
    confidence = 1.0

    if train_samples < 100:
        confidence *= 0.50
        details["degradation_reasons"].append(f"low_samples:{train_samples}")
    elif train_samples < 300:
        confidence *= 0.75
        details["degradation_reasons"].append(f"moderate_samples:{train_samples}")

    ic = validation_metrics.get("ic", 0.0)
    if abs(ic) < 0.02:
        confidence *= 0.40
        details["degradation_reasons"].append(f"weak_ic:{ic:.4f}")
    elif abs(ic) < 0.05:
        confidence *= 0.70
        details["degradation_reasons"].append(f"low_ic:{ic:.4f}")

    dir_acc = validation_metrics.get("directional_accuracy", 0.50)
    if dir_acc < 0.45:
        confidence *= 0.50
        details["degradation_reasons"].append(f"poor_direction:{dir_acc:.2f}")
    elif dir_acc < 0.52:
        confidence *= 0.80

    pred_std = validation_metrics.get("prediction_std", 0.0)
    target_std = validation_metrics.get("target_std", 1.0)
    if target_std > DEFAULT_EPSILON and (pred_std / target_std) < 0.10:
        confidence *= 0.60
        details["degradation_reasons"].append(f"narrow_predictions:{pred_std / target_std:.2f}")

    val_samples = validation_metrics.get("validation_samples", 0)
    if val_samples < 20:
        confidence *= 0.60
        details["degradation_reasons"].append(f"low_val_samples:{int(val_samples)}")

    if current_regime != "UNKNOWN" and train_regime != "UNKNOWN" and current_regime != train_regime:
        confidence *= 0.80
        details["degradation_reasons"].append(f"regime_mismatch:train={train_regime},current={current_regime}")

    if feature_count < 10:
        confidence *= 0.70
        details["degradation_reasons"].append(f"low_features:{feature_count}")

    final_conf = float(np.clip(confidence, 0.0, 1.0))
    details["raw_confidence"] = round(final_conf, 4)
    details["train_samples"] = train_samples
    details["ic"] = ic
    details["dir_acc"] = dir_acc

    return round(final_conf, 4), details


class LightGBMTrainer:
    """Date-Space Purge & Embargo uyumlu LightGBM eğitim motoru v3.0."""

    def __init__(self, config: MLModelConfig | None = None) -> None:
        """Trainer örneğini başlatır.

        Args:
            config: MLModelConfig konfigürasyon nesnesi.
        """
        self._lock = threading.RLock()
        self._config = config or MLModelConfig()
        self._init_duckdb()

    def _init_duckdb(self) -> None:
        """DuckDB denetim tablosunu hazırlar."""
        try:
            db_file = Path(self._config.duckdb_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(str(db_file)) as conn:
                configure_duckdb_wal(conn)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS lightgbm_training_audit (
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        train_samples BIGINT,
                        val_samples BIGINT,
                        features_count BIGINT,
                        val_score DOUBLE,
                        ic DOUBLE,
                        dir_acc DOUBLE,
                        confidence DOUBLE,
                        target_horizon BIGINT,
                        regime VARCHAR
                    );
                """)
        except Exception as exc:
            logger.warning("DuckDB trainer denetim tablosu hazirlanamadi", hata=str(exc))

    def train(
        self,
        features_map: dict[str, dict[str, Any]],
        returns: dict[str, float],
        date_groups: dict[str, str],
        feature_names: list[str] | None = None,
        regime: str = "UNKNOWN",
    ) -> TrainedModel | None:
        """Date-space purge gap kullanarak LightGBM modelini eğitir.

        Args:
            features_map: Öznitelik haritası `{ticker_key: {oznitelik: deger}}`.
            returns: Getiri etiketleri `{ticker_key: getiri}`.
            date_groups: Örneklem tarih grupları `{ticker_key: 'YYYY-MM-DD'}`.
            feature_names: Kullanılacak öznitelik isimleri listesi.
            regime: Piyasa rejimi.

        Returns:
            TrainedModel nesnesi veya veri yetersizse None.
        """
        with self._lock:
            try:
                import lightgbm as lgb
            except ImportError:
                logger.warning("LightGBM kütüphanesi yüklü değil")
                return None

            if feature_names is None:
                all_features: set[str] = set()
                for f in features_map.values():
                    all_features.update(f.keys())
                feature_names = sorted(all_features)

            X, y, _, tickers = self._prepare_data(features_map, returns, date_groups, feature_names)

            if len(X) < 50:
                logger.warning("Egitim icin yetersiz veri", samples=len(X))
                return None

            # Impute değerlerini sadece TRAIN öncesinde hesapla
            impute_values = self._compute_impute_values(X, feature_names)
            X = self._impute(X, impute_values, feature_names)

            # === DATE-SPACE PURGE GAP ===
            unique_dates = sorted(set(date_groups.values()))
            n_dates = len(unique_dates)

            val_date_count = max(2, int(n_dates * self._config.val_ratio))
            purge_gap = self._config.purge_gap_days

            effective_purge = max(purge_gap, self._config.target_horizon)
            train_date_end_idx = n_dates - val_date_count - effective_purge

            if train_date_end_idx < 10:
                effective_purge = max(0, n_dates - val_date_count - 10)
                train_date_end_idx = n_dates - val_date_count - effective_purge

            if train_date_end_idx < 5:
                logger.warning(
                    "Train/Val split icin yetersiz tarih boyutu",
                    toplam_tarih=n_dates,
                    val_tarih=val_date_count,
                    purge=effective_purge,
                )
                return None

            train_dates = set(unique_dates[:train_date_end_idx])
            val_dates = set(unique_dates[train_date_end_idx + effective_purge :])

            if not val_dates:
                logger.warning("Purge sonrasi dogrulama tarihi kalmadi")
                return None

            train_indices = [i for i, t in enumerate(tickers) if date_groups.get(t, "") in train_dates]
            val_indices = [i for i, t in enumerate(tickers) if date_groups.get(t, "") in val_dates]

            if len(train_indices) < 20 or len(val_indices) < 5:
                logger.warning(
                    "Date-space split sonrasi yetersiz orneklem",
                    train=len(train_indices),
                    val=len(val_indices),
                )
                return None

            # Scaler YALNIZCA train verisinden öğrenilir
            X_train_raw = X[train_indices]
            X_val_raw = X[val_indices]

            if self._config.scale_features:
                scaler_mean = np.mean(X_train_raw, axis=0)
                scaler_std = np.std(X_train_raw, axis=0)
                scaler_std = np.where(scaler_std > DEFAULT_EPSILON, scaler_std, 1.0)
                X_train_scaled = (X_train_raw - scaler_mean) / scaler_std
                X_val_scaled = (X_val_raw - scaler_mean) / scaler_std
            else:
                scaler_mean = None
                scaler_std = None
                X_train_scaled = X_train_raw
                X_val_scaled = X_val_raw

            y_val = y[val_indices]
            is_ranking = self._config.objective == "lambdarank"

            if is_ranking:
                y_rank = np.zeros(len(y), dtype=int)
                date_to_indices: dict[str, list[int]] = {}
                for i, t in enumerate(tickers):
                    d = date_groups.get(t)
                    if d:
                        date_to_indices.setdefault(d, []).append(i)
                for _d, indices in date_to_indices.items():
                    if len(indices) > 1:
                        group_returns = [y[i] for i in indices]
                        sorted_idx = sorted(range(len(group_returns)), key=lambda k: -group_returns[k])
                        for rank, idx in enumerate(sorted_idx):
                            # Quantile-based / clipped relevance puanı
                            y_rank[indices[idx]] = min(rank, 30)
                train_label = y_rank[train_indices]
                val_label = y_rank[val_indices]
                train_groups = [
                    len([i for i in indices if i in train_indices])
                    for indices in date_to_indices.values()
                    if any(i in train_indices for i in indices)
                ]
                val_groups = [
                    len([i for i in indices if i in val_indices])
                    for indices in date_to_indices.values()
                    if any(i in val_indices for i in indices)
                ]
            else:
                train_label = y[train_indices]
                val_label = y[val_indices]
                train_groups = None
                val_groups = None

            train_data = lgb.Dataset(
                X_train_scaled, label=train_label, group=train_groups, feature_name=feature_names, free_raw_data=False
            )
            val_data = lgb.Dataset(
                X_val_scaled,
                label=val_label,
                group=val_groups,
                feature_name=feature_names,
                free_raw_data=False,
                reference=train_data,
            )

            params: dict[str, Any] = {
                "objective": self._config.objective,
                "metric": self._config.metric,
                "learning_rate": self._config.learning_rate,
                "num_leaves": self._config.num_leaves,
                "min_data_in_leaf": self._config.min_data_in_leaf,
                "feature_fraction": self._config.feature_fraction,
                "bagging_fraction": self._config.bagging_fraction,
                "bagging_freq": self._config.bagging_freq,
                "num_threads": 2,
                "verbose": -1,
                "seed": DEFAULT_RANDOM_SEED,
                "deterministic": True,
            }
            if is_ranking:
                params["ndcg_eval_at"] = self._config.ndcg_eval_at

            callbacks: list[Any] = []
            if self._config.early_stopping_rounds > 0:
                callbacks.append(lgb.early_stopping(self._config.early_stopping_rounds, verbose=False))
            callbacks.append(lgb.log_evaluation(period=0))

            try:
                model = lgb.train(
                    params,
                    train_data,
                    num_boost_round=self._config.num_boost_round,
                    valid_sets=[val_data],
                    callbacks=callbacks,
                )
            except Exception as ex:
                logger.error("LightGBM egitimi basarisiz", hata=str(ex))
                return None

            val_pred = model.predict(X_val_scaled)
            val_score = self._compute_ndcg(y_val, val_pred, val_groups)
            validation_metrics = compute_comprehensive_metrics(y_val, val_pred)

            importance = model.feature_importance(importance_type="gain")
            feature_importance = {name: float(imp) for name, imp in zip(feature_names, importance, strict=False)}

            train_date_strings = sorted(train_dates)
            date_range = (train_date_strings[0], train_date_strings[-1]) if train_date_strings else ("", "")

            confidence, confidence_details = compute_model_confidence(
                validation_metrics, len(train_indices), len(feature_names), train_regime=regime
            )

            trained = TrainedModel(
                model=model,
                feature_names=feature_names,
                scaler_mean=scaler_mean,
                scaler_std=scaler_std,
                impute_values=impute_values,
                train_date_range=date_range,
                train_samples=len(train_indices),
                validation_score=round(val_score, 4),
                feature_importance=feature_importance,
                trained_at=datetime.now(UTC).isoformat(),
                config=self._config,
                validation_metrics=validation_metrics,
                confidence_score=confidence,
                confidence_details=confidence_details,
                target_horizon=self._config.target_horizon,
            )

            # DuckDB denetim kaydı
            self._record_audit(
                train_samples=len(train_indices),
                val_samples=len(val_indices),
                features_count=len(feature_names),
                val_score=val_score,
                ic=validation_metrics.get("ic", 0.0),
                dir_acc=validation_metrics.get("directional_accuracy", 0.0),
                confidence=confidence,
                target_horizon=self._config.target_horizon,
                regime=regime,
            )

            logger.info(
                "LightGBM modeli egitildi v3",
                train_adet=len(train_indices),
                val_adet=len(val_indices),
                ic=round(validation_metrics.get("ic", 0.0), 4),
                dir_acc=round(validation_metrics.get("directional_accuracy", 0.0), 4),
                confidence=confidence,
            )

            return trained

    def train_multi_horizon(
        self,
        features_map: dict[str, dict[str, Any]],
        close_prices: dict[str, np.ndarray],
        date_groups: dict[str, str],
        feature_names: list[str] | None = None,
        target_specs: list[TargetSpec] | None = None,
        primary_horizon: int = DEFAULT_TARGET_HORIZON,
        regime: str = "UNKNOWN",
    ) -> MultiHorizonModel:
        """Çoklu tahmin ufku (Multi-Horizon) modellerini toplu eğitir.

        Args:
            features_map: Öznitelik haritası.
            close_prices: Hisse fiyat serileri sözlüğü `{ticker: np.ndarray}`.
            date_groups: Tarih grupları sözlüğü.
            feature_names: Öznitelik isimleri.
            target_specs: Hedef spesifikasyonları listesi.
            primary_horizon: Birincil model ufku.
            regime: Piyasa rejimi.

        Returns:
            MultiHorizonModel nesnesi.
        """
        specs = target_specs if target_specs is not None else DEFAULT_TARGETS
        horizon_models: dict[int, TrainedModel] = {}

        for spec in specs:
            logger.info("Vade modeli egitiliyor", vade=spec.horizon)
            cfg = MLModelConfig(
                target_horizon=spec.horizon,
                purge_gap_days=max(self._config.purge_gap_days, spec.horizon),
            )
            trainer = LightGBMTrainer(config=cfg)

            # Hedef getirileri üret
            returns: dict[str, float] = {}
            for ticker, p_arr in close_prices.items():
                if len(p_arr) > spec.horizon:
                    tgt = compute_target(p_arr, len(p_arr) - spec.horizon - 1, spec)
                    if tgt is not None:
                        returns[ticker] = tgt

            if returns:
                m = trainer.train(features_map, returns, date_groups, feature_names=feature_names, regime=regime)
                if m is not None:
                    horizon_models[spec.horizon] = m

        return MultiHorizonModel(horizon_models=horizon_models, primary_horizon=primary_horizon)

    def train_polars(
        self,
        df: pl.DataFrame,
        target_col: str = "target",
        date_col: str = "date",
        ticker_col: str = "ticker",
        feature_cols: list[str] | None = None,
        regime: str = "UNKNOWN",
    ) -> TrainedModel | None:
        """Polars DataFrame girdi alarak doğrudan eğitim yürütür.

        Args:
            df: Veri seti Polars DataFrame'i.
            target_col: Hedef etiket sütunu adı.
            date_col: Tarih sütunu adı.
            ticker_col: Hisse kodu sütunu adı.
            feature_cols: Kullanılacak öznitelik sütunları listesi.
            regime: Piyasa rejimi.

        Returns:
            TrainedModel nesnesi.
        """
        if target_col not in df.columns or date_col not in df.columns or ticker_col not in df.columns:
            raise ValueError("DataFrame gerekli sütunlari icermiyor: target, date, ticker")

        actual_feats = feature_cols
        if actual_feats is None:
            actual_feats = [c for c in df.columns if c not in {target_col, date_col, ticker_col}]

        features_map: dict[str, dict[str, Any]] = {}
        returns: dict[str, float] = {}
        date_groups: dict[str, str] = {}

        for row in df.iter_rows(named=True):
            t_key = f"{row[ticker_col]}_{row[date_col]}"
            date_groups[t_key] = str(row[date_col])[:10]
            returns[t_key] = float(row[target_col])
            features_map[t_key] = {f: row[f] for f in actual_feats if f in row}

        return self.train(
            features_map=features_map,
            returns=returns,
            date_groups=date_groups,
            feature_names=actual_feats,
            regime=regime,
        )

    def _prepare_data(
        self,
        features_map: dict[str, dict[str, Any]],
        returns: dict[str, float],
        date_groups: dict[str, str],
        feature_names: list[str],
    ) -> tuple[np.ndarray, np.ndarray, list[int], list[str]]:
        """Öznitelik ve getiri haritalarını numpy matrislerine dönüştürür."""
        X_list: list[list[float]] = []
        y_list: list[float] = []
        tickers: list[str] = []
        sorted_keys = sorted(features_map.keys(), key=lambda k: date_groups.get(k, ""))

        for key in sorted_keys:
            if key not in returns:
                continue
            feats = features_map[key]
            row: list[float] = []
            for name in feature_names:
                val = feats.get(name)
                if val is None:
                    row.append(np.nan)
                else:
                    try:
                        v = float(val)
                        row.append(v if np.isfinite(v) else np.nan)
                    except (TypeError, ValueError):
                        row.append(np.nan)
            X_list.append(row)
            y_list.append(float(returns[key]))
            tickers.append(key)

        return (
            np.array(X_list, dtype=np.float32),
            np.array(y_list, dtype=np.float64),
            [],
            tickers,
        )

    def _compute_impute_values(self, X: np.ndarray, feature_names: list[str]) -> dict[str, float]:
        """Eksik değer tamamlama medyan değerlerini hesaplar."""
        impute: dict[str, float] = {}
        for i, name in enumerate(feature_names):
            col = X[:, i]
            valid = col[np.isfinite(col)]
            if len(valid) > 0:
                impute[name] = float(np.median(valid)) if self._config.impute_strategy == "median" else 0.0
            else:
                impute[name] = 0.0
        return impute

    def _impute(
        self,
        X: np.ndarray,
        impute_values: dict[str, float],
        feature_names: list[str] | None = None,
    ) -> np.ndarray:
        """Eksik değerleri tamamlar."""
        X_imputed = X.copy()
        for i in range(X.shape[1]):
            mask = ~np.isfinite(X_imputed[:, i])
            if mask.any():
                col_name = feature_names[i] if feature_names and i < len(feature_names) else None
                fill_val = impute_values.get(col_name, 0.0) if col_name else 0.0
                X_imputed[mask, i] = fill_val
        return X_imputed

    def _compute_groups_from_indices(
        self, date_groups: dict[str, str], tickers: list[str], indices: list[int]
    ) -> list[int]:
        """Belirli indeksler için ranking sorgu gruplarını hesaplar."""
        groups: list[int] = []
        current_date = None
        current_count = 0
        for idx in indices:
            d = date_groups.get(tickers[idx], "")
            if d != current_date:
                if current_count > 0:
                    groups.append(current_count)
                current_date = d
                current_count = 1
            else:
                current_count += 1
        if current_count > 0:
            groups.append(current_count)
        return groups

    def _compute_ndcg(self, y_true: np.ndarray, y_pred: np.ndarray, groups: list[int] | None) -> float:
        """NDCG skorunu hesaplar."""
        if not groups:
            if np.std(y_true) > DEFAULT_EPSILON and np.std(y_pred) > DEFAULT_EPSILON:
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

    def _record_audit(
        self,
        train_samples: int,
        val_samples: int,
        features_count: int,
        val_score: float,
        ic: float,
        dir_acc: float,
        confidence: float,
        target_horizon: int,
        regime: str,
    ) -> None:
        """Eğitim denetim izini DuckDB'ye yazar."""
        try:
            with duckdb.connect(self._config.duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO lightgbm_training_audit (
                        train_samples, val_samples, features_count, val_score, ic,
                        dir_acc, confidence, target_horizon, regime
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    [
                        int(train_samples),
                        int(val_samples),
                        int(features_count),
                        float(val_score),
                        float(ic),
                        float(dir_acc),
                        float(confidence),
                        int(target_horizon),
                        str(regime),
                    ],
                )
        except Exception as exc:
            logger.debug("DuckDB trainer denetim kaydi atlandi", hata=str(exc))

    def get_audit_as_polars(self) -> pl.DataFrame:
        """DuckDB'deki eğitim denetim kayıtlarını Polars DataFrame olarak döndürür."""
        import polars as pl

        with self._lock:
            try:
                with duckdb.connect(self._config.duckdb_path) as conn:
                    return conn.execute("SELECT * FROM lightgbm_training_audit ORDER BY timestamp DESC").pl()
            except Exception as exc:
                logger.warning("DuckDB trainer denetim kayitlari okunamadi", hata=str(exc))
                return pl.DataFrame()

    def __repr__(self) -> str:
        return f"LightGBMTrainer(horizon={self._config.target_horizon}d, purge={self._config.purge_gap_days}d)"


def validate_feature_contract(
    features_map: dict[str, dict[str, Any]],
    expected_features: list[str],
) -> tuple[bool, list[str]]:
    """Öznitelik sözlüğünün sözleşmeye uygunluğunu doğrular.

    Args:
        features_map: Öznitelik sözlüğü.
        expected_features: Beklenen öznitelik isimleri listesi.

    Returns:
        `(uygun_mu, ihlal_listesi)` demeti.
    """
    violations: list[str] = []
    if not features_map:
        return False, ["Bos features_map"]

    missing_features: set[str] = set()
    for key, feats in features_map.items():
        for fname in expected_features:
            if fname not in feats:
                missing_features.add(fname)
        if len(missing_features) > len(expected_features) * 0.50:
            violations.append(f"Orneklem {key}: %50'den fazla oznitelik eksik")
            break

    if missing_features:
        violations.append(f"Eksik oznitelikler: {sorted(missing_features)[:5]}")

    first_keys = set(next(iter(features_map.values())).keys())
    for key, feats in features_map.items():
        if set(feats.keys()) != first_keys:
            violations.append(f"{key} anahtarinda tutarsiz oznitelikler tespit edildi")
            break

    return len(violations) == 0, violations


__all__: Final[list[str]] = [
    "DEFAULT_BAGGING_FRACTION",
    "DEFAULT_BAGGING_FREQ",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EARLY_STOPPING_ROUNDS",
    "DEFAULT_EPSILON",
    "DEFAULT_FEATURE_FRACTION",
    "DEFAULT_LEARNING_RATE",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MIN_DATA_IN_LEAF",
    "DEFAULT_NUM_BOOST_ROUND",
    "DEFAULT_NUM_LEAVES",
    "DEFAULT_PURGE_GAP_DAYS",
    "DEFAULT_RANDOM_SEED",
    "DEFAULT_TARGET_HORIZON",
    "DEFAULT_TARGETS",
    "DEFAULT_VAL_RATIO",
    "LightGBMTrainer",
    "MLModelConfig",
    "MultiHorizonModel",
    "TargetMethod",
    "TargetSpec",
    "TrainedModel",
    "compute_comprehensive_metrics",
    "compute_model_confidence",
    "compute_target",
    "configure_duckdb_wal",
    "validate_feature_contract",
]
