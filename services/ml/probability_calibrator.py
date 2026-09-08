"""ALPHA BIST — Olasılık Kalibrasyon Motoru (Nihai — ⭐⭐⭐⭐⭐).

Bu modül; sınıflandırıcı modellerin (CatBoost, XGBoost, LightGBM) ham güven skorlarını
gerçek ampirik olasılıklara dönüştürür. Platt Scaling (Lojistik Regresyon / Sigmoid) ve
İzotonik Regresyon (Isotonic Regression) yöntemlerini destekler. Brier Skoru ve ECE (Expected
Calibration Error) metrikleriyle kalibrasyon doğruluğunu ölçer ve DuckDB üzerinde denetim izi tutar.

Temel Yetenekler:
- Platt Scaling (Sigmoid L-BFGS) ve Monotonik İzotonik Regresyon (Isotonic Regression)
- Beklenen Kalibrasyon Hatası (Expected Calibration Error - ECE) ve Brier Skoru Analizi
- İkili Etiket Normalizasyonu ({-1, 1} -> {0, 1}) ve Uç Değer Koruma Mekanizmaları (Fail-Closed)
- [0, 1] Dışı Ham Marj Skorları için Güvenli Lojistik Sigmoid Dönüşümü (Uç Olasılık Bozulma Koruması)
- Polars DataFrame Tabanlı Doğrudan Vektörize Kalibrasyon Desteği (`fit_polars`, `calibrate_polars`)
- Tekil Hızlı Skor Kalibrasyonu (`calibrate_scalar`)
- DuckDB SSD Korumalı WAL ile Kalibrasyon Denetim İzi (Audit Trail)
- İş Parçacığı Güvenliği (`threading.RLock`) ve Kesin Tip Belirteçleri
"""

from __future__ import annotations

import threading
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
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss

logger = structlog.get_logger(__name__)

# --- Sabitler ---
DEFAULT_N_BINS: Final[int] = 10
DEFAULT_EPSILON: Final[float] = 1e-6
DEFAULT_DUCKDB_PATH: Final[str] = "data/probability_calibrator.duckdb"
DEFAULT_PROB_CLIP_MIN: Final[float] = 1e-4
DEFAULT_PROB_CLIP_MAX: Final[float] = 1.0 - 1e-4
DEFAULT_NEUTRAL_PROB: Final[float] = 0.5
DEFAULT_MAX_ITER: Final[int] = 1000
DEFAULT_LOGIT_CLIP: Final[float] = 15.0


class CalibrationMethod(StrEnum):
    """Desteklenen olasılık kalibrasyon yöntemleri."""

    SIGMOID = "sigmoid"
    ISOTONIC = "isotonic"


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
class CalibrationMetrics:
    """Kalibrasyon başarı ve hata metrikleri veri modeli."""

    method: str
    raw_brier: float
    calibrated_brier: float
    raw_ece: float
    calibrated_ece: float
    ece_improvement_pct: float
    sample_count: int

    def to_dict(self) -> dict[str, Any]:
        """Metrik verisini standart sözlük yapısına dönüştürür."""
        return asdict(self)

    def to_orjson_bytes(self) -> bytes:
        """Metrik verisini orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CalibrationMetrics:
        """Sözlükten CalibrationMetrics nesnesi oluşturur."""
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def __repr__(self) -> str:
        """Metrik nesnesinin özet metin gösterimini oluşturur."""
        return (
            f"CalibrationMetrics(method='{self.method}', "
            f"raw_brier={self.raw_brier:.4f} -> cal_brier={self.calibrated_brier:.4f}, "
            f"raw_ece={self.raw_ece:.4f} -> cal_ece={self.calibrated_ece:.4f}, "
            f"improvement={self.ece_improvement_pct:.1f}%)"
        )


def compute_ece(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = DEFAULT_N_BINS) -> float:
    """Beklenen Kalibrasyon Hatasını (Expected Calibration Error - ECE) hesaplar.

    Olasılıkları [0, 1] aralığında n_bins eşit parçaya böler ve
    tahmin edilen güven skoru ile gerçek pozitif oranı arasındaki farkın
    örneklem ağırlıklı ortalamasını alır.

    Args:
        y_true: Gerçek ikili etiketler dizisi (0 veya 1).
        y_prob: Modelin ürettiği olasılık/güven skorları [0, 1].
        n_bins: Olasılık bölme (bin) sayısı.

    Returns:
        ECE hata skoru [0.0 - 1.0].
    """
    yt = np.asarray(y_true, dtype=np.float64).flatten()
    yp = np.asarray(y_prob, dtype=np.float64).flatten()

    if len(yt) == 0 or len(yp) == 0 or len(yt) != len(yp):
        return 0.0

    valid_mask = np.isfinite(yt) & np.isfinite(yp)
    if not np.any(valid_mask):
        return 0.0

    # İkili etiket normalizasyonu: { >0 -> 1.0, <=0 -> 0.0 }
    yt = np.where(yt[valid_mask] > 0.0, 1.0, 0.0)
    yp = np.clip(yp[valid_mask], 0.0, 1.0)
    total_samples = len(yp)
    if total_samples == 0:
        return 0.0

    actual_bins = max(2, n_bins)
    bins = np.linspace(0.0, 1.0, actual_bins + 1)
    bin_indices = np.digitize(yp, bins) - 1
    bin_indices = np.clip(bin_indices, 0, actual_bins - 1)

    ece = 0.0
    for i in range(actual_bins):
        mask = bin_indices == i
        bin_count = int(np.sum(mask))
        if bin_count > 0:
            bin_acc = float(np.mean(yt[mask]))
            bin_conf = float(np.mean(yp[mask]))
            ece += (bin_count / total_samples) * abs(bin_acc - bin_conf)

    return float(ece)


class ProbabilityCalibrator:
    """Sınıflandırıcı modellerin ham tahmin skorlarını kalibre eden motor."""

    def __init__(
        self,
        method: str | CalibrationMethod = CalibrationMethod.SIGMOID,
        duckdb_path: str = DEFAULT_DUCKDB_PATH,
    ) -> None:
        """ProbabilityCalibrator bileşenini başlatır.

        Args:
            method: 'sigmoid' (Platt scaling) veya 'isotonic' (İzotonik regresyon).
            duckdb_path: Denetim kayıtlarının yazılacağı DuckDB veritabanı yolu.
        """
        self.method: str = str(method).lower()
        self._duckdb_path: str = duckdb_path
        self._lock: threading.RLock = threading.RLock()
        self.calibrator: Any = None

    def __getstate__(self) -> dict[str, Any]:
        """Pickle serileştirmesinde threading.RLock nesnesini dışlayarak durum döndürür."""
        state = self.__dict__.copy()
        state["_lock"] = None
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Pickle deserializasyonunda threading.RLock nesnesini yeniden ilklendirir."""
        self.__dict__.update(state)
        self._lock = threading.RLock()
        self.is_fitted: bool = False
        self.raw_brier: float = 0.0
        self.calibrated_brier: float = 0.0
        self.raw_ece: float = 0.0
        self.calibrated_ece: float = 0.0
        self.sample_count: int = 0

        self._init_duckdb()

    def _init_duckdb(self) -> None:
        """DuckDB denetim tablosunu güvenle ilklendirir."""
        try:
            db_dir = Path(self._duckdb_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS probability_calibration_audit (
                        timestamp TIMESTAMPTZ NOT NULL,
                        method VARCHAR NOT NULL,
                        sample_count BIGINT NOT NULL,
                        raw_brier DOUBLE NOT NULL,
                        calibrated_brier DOUBLE NOT NULL,
                        raw_ece DOUBLE NOT NULL,
                        calibrated_ece DOUBLE NOT NULL,
                        improvement_pct DOUBLE NOT NULL
                    );
                    """
                )
        except Exception as exc:
            logger.warning("DuckDB kalibrasyon denetim tablosu olusturulamadi", hata=str(exc))

    def _record_audit_event(self, metrics: CalibrationMetrics) -> None:
        """Kalibrasyon sonuçlarını DuckDB denetim tablosuna yazar."""
        try:
            now_iso = datetime.now(UTC).isoformat()
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO probability_calibration_audit
                    (timestamp, method, sample_count, raw_brier, calibrated_brier, raw_ece, calibrated_ece, improvement_pct)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    [
                        now_iso,
                        metrics.method,
                        metrics.sample_count,
                        metrics.raw_brier,
                        metrics.calibrated_brier,
                        metrics.raw_ece,
                        metrics.calibrated_ece,
                        metrics.ece_improvement_pct,
                    ],
                )
        except Exception as exc:
            logger.warning("DuckDB kalibrasyon denetim kaydi basarisiz", hata=str(exc))

    def fit(self, y_raw_scores: np.ndarray, y_true: np.ndarray) -> ProbabilityCalibrator:
        """Kalibratörü eğitir, Brier skoru ve ECE iyileşmesini kaydeder.

        Args:
            y_raw_scores: Modelin ürettiği ham tahmin olasılıkları veya lojit dizisi.
            y_true: Gerçek ikili etiketler dizisi (0/1 veya -1/+1).

        Returns:
            Eğitilmiş ProbabilityCalibrator nesnesi.

        Raises:
            ValueError: Giriş dizileri boş, boyutları uyumsuz veya geçersiz veri durumunda.
        """
        with self._lock:
            # Tip güvenli ve None/null korumalı NumPy dizisine çevir
            y_raw = np.asarray(y_raw_scores, dtype=np.float64).flatten()
            y_raw_labels = np.asarray(y_true, dtype=np.float64).flatten()

            if len(y_raw) == 0 or len(y_raw_labels) == 0:
                raise ValueError("Giris dizileri bos olamaz.")
            if len(y_raw) != len(y_raw_labels):
                raise ValueError(f"Dizi boyutlari uyumsuz: y_raw={len(y_raw)}, y_true={len(y_raw_labels)}")

            # NaN / Inf ve None filtreleme
            valid_mask = np.isfinite(y_raw) & np.isfinite(y_raw_labels)
            if not np.any(valid_mask):
                raise ValueError("Gecerli sonlu sayisal veri bulunamadi.")

            y_raw = y_raw[valid_mask]
            # Kesin ikili {0, 1} etiket normalizasyonu (-1 / +1 veya float etiketleri çözer)
            y_label = np.where(y_raw_labels[valid_mask] > 0.0, 1, 0).astype(np.int32)
            self.sample_count = len(y_raw)

            # Ham skorları [0, 1] aralığına normalize et
            if np.min(y_raw) < 0.0 or np.max(y_raw) > 1.0:
                # Marj/Lojit formatındaki ham skorlar için lojistik haritalama
                clipped_logits = np.clip(y_raw, -DEFAULT_LOGIT_CLIP, DEFAULT_LOGIT_CLIP)
                y_raw_prob = 1.0 / (1.0 + np.exp(-clipped_logits))
            else:
                y_raw_prob = np.clip(y_raw, DEFAULT_PROB_CLIP_MIN, DEFAULT_PROB_CLIP_MAX)

            self.raw_brier = float(brier_score_loss(y_label, y_raw_prob))
            self.raw_ece = compute_ece(y_label, y_raw_prob)

            unique_labels = np.unique(y_label)
            if len(unique_labels) < 2:
                logger.warning("Veri setinde tek sinif tespit edildi, kalibrator bypass moduna alindi")
                self.calibrator = None
                self.is_fitted = True
                self.calibrated_brier = self.raw_brier
                self.calibrated_ece = self.raw_ece
                return self

            if self.method == CalibrationMethod.SIGMOID.value:
                lr = LogisticRegression(C=1.0, solver="lbfgs", max_iter=DEFAULT_MAX_ITER)
                X = y_raw.reshape(-1, 1)
                lr.fit(X, y_label)
                self.calibrator = lr
            elif self.method == CalibrationMethod.ISOTONIC.value:
                iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
                iso.fit(y_raw, y_label)
                self.calibrator = iso
            else:
                raise ValueError(f"Bilinmeyen kalibrasyon yontemi: {self.method}")

            self.is_fitted = True

            # Kalibre edilmiş metrikler
            y_cal_prob = self.calibrate(y_raw)
            self.calibrated_brier = float(brier_score_loss(y_label, y_cal_prob))
            self.calibrated_ece = compute_ece(y_label, y_cal_prob)

            # Sıfır bölme korumalı ECE iyileşme yüzdesi
            if self.raw_ece <= DEFAULT_EPSILON:
                ece_improvement = 0.0
            else:
                ece_improvement = (1.0 - (self.calibrated_ece / self.raw_ece)) * 100.0

            metrics = CalibrationMetrics(
                method=self.method,
                raw_brier=round(self.raw_brier, 4),
                calibrated_brier=round(self.calibrated_brier, 4),
                raw_ece=round(self.raw_ece, 4),
                calibrated_ece=round(self.calibrated_ece, 4),
                ece_improvement_pct=round(ece_improvement, 1),
                sample_count=self.sample_count,
            )

            self._record_audit_event(metrics)

            logger.info(
                "Olasilik kalibratoru basariyla egitildi",
                method=self.method,
                raw_brier=metrics.raw_brier,
                calibrated_brier=metrics.calibrated_brier,
                raw_ece=metrics.raw_ece,
                calibrated_ece=metrics.calibrated_ece,
                ece_improvement_pct=metrics.ece_improvement_pct,
            )

            return self

    def fit_polars(self, df: pl.DataFrame, score_col: str, label_col: str) -> ProbabilityCalibrator:
        """Polars DataFrame girdi kullanarak kalibratörü eğitir.

        Null ve eksik satırları Polars seviyesinde çift yönlü temizler.

        Args:
            df: Veri çerçevesi.
            score_col: Model ham tahmin skoru sütun adı.
            label_col: Gerçek ikili etiket sütun adı.

        Returns:
            Eğitilmiş ProbabilityCalibrator nesnesi.
        """
        clean_df = df.select([score_col, label_col]).drop_nulls()
        if clean_df.height == 0:
            raise ValueError("Polars veri cercevesinde gecerli (null olmayan) satir bulunamadi.")

        scores = clean_df[score_col].to_numpy()
        labels = clean_df[label_col].to_numpy()
        return self.fit(scores, labels)

    def calibrate(self, y_raw_scores: np.ndarray) -> np.ndarray:
        """Ham model skorlarını kalibre edilmiş güven/olasılık değerine çevirir.

        Args:
            y_raw_scores: Ham tahmin dizisi.

        Returns:
            [0.0, 1.0] aralığında kalibre edilmiş olasılıklar dizisi.
        """
        with self._lock:
            y_raw = np.asarray(y_raw_scores, dtype=np.float64).flatten()
            if len(y_raw) == 0:
                return np.array([], dtype=np.float64)

            # Polars null veya NaN/Inf taşmalarına karşı maskeleme
            finite_mask = np.isfinite(y_raw)
            clean_raw = np.where(finite_mask, y_raw, DEFAULT_NEUTRAL_PROB)

            # Eğitilmemiş veya bypass modunda güvenli dönüşüm
            if not self.is_fitted or self.calibrator is None:
                if np.min(clean_raw) < 0.0 or np.max(clean_raw) > 1.0:
                    clipped_logits = np.clip(clean_raw, -DEFAULT_LOGIT_CLIP, DEFAULT_LOGIT_CLIP)
                    raw_mapped = 1.0 / (1.0 + np.exp(-clipped_logits))
                else:
                    raw_mapped = np.clip(clean_raw, 0.0, 1.0)
                return np.where(finite_mask, raw_mapped, DEFAULT_NEUTRAL_PROB)

            if self.method == CalibrationMethod.SIGMOID.value:
                # Sınıf kontrolü korumalı predict_proba
                if hasattr(self.calibrator, "classes_") and len(self.calibrator.classes_) > 1:
                    probs = self.calibrator.predict_proba(clean_raw.reshape(-1, 1))[:, 1]
                else:
                    probs = np.full_like(clean_raw, DEFAULT_NEUTRAL_PROB)
            else:
                probs = self.calibrator.predict(clean_raw)

            result = np.clip(probs, 0.0, 1.0)
            if not np.all(finite_mask):
                result = np.where(finite_mask, result, DEFAULT_NEUTRAL_PROB)
            return result

    def calibrate_scalar(self, score: float) -> float:
        """Tekil bir ham model skorunu hızlıca kalibre eder.

        Args:
            score: Ham tahmin skoru veya lojit.

        Returns:
            [0.0, 1.0] aralığında kalibre edilmiş olasılık.
        """
        if not np.isfinite(score):
            return DEFAULT_NEUTRAL_PROB
        arr = np.array([score], dtype=np.float64)
        return float(self.calibrate(arr)[0])

    def calibrate_polars(self, df: pl.DataFrame, score_col: str, output_col: str = "calibrated_score") -> pl.DataFrame:
        """Polars DataFrame içindeki ham skor sütununu kalibre ederek yeni sütun ekler.

        Orijinalde null/None olan satırlar kesin nötr olasılık (DEFAULT_NEUTRAL_PROB = 0.5) olarak atanır.

        Args:
            df: Girdi veri çerçevesi.
            score_col: Ham skor sütunu.
            output_col: Kalibre edilmiş değerlerin ekleneceği yeni sütun adı.

        Returns:
            Yeni sütun eklenmiş Polars DataFrame.
        """
        # Orijinal null maskesini tespit et
        is_null_mask = df[score_col].is_null().to_numpy()
        clean_series = df[score_col].fill_null(DEFAULT_NEUTRAL_PROB)
        scores = clean_series.to_numpy()
        calibrated = self.calibrate(scores)

        # Orijinalde eksik/null olan satırları model ağırlıklarından bağımsız kesin nötr olasılığa çek
        if np.any(is_null_mask):
            calibrated = np.where(is_null_mask, DEFAULT_NEUTRAL_PROB, calibrated)

        return df.with_columns(pl.Series(name=output_col, values=calibrated))

    def get_metrics(self) -> dict[str, float | str | int]:
        """Kalibrasyon metriklerini sözlük olarak döndürür."""
        with self._lock:
            return {
                "method": self.method,
                "raw_brier": round(self.raw_brier, 4),
                "calibrated_brier": round(self.calibrated_brier, 4),
                "raw_ece": round(self.raw_ece, 4),
                "calibrated_ece": round(self.calibrated_ece, 4),
                "sample_count": self.sample_count,
            }

    def get_metrics_object(self) -> CalibrationMetrics:
        """Kalibrasyon metriklerini nesne olarak döndürür."""
        with self._lock:
            if self.raw_ece <= DEFAULT_EPSILON:
                improvement = 0.0
            else:
                improvement = (1.0 - (self.calibrated_ece / self.raw_ece)) * 100.0
            return CalibrationMetrics(
                method=self.method,
                raw_brier=round(self.raw_brier, 4),
                calibrated_brier=round(self.calibrated_brier, 4),
                raw_ece=round(self.raw_ece, 4),
                calibrated_ece=round(self.calibrated_ece, 4),
                ece_improvement_pct=round(improvement, 1),
                sample_count=self.sample_count,
            )

    def __repr__(self) -> str:
        """ProbabilityCalibrator özet metin gösterimini oluşturur."""
        with self._lock:
            return (
                f"ProbabilityCalibrator(method='{self.method}', is_fitted={self.is_fitted}, "
                f"cal_brier={self.calibrated_brier:.4f}, cal_ece={self.calibrated_ece:.4f})"
            )


probability_calibrator: Final[ProbabilityCalibrator] = ProbabilityCalibrator()

__all__: Final[list[str]] = [
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EPSILON",
    "DEFAULT_LOGIT_CLIP",
    "DEFAULT_MAX_ITER",
    "DEFAULT_NEUTRAL_PROB",
    "DEFAULT_N_BINS",
    "DEFAULT_PROB_CLIP_MAX",
    "DEFAULT_PROB_CLIP_MIN",
    "CalibrationMethod",
    "CalibrationMetrics",
    "ProbabilityCalibrator",
    "compute_ece",
    "configure_duckdb_wal",
    "probability_calibrator",
]
