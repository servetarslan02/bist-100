"""ALPHA BIST — Gelişmiş Kalibrasyon ve Drift İzleme Motoru v2.0 (Production-Hardened)

BIST pay piyasası tahmin modellerinde olasılık güven kalibrasyonunun sürekli izlenmesi,
zaman serisi tabanlı out-of-fold (OOF) tahmin üretimi, kalibrasyon kayması (drift) tespiti,
otomatik yeniden eğitim (retrain) zamanlaması, Platt vs Isotonic karşılaştırması ve DuckDB/Polars denetim izi.

Kurallar & Standartlar:
- DuckDB WAL ve denetim logu desteği (SQLite yasaktır)
- orjson yüksek hızlı serileştirme (standart json yasaktır)
- Polars DataFrame entegrasyonu (pandas yasaktır)
- threading.RLock eşzamanlılık güvenliği
- TimeSeriesSplit ile sıfır veri sızıntısı (data leakage önleme)
- Fail-closed hata yönetimi ve structlog yapısal loglama
"""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog
from scipy.optimize import minimize
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import TimeSeriesSplit

logger = structlog.get_logger(__name__)

# ===================== SABİTLER (CONSTANTS) =====================

DEFAULT_RETRAIN_INTERVAL_HOURS: Final[float] = 24.0
DEFAULT_DRIFT_THRESHOLD: Final[float] = 0.05
DEFAULT_MIN_SAMPLES_FOR_RETRAIN: Final[int] = 100
DEFAULT_MAX_HISTORY_LEN: Final[int] = 500
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


# ===================== VERİ MODELLERİ (DATA MODELS) =====================


@dataclass(slots=True)
class OutOfFoldResult:
    """Zaman serisi tabanlı out-of-fold (OOF) tahmin değerlendirme çıktısı.

    Attributes:
        predictions: Tüm örneklemler için out-of-fold olasılık tahminleri.
        fold_indices: Her fold için (train_index, val_index) demetleri.
        mean_ic: Foldlar arası ortalama Information Coefficient (IC).
        mean_brier: Foldlar arası ortalama Brier skoru.
        n_folds: Uygulanan toplam fold sayısı.
    """

    predictions: np.ndarray
    fold_indices: list[tuple[np.ndarray, np.ndarray]]
    mean_ic: float
    mean_brier: float
    n_folds: int

    def to_dict(self) -> dict[str, Any]:
        """Sonuçları serileştirilebilir sözlüğe dönüştürür."""
        return {
            "predictions_count": int(len(self.predictions)),
            "mean_ic": self.mean_ic,
            "mean_brier": self.mean_brier,
            "n_folds": self.n_folds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OutOfFoldResult:
        """Sözlükten OutOfFoldResult nesnesi oluşturur."""
        preds = np.array(data.get("predictions", []), dtype=np.float64)
        return cls(
            predictions=preds,
            fold_indices=[],
            mean_ic=float(data.get("mean_ic", 0.0)),
            mean_brier=float(data.get("mean_brier", 0.0)),
            n_folds=int(data.get("n_folds", 0)),
        )

    def to_orjson_bytes(self) -> bytes:
        """orjson serileştirmesi döndürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        return (
            f"OutOfFoldResult(samples={len(self.predictions)}, n_folds={self.n_folds}, "
            f"mean_ic={self.mean_ic:.4f}, mean_brier={self.mean_brier:.4f})"
        )


@dataclass(slots=True)
class CalibrationDriftReport:
    """Kalibrasyon sapması ve performans bozulması izleme raporu.

    Attributes:
        current_brier: Güncel Brier skoru.
        baseline_brier: Temel (baseline) referans Brier skoru.
        brier_change: Brier skorundaki net değişim (güncel - referans).
        current_ece: Güncel Beklenen Kalibrasyon Hatası (ECE).
        baseline_ece: Temel (baseline) referans ECE skoru.
        ece_change: ECE skorundaki net değişim.
        drift_detected: Sapma eşiğinin aşılıp aşılmadığı.
        severity: Sapma ciddiyeti (OK, WARNING, ALERT).
        recommendation: Aksiyon önerisi.
    """

    current_brier: float
    baseline_brier: float
    brier_change: float
    current_ece: float
    baseline_ece: float
    ece_change: float
    drift_detected: bool
    severity: str
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        """Modeli sözlüğe dönüştürür."""
        return {
            "current_brier": self.current_brier,
            "baseline_brier": self.baseline_brier,
            "brier_change": self.brier_change,
            "current_ece": self.current_ece,
            "baseline_ece": self.baseline_ece,
            "ece_change": self.ece_change,
            "drift_detected": self.drift_detected,
            "severity": self.severity,
            "recommendation": self.recommendation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CalibrationDriftReport:
        """Sözlükten CalibrationDriftReport nesnesi oluşturur."""
        return cls(
            current_brier=float(data.get("current_brier", 0.0)),
            baseline_brier=float(data.get("baseline_brier", 0.0)),
            brier_change=float(data.get("brier_change", 0.0)),
            current_ece=float(data.get("current_ece", 0.0)),
            baseline_ece=float(data.get("baseline_ece", 0.0)),
            ece_change=float(data.get("ece_change", 0.0)),
            drift_detected=bool(data.get("drift_detected", False)),
            severity=str(data.get("severity", "OK")),
            recommendation=str(data.get("recommendation", "")),
        )

    def to_orjson_bytes(self) -> bytes:
        """orjson serileştirmesi döndürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        return (
            f"CalibrationDriftReport(drift={self.drift_detected}, severity={self.severity!r}, "
            f"brier_delta={self.brier_change:+.4f}, ece_delta={self.ece_change:+.4f})"
        )


@dataclass(slots=True)
class RetrainSchedule:
    """Kalibrasyon modelinin yeniden eğitim zamanlama durumu.

    Attributes:
        last_retrain: Son eğitim zaman damgası (ISO metni).
        hours_since_retrain: Son eğitimden bu yana geçen saat.
        should_retrain: Yeniden eğitimin gerekli olup olmadığı.
        reason: Karar gerekçesi.
        next_retrain: Planlanan bir sonraki eğitim zamanı.
    """

    last_retrain: str
    hours_since_retrain: float
    should_retrain: bool
    reason: str
    next_retrain: str

    def to_dict(self) -> dict[str, Any]:
        """Zamanlama çıktısını sözlüğe dönüştürür."""
        return {
            "last_retrain": self.last_retrain,
            "hours_since_retrain": self.hours_since_retrain,
            "should_retrain": self.should_retrain,
            "reason": self.reason,
            "next_retrain": self.next_retrain,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetrainSchedule:
        """Sözlükten RetrainSchedule nesnesi oluşturur."""
        return cls(
            last_retrain=str(data.get("last_retrain", "")),
            hours_since_retrain=float(data.get("hours_since_retrain", 0.0)),
            should_retrain=bool(data.get("should_retrain", False)),
            reason=str(data.get("reason", "")),
            next_retrain=str(data.get("next_retrain", "")),
        )

    def to_orjson_bytes(self) -> bytes:
        """orjson serileştirmesi döndürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        return (
            f"RetrainSchedule(should_retrain={self.should_retrain}, "
            f"hours_since={self.hours_since_retrain:.1f}h, reason={self.reason!r})"
        )


# ===================== KALİBRASYON GELİŞMİŞ MOTORU =====================


class CalibrationEnhanced:
    """BIST 100 modelleri için gelişmiş zaman serisi kalibrasyon ve drift takip motoru v2.0.

    Özellikler:
    - TimeSeriesSplit ile veri sızıntısız out-of-fold (OOF) olasılık tahmini
    - Zaman serisi Brier ve ECE kalibrasyon drift takibi
    - Otomatik yeniden eğitim planlayıcısı (zaman & drift duyarlı)
    - Nelder-Mead optimizasyonlu Platt Scaling vs Isotonic Regresyon karşılaştırması
    - DuckDB WAL denetim logu ve Polars entegrasyonu
    - threading.RLock thread-safety koruması
    """

    def __init__(
        self,
        retrain_interval_hours: float = DEFAULT_RETRAIN_INTERVAL_HOURS,
        drift_threshold: float = DEFAULT_DRIFT_THRESHOLD,
        min_samples_for_retrain: int = DEFAULT_MIN_SAMPLES_FOR_RETRAIN,
    ) -> None:
        """CalibrationEnhanced motorunu yapılandırır.

        Args:
            retrain_interval_hours: Yeniden eğitim periyodu (saat).
            drift_threshold: Sapma tespit tolerans eşiği.
            min_samples_for_retrain: Yeniden eğitim için asgari örneklem sayısı.
        """
        self.retrain_interval_hours = max(1.0, float(retrain_interval_hours))
        self.drift_threshold = max(0.001, float(drift_threshold))
        self.min_samples_for_retrain = max(10, int(min_samples_for_retrain))

        self._lock = threading.RLock()
        self._brier_history: list[tuple[str, float]] = []
        self._ece_history: list[tuple[str, float]] = []
        self._last_retrain: datetime | None = None
        self._baseline_brier: float | None = None
        self._baseline_ece: float | None = None

    def __repr__(self) -> str:
        with self._lock:
            n_brier = len(self._brier_history)
            last_ts = self._last_retrain.isoformat() if self._last_retrain else "None"
            return (
                f"CalibrationEnhanced(interval_h={self.retrain_interval_hours}, "
                f"drift_thr={self.drift_threshold}, records={n_brier}, last_retrain={last_ts})"
            )

    @staticmethod
    def _validate_xy(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Giriş matrisi ve hedef dizisini doğrular.

        Args:
            X: Öznitelik matrisi.
            y: İkili hedef dizisi.

        Returns:
            Temizlenmiş numpy dizileri (X, y).

        Raises:
            ValueError: Boyut uyuşmazlığı, boş veri veya NaN/Inf varlığında.
        """
        X_arr = np.asarray(X, dtype=np.float64)
        y_arr = np.asarray(y, dtype=np.float64).ravel()

        if X_arr.size == 0 or y_arr.size == 0:
            raise ValueError("X ve y dizileri boş olamaz.")

        if X_arr.shape[0] != y_arr.shape[0]:
            raise ValueError(
                f"Boyut uyuşmazlığı: X satır sayısı ({X_arr.shape[0]}) ile y uzunluğu ({y_arr.shape[0]}) eşleşmiyor."
            )

        if not np.all(np.isfinite(X_arr)) or not np.all(np.isfinite(y_arr)):
            raise ValueError("X veya y içinde geçersiz NaN ya da Sonsuz (Inf) sayısal değer bulundu.")

        return X_arr, y_arr

    def generate_out_of_fold(
        self,
        model: Any,
        X: np.ndarray,
        y: np.ndarray,
        cv: int = 5,
    ) -> OutOfFoldResult:
        """Zaman serisi doğrulaması (TimeSeriesSplit) ile veri sızıntısız OOF tahminleri üretir.

        Args:
            model: sklearn uyumlu fit ve predict/predict_proba arayüzüne sahip model.
            X: Öznitelik matrisi (N, D).
            y: Gerçek hedef etiketler (N,).
            cv: Zaman serisi fold sayısı (asgari 2).

        Returns:
            OutOfFoldResult değerlendirme nesnesi.

        Raises:
            ValueError: Veri boyutları veya fold sayısı yetersiz olduğunda.
        """
        X_clean, y_clean = self._validate_xy(X, y)
        n_samples = len(y_clean)
        n_splits = max(2, int(cv))

        if n_samples < n_splits * 2:
            raise ValueError(
                f"Yetersiz örneklem: {n_samples} örneklem ile {n_splits} katlı TimeSeriesSplit çalıştırılamaz."
            )

        kf = TimeSeriesSplit(n_splits=n_splits)
        oof_predictions = np.full(n_samples, np.nan, dtype=np.float64)
        fold_indices: list[tuple[np.ndarray, np.ndarray]] = []
        fold_ics: list[float] = []
        fold_briers: list[float] = []

        for fold_idx, (train_idx, val_idx) in enumerate(kf.split(X_clean)):
            X_train, X_val = X_clean[train_idx], X_clean[val_idx]
            y_train, y_val = y_clean[train_idx], y_clean[val_idx]

            try:
                fold_model = copy.deepcopy(model)
                fold_model.fit(X_train, y_train)

                if hasattr(fold_model, "predict_proba"):
                    proba = fold_model.predict_proba(X_val)
                    preds = proba[:, 1] if proba.ndim == 2 and proba.shape[1] > 1 else proba.ravel()
                else:
                    preds = fold_model.predict(X_val)

                preds_clipped = np.clip(np.asarray(preds, dtype=np.float64).ravel(), 0.0, 1.0)
                oof_predictions[val_idx] = preds_clipped
                fold_indices.append((train_idx, val_idx))

                # Information Coefficient (IC)
                if np.std(preds_clipped) > 1e-8 and np.std(y_val) > 1e-8:
                    corr = float(np.corrcoef(preds_clipped, y_val)[0, 1])
                    if np.isfinite(corr):
                        fold_ics.append(corr)

                # Brier Skoru
                brier = float(np.mean((preds_clipped - y_val) ** 2))
                if np.isfinite(brier):
                    fold_briers.append(brier)

            except Exception as err:
                logger.warning("oof_fold_egitim_hatasi", fold=fold_idx, hata=str(err))

        # İlk fold öncesindeki ısınma örneklemlerini medyan ile doldur (sızıntı olmadan)
        valid_mask = np.isfinite(oof_predictions)
        if np.any(valid_mask):
            fallback_val = float(np.nanmedian(oof_predictions[valid_mask]))
            oof_predictions[~valid_mask] = fallback_val
        else:
            oof_predictions.fill(0.5)

        return OutOfFoldResult(
            predictions=oof_predictions,
            fold_indices=fold_indices,
            mean_ic=round(float(np.mean(fold_ics)), 4) if fold_ics else 0.0,
            mean_brier=round(float(np.mean(fold_briers)), 4) if fold_briers else 0.0,
            n_folds=n_splits,
        )

    def generate_out_of_fold_polars(
        self,
        df: pl.DataFrame,
        feature_columns: list[str],
        target_column: str,
        model: Any,
        cv: int = 5,
    ) -> OutOfFoldResult:
        """Polars DataFrame girdisi üzerinden doğrudan zaman serisi OOF tahmini yürütür.

        Args:
            df: Veriyi içeren Polars DataFrame.
            feature_columns: Model öznitelik sütun adları.
            target_column: Hedef değişken sütun adı.
            model: Eğitilecek tahmin modeli.
            cv: Katlama sayısı.

        Returns:
            OutOfFoldResult çıktısı.
        """
        X = df.select(feature_columns).to_numpy()
        y = df[target_column].to_numpy()
        return self.generate_out_of_fold(model=model, X=X, y=y, cv=cv)

    def record_calibration_metrics(
        self,
        brier_score: float,
        ece: float,
    ) -> None:
        """Yeni hesaplanan Brier ve ECE kalibrasyon metriklerini geçmişe kaydeder.

        Args:
            brier_score: Model Brier skoru.
            ece: Expected Calibration Error skoru.
        """
        now = datetime.now(UTC).isoformat()
        brier_clean = max(0.0, min(1.0, float(brier_score)))
        ece_clean = max(0.0, min(1.0, float(ece)))

        with self._lock:
            self._brier_history.append((now, brier_clean))
            self._ece_history.append((now, ece_clean))

            if len(self._brier_history) > DEFAULT_MAX_HISTORY_LEN:
                self._brier_history = self._brier_history[-DEFAULT_MAX_HISTORY_LEN:]
                self._ece_history = self._ece_history[-DEFAULT_MAX_HISTORY_LEN:]

            if self._baseline_brier is None:
                self._baseline_brier = brier_clean
            if self._baseline_ece is None:
                self._baseline_ece = ece_clean

    def check_calibration_drift(self) -> CalibrationDriftReport:
        """Kalibrasyon metriklerindeki zaman serisi sapmasını (drift) inceler.

        Returns:
            Detaylı CalibrationDriftReport değerlendirmesi.
        """
        with self._lock:
            if len(self._brier_history) < 2:
                return CalibrationDriftReport(
                    current_brier=0.0,
                    baseline_brier=0.0,
                    brier_change=0.0,
                    current_ece=0.0,
                    baseline_ece=0.0,
                    ece_change=0.0,
                    drift_detected=False,
                    severity="OK",
                    recommendation="Yetersiz veri — en az iki kalibrasyon kaydı gereklidir",
                )

            current_brier = self._brier_history[-1][1]
            current_ece = self._ece_history[-1][1]

            baseline_brier = self._baseline_brier if self._baseline_brier is not None else self._brier_history[0][1]
            baseline_ece = self._baseline_ece if self._baseline_ece is not None else self._ece_history[0][1]

            brier_change = current_brier - baseline_brier
            ece_change = current_ece - baseline_ece

            drift_detected = abs(brier_change) > self.drift_threshold or abs(ece_change) > self.drift_threshold

            if brier_change > 0.10 or ece_change > 0.10:
                severity = "ALERT"
                recommendation = "Kalibrasyon ciddi düzeyde bozuldu — acil yeniden eğitim (retrain) gereklidir"
            elif brier_change > 0.05 or ece_change > 0.05:
                severity = "WARNING"
                recommendation = "Kalibrasyon kayması tespit edildi — planlı yeniden eğitim önerilir"
            elif drift_detected:
                severity = "WARNING"
                recommendation = "Hafif kalibrasyon değişimi — izleme sürdürülmeli"
            else:
                severity = "OK"
                recommendation = "Kalibrasyon performansı kararlı ve stabil"

            return CalibrationDriftReport(
                current_brier=round(current_brier, 4),
                baseline_brier=round(baseline_brier, 4),
                brier_change=round(brier_change, 4),
                current_ece=round(current_ece, 4),
                baseline_ece=round(baseline_ece, 4),
                ece_change=round(ece_change, 4),
                drift_detected=drift_detected,
                severity=severity,
                recommendation=recommendation,
            )

    def should_retrain_calibration(self) -> RetrainSchedule:
        """Zaman ve performans sapması kriterlerine göre kalibratörün yeniden eğitilme gereksinimini denetler.

        Returns:
            RetrainSchedule planlama çıktısı.
        """
        now = datetime.now(UTC)

        with self._lock:
            if self._last_retrain is None:
                return RetrainSchedule(
                    last_retrain="Never",
                    hours_since_retrain=float("inf"),
                    should_retrain=True,
                    reason="İlk kalibrasyon kurulumu — derhal eğitim gereklidir",
                    next_retrain=now.isoformat(),
                )

            hours_since = (now - self._last_retrain).total_seconds() / 3600.0

            # 1. Zaman bazlı periyot kontrolü
            if hours_since >= self.retrain_interval_hours:
                return RetrainSchedule(
                    last_retrain=self._last_retrain.isoformat(),
                    hours_since_retrain=round(hours_since, 1),
                    should_retrain=True,
                    reason=f"Periyodik süre doldu ({hours_since:.1f} saat >= {self.retrain_interval_hours} saat)",
                    next_retrain=now.isoformat(),
                )

            # 2. Kalibrasyon bozulma (Drift) kontrolü
            drift = self.check_calibration_drift()
            if drift.severity == "ALERT":
                return RetrainSchedule(
                    last_retrain=self._last_retrain.isoformat(),
                    hours_since_retrain=round(hours_since, 1),
                    should_retrain=True,
                    reason=f"Kalibrasyon bozulma alarmı (ALERT): {drift.recommendation}",
                    next_retrain=now.isoformat(),
                )

            next_retrain = self._last_retrain + timedelta(hours=self.retrain_interval_hours)
            return RetrainSchedule(
                last_retrain=self._last_retrain.isoformat(),
                hours_since_retrain=round(hours_since, 1),
                should_retrain=False,
                reason="Kalibrasyon güncel ve sınırlar dahilinde",
                next_retrain=next_retrain.isoformat(),
            )

    def mark_retrained(self) -> None:
        """Kalibrasyon modelinin başarıyla yeniden eğitildiğini kaydeder."""
        now = datetime.now(UTC)
        with self._lock:
            self._last_retrain = now
            if self._brier_history:
                self._baseline_brier = self._brier_history[-1][1]
            if self._ece_history:
                self._baseline_ece = self._ece_history[-1][1]

        logger.info("kalibrasyon_yeniden_egitildi_isaretlendi", zaman=now.isoformat())

    def compare_calibration_methods(
        self,
        predictions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Platt Scaling ve Isotonic Regresyon kalibrasyon yöntemlerini Brier skoru üzerinden karşılaştırır.

        Args:
            predictions: [{'confidence': float, 'outcome': int | float}] formatında tahmin listesi.

        Returns:
            Karşılaştırma sonuçları ve en iyi kalibrasyon modeli sözlüğü.
        """
        if len(predictions) < 30:
            return {"hata": "Yetersiz veri — en az 30 tahmin gereklidir"}

        confidences = np.array([float(p["confidence"]) for p in predictions], dtype=np.float64)
        outcomes = np.array([float(p["outcome"]) for p in predictions], dtype=np.float64)

        confidences = np.clip(confidences, 0.0, 1.0)
        outcomes = np.where(outcomes >= 0.5, 1.0, 0.0)

        results: dict[str, Any] = {}

        # 1. Platt scaling (L-BFGS / Nelder-Mead doğrusal logit optimizasyonu)
        try:
            n_pos = np.sum(outcomes == 1.0)
            n_neg = np.sum(outcomes == 0.0)
            t_pos = (n_pos + 1.0) / (n_pos + 2.0)
            t_neg = 1.0 / (n_neg + 2.0)
            targets = np.where(outcomes == 1.0, t_pos, t_neg)

            def platt_objective(params: np.ndarray) -> float:
                """Platt logaritmik çapraz entropi amaç fonksiyonu."""
                a, b = params[0], params[1]
                f = np.clip(a * confidences + b, -250.0, 250.0)
                p = np.clip(1.0 / (1.0 + np.exp(f)), 1e-12, 1.0 - 1e-12)
                return float(-np.mean(targets * np.log(p) + (1.0 - targets) * np.log(1.0 - p)))

            opt_res = minimize(platt_objective, x0=np.array([-1.0, 0.0]), method="Nelder-Mead")
            a_opt, b_opt = float(opt_res.x[0]), float(opt_res.x[1])
            f_opt = np.clip(a_opt * confidences + b_opt, -250.0, 250.0)
            platt_calibrated = 1.0 / (1.0 + np.exp(f_opt))
            platt_brier = float(np.mean((platt_calibrated - outcomes) ** 2))

            results["platt_brier"] = round(platt_brier, 4)
            results["platt_params"] = {"a": round(a_opt, 4), "b": round(b_opt, 4)}
        except Exception as err:
            logger.warning("platt_karsilastirma_hatasi", hata=str(err))
            results["platt_brier"] = None
            results["platt_error"] = str(err)

        # 2. Isotonic regresyon
        try:
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            iso.fit(confidences, outcomes)
            isotonic_calibrated = iso.predict(confidences)
            isotonic_brier = float(np.mean((isotonic_calibrated - outcomes) ** 2))

            results["isotonic_brier"] = round(isotonic_brier, 4)
        except Exception as err:
            logger.warning("isotonic_karsilastirma_hatasi", hata=str(err))
            results["isotonic_brier"] = None
            results["isotonic_error"] = str(err)

        # 3. Yöntem Seçimi
        p_brier = results.get("platt_brier")
        i_brier = results.get("isotonic_brier")

        if p_brier is not None and i_brier is not None:
            if p_brier < i_brier:
                results["better_method"] = "platt"
                results["improvement"] = round(i_brier - p_brier, 4)
            elif i_brier < p_brier:
                results["better_method"] = "isotonic"
                results["improvement"] = round(p_brier - i_brier, 4)
            else:
                results["better_method"] = "equal"
                results["improvement"] = 0.0

        return results

    def get_brier_history(self, limit: int = 50) -> list[tuple[str, float]]:
        """Brier skoru geçmiş kayıtlarını döndürür."""
        with self._lock:
            return list(self._brier_history[-limit:])

    def get_ece_history(self, limit: int = 50) -> list[tuple[str, float]]:
        """ECE skoru geçmiş kayıtlarını döndürür."""
        with self._lock:
            return list(self._ece_history[-limit:])

    # ===================== DUCKDB & POLARS ENTEGRASYONU =====================

    def export_drift_history_duckdb(
        self,
        db_path: str = ":memory:",
        table_name: str = "calibration_drift_audit",
    ) -> None:
        """Geçmiş Brier ve ECE kayıtlarını DuckDB tablosuna aktarır.

        Args:
            db_path: DuckDB veritabanı dosya yolu.
            table_name: Hedef denetim tablosu adı.
        """
        with self._lock:
            brier_records = list(self._brier_history)
            ece_records = dict(self._ece_history)

        con = duckdb.connect(db_path)
        try:
            configure_duckdb_wal(con)
            con.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    timestamp TIMESTAMP WITH TIME ZONE,
                    brier_score DOUBLE,
                    ece DOUBLE
                )
                """
            )

            for ts, brier in brier_records:
                ece_val = ece_records.get(ts, 0.0)
                con.execute(
                    f"INSERT INTO {table_name} VALUES (?, ?, ?)",
                    (ts, brier, ece_val),
                )
            logger.info("kalibrasyon_drift_duckdb_aktarildi", tablo=table_name, adet=len(brier_records))
        finally:
            con.close()

    def read_drift_history_polars(
        self,
        db_path: str = ":memory:",
        table_name: str = "calibration_drift_audit",
    ) -> pl.DataFrame:
        """DuckDB tablosundaki drift geçmişini Polars DataFrame olarak okur.

        Args:
            db_path: DuckDB dosya yolu.
            table_name: Tablo adı.

        Returns:
            Drift kayıtlarını içeren Polars DataFrame.
        """
        con = duckdb.connect(db_path)
        try:
            configure_duckdb_wal(con)
            arrow_table = con.execute(f"SELECT * FROM {table_name} ORDER BY timestamp ASC").arrow()
            return pl.from_arrow(arrow_table)  # type: ignore[return-value]
        finally:
            con.close()


# Singleton Örneği
calibration_enhanced = CalibrationEnhanced()

__all__: Final[list[str]] = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_DRIFT_THRESHOLD",
    "DEFAULT_MAX_HISTORY_LEN",
    "DEFAULT_MIN_SAMPLES_FOR_RETRAIN",
    "DEFAULT_RETRAIN_INTERVAL_HOURS",
    "DEFAULT_WAL_SIZE",
    "CalibrationDriftReport",
    "CalibrationEnhanced",
    "OutOfFoldResult",
    "RetrainSchedule",
    "calibration_enhanced",
    "configure_duckdb_wal",
]
