"""ALPHA BIST — Model Sağlığı, Tahmin Kayması (Drift) ve Bozulma (Decay) İzleme Motoru (Nihai — ⭐⭐⭐⭐⭐).

Bu modül; üretimdeki makine öğrenimi modellerinin zaman içindeki performans metriklerini (IC,
Sharpe, Win Rate, Doğruluk vb.) anlık olarak izler, Kolmogorov-Smirnov (KS) testi ile tahmin
dağılımındaki sapmaları (Prediction Drift) tespit eder, z-skoru tabanlı model performans erimesini
(Model Decay) belirler ve kritik eşik aşımlarında otomatik yeniden eğitme (Auto-Retrain) tetikleyicisi
ile uyarı (Alert) mekanizmasını devreye sokar.

Temel Yetenekler:
- Zaman Serisi Performans Takibi: Kayan pencere (Rolling Window) bazlı ortalama, std ve z-skoru
- Tahmin Dağılım Kayması (Prediction Drift): İki örneklemli KS testi ile p-değeri analizi
- Model Bozulması (Decay Detection): Negatif z-skoru eşiği ile performans erimesini yakalama
- Otomatik Yeniden Eğitim (Auto-Retrain Trigger): Kritik seviyede kayıtlı geri çağrıları (callbacks) yürütme
- Model Sağlık Skoru (Health Score): 0-100 arası genel sağlık notu (A/B/C/D)
- Polars DataFrame üzerinden metrik ve tahmin geçmişi çıktısı (`get_metrics_polars`)
- DuckDB üzerinde SSD korumalı WAL ile izleme ve alarm denetim izi
- İş parçacığı güvenliği (`threading.RLock`) ve fail-closed mimari
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import duckdb
import numpy as np
import orjson
import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

    import polars as pl

logger = structlog.get_logger(__name__)

# --- Sabitler ---
DEFAULT_DECAY_Z_THRESHOLD: Final[float] = -2.0
DEFAULT_RETRAIN_Z_THRESHOLD: Final[float] = -3.0
DEFAULT_MIN_HISTORY: Final[int] = 10
DEFAULT_WINDOW_SIZE: Final[int] = 20
DEFAULT_ALERT_COOLDOWN_MINUTES: Final[int] = 60
DEFAULT_MAX_PREDICTION_HISTORY: Final[int] = 2000
DEFAULT_MAX_ALERTS_HISTORY: Final[int] = 500
DEFAULT_DUCKDB_PATH: Final[str] = "data/model_monitor.duckdb"
DEFAULT_EPSILON: Final[float] = 1e-8
DEFAULT_MIN_STD: Final[float] = 0.001  # Sıfır varyans durumunda z-skoru patlamasını önleyen taban std


class AlertLevel(StrEnum):
    """Alarm ciddiyet seviyeleri."""

    OK = "OK"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertType(StrEnum):
    """Alarm türleri."""

    DECAY = "DECAY"
    DRIFT = "DRIFT"
    RETRAIN = "RETRAIN"
    PERFORMANCE = "PERFORMANCE"


class PerformanceTrend(StrEnum):
    """Performans trendi eğilimleri."""

    IMPROVING = "improving"
    DEGRADING = "degrading"
    STABLE = "stable"


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
class MonitorReport:
    """Model performans bozulma ve izleme raporu veri modeli."""

    model_id: str
    metric_name: str
    current_value: float
    historical_mean: float
    historical_std: float
    z_score: float
    decay_detected: bool
    retrain_recommended: bool
    alert_level: AlertLevel | str
    trend: PerformanceTrend | str = PerformanceTrend.STABLE

    def to_dict(self) -> dict[str, Any]:
        """Raporu sözlük formatına dönüştürür."""
        return {
            "model_id": self.model_id,
            "metric_name": self.metric_name,
            "current_value": round(self.current_value, 4),
            "historical_mean": round(self.historical_mean, 4),
            "historical_std": round(self.historical_std, 4),
            "z_score": round(self.z_score, 4),
            "decay_detected": self.decay_detected,
            "retrain_recommended": self.retrain_recommended,
            "alert_level": str(self.alert_level),
            "trend": str(self.trend),
        }

    def to_orjson_bytes(self) -> bytes:
        """Raporu orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MonitorReport:
        """Sözlükten MonitorReport nesnesi oluşturur."""
        return cls(
            model_id=str(data.get("model_id", "")),
            metric_name=str(data.get("metric_name", "")),
            current_value=float(data.get("current_value", 0.0)),
            historical_mean=float(data.get("historical_mean", 0.0)),
            historical_std=float(data.get("historical_std", 0.0)),
            z_score=float(data.get("z_score", 0.0)),
            decay_detected=bool(data.get("decay_detected", False)),
            retrain_recommended=bool(data.get("retrain_recommended", False)),
            alert_level=AlertLevel(str(data.get("alert_level", "OK"))),
            trend=PerformanceTrend(str(data.get("trend", "stable"))),
        )

    def __repr__(self) -> str:
        return (
            f"MonitorReport(model='{self.model_id}', metric='{self.metric_name}', "
            f"cur={self.current_value:.4f}, z={self.z_score:.2f}, level='{self.alert_level}', trend='{self.trend}')"
        )


@dataclass(slots=True)
class Alert:
    """Model alarm kaydı veri modeli."""

    timestamp: str
    model_id: str
    alert_type: AlertType | str
    severity: AlertLevel | str
    message: str
    metric_name: str
    current_value: float
    threshold: float

    def to_dict(self) -> dict[str, Any]:
        """Alarm kaydını sözlüğe dönüştürür."""
        return {
            "timestamp": self.timestamp,
            "model_id": self.model_id,
            "alert_type": str(self.alert_type),
            "severity": str(self.severity),
            "message": self.message,
            "metric_name": self.metric_name,
            "current_value": round(self.current_value, 4),
            "threshold": round(self.threshold, 4),
        }

    def to_orjson_bytes(self) -> bytes:
        """Alarm kaydını orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Alert:
        """Sözlükten Alert nesnesi oluşturur."""
        return cls(
            timestamp=str(data.get("timestamp", "")),
            model_id=str(data.get("model_id", "")),
            alert_type=AlertType(str(data.get("alert_type", "PERFORMANCE"))),
            severity=AlertLevel(str(data.get("severity", "OK"))),
            message=str(data.get("message", "")),
            metric_name=str(data.get("metric_name", "")),
            current_value=float(data.get("current_value", 0.0)),
            threshold=float(data.get("threshold", 0.0)),
        )

    def __repr__(self) -> str:
        return (
            f"Alert(time='{self.timestamp}', model='{self.model_id}', "
            f"type='{self.alert_type}', sev='{self.severity}', msg='{self.message}')"
        )


@dataclass(slots=True)
class DriftReport:
    """Tahmin dağılım kayması (KS Test) raporu veri modeli."""

    drift_detected: bool
    ks_statistic: float = 0.0
    p_value: float = 1.0
    recent_mean: float = 0.0
    historical_mean: float = 0.0
    recent_std: float = 0.0
    historical_std: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Drift raporunu sözlüğe dönüştürür."""
        return {
            "drift_detected": self.drift_detected,
            "ks_statistic": round(self.ks_statistic, 4),
            "p_value": round(self.p_value, 4),
            "recent_mean": round(self.recent_mean, 4),
            "historical_mean": round(self.historical_mean, 4),
            "recent_std": round(self.recent_std, 4),
            "historical_std": round(self.historical_std, 4),
            "reason": self.reason,
        }

    def to_orjson_bytes(self) -> bytes:
        """Drift raporunu orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DriftReport:
        """Sözlükten DriftReport nesnesi oluşturur."""
        return cls(
            drift_detected=bool(data.get("drift_detected", False)),
            ks_statistic=float(data.get("ks_statistic", 0.0)),
            p_value=float(data.get("p_value", 1.0)),
            recent_mean=float(data.get("recent_mean", 0.0)),
            historical_mean=float(data.get("historical_mean", 0.0)),
            recent_std=float(data.get("recent_std", 0.0)),
            historical_std=float(data.get("historical_std", 0.0)),
            reason=str(data.get("reason", "")),
        )

    def __repr__(self) -> str:
        return f"DriftReport(drift={self.drift_detected}, ks={self.ks_statistic:.4f}, p_val={self.p_value:.4f})"


class ModelMonitor:
    """Model performansını, tahmin kaymasını ve sağlık skorunu izleyen motor."""

    def __init__(
        self,
        decay_z_threshold: float = DEFAULT_DECAY_Z_THRESHOLD,
        retrain_z_threshold: float = DEFAULT_RETRAIN_Z_THRESHOLD,
        min_history: int = DEFAULT_MIN_HISTORY,
        window_size: int = DEFAULT_WINDOW_SIZE,
        alert_cooldown_minutes: int = DEFAULT_ALERT_COOLDOWN_MINUTES,
        duckdb_path: str = DEFAULT_DUCKDB_PATH,
    ) -> None:
        """ModelMonitor motorunu başlatır.

        Args:
            decay_z_threshold: Bozulma (decay) alarmı için z-skoru alt eşiği (örn: -2.0).
            retrain_z_threshold: Yeniden eğitim (retrain) için kritik z-skoru eşiği (örn: -3.0).
            min_history: İstatistiksel analiz için asgari örneklem sayısı.
            window_size: Kayan pencere periyot boyutu.
            alert_cooldown_minutes: Tekrarlayan alarmlar arasındaki bekleme süresi (dakika).
            duckdb_path: Denetim izi DuckDB veritabanı yolu.
        """
        self._lock = threading.RLock()
        self.decay_z_threshold = float(decay_z_threshold)
        self.retrain_z_threshold = float(retrain_z_threshold)
        self.min_history = int(min_history)
        self.window_size = int(window_size)
        self.alert_cooldown_minutes = int(alert_cooldown_minutes)
        self.duckdb_path = duckdb_path

        self._metric_history: dict[str, list[tuple[str, float]]] = {}
        self._prediction_history: list[dict[str, Any]] = []
        self._alerts: list[Alert] = []
        self._last_alert: dict[str, datetime] = {}
        self._retrain_callbacks: list[Callable[[str, MonitorReport], Any]] = []

        self._init_duckdb()

    def _init_duckdb(self) -> None:
        """DuckDB denetim tablosunu hazırlar."""
        try:
            db_file = Path(self.duckdb_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(str(db_file)) as conn:
                configure_duckdb_wal(conn)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS model_monitor_audit (
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        model_id VARCHAR,
                        metric_name VARCHAR,
                        current_value DOUBLE,
                        z_score DOUBLE,
                        alert_level VARCHAR,
                        trend VARCHAR
                    );
                    CREATE TABLE IF NOT EXISTS model_monitor_alerts (
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        model_id VARCHAR,
                        alert_type VARCHAR,
                        severity VARCHAR,
                        message VARCHAR,
                        metric_name VARCHAR,
                        current_value DOUBLE,
                        threshold DOUBLE
                    );
                """)
        except Exception as exc:
            logger.warning("DuckDB monitor denetim tablosu hazirlanamadi", hata=str(exc))

    def record_metric(self, metric_name: str, value: float, model_id: str = "") -> MonitorReport:
        """Yeni bir model performans metriğini kaydeder ve bozulma kontrolü yapar.

        Args:
            metric_name: Metrik adı ('ic', 'sharpe', 'win_rate' vb.).
            value: Metrik değeri.
            model_id: Modeli niteleyen kimlik.

        Returns:
            MonitorReport nesnesi.
        """
        with self._lock:
            safe_val = float(value) if np.isfinite(value) else 0.0
            ts = datetime.now(UTC).isoformat()

            if metric_name not in self._metric_history:
                self._metric_history[metric_name] = []

            self._metric_history[metric_name].append((ts, safe_val))

            # Bellek koruması: maksimum periyot tut
            max_len = self.window_size * 5
            if len(self._metric_history[metric_name]) > max_len:
                self._metric_history[metric_name] = self._metric_history[metric_name][-max_len:]

            report = self.check_decay(metric_name, model_id)
            if str(report.alert_level) in (AlertLevel.WARNING, AlertLevel.CRITICAL):
                self._emit_alert(report, model_id)

            self._record_audit(report)
            return report

    def record_prediction(self, prediction: float, actual: float | None = None, ticker: str = "") -> None:
        """Canlı model tahminini ve gerçekleşen hedefi kaydeder.

        Args:
            prediction: Model tahmini skoru.
            actual: Gerçekleşen getiri veya yön (biliniyorsa).
            ticker: İlgili hisse senedi kodu.
        """
        with self._lock:
            p_val = float(prediction) if np.isfinite(prediction) else 0.0
            a_val = float(actual) if (actual is not None and np.isfinite(actual)) else None

            is_correct = None
            if a_val is not None:
                is_correct = bool((p_val > 0.50 and a_val > 0.0) or (p_val <= 0.50 and a_val <= 0.0))

            self._prediction_history.append({
                "prediction": p_val,
                "actual": a_val,
                "ticker": ticker,
                "timestamp": datetime.now(UTC).isoformat(),
                "correct": is_correct,
            })

            # Bellek koruması
            if len(self._prediction_history) > DEFAULT_MAX_PREDICTION_HISTORY:
                self._prediction_history = self._prediction_history[-DEFAULT_MAX_PREDICTION_HISTORY:]

    def record_predictions(
        self,
        predictions: list[float],
        actuals: list[float] | None = None,
        ticker: str = "",
        model_id: str = "",
    ) -> None:
        """Toplu tahmin listesini kaydeder.

        Args:
            predictions: Model tahmin listesi.
            actuals: Gerçekleşen değerler listesi (opsiyonel).
            ticker: Hisse kodu.
            model_id: Model kimliği.
        """
        for i, pred in enumerate(predictions):
            act = actuals[i] if actuals and i < len(actuals) else None
            self.record_prediction(prediction=pred, actual=act, ticker=ticker)

    def check_decay(self, metric_name: str = "ic", model_id: str = "") -> MonitorReport:
        """Belirtilen metrik için performans bozulmasını (Decay) analiz eder.

        Args:
            metric_name: İncelenecek metrik adı.
            model_id: Model kimliği.

        Returns:
            MonitorReport nesnesi.
        """
        with self._lock:
            history = self._metric_history.get(metric_name, [])
            values = [v for _, v in history if np.isfinite(v)]

            if len(values) < self.min_history:
                return MonitorReport(
                    model_id=model_id,
                    metric_name=metric_name,
                    current_value=float(values[-1]) if values else 0.0,
                    historical_mean=float(np.mean(values)) if values else 0.0,
                    historical_std=0.0,
                    z_score=0.0,
                    decay_detected=False,
                    retrain_recommended=False,
                    alert_level=AlertLevel.OK,
                    trend=PerformanceTrend.STABLE,
                )

            recent_len = max(2, min(self.window_size, len(values) // 2))
            recent = values[-recent_len:]
            historical = values[:-recent_len] if len(values) > recent_len else values

            current_val = float(np.mean(recent))
            hist_mean = float(np.mean(historical))
            hist_std = float(np.std(historical)) if len(historical) > 1 else DEFAULT_MIN_STD

            z_score = (current_val - hist_mean) / max(hist_std, DEFAULT_MIN_STD)
            trend = self._compute_trend(values)

            decay_detected = bool(z_score < self.decay_z_threshold)
            retrain_recommended = bool(z_score < self.retrain_z_threshold)

            if retrain_recommended:
                alert_level = AlertLevel.CRITICAL
            elif decay_detected:
                alert_level = AlertLevel.WARNING
            else:
                alert_level = AlertLevel.OK

            return MonitorReport(
                model_id=model_id,
                metric_name=metric_name,
                current_value=round(current_val, 4),
                historical_mean=round(hist_mean, 4),
                historical_std=round(hist_std, 4),
                z_score=round(z_score, 4),
                decay_detected=decay_detected,
                retrain_recommended=retrain_recommended,
                alert_level=alert_level,
                trend=trend,
            )

    def check_prediction_drift(
        self,
        model_id: str = "",
        recent_predictions: list[float] | None = None,
    ) -> DriftReport:
        """Tahmin dağılımındaki kaymayı (Kolmogorov-Smirnov Testi) kontrol eder.

        Args:
            model_id: Model kimliği.
            recent_predictions: İsteğe bağlı yeni/anlık tahmin listesi (verilirse tarihsel veriyle kıyaslanır).

        Returns:
            DriftReport nesnesi.
        """
        with self._lock:
            preds = [p["prediction"] for p in self._prediction_history if np.isfinite(p["prediction"])]

            if recent_predictions is not None:
                recent = [float(p) for p in recent_predictions if np.isfinite(p)]
                historical = preds
                if len(recent) < 5 or len(historical) < 5:
                    return DriftReport(drift_detected=False, reason="Yetersiz karsilastirma verisi")
            else:
                if len(preds) < self.min_history * 2:
                    return DriftReport(drift_detected=False, reason="Yetersiz tahmin gecmisi")
                recent_len = min(self.window_size, len(preds) // 2)
                recent = preds[-recent_len:]
                historical = preds[:-recent_len]

            try:
                from scipy import stats

                ks_stat, p_val = stats.ks_2samp(historical, recent)
                drift_detected = bool(p_val < 0.05)
                return DriftReport(
                    drift_detected=drift_detected,
                    ks_statistic=round(float(ks_stat), 4),
                    p_value=round(float(p_val), 4),
                    recent_mean=round(float(np.mean(recent)), 4),
                    historical_mean=round(float(np.mean(historical)), 4),
                    recent_std=round(float(np.std(recent)), 4),
                    historical_std=round(float(np.std(historical)), 4),
                    reason="KS p-degeri < 0.05 esigi asildi" if drift_detected else "Normal dagilim",
                )
            except Exception as ex:
                logger.debug("KS drift hesaplama istisnasi", hata=str(ex))
                # Scipy yoksa ortalama ve std karşılaştırma fallback'i
                h_mean = float(np.mean(historical))
                r_mean = float(np.mean(recent))
                h_std = float(np.std(historical))
                drift_detected = abs(r_mean - h_mean) > (2.0 * max(h_std, DEFAULT_EPSILON))
                return DriftReport(
                    drift_detected=drift_detected,
                    ks_statistic=0.0,
                    p_value=0.01 if drift_detected else 0.50,
                    recent_mean=round(r_mean, 4),
                    historical_mean=round(h_mean, 4),
                    recent_std=round(float(np.std(recent)), 4),
                    historical_std=round(h_std, 4),
                    reason="Ortalama kaymasi fallback testi",
                )

    def get_win_rate(self, window: int | None = None) -> float:
        """Son periyottaki yön doğruluğu (Win Rate) oranını hesaplar.

        Args:
            window: Dikkate alınacak son tahmin sayısı (None ise tümü).

        Returns:
            Kazanma oranı [0.0, 1.0].
        """
        with self._lock:
            preds = self._prediction_history[-window:] if window else self._prediction_history
            valid_cases = [p for p in preds if p.get("correct") is not None]
            if not valid_cases:
                return 0.0
            correct_cnt = sum(1 for p in valid_cases if p["correct"])
            return round(float(correct_cnt) / float(len(valid_cases)), 4)

    def get_health_score(self, model_id: str = "") -> dict[str, Any]:
        """Modelin anlık genel sağlık puanını (0-100) ve harf notunu (A/B/C/D) hesaplar.

        Args:
            model_id: Model kimliği.

        Returns:
            Sağlık skoru, harf notu ve bileşen detayları sözlüğü.
        """
        with self._lock:
            scores: list[float] = []
            details: dict[str, Any] = {}

            # Metrik sağlığı
            for metric_name in self._metric_history:
                report = self.check_decay(metric_name, model_id)
                if str(report.alert_level) == AlertLevel.OK:
                    m_score = 100.0
                elif str(report.alert_level) == AlertLevel.WARNING:
                    m_score = 50.0
                else:
                    m_score = 10.0
                scores.append(m_score)
                details[metric_name] = {
                    "score": m_score,
                    "z_score": report.z_score,
                    "trend": str(report.trend),
                }

            # Tahmin kayması
            drift_rep = self.check_prediction_drift()
            if drift_rep.drift_detected:
                scores.append(30.0)
                details["prediction_drift"] = "DRIFT_DETECTED"
            else:
                scores.append(90.0)
                details["prediction_drift"] = "OK"

            # Win rate (Sadece doğrulanmış gerçek değerler varsa değerlendirmeye katılır)
            valid_cases = [p for p in self._prediction_history if p.get("correct") is not None]
            if valid_cases:
                wr = self.get_win_rate()
                if wr >= 0.55:
                    scores.append(90.0)
                elif wr >= 0.50:
                    scores.append(70.0)
                elif wr >= 0.45:
                    scores.append(50.0)
                else:
                    scores.append(20.0)
                details["win_rate"] = wr
            else:
                details["win_rate"] = None

            overall = int(round(float(np.mean(scores)))) if scores else 0
            grade = "A" if overall >= 80 else "B" if overall >= 60 else "C" if overall >= 40 else "D"

            return {
                "overall_score": overall,
                "health_score": overall,
                "grade": grade,
                "details": details,
                "n_metrics": len(self._metric_history),
                "n_predictions": len(self._prediction_history),
            }

    def get_dashboard_data(self, model_id: str = "") -> dict[str, Any]:
        """İzleme paneli (Monitoring Dashboard) için derlenmiş zaman serisi ve özet veriyi sunar."""
        with self._lock:
            metric_series: dict[str, Any] = {}
            for metric_name, history in self._metric_history.items():
                timestamps = [h[0] for h in history[-50:]]
                values = [h[1] for h in history[-50:]]
                metric_series[metric_name] = {
                    "timestamps": timestamps,
                    "values": [round(v, 4) for v in values],
                    "current": round(values[-1], 4) if values else 0.0,
                    "mean": round(float(np.mean(values)), 4) if values else 0.0,
                }

            recent_alerts = [a.to_dict() for a in self._alerts[-10:]]
            health = self.get_health_score(model_id)

            return {
                "model_id": model_id,
                "health": health,
                "metric_series": metric_series,
                "recent_alerts": recent_alerts,
                "prediction_drift": self.check_prediction_drift().to_dict(),
                "win_rate": self.get_win_rate(),
                "summary": self.get_summary(),
            }

    def get_summary(self) -> dict[str, Any]:
        """Tüm metrikler ve alarmlar için özet durum sözlüğü üretir."""
        with self._lock:
            summaries: dict[str, Any] = {}
            for metric_name in self._metric_history:
                rep = self.check_decay(metric_name)
                summaries[metric_name] = {
                    "current": rep.current_value,
                    "historical_mean": rep.historical_mean,
                    "z_score": rep.z_score,
                    "alert": str(rep.alert_level),
                    "trend": str(rep.trend),
                }

            return {
                "metrics": summaries,
                "win_rate": self.get_win_rate(),
                "total_predictions": len(self._prediction_history),
                "prediction_drift": self.check_prediction_drift().to_dict(),
                "n_alerts": len(self._alerts),
                "health_score": self.get_health_score().get("overall_score", 0),
            }

    def get_alerts(self, severity: AlertLevel | str | None = None) -> list[dict[str, Any]]:
        """Oluşan alarmları ciddiyet derecesine göre filtreleyip listeler."""
        with self._lock:
            alerts = self._alerts
            if severity:
                alerts = [a for a in alerts if str(a.severity) == str(severity)]
            return [a.to_dict() for a in alerts[-50:]]

    def register_retrain_callback(self, callback: Callable[[str, MonitorReport], Any]) -> None:
        """Model bozulduğunda tetiklenecek geri çağrı (Callback) fonksiyonunu kaydeder."""
        with self._lock:
            self._retrain_callbacks.append(callback)
            if len(self._retrain_callbacks) > 100:
                self._retrain_callbacks = self._retrain_callbacks[-100:]

    def get_metrics_polars(self, metric_name: str = "ic", model_id: str = "") -> pl.DataFrame:
        """Belirtilen metriğin tarihsel geçmişini Polars DataFrame olarak döndürür.

        Args:
            metric_name: Metrik adı.
            model_id: Model kimliği (opsiyonel filtre).

        Returns:
            Polars DataFrame `(timestamp, value)`.
        """
        import polars as pl

        with self._lock:
            history = self._metric_history.get(metric_name, [])
            if not history:
                return pl.DataFrame(schema={"timestamp": pl.Utf8, "value": pl.Float64})
            return pl.DataFrame({
                "timestamp": [h[0] for h in history],
                "value": [h[1] for h in history],
            })

    def _compute_trend(self, values: list[float]) -> PerformanceTrend:
        """Metrik değerlerinin yönsel eğilimini hesaplar."""
        if len(values) < 6:
            return PerformanceTrend.STABLE

        recent_vals = values[-5:]
        older_vals = values[:-5]
        if not older_vals:
            return PerformanceTrend.STABLE

        recent = float(np.mean(recent_vals))
        older = float(np.mean(older_vals))

        denom = max(abs(older), DEFAULT_EPSILON)
        change = (recent - older) / denom

        if change > 0.05:
            return PerformanceTrend.IMPROVING
        elif change < -0.05:
            return PerformanceTrend.DEGRADING
        else:
            return PerformanceTrend.STABLE

    def _emit_alert(self, report: MonitorReport, model_id: str) -> None:
        """Alarm nesnesi oluşturur, kaydeder ve geri çağrıları tetikler."""
        alert_key = f"{model_id}_{report.metric_name}"
        now = datetime.now(UTC)
        last = self._last_alert.get(alert_key)
        if last and (now - last).total_seconds() < float(self.alert_cooldown_minutes * 60):
            return

        alert_type = AlertType.DECAY if report.decay_detected else AlertType.PERFORMANCE
        alert = Alert(
            timestamp=now.isoformat(),
            model_id=model_id,
            alert_type=alert_type,
            severity=report.alert_level,
            message=f"{report.metric_name}: {report.current_value} (z={report.z_score}, trend={report.trend})",
            metric_name=report.metric_name,
            current_value=report.current_value,
            threshold=self.decay_z_threshold,
        )

        self._alerts.append(alert)
        if len(self._alerts) > DEFAULT_MAX_ALERTS_HISTORY:
            self._alerts = self._alerts[-DEFAULT_MAX_ALERTS_HISTORY:]
        self._last_alert[alert_key] = now

        self._record_alert_db(alert)

        logger.warning(
            "Model performans alarmi tetiklendi",
            model_id=model_id,
            seviye=str(report.alert_level),
            metrik=report.metric_name,
            z_skor=report.z_score,
        )

        # Otomatik yeniden eğitim tetikleyicisi
        if report.retrain_recommended and self._retrain_callbacks:
            for cb in self._retrain_callbacks:
                try:
                    cb(model_id, report)
                except Exception as ex:
                    logger.error("Yeniden egitim callback cagrisi basarisiz", hata=str(ex))

    def _record_audit(self, report: MonitorReport) -> None:
        """İzleme kaydını DuckDB'ye yazar."""
        try:
            with duckdb.connect(self.duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO model_monitor_audit (
                        model_id, metric_name, current_value, z_score, alert_level, trend
                    ) VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    [
                        str(report.model_id),
                        str(report.metric_name),
                        float(report.current_value),
                        float(report.z_score),
                        str(report.alert_level),
                        str(report.trend),
                    ],
                )
        except Exception as exc:
            logger.debug("DuckDB monitor denetim kaydi atlandi", hata=str(exc))

    def _record_alert_db(self, alert: Alert) -> None:
        """Alarm kaydını DuckDB'ye yazar."""
        try:
            with duckdb.connect(self.duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO model_monitor_alerts (
                        model_id, alert_type, severity, message, metric_name, current_value, threshold
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    [
                        str(alert.model_id),
                        str(alert.alert_type),
                        str(alert.severity),
                        str(alert.message),
                        str(alert.metric_name),
                        float(alert.current_value),
                        float(alert.threshold),
                    ],
                )
        except Exception as exc:
            logger.debug("DuckDB alarm kaydi atlandi", hata=str(exc))

    def get_audit_as_polars(self) -> pl.DataFrame:
        """DuckDB'deki izleme denetim kayıtlarını Polars DataFrame olarak döndürür."""
        import polars as pl

        with self._lock:
            try:
                with duckdb.connect(self.duckdb_path) as conn:
                    return conn.execute("SELECT * FROM model_monitor_audit ORDER BY timestamp DESC").pl()
            except Exception as exc:
                logger.warning("DuckDB izleme kayitlari okunamadi", hata=str(exc))
                return pl.DataFrame()

    def get_alerts_as_polars(self) -> pl.DataFrame:
        """DuckDB'deki alarm kayıtlarını Polars DataFrame olarak döndürür."""
        import polars as pl

        with self._lock:
            try:
                with duckdb.connect(self.duckdb_path) as conn:
                    return conn.execute("SELECT * FROM model_monitor_alerts ORDER BY timestamp DESC").pl()
            except Exception as exc:
                logger.warning("DuckDB alarm kayitlari okunamadi", hata=str(exc))
                return pl.DataFrame()

    def __repr__(self) -> str:
        return (
            f"ModelMonitor(metrics={len(self._metric_history)}, preds={len(self._prediction_history)}, "
            f"alerts={len(self._alerts)})"
        )


# Singleton
model_monitor = ModelMonitor()

__all__: Final[list[str]] = [
    "DEFAULT_ALERT_COOLDOWN_MINUTES",
    "DEFAULT_DECAY_Z_THRESHOLD",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EPSILON",
    "DEFAULT_MAX_ALERTS_HISTORY",
    "DEFAULT_MAX_PREDICTION_HISTORY",
    "DEFAULT_MIN_HISTORY",
    "DEFAULT_MIN_STD",
    "DEFAULT_RETRAIN_Z_THRESHOLD",
    "DEFAULT_WINDOW_SIZE",
    "Alert",
    "AlertLevel",
    "AlertType",
    "DriftReport",
    "ModelMonitor",
    "MonitorReport",
    "PerformanceTrend",
    "configure_duckdb_wal",
    "model_monitor",
]
