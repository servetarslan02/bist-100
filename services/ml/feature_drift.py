# c:\Users\serve\Downloads\Compressed\bist-100\services\ml\feature_drift.py
"""ALPHA BIST — Öznitelik Kayması Tespit Motoru (Feature Drift Detector).

SHAP geçmişi izleme, Nüfus Kararlılık İndeksi (PSI - Population Stability Index),
öznitelik önem trendi analizi, çoklu metrik kayma tespiti, otomatik iyileştirme
önerileri ve sistemik drift alarmları sağlar.

Kullanım Prensipleri:
- Sıfır Veri Sızıntısı: Referans ve mevcut dönem dağılımları zaman serisi sırasına uygun ayrıştırılır.
- Eşzamanlılık Güvenliği: `threading.RLock()` ile çoklu iş parçacığı koruması.
- DuckDB Entegrasyonu: SSD korumalı WAL ayarları ile denetim izi kaydı.
- Polars Desteği: Doğrudan Polars DataFrame üzerinden vektörize drift ve dağılım karşılaştırması.
- Fail-Closed Mimarisi: Sabit değerli öznitelikler, NaN/Inf taşmaları ve sıfıra bölmelerde güvenli guard'lar.
"""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

logger = structlog.get_logger(__name__)

# ==============================================================================
# 1. STANDART YAPILANDIRMA SABİTLERİ (DEFAULT_*)
# ==============================================================================
DEFAULT_PSI_THRESHOLD: Final[float] = 0.20
DEFAULT_IMPORTANCE_CHANGE_THRESHOLD: Final[float] = 0.30
DEFAULT_N_BINS: Final[int] = 10
DEFAULT_ALERT_COOLDOWN_HOURS: Final[int] = 24
DEFAULT_MAX_SHAP_HISTORY: Final[int] = 1000
DEFAULT_MAX_DIST_HISTORY: Final[int] = 500
DEFAULT_MAX_TICKER_HISTORY: Final[int] = 500

DEFAULT_PSI_STABLE_THRESHOLD: Final[float] = 0.10
DEFAULT_PSI_SIGNIFICANT_THRESHOLD: Final[float] = 0.25
DEFAULT_PSI_CRITICAL_THRESHOLD: Final[float] = 1.00
DEFAULT_CORRELATION_DRIFT_THRESHOLD: Final[float] = 0.30

DEFAULT_DUCKDB_PATH: Final[str] = "data/ml_audit.duckdb"
DEFAULT_WAL_AUTO_CHECKPOINT: Final[str] = "10MB"


def configure_duckdb_wal(
    con: duckdb.DuckDBPyConnection,
    checkpoint_size: str = DEFAULT_WAL_AUTO_CHECKPOINT,
) -> None:
    """DuckDB bağlantısını SSD korumalı WAL sınırları ile optimize eder.

    Args:
        con: Yapılandırılacak DuckDB bağlantısı.
        checkpoint_size: WAL otomatik kontrol noktası boyutu (örn: '10MB').
    """
    try:
        con.execute(f"PRAGMA wal_autocheckpoint='{checkpoint_size}';")
    except Exception as e:
        logger.warning("duckdb_wal_config_failed", error=str(e))


# ==============================================================================
# 2. ENUM VE VERİ MODELLERİ
# ==============================================================================
class DriftSeverity(StrEnum):
    """Kayma ciddiyet seviyesi."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DriftTrend(StrEnum):
    """Öznitelik önemi yön trendi."""

    STABLE = "stable"
    INCREASING = "increasing"
    DECREASING = "decreasing"
    VOLATILE = "volatile"


@dataclass(slots=True)
class DriftReport:
    """Tek bir öznitelik için kapsamlı drift tespit raporu."""

    feature_name: str
    psi: float
    drift_detected: bool
    importance_trend: str
    current_importance: float
    historical_importance: float
    alert: bool
    severity: str = DriftSeverity.LOW.value
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Raporu standart sözlük formatına dönüştürür."""
        return {
            "feature_name": self.feature_name,
            "psi": float(self.psi),
            "drift_detected": bool(self.drift_detected),
            "importance_trend": str(self.importance_trend),
            "current_importance": float(self.current_importance),
            "historical_importance": float(self.historical_importance),
            "alert": bool(self.alert),
            "severity": str(self.severity),
            "remediation": str(self.remediation),
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı serileştirilmiş orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DriftReport:
        """Sözlükten DriftReport nesnesi oluşturur."""
        return cls(
            feature_name=str(data.get("feature_name", "")),
            psi=float(data.get("psi", 0.0)),
            drift_detected=bool(data.get("drift_detected", False)),
            importance_trend=str(data.get("importance_trend", DriftTrend.STABLE.value)),
            current_importance=float(data.get("current_importance", 0.0)),
            historical_importance=float(data.get("historical_importance", 0.0)),
            alert=bool(data.get("alert", False)),
            severity=str(data.get("severity", DriftSeverity.LOW.value)),
            remediation=str(data.get("remediation", "")),
        )

    def __repr__(self) -> str:
        """Kullanıcı dostu metin temsili."""
        return (
            f"DriftReport(feature='{self.feature_name}', psi={self.psi:.4f}, "
            f"drift={self.drift_detected}, trend='{self.importance_trend}', "
            f"sev='{self.severity}', alert={self.alert})"
        )


@dataclass(slots=True)
class DriftSummary:
    """Tüm öznitelikler genelindeki drift özeti ve eylem planı."""

    total_features: int
    drifted_features: int
    alert_features: int
    critical_features: int
    overall_drift_score: float
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Özeti sözlük formatına dönüştürür."""
        return {
            "total_features": int(self.total_features),
            "drifted_features": int(self.drifted_features),
            "alert_features": int(self.alert_features),
            "critical_features": int(self.critical_features),
            "overall_drift_score": float(self.overall_drift_score),
            "recommendations": list(self.recommendations),
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı serileştirilmiş orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DriftSummary:
        """Sözlükten DriftSummary nesnesi oluşturur."""
        return cls(
            total_features=int(data.get("total_features", 0)),
            drifted_features=int(data.get("drifted_features", 0)),
            alert_features=int(data.get("alert_features", 0)),
            critical_features=int(data.get("critical_features", 0)),
            overall_drift_score=float(data.get("overall_drift_score", 0.0)),
            recommendations=[str(r) for r in data.get("recommendations", [])],
        )

    def __repr__(self) -> str:
        """Kullanıcı dostu metin temsili."""
        return (
            f"DriftSummary(total={self.total_features}, drifted={self.drifted_features}, "
            f"critical={self.critical_features}, score={self.overall_drift_score:.4f})"
        )


# ==============================================================================
# 3. ÖZNİTELİK KAYMASI TESPİT MOTORU
# ==============================================================================
class FeatureDriftDetector:
    """BIST-100 öznitelik kayması tespiti ve uyarı motoru."""

    def __init__(
        self,
        psi_threshold: float = DEFAULT_PSI_THRESHOLD,
        importance_change_threshold: float = DEFAULT_IMPORTANCE_CHANGE_THRESHOLD,
        n_bins: int = DEFAULT_N_BINS,
        alert_cooldown_hours: int = DEFAULT_ALERT_COOLDOWN_HOURS,
    ) -> None:
        """FeatureDriftDetector motorunu başlatır.

        Args:
            psi_threshold: Drift kabul edilecek asgari PSI eşiği (örn: 0.20).
            importance_change_threshold: SHAP önem değişim eşiği (örn: 0.30).
            n_bins: PSI hesaplamasında kullanılacak dilim sayısı.
            alert_cooldown_hours: Tekrarlayan alarmlar arasındaki bekleme saati.

        Raises:
            ValueError: Parametreler sıfır veya negatif ise.
        """
        if psi_threshold <= 0 or importance_change_threshold <= 0 or n_bins < 2:
            raise ValueError("Gecersiz parametreler: psi_th ve importance_th pozitif, n_bins >= 2 olmalidir.")

        self._lock: Final[threading.RLock] = threading.RLock()
        self.psi_threshold: float = psi_threshold
        self.importance_change_threshold: float = importance_change_threshold
        self.n_bins: int = n_bins
        self.alert_cooldown_hours: int = alert_cooldown_hours

        self._shap_history: list[dict[str, Any]] = []
        self._feature_distributions: list[dict[str, np.ndarray]] = []
        self._drift_history: list[dict[str, Any]] = []
        self._last_alert: dict[str, datetime] = {}
        self._shap_by_ticker: dict[str, list[dict[str, Any]]] = {}

        logger.info(
            "feature_drift_detector_initialized",
            psi_threshold=self.psi_threshold,
            importance_change_th=self.importance_change_threshold,
            n_bins=self.n_bins,
        )

    def record_shap(self, shap_values: dict[str, float]) -> None:
        """Yeni bir eğitim veya tahmin döngüsü sonrası SHAP önem değerlerini kaydeder.

        Args:
            shap_values: Öznitelik adı -> mutlak SHAP önemi eşlemesi.
        """
        if not shap_values:
            return

        with self._lock:
            # Temizlenmiş ve doğrulanmış değerler
            clean_values: dict[str, Any] = {
                k: float(v) for k, v in shap_values.items() if np.isfinite(float(v))
            }
            clean_values["_timestamp"] = datetime.now(UTC).isoformat()

            self._shap_history.append(clean_values)
            if len(self._shap_history) > DEFAULT_MAX_SHAP_HISTORY:
                self._shap_history = self._shap_history[-DEFAULT_MAX_SHAP_HISTORY:]

    def record_distribution(self, feature_data: dict[str, np.ndarray]) -> None:
        """Dağılım tabanlı PSI hesabı için öznitelik dağılım dizilerini kaydeder.

        Args:
            feature_data: Öznitelik adı -> 1D numpy sayısal dizisi.
        """
        if not feature_data:
            return

        with self._lock:
            valid_arrays: dict[str, np.ndarray] = {}
            for k, arr in feature_data.items():
                if arr is None or len(arr) == 0:
                    continue
                np_arr = np.asarray(arr, dtype=np.float64)
                finite_mask = np.isfinite(np_arr)
                if np.any(finite_mask):
                    valid_arrays[k] = np_arr[finite_mask]

            if valid_arrays:
                self._feature_distributions.append(valid_arrays)
                if len(self._feature_distributions) > DEFAULT_MAX_DIST_HISTORY:
                    self._feature_distributions = self._feature_distributions[-DEFAULT_MAX_DIST_HISTORY:]

    def check_drift(self) -> list[DriftReport]:
        """Kayıtlı SHAP ve dağılım geçmişi üzerinden çok katmanlı drift analizi yürütür.

        Katmanlar:
        1. SHAP Importance Drift (z-score ve trend)
        2. Dağılım Tabanlı Population Stability Index (PSI)
        3. Korelasyon Yapısı Kayması (Correlation Drift)

        Returns:
            Her öznitelik için üretilmiş DriftReport listesi.
        """
        with self._lock:
            reports: list[DriftReport] = []

            if len(self._shap_history) < 2:
                return reports

            current_shap = self._shap_history[-1]
            historical_shap = self._shap_history[:-1]

            for feature in current_shap:
                if feature.startswith("_"):
                    continue

                current_imp = float(current_shap.get(feature, 0.0))
                historical_imps = [
                    float(h[feature])
                    for h in historical_shap
                    if feature in h and np.isfinite(float(h[feature]))
                ]

                if not historical_imps:
                    continue

                hist_mean = float(np.mean(historical_imps))
                hist_std = float(np.std(historical_imps)) if len(historical_imps) > 1 else 0.01
                hist_std = max(hist_std, 1e-4)

                trend = self._compute_trend(historical_imps, current_imp)
                importance_zscore = abs(current_imp - hist_mean) / hist_std

                severity = self._compute_severity(importance_zscore, trend)
                alert = (
                    importance_zscore > self.psi_threshold
                    or trend in (DriftTrend.INCREASING.value, DriftTrend.DECREASING.value, DriftTrend.VOLATILE.value)
                )
                remediation = self._suggest_remediation(feature, importance_zscore, trend, severity)

                reports.append(
                    DriftReport(
                        feature_name=feature,
                        psi=round(float(importance_zscore), 4),
                        drift_detected=importance_zscore > self.psi_threshold,
                        importance_trend=trend,
                        current_importance=round(float(current_imp), 4),
                        historical_importance=round(hist_mean, 4),
                        alert=alert,
                        severity=severity,
                        remediation=remediation,
                    )
                )

            # Dağılım tabanlı gerçek PSI analizi
            if len(self._feature_distributions) >= 2:
                self._check_distribution_drift(reports)

            # Korelasyon drift analizi
            if len(self._feature_distributions) >= 2:
                self._check_correlation_drift(reports)

            # Geçmiş kaydına ekle
            self._drift_history.append(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "n_drifted": sum(1 for r in reports if r.drift_detected),
                    "n_alerts": sum(1 for r in reports if r.alert),
                    "n_critical": sum(1 for r in reports if r.severity == DriftSeverity.CRITICAL.value),
                }
            )
            if len(self._drift_history) > DEFAULT_MAX_SHAP_HISTORY:
                self._drift_history = self._drift_history[-DEFAULT_MAX_SHAP_HISTORY:]

            return reports

    def get_summary(self) -> DriftSummary:
        """Tüm öznitelikler için genel sistemik drift durumunu ve önerileri özetler.

        Returns:
            DriftSummary nesnesi.
        """
        with self._lock:
            reports = self.check_drift()

            if not reports:
                return DriftSummary(
                    total_features=0,
                    drifted_features=0,
                    alert_features=0,
                    critical_features=0,
                    overall_drift_score=0.0,
                    recommendations=[],
                )

            drifted = [r for r in reports if r.drift_detected]
            alerts = [r for r in reports if r.alert]
            critical = [r for r in reports if r.severity == DriftSeverity.CRITICAL.value]

            drift_scores = [r.psi for r in reports]
            overall_score = float(np.mean(drift_scores)) if drift_scores else 0.0

            recommendations: list[str] = []
            if critical:
                recommendations.append(
                    f"KRİTİK: {len(critical)} öznitelikte şiddetli kayma var — model yeniden eğitimi zorunludur."
                )
            if len(drifted) > len(reports) * 0.3:
                drift_pct = int(len(drifted) / len(reports) * 100)
                recommendations.append(f"UYARI: Özniteliklerin %{drift_pct}'inde kayma tespit edildi.")
            if overall_score > self.psi_threshold:
                recommendations.append(
                    "Genel drift skoru eşik üstünde — öznitelik havuzunun gözden geçirilmesi önerilir."
                )

            summary = DriftSummary(
                total_features=len(reports),
                drifted_features=len(drifted),
                alert_features=len(alerts),
                critical_features=len(critical),
                overall_drift_score=round(overall_score, 4),
                recommendations=recommendations,
            )

            # DuckDB denetim tablosuna kaydet
            try:
                save_drift_summary_to_duckdb(summary)
            except Exception as e:
                logger.warning("save_drift_summary_to_duckdb_failed", error=str(e))

            return summary

    def get_alerts(self) -> list[DriftReport]:
        """Yalnızca uyarı durumundaki (alert=True) raporları döndürür."""
        with self._lock:
            return [r for r in self.check_drift() if r.alert]

    def get_critical_alerts(self) -> list[DriftReport]:
        """Yalnızca KRİTİK seviyedeki drift raporlarını döndürür."""
        with self._lock:
            return [r for r in self.check_drift() if r.severity == DriftSeverity.CRITICAL.value]

    def get_drift_history(self) -> list[dict[str, Any]]:
        """Sistemik drift geçmişinin kopyasını döndürür."""
        with self._lock:
            return list(self._drift_history)

    def get_history(self) -> list[dict[str, Any]]:
        """SHAP geçmiş kayıtlarının kopyasını döndürür."""
        with self._lock:
            return list(self._shap_history)

    def record_shap_per_ticker(
        self,
        ticker: str,
        shap_values: dict[str, float],
    ) -> None:
        """Hisse bazında öznitelik SHAP değerlerini kaydeder.

        Args:
            ticker: BIST hisse kodu (örn: THYAO).
            shap_values: Öznitelik önem değerleri.
        """
        if not ticker or not shap_values:
            return

        with self._lock:
            if ticker not in self._shap_by_ticker:
                self._shap_by_ticker[ticker] = []

            clean_values: dict[str, Any] = {
                k: float(v) for k, v in shap_values.items() if np.isfinite(float(v))
            }
            clean_values["_timestamp"] = datetime.now(UTC).isoformat()

            self._shap_by_ticker[ticker].append(clean_values)
            if len(self._shap_by_ticker[ticker]) > DEFAULT_MAX_TICKER_HISTORY:
                self._shap_by_ticker[ticker] = self._shap_by_ticker[ticker][-DEFAULT_MAX_TICKER_HISTORY:]

    def get_importance_time_series(
        self,
        feature_name: str,
        window: int = 30,
    ) -> dict[str, Any]:
        """Belirtilen özniteliğin zaman serisi önem geçmişini çıkarır.

        Args:
            feature_name: İncelenecek öznitelik adı.
            window: Son kaç kaydın inceleneceği.

        Returns:
            Zaman serisi değerleri, eğilimi ve istatistikleri içeren sözlük.
        """
        with self._lock:
            if len(self._shap_history) < 2:
                return {
                    "feature": feature_name,
                    "values": [],
                    "timestamps": [],
                    "trend": DriftTrend.STABLE.value,
                    "mean": 0.0,
                    "std": 0.0,
                }

            recent = self._shap_history[-window:]
            values = [float(h[feature_name]) for h in recent if feature_name in h and np.isfinite(float(h[feature_name]))]
            timestamps = [str(h.get("_timestamp", "")) for h in recent if feature_name in h]

            if not values:
                return {
                    "feature": feature_name,
                    "values": [],
                    "timestamps": [],
                    "trend": DriftTrend.STABLE.value,
                    "mean": 0.0,
                    "std": 0.0,
                }

            arr = np.array(values, dtype=np.float64)
            mean_val = float(np.mean(arr))
            std_val = float(np.std(arr))

            trend = DriftTrend.STABLE.value
            if len(values) >= 4:
                first_half = float(np.mean(arr[: len(arr) // 2]))
                second_half = float(np.mean(arr[len(arr) // 2 :]))
                change = (second_half - first_half) / max(abs(first_half), 0.001)

                if change > 0.2:
                    trend = DriftTrend.INCREASING.value
                elif change < -0.2:
                    trend = DriftTrend.DECREASING.value
                elif std_val > mean_val * 0.5:
                    trend = DriftTrend.VOLATILE.value

            return {
                "feature": feature_name,
                "values": [round(v, 6) for v in values],
                "timestamps": timestamps,
                "trend": trend,
                "mean": round(mean_val, 6),
                "std": round(std_val, 6),
            }

    def get_strengthening_features(
        self,
        threshold: float = 0.1,
    ) -> list[dict[str, Any]]:
        """Önemi tarihsel ortalamasına göre anlamlı derecede artan (güçlenen) öznitelikleri listeler.

        Args:
            threshold: Artış oranı eşiği.

        Returns:
            Güçlenen özniteliklerin azalan sırada listesi.
        """
        with self._lock:
            if len(self._shap_history) < 4:
                return []

            current = self._shap_history[-1]
            historical = self._shap_history[:-1]
            strengthening: list[dict[str, Any]] = []

            for feature in current:
                if feature.startswith("_"):
                    continue

                current_imp = float(current.get(feature, 0.0))
                historical_imps = [
                    float(h[feature]) for h in historical if feature in h and np.isfinite(float(h[feature]))
                ]

                if not historical_imps or current_imp <= 0.0:
                    continue

                hist_mean = float(np.mean(historical_imps))
                if hist_mean <= 0.0:
                    continue

                change_ratio = (current_imp - hist_mean) / hist_mean
                if change_ratio > threshold:
                    strengthening.append(
                        {
                            "feature": feature,
                            "current_importance": round(current_imp, 6),
                            "historical_importance": round(hist_mean, 6),
                            "change_ratio": round(change_ratio, 4),
                            "trend": "strengthening",
                        }
                    )

            return sorted(strengthening, key=lambda x: x["change_ratio"], reverse=True)

    def get_weakening_features(
        self,
        threshold: float = 0.1,
    ) -> list[dict[str, Any]]:
        """Önemi tarihsel ortalamasına göre anlamlı derecede azalan (zayıflayan) öznitelikleri listeler.

        Args:
            threshold: Azalma oranı eşiği.

        Returns:
            Zayıflayan özniteliklerin listesi.
        """
        with self._lock:
            if len(self._shap_history) < 4:
                return []

            current = self._shap_history[-1]
            historical = self._shap_history[:-1]
            weakening: list[dict[str, Any]] = []

            for feature in current:
                if feature.startswith("_"):
                    continue

                current_imp = float(current.get(feature, 0.0))
                historical_imps = [
                    float(h[feature]) for h in historical if feature in h and np.isfinite(float(h[feature]))
                ]

                if not historical_imps:
                    continue

                hist_mean = float(np.mean(historical_imps))
                if hist_mean <= 0.0:
                    continue

                change_ratio = (current_imp - hist_mean) / hist_mean
                if change_ratio < -threshold:
                    weakening.append(
                        {
                            "feature": feature,
                            "current_importance": round(current_imp, 6),
                            "historical_importance": round(hist_mean, 6),
                            "change_ratio": round(change_ratio, 4),
                            "trend": "weakening",
                        }
                    )

            return sorted(weakening, key=lambda x: x["change_ratio"])

    def get_ticker_shap_summary(
        self,
        ticker: str,
    ) -> dict[str, Any]:
        """Belirtilen hisse senedi için kaydedilmiş öznitelik önem özetini sunar.

        Args:
            ticker: BIST sembolü.

        Returns:
            Hisseye özel SHAP özet sözlüğü.
        """
        with self._lock:
            if ticker not in self._shap_by_ticker:
                return {
                    "ticker": ticker,
                    "n_records": 0,
                    "top_features": [],
                    "latest_shap": {},
                }

            records = self._shap_by_ticker[ticker]
            latest = records[-1] if records else {}

            feature_sums: dict[str, float] = {}
            for r in records:
                for k, v in r.items():
                    if not k.startswith("_"):
                        feature_sums[k] = feature_sums.get(k, 0.0) + abs(float(v))

            n = len(records)
            avg_importance = {k: round(v / n, 6) for k, v in feature_sums.items()}
            top_features = sorted(avg_importance.items(), key=lambda x: x[1], reverse=True)[:10]

            return {
                "ticker": ticker,
                "n_records": n,
                "top_features": [{"feature": f, "importance": i} for f, i in top_features],
                "latest_shap": {k: v for k, v in latest.items() if not k.startswith("_")},
            }

    def _compute_trend(self, historical: list[float], current: float) -> str:
        """Tarihsel değerler ile mevcut değer arasındaki trendi belirler."""
        if len(historical) < 3:
            return DriftTrend.STABLE.value

        recent = float(np.mean(historical[-3:]))
        older = float(np.mean(historical[:-3])) if len(historical) > 3 else recent
        std = float(np.std(historical))

        if std > np.mean(historical) * 0.5:
            return DriftTrend.VOLATILE.value

        change = (recent - older) / max(abs(older), 0.01)
        if change > self.importance_change_threshold:
            return DriftTrend.INCREASING.value
        elif change < -self.importance_change_threshold:
            return DriftTrend.DECREASING.value
        return DriftTrend.STABLE.value

    def _compute_severity(self, psi: float, trend: str) -> str:
        """Hesaplanan PSI/z-score ve trende göre ciddiyet seviyesi üretir."""
        if psi > DEFAULT_PSI_CRITICAL_THRESHOLD or (psi > 0.5 and trend == DriftTrend.VOLATILE.value):
            return DriftSeverity.CRITICAL.value
        elif psi > 0.5 or (psi > 0.3 and trend in (DriftTrend.INCREASING.value, DriftTrend.DECREASING.value)):
            return DriftSeverity.HIGH.value
        elif psi > DEFAULT_PSI_THRESHOLD or trend in (DriftTrend.INCREASING.value, DriftTrend.DECREASING.value):
            return DriftSeverity.MEDIUM.value
        return DriftSeverity.LOW.value

    def _suggest_remediation(self, feature: str, psi: float, trend: str, severity: str) -> str:
        """Drift durumuna göre otomatik eylem tavsiyesi oluşturur."""
        if severity == DriftSeverity.CRITICAL.value:
            return f"Model yeniden eğitimi zorunludur — '{feature}' özniteliğinde kritik kayma tespit edildi."
        elif severity == DriftSeverity.HIGH.value:
            return f"'{feature}' özniteliğini yakından izleyin — kayma sürerse yeniden eğitim başlatılmalıdır."
        elif trend in (DriftTrend.INCREASING.value, DriftTrend.DECREASING.value):
            return f"'{feature}' öznitelik önemi yön değiştiriyor — hesaplama formülünü gözden geçirin."
        return ""

    def _check_distribution_drift(self, reports: list[DriftReport]) -> None:
        """Kayıtlı referans ve güncel dağılımlar üzerinden gerçek PSI formülüyle dağılım kaymasını kontrol eder."""
        current_dist = self._feature_distributions[-1]
        reference_dist = self._feature_distributions[0]

        for feature, cur_arr in current_dist.items():
            if feature not in reference_dist:
                continue

            ref_arr = reference_dist[feature]
            psi = self._calculate_psi(ref_arr, cur_arr)
            if psi > DEFAULT_PSI_STABLE_THRESHOLD:
                existing = next((r for r in reports if r.feature_name == feature), None)
                if existing:
                    combined_score = max(existing.psi, psi)
                    existing.psi = round(float(combined_score), 4)
                    existing.drift_detected = combined_score > self.psi_threshold
                    existing.alert = True
                    if psi > DEFAULT_PSI_SIGNIFICANT_THRESHOLD:
                        existing.severity = DriftSeverity.HIGH.value
                    if psi > DEFAULT_PSI_CRITICAL_THRESHOLD:
                        existing.severity = DriftSeverity.CRITICAL.value
                    existing.remediation = self._suggest_remediation(
                        feature, combined_score, existing.importance_trend, existing.severity
                    )

    def _check_correlation_drift(self, reports: list[DriftReport]) -> None:
        """Öznitelikler arası korelasyon yapısındaki çözülme veya değişimleri denetler."""
        current_dist = self._feature_distributions[-1]
        reference_dist = self._feature_distributions[0]

        common_features = [f for f in current_dist if f in reference_dist]
        if len(common_features) < 3:
            return

        try:
            ref_arrays = [reference_dist[f] for f in common_features]
            min_len = min(len(a) for a in ref_arrays)
            if min_len < 10:
                return

            ref_matrix = np.column_stack([a[:min_len] for a in ref_arrays])
            ref_corr = np.nan_to_num(np.corrcoef(ref_matrix.T), nan=0.0)

            cur_arrays = [current_dist[f] for f in common_features]
            min_len = min(len(a) for a in cur_arrays)
            if min_len < 10:
                return

            cur_matrix = np.column_stack([a[:min_len] for a in cur_arrays])
            cur_corr = np.nan_to_num(np.corrcoef(cur_matrix.T), nan=0.0)

            corr_diff = np.abs(cur_corr - ref_corr)
            triu_idx = np.triu_indices_from(corr_diff, k=1)
            if len(triu_idx[0]) == 0:
                return

            max_diff = float(np.max(corr_diff[triu_idx]))
            mean_diff = float(np.mean(corr_diff[triu_idx]))

            if max_diff > DEFAULT_CORRELATION_DRIFT_THRESHOLD:
                i, j = np.unravel_index(np.argmax(corr_diff), corr_diff.shape)
                feat_i, feat_j = common_features[i], common_features[j]

                for fname in [feat_i, feat_j]:
                    existing = next((r for r in reports if r.feature_name == fname), None)
                    if existing:
                        existing.alert = True
                        if existing.severity == DriftSeverity.LOW.value:
                            existing.severity = DriftSeverity.MEDIUM.value
                        partner = feat_j if fname == feat_i else feat_i
                        existing.remediation += (
                            f" [Korelasyon Kayması: {fname}↔{partner}, maks_fark={max_diff:.2f}]"
                        )

                logger.info(
                    "correlation_drift_detected",
                    max_diff=round(max_diff, 4),
                    mean_diff=round(mean_diff, 4),
                    pair=f"{feat_i}↔{feat_j}",
                )
        except Exception as e:
            logger.debug("correlation_drift_check_failed", error=str(e))

    def _calculate_psi(self, reference: np.ndarray, current: np.ndarray) -> float:
        """Nüfus Kararlılık İndeksi (PSI) hesaplar.

        Formül:
            PSI = Σ (P_current - P_reference) * ln(P_current / P_reference)

        Args:
            reference: Referans (eğitim dönemi) dağılımı.
            current: Mevcut (canlı/izleme dönemi) dağılımı.

        Returns:
            Pozitif ve sonlu PSI skoru.
        """
        try:
            ref_clean = reference[np.isfinite(reference)]
            cur_clean = current[np.isfinite(current)]

            if len(ref_clean) < 10 or len(cur_clean) < 10:
                return 0.0

            ref_sorted = np.sort(ref_clean)
            n = len(ref_sorted)

            # Eşit miktarlı quantile sınırları
            quantiles = [float(ref_sorted[int(n * i / self.n_bins)]) for i in range(1, self.n_bins)]
            quantiles_unique = sorted(set(quantiles))

            if len(quantiles_unique) < 2:
                # Dağılım tek bir sabit değere sıkışmışsa
                return 0.0

            bins = [-np.inf] + quantiles_unique + [np.inf]

            ref_hist, _ = np.histogram(ref_clean, bins=bins)
            cur_hist, _ = np.histogram(cur_clean, bins=bins)

            eps = 1e-4
            ref_pct = (ref_hist / max(len(ref_clean), 1)) + eps
            cur_pct = (cur_hist / max(len(cur_clean), 1)) + eps

            psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
            return max(0.0, psi) if np.isfinite(psi) else 0.0
        except Exception:
            return 0.0

    def __repr__(self) -> str:
        """FeatureDriftDetector nesnesinin metin temsili."""
        return (
            f"FeatureDriftDetector(psi_threshold={self.psi_threshold}, "
            f"importance_th={self.importance_change_threshold}, "
            f"shap_records={len(self._shap_history)}, dist_records={len(self._feature_distributions)})"
        )


# ==============================================================================
# 4. POLARS İLE VEKTÖRİZE DRİFT TESPİTİ
# ==============================================================================
def check_drift_polars(
    reference_df: pl.DataFrame,
    current_df: pl.DataFrame,
    features: list[str] | None = None,
    n_bins: int = DEFAULT_N_BINS,
    psi_threshold: float = DEFAULT_PSI_THRESHOLD,
) -> list[DriftReport]:
    """İki Polars DataFrame arasında öznitelik bazında doğrudan PSI drift analizi yapar.

    Args:
        reference_df: Referans (örneğin eğitim/geçmiş) Polars DataFrame'i.
        current_df: Güncel (canlı/yeni dönem) Polars DataFrame'i.
        features: Test edilecek öznitelikler (None ise ortak numerik sütunlar).
        n_bins: Histogram quantile dilim sayısı.
        psi_threshold: Kayma kabul edilecek PSI eşiği.

    Returns:
        Hesaplanan DriftReport nesneleri listesi.
    """
    if reference_df is None or current_df is None or len(reference_df) == 0 or len(current_df) == 0:
        return []

    common_cols = [
        c
        for c in reference_df.columns
        if c in current_df.columns
        and c != "Date"
        and reference_df[c].dtype in (pl.Float32, pl.Float64, pl.Int32, pl.Int64)
    ]
    target_features = [f for f in (features or common_cols) if f in common_cols]

    reports: list[DriftReport] = []
    detector = FeatureDriftDetector(psi_threshold=psi_threshold, n_bins=n_bins)

    for col in target_features:
        ref_arr = reference_df[col].drop_nulls().to_numpy()
        cur_arr = current_df[col].drop_nulls().to_numpy()

        psi = detector._calculate_psi(ref_arr, cur_arr)
        drift_detected = psi > psi_threshold
        sev = (
            DriftSeverity.CRITICAL.value
            if psi > DEFAULT_PSI_CRITICAL_THRESHOLD
            else (
                DriftSeverity.HIGH.value
                if psi > DEFAULT_PSI_SIGNIFICANT_THRESHOLD
                else (DriftSeverity.MEDIUM.value if drift_detected else DriftSeverity.LOW.value)
            )
        )

        remediation = ""
        if sev == DriftSeverity.CRITICAL.value:
            remediation = f"Acil yeniden eğitim — '{col}' özniteliğinde kritik PSI kayması ({psi:.3f})."
        elif drift_detected:
            remediation = f"'{col}' dağılımında kayma tespit edildi ({psi:.3f})."

        reports.append(
            DriftReport(
                feature_name=col,
                psi=round(psi, 4),
                drift_detected=drift_detected,
                importance_trend=DriftTrend.STABLE.value,
                current_importance=0.0,
                historical_importance=0.0,
                alert=drift_detected,
                severity=sev,
                remediation=remediation,
            )
        )

    return reports


# ==============================================================================
# 5. DUCKDB VERİTABANI DENETİM İZİ YÖNETİMİ
# ==============================================================================
def save_drift_summary_to_duckdb(
    summary: DriftSummary,
    db_path: str = DEFAULT_DUCKDB_PATH,
) -> None:
    """Drift özet raporunu DuckDB denetim tablosuna SSD korumalı WAL sınırlarıyla kaydeder.

    Args:
        summary: Kaydedilecek DriftSummary nesnesi.
        db_path: Hedef DuckDB veritabanı dosya yolu.
    """
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    con = duckdb.connect(db_path)
    try:
        configure_duckdb_wal(con)

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS ml_feature_drift_summaries (
                report_id VARCHAR PRIMARY KEY,
                created_at TIMESTAMP,
                total_features BIGINT,
                drifted_features BIGINT,
                alert_features BIGINT,
                critical_features BIGINT,
                overall_drift_score DOUBLE,
                recommendations_json VARCHAR
            );
            """
        )

        report_id = f"drift_{uuid.uuid4().hex[:8]}"
        created_at = datetime.now(UTC).isoformat()
        recs_json = orjson.dumps(summary.recommendations).decode("utf-8")

        con.execute(
            """
            INSERT OR REPLACE INTO ml_feature_drift_summaries
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            [
                report_id,
                created_at,
                summary.total_features,
                summary.drifted_features,
                summary.alert_features,
                summary.critical_features,
                summary.overall_drift_score,
                recs_json,
            ],
        )
        logger.info("drift_summary_saved_to_duckdb", report_id=report_id, score=summary.overall_drift_score)
    finally:
        con.close()


def read_drift_history_polars(
    db_path: str = DEFAULT_DUCKDB_PATH,
    limit: int = 50,
) -> pl.DataFrame:
    """DuckDB'de kayıtlı geçmiş drift özetlerini Polars DataFrame olarak döndürür.

    Args:
        db_path: DuckDB veritabanı dosya yolu.
        limit: Alınacak azami rapor sayısı.

    Returns:
        Polars DataFrame formatında drift geçmişi.
    """
    if not os.path.exists(db_path):
        return pl.DataFrame()

    con = duckdb.connect(db_path, read_only=True)
    try:
        configure_duckdb_wal(con)
        query = f"""
            SELECT report_id, created_at, total_features, drifted_features,
                   alert_features, critical_features, overall_drift_score,
                   recommendations_json
            FROM ml_feature_drift_summaries
            ORDER BY created_at DESC
            LIMIT {limit};
        """
        arrow_table = con.execute(query).arrow()
        return pl.from_arrow(arrow_table)
    except Exception as e:
        logger.warning("read_drift_history_polars_failed", error=str(e))
        return pl.DataFrame()
    finally:
        con.close()


# ==============================================================================
# 6. DIŞA AKTARILAN MODÜL SEMBOLLERİ (__all__)
# ==============================================================================
__all__: Final[list[str]] = [
    "DEFAULT_ALERT_COOLDOWN_HOURS",
    "DEFAULT_CORRELATION_DRIFT_THRESHOLD",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_IMPORTANCE_CHANGE_THRESHOLD",
    "DEFAULT_MAX_DIST_HISTORY",
    "DEFAULT_MAX_SHAP_HISTORY",
    "DEFAULT_MAX_TICKER_HISTORY",
    "DEFAULT_N_BINS",
    "DEFAULT_PSI_CRITICAL_THRESHOLD",
    "DEFAULT_PSI_SIGNIFICANT_THRESHOLD",
    "DEFAULT_PSI_STABLE_THRESHOLD",
    "DEFAULT_PSI_THRESHOLD",
    "DEFAULT_WAL_AUTO_CHECKPOINT",
    "DriftSeverity",
    "DriftTrend",
    "DriftReport",
    "DriftSummary",
    "FeatureDriftDetector",
    "check_drift_polars",
    "configure_duckdb_wal",
    "save_drift_summary_to_duckdb",
    "read_drift_history_polars",
]
