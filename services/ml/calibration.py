"""ALPHA BIST — Model Calibration v2.0 (Production-Hardened)

BIST pay piyasası yapay zeka modelleri için olasılık güven kalibrasyonu:
Brier score, Expected Calibration Error (ECE), Maximum Calibration Error (MCE),
Platt scaling (lojistik regresyon), Isotonic regresyon, rejim bazlı kalibrasyon,
aşırı güven (overconfidence) tespiti, online adaptif kalibrasyon ve DuckDB/Polars denetim izi.

Kurallar & Standartlar:
- DuckDB WAL ve denetim logu desteği (SQLite yasaktır)
- orjson yüksek hızlı serileştirme (standart json yasaktır)
- Polars DataFrame entegrasyonu (pandas yasaktır)
- threading.RLock eşzamanlılık güvenliği
- Sıfır veri sızıntısı (train/val ayrımı ile kalibratör fitting)
- Fail-closed hata yönetimi ve structlog yapısal loglama
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog
from sklearn.calibration import calibration_curve
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

logger = structlog.get_logger(__name__)

# ===================== SABİTLER (CONSTANTS) =====================

DEFAULT_N_BINS: Final[int] = 10
DEFAULT_OVERCONFIDENCE_THRESHOLD: Final[float] = 0.15
DEFAULT_ECE_THRESHOLD: Final[float] = 0.05
DEFAULT_DRIFT_THRESHOLD: Final[float] = 0.05
DEFAULT_BOOTSTRAP_N: Final[int] = 100
DEFAULT_ADAPTIVE_WINDOW: Final[int] = 500
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
class CalibrationResult:
    """Model kalibrasyon metrikleri ve değerlendirme çıktısı.

    Attributes:
        is_calibrated: Modelin kabul edilebilir kalibrasyon sınırları içinde olup olmadığı.
        brier_score: Brier skoru (0 mükemmel, 1 en kötü).
        calibration_curve: Aralık bazlı güven ve gerçekleşme oranı eğrisi.
        miscalibration: Ortalama kalibrasyon sapması.
        overconfident: Aşırı güven uyarısı aktif mi.
        recommendation: Kalibrasyon durumu tavsiyesi (EXCELLENT, GOOD, vb.).
        expected_calibration_error: Beklenen Kalibrasyon Hatası (ECE).
        maximum_calibration_error: Maksimum Kalibrasyon Hatası (MCE).
        log_loss: Çapraz entropi / logaritmik kayıp.
        brier_skill_score: Baseline'a kıyasla Brier yetenek skoru.
        brier_baseline: Baseline (0.5 sabit tahmin) Brier skoru.
        ece_ci_lower: ECE bootstrap %95 alt güven sınırı.
        ece_ci_upper: ECE bootstrap %95 üst güven sınırı.
        brier_ci_lower: Brier bootstrap %95 alt güven sınırı.
        brier_ci_upper: Brier bootstrap %95 üst güven sınırı.
        platt_ece: Platt ölçekleme sonrası doğrulama seti ECE skoru.
        isotonic_ece: Isotonic regresyon sonrası doğrulama seti ECE skoru.
        best_calibrator: En iyi kalibratör yöntemi ('platt', 'isotonic' veya 'equal').
        nri: Net Yeniden Sınıflandırma İndeksi (Net Reclassification Index).
    """

    is_calibrated: bool
    brier_score: float
    calibration_curve: list[dict[str, float]]
    miscalibration: float
    overconfident: bool
    recommendation: str
    expected_calibration_error: float = 0.0
    maximum_calibration_error: float = 0.0
    log_loss: float = 0.0
    brier_skill_score: float = 0.0
    brier_baseline: float = 0.0
    ece_ci_lower: float = 0.0
    ece_ci_upper: float = 0.0
    brier_ci_lower: float = 0.0
    brier_ci_upper: float = 0.0
    platt_ece: float = 0.0
    isotonic_ece: float = 0.0
    best_calibrator: str = "none"
    nri: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Modeli standart Python sözlüğüne dönüştürür."""
        return {
            "is_calibrated": self.is_calibrated,
            "brier_score": self.brier_score,
            "calibration_curve": self.calibration_curve,
            "miscalibration": self.miscalibration,
            "overconfident": self.overconfident,
            "recommendation": self.recommendation,
            "expected_calibration_error": self.expected_calibration_error,
            "maximum_calibration_error": self.maximum_calibration_error,
            "log_loss": self.log_loss,
            "brier_skill_score": self.brier_skill_score,
            "brier_baseline": self.brier_baseline,
            "ece_ci_lower": self.ece_ci_lower,
            "ece_ci_upper": self.ece_ci_upper,
            "brier_ci_lower": self.brier_ci_lower,
            "brier_ci_upper": self.brier_ci_upper,
            "platt_ece": self.platt_ece,
            "isotonic_ece": self.isotonic_ece,
            "best_calibrator": self.best_calibrator,
            "nri": self.nri,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CalibrationResult:
        """Sözlükten CalibrationResult nesnesi oluşturur."""
        return cls(
            is_calibrated=bool(data.get("is_calibrated", False)),
            brier_score=float(data.get("brier_score", 0.0)),
            calibration_curve=list(data.get("calibration_curve", [])),
            miscalibration=float(data.get("miscalibration", 0.0)),
            overconfident=bool(data.get("overconfident", False)),
            recommendation=str(data.get("recommendation", "")),
            expected_calibration_error=float(data.get("expected_calibration_error", 0.0)),
            maximum_calibration_error=float(data.get("maximum_calibration_error", 0.0)),
            log_loss=float(data.get("log_loss", 0.0)),
            brier_skill_score=float(data.get("brier_skill_score", 0.0)),
            brier_baseline=float(data.get("brier_baseline", 0.0)),
            ece_ci_lower=float(data.get("ece_ci_lower", 0.0)),
            ece_ci_upper=float(data.get("ece_ci_upper", 0.0)),
            brier_ci_lower=float(data.get("brier_ci_lower", 0.0)),
            brier_ci_upper=float(data.get("brier_ci_upper", 0.0)),
            platt_ece=float(data.get("platt_ece", 0.0)),
            isotonic_ece=float(data.get("isotonic_ece", 0.0)),
            best_calibrator=str(data.get("best_calibrator", "none")),
            nri=float(data.get("nri", 0.0)),
        )

    def to_orjson_bytes(self) -> bytes:
        """Sonuçları orjson bayt dizisi olarak serileştirir."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        return (
            f"CalibrationResult(is_calibrated={self.is_calibrated}, brier={self.brier_score:.4f}, "
            f"ece={self.expected_calibration_error:.4f}, mce={self.maximum_calibration_error:.4f}, "
            f"best={self.best_calibrator!r}, rec={self.recommendation!r})"
        )


@dataclass(slots=True)
class RegimeCalibrationResult:
    """Piyasa rejimi bazlı kalibrasyon sonucu.

    Attributes:
        regime: Piyasa rejimi etiketi (BULL, BEAR, RANGE, VOLATILE vb.).
        result: Rejime ait kalibrasyon sonucu.
        n_samples: Rejimdeki örneklem sayısı.
    """

    regime: str
    result: CalibrationResult
    n_samples: int

    def to_dict(self) -> dict[str, Any]:
        """Modeli sözlüğe dönüştürür."""
        return {
            "regime": self.regime,
            "result": self.result.to_dict(),
            "n_samples": self.n_samples,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RegimeCalibrationResult:
        """Sözlükten RegimeCalibrationResult nesnesi oluşturur."""
        res_data = data.get("result", {})
        res = (
            CalibrationResult.from_dict(res_data)
            if isinstance(res_data, dict)
            else res_data
        )
        return cls(
            regime=str(data.get("regime", "")),
            result=res,
            n_samples=int(data.get("n_samples", 0)),
        )

    def to_orjson_bytes(self) -> bytes:
        """orjson serileştirmesi döndürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        return f"RegimeCalibrationResult(regime={self.regime!r}, n_samples={self.n_samples}, ece={self.result.expected_calibration_error:.4f})"


@dataclass(slots=True)
class CalibrationAlert:
    """Kalibrasyon bozulması veya aşırı güven alarmı.

    Attributes:
        timestamp: ISO formatında alarm zaman damgası.
        alert_type: Alarm türü (DRIFT, DEGRADATION, OVERCONFIDENCE).
        severity: Önem derecesi (LOW, MEDIUM, HIGH, CRITICAL).
        message: Açıklayıcı alarm mesajı.
        metric: İlgili metrik adı (ece, brier_skill_score vb.).
        value: Tespit edilen mevcut değer.
        threshold: İhlal edilen sınır eşik değeri.
    """

    timestamp: str
    alert_type: str
    severity: str
    message: str
    metric: str
    value: float
    threshold: float

    def to_dict(self) -> dict[str, Any]:
        """Alarm verisini sözlüğe dönüştürür."""
        return {
            "timestamp": self.timestamp,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "message": self.message,
            "metric": self.metric,
            "value": self.value,
            "threshold": self.threshold,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CalibrationAlert:
        """Sözlükten CalibrationAlert nesnesi oluşturur."""
        return cls(
            timestamp=str(data.get("timestamp", "")),
            alert_type=str(data.get("alert_type", "")),
            severity=str(data.get("severity", "")),
            message=str(data.get("message", "")),
            metric=str(data.get("metric", "")),
            value=float(data.get("value", 0.0)),
            threshold=float(data.get("threshold", 0.0)),
        )

    def to_orjson_bytes(self) -> bytes:
        """orjson serileştirmesi döndürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        return (
            f"CalibrationAlert(type={self.alert_type!r}, sev={self.severity!r}, "
            f"metric={self.metric!r}, val={self.value:.4f}, thr={self.threshold:.4f})"
        )


# ===================== MODEL KALİBRASYON ÇEKİRDEĞİ =====================


class ModelCalibration:
    """BIST 100 kantitatif tahmin modelleri için kalibrasyon motoru v2.0.

    Özellikler:
    - Brier skoru ve Brier Yetenek Skoru (BSS)
    - Expected Calibration Error (ECE) ve Maximum Calibration Error (MCE)
    - Bootstrap güven aralıkları (%95 CI)
    - Platt Scaling ve Isotonic Regresyon karşılaştırmalı testi
    - Piyasa rejimi bazlı adaptif kalibratör yönetimi
    - Aşırı güven (overconfidence) ve kalibrasyon kayması (drift) tespiti
    - DuckDB WAL denetim tablosuna otomatik loglama
    - Polars DataFrame ile vektörize kalibrasyon değerlendirmesi
    - threading.RLock eşzamanlı erişim koruması
    """

    def __init__(
        self,
        n_bins: int = DEFAULT_N_BINS,
        overconfidence_threshold: float = DEFAULT_OVERCONFIDENCE_THRESHOLD,
        ece_threshold: float = DEFAULT_ECE_THRESHOLD,
        drift_threshold: float = DEFAULT_DRIFT_THRESHOLD,
        bootstrap_n: int = DEFAULT_BOOTSTRAP_N,
        adaptive_window: int = DEFAULT_ADAPTIVE_WINDOW,
    ) -> None:
        """ModelCalibration nesnesini yapılandırır.

        Args:
            n_bins: Güven aralığı dilim sayısı (varsayılan 10).
            overconfidence_threshold: Aşırı güven tolerans eşiği (varsayılan 0.15).
            ece_threshold: Kabul edilebilir ECE üst eşiği (varsayılan 0.05).
            drift_threshold: Kalibrasyon kayması tespit eşiği (varsayılan 0.05).
            bootstrap_n: Bootstrap simülasyon tekrar sayısı (varsayılan 100).
            adaptive_window: Çevrimiçi adaptif kalibrasyon tampon boyutu (varsayılan 500).
        """
        self.n_bins = max(2, n_bins)
        self.overconfidence_threshold = overconfidence_threshold
        self.ece_threshold = ece_threshold
        self.drift_threshold = drift_threshold
        self.bootstrap_n = max(10, bootstrap_n)
        self._adaptive_window = max(50, adaptive_window)

        self._lock = threading.RLock()
        self._calibration_history: list[dict[str, Any]] = []
        self._regime_calibrators: dict[str, Any] = {}
        self._alerts: list[CalibrationAlert] = []
        self._platt_calibrator: LogisticRegression | None = None
        self._isotonic_calibrator: IsotonicRegression | None = None
        self._adaptive_buffer: list[tuple[float, float]] = []

    def __repr__(self) -> str:
        with self._lock:
            n_hist = len(self._calibration_history)
            n_alerts = len(self._alerts)
            n_regimes = len(self._regime_calibrators)
            return (
                f"ModelCalibration(bins={self.n_bins}, history_len={n_hist}, "
                f"alerts={n_alerts}, active_regimes={n_regimes})"
            )

    @staticmethod
    def _validate_inputs(y_true: np.ndarray, y_prob: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Giriş dizilerini doğrular, boyut ve NaN/Inf kontrolü uygular.

        Args:
            y_true: Gerçek ikili etiketler.
            y_prob: Model olasılık tahminleri [0, 1].

        Returns:
            Doğrulanmış numpy dizileri (y_true, y_prob).

        Raises:
            ValueError: Boş dizi, boyut uyuşmazlığı veya geçersiz sayısal değer durumunda.
        """
        y_true_arr = np.asarray(y_true, dtype=np.float64).ravel()
        y_prob_arr = np.asarray(y_prob, dtype=np.float64).ravel()

        if y_true_arr.size == 0 or y_prob_arr.size == 0:
            raise ValueError("Kalibrasyon dizileri boş olamaz.")

        if y_true_arr.shape != y_prob_arr.shape:
            raise ValueError(
                f"Boyut uyuşmazlığı: y_true={y_true_arr.shape} ile y_prob={y_prob_arr.shape} eşleşmiyor."
            )

        if not np.all(np.isfinite(y_true_arr)) or not np.all(np.isfinite(y_prob_arr)):
            raise ValueError("y_true veya y_prob dizilerinde geçersiz NaN ya da Sonsuz (Inf) değer tespit edildi.")

        # Olasılıkları [0, 1] aralığına sıkıştır
        y_prob_clipped = np.clip(y_prob_arr, 0.0, 1.0)
        return y_true_arr, y_prob_clipped

    def check_calibration(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
    ) -> CalibrationResult:
        """Kapsamlı olasılık kalibrasyonu analizi yürütür.

        Args:
            y_true: Gerçekleşen ikili hedef değerler (0 veya 1).
            y_prob: Modelin ürettiği olasılık tahminleri [0, 1].

        Returns:
            Detaylı metrikleri içeren CalibrationResult nesnesi.

        Raises:
            ValueError: Giriş verileri geçersiz olduğunda.
        """
        y_true_clean, y_prob_clean = self._validate_inputs(y_true, y_prob)

        # 1. Brier Skoru
        try:
            brier = float(brier_score_loss(y_true_clean, y_prob_clean))
        except Exception as err:
            logger.error("brier_score_hesaplama_hatasi", hata=str(err))
            brier = 1.0

        # 2. Brier Yetenek Skoru (Baseline = 0.5 sabit tahmin)
        baseline_prob = np.full_like(y_prob_clean, 0.5)
        try:
            brier_baseline = float(brier_score_loss(y_true_clean, baseline_prob))
        except Exception:
            brier_baseline = 0.25
        brier_skill_score = 1.0 - (brier / max(brier_baseline, 1e-10))

        # 3. Log Kaybı (Çapraz Entropi)
        try:
            ll = float(log_loss(y_true_clean, y_prob_clean))
        except Exception as err:
            logger.warning("log_loss_hesaplama_hatasi", hata=str(err))
            ll = 1.0

        # 4. Kalibrasyon Eğrisi
        curve: list[dict[str, float]] = []
        try:
            fraction_pos, mean_predicted = calibration_curve(
                y_true_clean, y_prob_clean, n_bins=self.n_bins, strategy="uniform"
            )
            for frac, mean_pred in zip(fraction_pos, mean_predicted, strict=False):
                gap = abs(float(mean_pred) - float(frac))
                curve.append(
                    {
                        "mean_predicted": round(float(mean_pred), 4),
                        "fraction_positive": round(float(frac), 4),
                        "gap": round(gap, 4),
                    }
                )
        except Exception as err:
            logger.warning("kalibrasyon_egrisi_olusturulamadi", hata=str(err))

        # 5. ECE, MCE ve Yanılgı Oranı
        ece = self._compute_ece(y_true_clean, y_prob_clean)
        mce = max([c["gap"] for c in curve]) if curve else 0.0
        miscalibration = float(np.mean([c["gap"] for c in curve])) if curve else 0.0

        # 6. Bootstrap Güven Aralıkları
        ece_ci = self._bootstrap_ece_ci(y_true_clean, y_prob_clean)
        brier_ci = self._bootstrap_brier_ci(y_true_clean, y_prob_clean)

        # 7. Platt vs Isotonic Karşılaştırması
        platt_ece, isotonic_ece, best_calibrator = self._compare_calibrators(y_true_clean, y_prob_clean)

        # 8. Net Yeniden Sınıflandırma İndeksi (NRI)
        nri = self._compute_nri(y_true_clean, y_prob_clean)

        # 9. Aşırı Güven ve Durum Tavsiyesi
        overconfident = miscalibration > self.overconfidence_threshold or ece > self.ece_threshold
        if brier < 0.1 and ece < 0.03:
            recommendation = "EXCELLENT"
        elif brier < 0.2 and ece < 0.05:
            recommendation = "GOOD"
        elif brier < 0.3 and ece < 0.1:
            recommendation = "NEEDS_CALIBRATION"
        else:
            recommendation = "POOR"

        result = CalibrationResult(
            is_calibrated=(miscalibration < self.overconfidence_threshold and ece < self.ece_threshold),
            brier_score=round(brier, 4),
            calibration_curve=curve,
            miscalibration=round(miscalibration, 4),
            overconfident=overconfident,
            recommendation=recommendation,
            expected_calibration_error=round(ece, 4),
            maximum_calibration_error=round(mce, 4),
            log_loss=round(ll, 4),
            brier_skill_score=round(brier_skill_score, 4),
            brier_baseline=round(brier_baseline, 4),
            ece_ci_lower=round(ece_ci[0], 4),
            ece_ci_upper=round(ece_ci[1], 4),
            brier_ci_lower=round(brier_ci[0], 4),
            brier_ci_upper=round(brier_ci[1], 4),
            platt_ece=round(platt_ece, 4),
            isotonic_ece=round(isotonic_ece, 4),
            best_calibrator=best_calibrator,
            nri=round(nri, 4),
        )

        with self._lock:
            self._calibration_history.append(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "brier_score": brier,
                    "ece": ece,
                    "miscalibration": miscalibration,
                    "n_samples": len(y_true_clean),
                    "brier_skill_score": brier_skill_score,
                }
            )
            if len(self._calibration_history) > 1000:
                self._calibration_history = self._calibration_history[-1000:]

            self._check_alerts_locked(result, len(y_true_clean))

        return result

    def check_calibration_polars(
        self,
        df: pl.DataFrame,
        true_column: str,
        prob_column: str,
    ) -> CalibrationResult:
        """Polars DataFrame sütunları üzerinden doğrudan kalibrasyon kontrolü yürütür.

        Args:
            df: Veriyi içeren Polars DataFrame.
            true_column: Gerçek hedef etiket sütun adı.
            prob_column: Model olasılık tahmin sütun adı.

        Returns:
            CalibrationResult değerlendirme nesnesi.

        Raises:
            KeyError: Belirtilen sütunlar tabloda mevcut değilse.
            ValueError: Tabloda geçerli satır bulunamazsa.
        """
        if true_column not in df.columns or prob_column not in df.columns:
            raise KeyError(
                f"Sütunlar tabloda bulunamadı: {true_column}, {prob_column} (Mevcut: {df.columns})"
            )

        clean_df = df.select([true_column, prob_column]).drop_nulls()
        if clean_df.height == 0:
            raise ValueError("Polars DataFrame belirtilen sütunlarda geçerli satır içermiyor.")

        y_true = clean_df[true_column].to_numpy()
        y_prob = clean_df[prob_column].to_numpy()
        return self.check_calibration(y_true, y_prob)

    def calibrate_platt(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        y_prob_val: np.ndarray | None = None,
        y_true_train: np.ndarray | None = None,
    ) -> tuple[LogisticRegression, np.ndarray]:
        """Platt scaling (lojistik regresyon) kalibratörünü eğitir ve olasılıkları dönüştürür.

        Args:
            y_true: Eğitim seti gerçek etiketleri (veya tam etiket kümesi).
            y_prob: Eğitim seti olasılıkları.
            y_prob_val: İsteğe bağlı doğrulama olasılıkları (varsa dönüşüm val üzerine yapılır).
            y_true_train: İsteğe bağlı bağımsız eğitim etiketleri.

        Returns:
            Eğitilen LogisticRegression modeli ve kalibre edilmiş olasılıklar dizisi.
        """
        y_true_arr, y_prob_arr = self._validate_inputs(y_true, y_prob)
        train_y = y_true_train if y_true_train is not None and y_prob_val is not None else y_true_arr
        train_prob = y_prob_arr

        calibrator = LogisticRegression(max_iter=1000, solver="lbfgs")
        calibrator.fit(train_prob.reshape(-1, 1), train_y)

        with self._lock:
            self._platt_calibrator = calibrator

        eval_prob = y_prob_val if y_prob_val is not None else train_prob
        eval_clean = np.clip(np.asarray(eval_prob, dtype=np.float64).reshape(-1, 1), 0.0, 1.0)
        calibrated = calibrator.predict_proba(eval_clean)[:, 1]
        return calibrator, calibrated

    def calibrate_isotonic(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        y_prob_val: np.ndarray | None = None,
    ) -> tuple[IsotonicRegression, np.ndarray]:
        """Isotonic regresyon kalibratörünü eğitir ve olasılıkları dönüştürür.

        Args:
            y_true: Gerçek etiketler.
            y_prob: Model ham olasılıkları.
            y_prob_val: İsteğe bağlı doğrulama seti olasılıkları.

        Returns:
            Eğitilen IsotonicRegression modeli ve kalibre edilmiş olasılıklar.
        """
        y_true_arr, y_prob_arr = self._validate_inputs(y_true, y_prob)
        calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        calibrator.fit(y_prob_arr, y_true_arr)

        with self._lock:
            self._isotonic_calibrator = calibrator

        eval_prob = y_prob_val if y_prob_val is not None else y_prob_arr
        eval_clean = np.clip(np.asarray(eval_prob, dtype=np.float64), 0.0, 1.0)
        calibrated = calibrator.predict(eval_clean)
        return calibrator, calibrated

    def calibrate_regime_specific(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        regimes: np.ndarray,
        method: str = "isotonic",
    ) -> dict[str, Any]:
        """Her piyasa rejimi için bağımsız kalibratör modeli eğitir.

        Args:
            y_true: Gerçek etiketler.
            y_prob: Model olasılıkları.
            regimes: Rejim etiket dizisi (ör. BULL, BEAR, RANGE).
            method: Kalibrasyon yöntemi ('isotonic' veya 'platt').

        Returns:
            Rejim bazlı eğitilmiş model sözlüğü {rejim: model}.
        """
        y_true_arr, y_prob_arr = self._validate_inputs(y_true, y_prob)
        regimes_arr = np.asarray(regimes).ravel()

        if regimes_arr.shape != y_true_arr.shape:
            raise ValueError("Rejim dizisi uzunluğu y_true ile uyuşmuyor.")

        unique_regimes = np.unique(regimes_arr)

        with self._lock:
            for regime in unique_regimes:
                regime_str = str(regime)
                mask = regimes_arr == regime
                if np.sum(mask) < 20:
                    logger.info("rejim_kalibrasyonu_yetersiz_orneklem", rejim=regime_str, n_samples=int(np.sum(mask)))
                    continue

                try:
                    if method == "platt":
                        calibrator, _ = self.calibrate_platt(y_true_arr[mask], y_prob_arr[mask])
                    else:
                        calibrator, _ = self.calibrate_isotonic(y_true_arr[mask], y_prob_arr[mask])

                    self._regime_calibrators[regime_str] = calibrator
                    logger.info("rejim_kalibrasyonu_tamamlandi", rejim=regime_str, n_samples=int(np.sum(mask)))
                except Exception as err:
                    logger.warning("rejim_kalibrasyonu_basarisiz", rejim=regime_str, hata=str(err))

            return self._regime_calibrators.copy()

    def apply_calibration(
        self,
        y_prob: np.ndarray,
        regime: str | None = None,
    ) -> np.ndarray:
        """Ham model olasılık tahminlerine uygun kalibratörü uygular.

        Args:
            y_prob: Ham model olasılıkları [0, 1].
            regime: İsteğe bağlı piyasa rejimi etiketi.

        Returns:
            Kalibre edilmiş olasılık dizisi.
        """
        y_prob_arr = np.clip(np.asarray(y_prob, dtype=np.float64), 0.0, 1.0)

        with self._lock:
            if regime and regime in self._regime_calibrators:
                calibrator = self._regime_calibrators[regime]
                try:
                    if hasattr(calibrator, "predict_proba"):
                        return calibrator.predict_proba(y_prob_arr.reshape(-1, 1))[:, 1]
                    return calibrator.predict(y_prob_arr)
                except Exception as err:
                    logger.warning("rejim_kalibrasyon_uygulama_hatasi", rejim=regime, hata=str(err))

            if self._isotonic_calibrator is not None:
                try:
                    return self._isotonic_calibrator.predict(y_prob_arr)
                except Exception as err:
                    logger.warning("isotonic_uygulama_hatasi", hata=str(err))

            if self._platt_calibrator is not None:
                try:
                    return self._platt_calibrator.predict_proba(y_prob_arr.reshape(-1, 1))[:, 1]
                except Exception as err:
                    logger.warning("platt_uygulama_hatasi", hata=str(err))

        return y_prob_arr

    def adaptive_update(self, confidence: float, outcome: float) -> None:
        """Yeni gerçekleşen tekil tahmin ile adaptif tamponu günceller.

        Tampon boyutu eşiğe ulaştığında modelleri otomatik yeniden eğitir.

        Args:
            confidence: Modelin verdiği güven olasılığı [0, 1].
            outcome: Gerçekleşen sonuç (0 veya 1).
        """
        conf_clamped = max(0.0, min(1.0, float(confidence)))
        outcome_clamped = 1.0 if outcome >= 0.5 else 0.0

        with self._lock:
            self._adaptive_buffer.append((conf_clamped, outcome_clamped))
            if len(self._adaptive_buffer) >= self._adaptive_window:
                self._refit_adaptive_locked()

    def _refit_adaptive_locked(self) -> None:
        """Kilit altındayken adaptif tampondan kalibratörleri yeniden eğitir."""
        if len(self._adaptive_buffer) < 30:
            return

        confidences = np.array([c for c, _ in self._adaptive_buffer], dtype=np.float64)
        outcomes = np.array([o for _, o in self._adaptive_buffer], dtype=np.float64)

        try:
            self.calibrate_platt(outcomes, confidences)
            logger.info("adaptif_platt_yeniden_egitildi", orneklem=len(self._adaptive_buffer))
        except Exception as err:
            logger.warning("adaptif_platt_egitimi_basarisiz", hata=str(err))

        try:
            self.calibrate_isotonic(outcomes, confidences)
            logger.info("adaptif_isotonic_yeniden_egitildi", orneklem=len(self._adaptive_buffer))
        except Exception as err:
            logger.warning("adaptif_isotonic_egitimi_basarisiz", hata=str(err))

        keep = max(10, len(self._adaptive_buffer) // 5)
        self._adaptive_buffer = self._adaptive_buffer[-keep:]

    def check_overconfidence(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        confidence_threshold: float = 0.8,
    ) -> dict[str, Any]:
        """Yüksek güvenli tahminlerin doğruluğunu ve aşırı güven sapmasını analiz eder.

        Args:
            y_true: Gerçek etiketler.
            y_prob: Model olasılıkları.
            confidence_threshold: Yüksek güven eşik değeri (varsayılan 0.8).

        Returns:
            Aşırı güven analiz raporu sözlüğü.
        """
        y_true_arr, y_prob_arr = self._validate_inputs(y_true, y_prob)
        high_conf_mask = (y_prob_arr > confidence_threshold) | (y_prob_arr < (1.0 - confidence_threshold))
        n_high_conf = int(np.sum(high_conf_mask))

        if n_high_conf == 0:
            return {
                "overconfident": False,
                "n_high_confidence": 0,
                "reason": "no_high_confidence_predictions",
            }

        high_conf_preds = (y_prob_arr[high_conf_mask] > 0.5).astype(int)
        high_conf_true = y_true_arr[high_conf_mask]
        high_conf_accuracy = float(np.mean(high_conf_preds == high_conf_true))

        low_conf_mask = ~high_conf_mask
        if np.sum(low_conf_mask) > 0:
            low_conf_preds = (y_prob_arr[low_conf_mask] > 0.5).astype(int)
            low_conf_true = y_true_arr[low_conf_mask]
            low_conf_accuracy = float(np.mean(low_conf_preds == low_conf_true))
        else:
            low_conf_accuracy = 0.0

        expected_accuracy = float(np.mean(np.maximum(y_prob_arr[high_conf_mask], 1.0 - y_prob_arr[high_conf_mask])))
        overconfidence_gap = expected_accuracy - high_conf_accuracy

        return {
            "overconfident": overconfidence_gap > self.overconfidence_threshold,
            "n_high_confidence": n_high_conf,
            "high_confidence_accuracy": round(high_conf_accuracy, 4),
            "expected_accuracy": round(expected_accuracy, 4),
            "overconfidence_gap": round(overconfidence_gap, 4),
            "low_confidence_accuracy": round(low_conf_accuracy, 4),
            "n_total": len(y_true_arr),
        }

    def get_calibration_history(self) -> list[dict[str, Any]]:
        """Geçmiş kalibrasyon denetim kayıtlarını döndürür."""
        with self._lock:
            return [h.copy() for h in self._calibration_history]

    def get_calibration_drift(self) -> dict[str, Any]:
        """Zaman içindeki kalibrasyon kaymasını (drift) analiz eder.

        Returns:
            Kayma tespit raporu sözlüğü.
        """
        with self._lock:
            if len(self._calibration_history) < 3:
                return {"drift_detected": False, "reason": "insufficient_history"}

            recent = self._calibration_history[-3:]
            older = self._calibration_history[:-3] if len(self._calibration_history) > 3 else recent

            recent_ece = float(np.mean([h["ece"] for h in recent]))
            older_ece = float(np.mean([h["ece"] for h in older]))
            drift = abs(recent_ece - older_ece) > self.drift_threshold

            return {
                "drift_detected": drift,
                "recent_ece": round(recent_ece, 4),
                "historical_ece": round(older_ece, 4),
                "ece_change": round(recent_ece - older_ece, 4),
            }

    def get_alerts(self) -> list[CalibrationAlert]:
        """Oluşan kalibrasyon alarmlarının kopyasını döndürür."""
        with self._lock:
            return list(self._alerts)

    def get_reliability_diagram_data(self, y_true: np.ndarray, y_prob: np.ndarray) -> dict[str, Any]:
        """Güvenilirlik diyagramı (reliability diagram) görselleştirme verisi üretir.

        Args:
            y_true: Gerçek etiketler.
            y_prob: Model olasılıkları.

        Returns:
            Aralık bazlı diyagram verileri.
        """
        y_true_arr, y_prob_arr = self._validate_inputs(y_true, y_prob)
        bin_edges = np.linspace(0.0, 1.0, self.n_bins + 1)
        bins: list[dict[str, Any]] = []

        for i in range(self.n_bins):
            lower = bin_edges[i]
            upper = bin_edges[i + 1]
            if i == self.n_bins - 1:
                mask = (y_prob_arr >= lower) & (y_prob_arr <= upper)
            else:
                mask = (y_prob_arr >= lower) & (y_prob_arr < upper)

            count = int(np.sum(mask))
            if count == 0:
                continue

            avg_pred = float(np.mean(y_prob_arr[mask]))
            avg_actual = float(np.mean(y_true_arr[mask]))

            bins.append(
                {
                    "lower": round(lower, 2),
                    "upper": round(upper, 2),
                    "avg_predicted": round(avg_pred, 4),
                    "avg_actual": round(avg_actual, 4),
                    "count": count,
                    "gap": round(abs(avg_pred - avg_actual), 4),
                }
            )

        perfect = [{"x": round(b["avg_predicted"], 4), "y": round(b["avg_predicted"], 4)} for b in bins]

        return {
            "bins": bins,
            "perfect_line": perfect,
            "n_samples": len(y_true_arr),
        }

    # ===================== DUCKDB & POLARS ENTEGRASYONU =====================

    def export_calibration_audit_duckdb(
        self,
        db_path: str = ":memory:",
        table_name: str = "model_calibration_audit",
    ) -> None:
        """Kalibrasyon geçmişini ve alarmlarını DuckDB tablosuna kaydeder.

        Args:
            db_path: DuckDB veritabanı dosya yolu (veya ':memory:').
            table_name: Hedef tablo adı.
        """
        with self._lock:
            history = list(self._calibration_history)

        con = duckdb.connect(db_path)
        try:
            configure_duckdb_wal(con)
            con.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    timestamp TIMESTAMP WITH TIME ZONE,
                    brier_score DOUBLE,
                    ece DOUBLE,
                    miscalibration DOUBLE,
                    n_samples BIGINT,
                    brier_skill_score DOUBLE
                )
                """
            )

            for record in history:
                con.execute(
                    f"""
                    INSERT INTO {table_name} VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["timestamp"],
                        record["brier_score"],
                        record["ece"],
                        record["miscalibration"],
                        record["n_samples"],
                        record["brier_skill_score"],
                    ),
                )
            logger.info("kalibrasyon_denetim_kaydedildi", tablo=table_name, adet=len(history))
        finally:
            con.close()


    def read_calibration_audit_polars(
        self,
        db_path: str = ":memory:",
        table_name: str = "model_calibration_audit",
    ) -> pl.DataFrame:
        """DuckDB kalibrasyon denetim tablosunu Polars DataFrame olarak okur.

        Args:
            db_path: DuckDB dosya yolu.
            table_name: Tablo adı.

        Returns:
            Denetim kayıtlarını içeren Polars DataFrame.
        """
        con = duckdb.connect(db_path)
        try:
            configure_duckdb_wal(con)
            arrow_table = con.execute(f"SELECT * FROM {table_name} ORDER BY timestamp ASC").arrow()
            return pl.from_arrow(arrow_table)  # type: ignore[return-value]
        finally:
            con.close()

    # ===================== DAHİLİ YARDIMCI METOTLAR =====================

    def _compare_calibrators(self, y_true: np.ndarray, y_prob: np.ndarray) -> tuple[float, float, str]:
        """Platt ve Isotonic yöntemlerini sıfır sızıntılı train/val ayrımı ile karşılaştırır.

        Returns:
            (platt_ece, isotonic_ece, best_calibrator)
        """
        n = len(y_true)
        split_idx = int(n * 0.7)
        if split_idx < 20 or n - split_idx < 10:
            return 0.0, 0.0, "insufficient_data"

        y_train, y_val = y_true[:split_idx], y_true[split_idx:]
        p_train, p_val = y_prob[:split_idx], y_prob[split_idx:]

        # Platt
        try:
            lr = LogisticRegression(max_iter=1000, solver="lbfgs")
            lr.fit(p_train.reshape(-1, 1), y_train)
            platt_cal = lr.predict_proba(p_val.reshape(-1, 1))[:, 1]
            platt_ece = self._compute_ece(y_val, platt_cal)
        except Exception:
            platt_ece = 999.0

        # Isotonic
        try:
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            iso.fit(p_train, y_train)
            isotonic_cal = iso.predict(p_val)
            isotonic_ece = self._compute_ece(y_val, isotonic_cal)
        except Exception:
            isotonic_ece = 999.0

        if platt_ece < isotonic_ece:
            best = "platt"
        elif isotonic_ece < platt_ece:
            best = "isotonic"
        else:
            best = "equal"

        return platt_ece, isotonic_ece, best

    @staticmethod
    def _compute_nri(y_true: np.ndarray, y_prob: np.ndarray, threshold: float = 0.5) -> float:
        """Net Yeniden Sınıflandırma İndeksini (NRI) hesaplar."""
        preds = (y_prob > threshold).astype(int)
        correct = float(np.sum(preds == y_true))
        incorrect = float(np.sum(preds != y_true))
        total = len(y_true)
        if total == 0:
            return 0.0
        return (correct - incorrect) / total

    def _bootstrap_ece_ci(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        confidence: float = 0.95,
    ) -> tuple[float, float]:
        """Bootstrap yöntemiyle ECE için %95 güven aralığı hesaplar."""
        n = len(y_true)
        if n < 30:
            ece = self._compute_ece(y_true, y_prob)
            return ece, ece

        rng = np.random.default_rng(42)
        ece_samples = []
        for _ in range(self.bootstrap_n):
            indices = rng.choice(n, n, replace=True)
            ece_samples.append(self._compute_ece(y_true[indices], y_prob[indices]))

        alpha = (1.0 - confidence) / 2.0
        lower = float(np.percentile(ece_samples, alpha * 100.0))
        upper = float(np.percentile(ece_samples, (1.0 - alpha) * 100.0))
        return lower, upper

    def _bootstrap_brier_ci(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        confidence: float = 0.95,
    ) -> tuple[float, float]:
        """Bootstrap yöntemiyle Brier skoru için %95 güven aralığı hesaplar."""
        n = len(y_true)
        if n < 30:
            brier = float(brier_score_loss(y_true, y_prob))
            return brier, brier

        rng = np.random.default_rng(42)
        brier_samples = []
        for _ in range(self.bootstrap_n):
            indices = rng.choice(n, n, replace=True)
            try:
                brier_samples.append(float(brier_score_loss(y_true[indices], y_prob[indices])))
            except Exception:
                continue

        if not brier_samples:
            return 0.0, 1.0

        alpha = (1.0 - confidence) / 2.0
        lower = float(np.percentile(brier_samples, alpha * 100.0))
        upper = float(np.percentile(brier_samples, (1.0 - alpha) * 100.0))
        return lower, upper

    def _check_alerts_locked(self, result: CalibrationResult, n_samples: int) -> None:
        """Kilit altındayken kalibrasyon bozulma alarmlarını denetler."""
        now = datetime.now(UTC).isoformat()

        if len(self._calibration_history) >= 3:
            recent_ece = float(np.mean([h["ece"] for h in self._calibration_history[-3:]]))
            if recent_ece > self.ece_threshold * 2:
                self._alerts.append(
                    CalibrationAlert(
                        timestamp=now,
                        alert_type="DEGRADATION",
                        severity="HIGH",
                        message=f"ECE {recent_ece:.4f} — kalibrasyon bozuluyor",
                        metric="ece",
                        value=recent_ece,
                        threshold=self.ece_threshold,
                    )
                )

        if result.overconfident:
            self._alerts.append(
                CalibrationAlert(
                    timestamp=now,
                    alert_type="OVERCONFIDENCE",
                    severity="MEDIUM",
                    message=f"Model overconfident — ECE={result.expected_calibration_error:.4f}",
                    metric="ece",
                    value=result.expected_calibration_error,
                    threshold=self.overconfidence_threshold,
                )
            )

        if result.brier_skill_score < 0:
            self._alerts.append(
                CalibrationAlert(
                    timestamp=now,
                    alert_type="DEGRADATION",
                    severity="CRITICAL",
                    message=f"Brier Skill Score negatif ({result.brier_skill_score:.4f}) — baseline'dan kötü",
                    metric="brier_skill_score",
                    value=result.brier_skill_score,
                    threshold=0.0,
                )
            )

        if len(self._alerts) > 100:
            self._alerts = self._alerts[-100:]

    def _compute_ece(self, y_true: np.ndarray, y_prob: np.ndarray) -> float:
        """Expected Calibration Error (ECE) hesaplar."""
        try:
            bin_edges = np.linspace(0.0, 1.0, self.n_bins + 1)
            ece = 0.0

            for i in range(self.n_bins):
                if i == self.n_bins - 1:
                    mask = (y_prob >= bin_edges[i]) & (y_prob <= bin_edges[i + 1])
                else:
                    mask = (y_prob >= bin_edges[i]) & (y_prob < bin_edges[i + 1])

                if np.sum(mask) == 0:
                    continue

                bin_accuracy = float(np.mean(y_true[mask]))
                bin_confidence = float(np.mean(y_prob[mask]))
                bin_size = float(np.sum(mask)) / len(y_true)

                ece += bin_size * abs(bin_accuracy - bin_confidence)

            return ece
        except Exception as err:
            logger.warning("ece_hesaplama_hatasi", hata=str(err))
            return 0.0


__all__: Final[list[str]] = [
    "DEFAULT_ADAPTIVE_WINDOW",
    "DEFAULT_BOOTSTRAP_N",
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_DRIFT_THRESHOLD",
    "DEFAULT_ECE_THRESHOLD",
    "DEFAULT_N_BINS",
    "DEFAULT_OVERCONFIDENCE_THRESHOLD",
    "DEFAULT_WAL_SIZE",
    "CalibrationAlert",
    "CalibrationResult",
    "ModelCalibration",
    "RegimeCalibrationResult",
    "configure_duckdb_wal",
]
