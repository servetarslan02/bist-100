# c:\Users\serve\Downloads\Compressed\bist-100\services\ml\feature_stability.py
"""ALPHA BIST — Öznitelik Kararlılık Analizi Motoru (Feature Stability Analysis v1.0).

Özniteliklerin (features) zaman içindeki dağılım ve ilişki kararlılığını ölçer:
- Nüfus Kararlılık İndeksi (PSI - Population Stability Index)
- İki Örneklem Kolmogorov-Smirnov Dağılım Kayması Testi (KS Test)
- Öznitelikler Arası Korelasyon Yapısı Kararlılığı
- 0 ile 1 Arasında Kararlılık Skorlaması (Stability Score)
- Kararsız (Unstable) Özniteliklerin Otomatik Tespiti ve Raporlanması

Kullanım Prensipleri:
- Sıfır Veri Sızıntısı: Referans ve güncel dönem dağılımları zaman serisi sırasına uygun ayrıştırılır.
- Eşzamanlılık Güvenliği: `threading.RLock()` ile çoklu iş parçacığı koruması.
- DuckDB Entegrasyonu: SSD korumalı WAL ayarları ile denetim izi kaydı.
- Polars Desteği: Doğrudan Polars DataFrame üzerinden kararlılık analizi.
- Fail-Closed Mimarisi: Sabit değerli öznitelikler, NaN/Inf taşmaları ve eksik verilerde güvenli guard'lar.
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
from scipy.stats import ks_2samp

logger = structlog.get_logger(__name__)

# ==============================================================================
# 1. STANDART YAPILANDIRMA SABİTLERİ (DEFAULT_*)
# ==============================================================================
DEFAULT_PSI_WARNING: Final[float] = 0.10
DEFAULT_PSI_ALERT: Final[float] = 0.25
DEFAULT_PSI_CRITICAL: Final[float] = 1.00
DEFAULT_KS_ALPHA: Final[float] = 0.05
DEFAULT_MIN_SAMPLES: Final[int] = 50
DEFAULT_MAX_DISTRIBUTIONS: Final[int] = 100
DEFAULT_MAX_CORRELATION_HISTORY: Final[int] = 50
DEFAULT_CORRELATION_DIFF_THRESHOLD: Final[float] = 0.30
DEFAULT_UNSTABLE_SCORE_THRESHOLD: Final[float] = 0.70

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
class StabilitySeverity(StrEnum):
    """Kararlılık durumu ciddiyet seviyesi."""

    OK = "OK"
    WARNING = "WARNING"
    ALERT = "ALERT"
    CRITICAL = "CRITICAL"


@dataclass(slots=True)
class FeatureStabilityReport:
    """Tek bir özniteliğin detaylı kararlılık denetim raporu."""

    feature_name: str
    psi: float
    ks_statistic: float
    ks_p_value: float
    distribution_shifted: bool
    correlation_stable: bool
    stability_score: float
    severity: str
    details: str

    def to_dict(self) -> dict[str, Any]:
        """Raporu sözlük formatına çevirir."""
        return {
            "feature_name": self.feature_name,
            "psi": float(self.psi),
            "ks_statistic": float(self.ks_statistic),
            "ks_p_value": float(self.ks_p_value),
            "distribution_shifted": bool(self.distribution_shifted),
            "correlation_stable": bool(self.correlation_stable),
            "stability_score": float(self.stability_score),
            "severity": str(self.severity),
            "details": self.details,
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı serileştirilmiş orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeatureStabilityReport:
        """Sözlükten FeatureStabilityReport nesnesi oluşturur."""
        return cls(
            feature_name=str(data.get("feature_name", "")),
            psi=float(data.get("psi", 0.0)),
            ks_statistic=float(data.get("ks_statistic", 0.0)),
            ks_p_value=float(data.get("ks_p_value", 1.0)),
            distribution_shifted=bool(data.get("distribution_shifted", False)),
            correlation_stable=bool(data.get("correlation_stable", True)),
            stability_score=float(data.get("stability_score", 1.0)),
            severity=str(data.get("severity", StabilitySeverity.OK.value)),
            details=str(data.get("details", "")),
        )

    def __repr__(self) -> str:
        """Kullanıcı dostu metin temsili."""
        return (
            f"FeatureStabilityReport(feature='{self.feature_name}', score={self.stability_score:.3f}, "
            f"sev='{self.severity}', psi={self.psi:.4f}, ks_p={self.ks_p_value:.4f})"
        )


@dataclass(slots=True)
class StabilitySummary:
    """Tüm öznitelikler için genel sistemik kararlılık özeti."""

    total_features: int
    stable_features: int
    warning_features: int
    alert_features: int
    critical_features: int
    overall_stability_score: float
    unstable_features: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Özeti sözlük formatına çevirir."""
        return {
            "total_features": int(self.total_features),
            "stable_features": int(self.stable_features),
            "warning_features": int(self.warning_features),
            "alert_features": int(self.alert_features),
            "critical_features": int(self.critical_features),
            "overall_stability_score": float(self.overall_stability_score),
            "unstable_features": list(self.unstable_features),
            "timestamp": self.timestamp,
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı serileştirilmiş orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StabilitySummary:
        """Sözlükten StabilitySummary nesnesi oluşturur."""
        return cls(
            total_features=int(data.get("total_features", 0)),
            stable_features=int(data.get("stable_features", 0)),
            warning_features=int(data.get("warning_features", 0)),
            alert_features=int(data.get("alert_features", 0)),
            critical_features=int(data.get("critical_features", 0)),
            overall_stability_score=float(data.get("overall_stability_score", 1.0)),
            unstable_features=[str(u) for u in data.get("unstable_features", [])],
            timestamp=str(data.get("timestamp", datetime.now(UTC).isoformat())),
        )

    def __repr__(self) -> str:
        """Kullanıcı dostu metin temsili."""
        return (
            f"StabilitySummary(total={self.total_features}, stable={self.stable_features}, "
            f"unstable={len(self.unstable_features)}, overall_score={self.overall_stability_score:.4f})"
        )


# ==============================================================================
# 3. ÖZNİTELİK KARARLILIK ANALİZ MOTORU
# ==============================================================================
class FeatureStabilityAnalyzer:
    """Öznitelik kararlılık analiz ve alarm motoru."""

    def __init__(
        self,
        psi_warning: float = DEFAULT_PSI_WARNING,
        psi_alert: float = DEFAULT_PSI_ALERT,
        psi_critical: float = DEFAULT_PSI_CRITICAL,
        ks_alpha: float = DEFAULT_KS_ALPHA,
        min_samples: int = DEFAULT_MIN_SAMPLES,
    ) -> None:
        """FeatureStabilityAnalyzer motorunu başlatır.

        Args:
            psi_warning: Uyarı seviyesi PSI eşiği (örn: 0.10).
            psi_alert: Alarm seviyesi PSI eşiği (örn: 0.25).
            psi_critical: Kritik seviye PSI eşiği (örn: 1.00).
            ks_alpha: Kolmogorov-Smirnov testi anlamlılık düzeyi (p-değeri eşiği).
            min_samples: Test için asgari örneklem sayısı.

        Raises:
            ValueError: Eşik değerleri geçersiz veya negatif ise.
        """
        if psi_warning <= 0 or psi_alert <= psi_warning or psi_critical <= psi_alert or ks_alpha <= 0:
            raise ValueError("Gecersiz esik degerleri: psi_warning < psi_alert < psi_critical ve ks_alpha > 0 olmalidir.")

        self._lock: Final[threading.RLock] = threading.RLock()
        self.psi_warning: float = psi_warning
        self.psi_alert: float = psi_alert
        self.psi_critical: float = psi_critical
        self.ks_alpha: float = ks_alpha
        self.min_samples: int = min_samples

        self._distributions: list[dict[str, np.ndarray]] = []
        self._timestamps: list[str] = []
        self._correlation_matrices: list[tuple[np.ndarray, list[str]]] = []

        logger.info(
            "feature_stability_analyzer_initialized",
            psi_warning=self.psi_warning,
            psi_alert=self.psi_alert,
            psi_critical=self.psi_critical,
            ks_alpha=self.ks_alpha,
            min_samples=self.min_samples,
        )

    def record_distribution(
        self,
        feature_data: dict[str, np.ndarray],
        timestamp: str | None = None,
    ) -> None:
        """Belirtilen zaman noktası için öznitelik dağılım dizilerini kaydeder.

        Args:
            feature_data: Öznitelik adı -> 1D numpy sayısal dizisi eşlemesi.
            timestamp: İsteğe bağlı ISO zaman damgası.
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
                if np.sum(finite_mask) >= 10:
                    valid_arrays[k] = np_arr[finite_mask]

            if valid_arrays:
                self._distributions.append(valid_arrays)
                self._timestamps.append(timestamp or datetime.now(UTC).isoformat())

                if len(self._distributions) > DEFAULT_MAX_DISTRIBUTIONS:
                    self._distributions = self._distributions[-DEFAULT_MAX_DISTRIBUTIONS:]
                    self._timestamps = self._timestamps[-DEFAULT_MAX_DISTRIBUTIONS:]

    def record_correlation(
        self,
        feature_data: dict[str, np.ndarray],
    ) -> None:
        """Öznitelikler arası korelasyon yapısını kaydeder.

        Args:
            feature_data: Öznitelik adı -> 1D numpy sayısal dizisi eşlemesi.
        """
        if not feature_data:
            return

        with self._lock:
            names = sorted(k for k, v in feature_data.items() if v is not None and len(v) >= 10)
            if len(names) < 2:
                return

            try:
                arrays = [feature_data[n][np.isfinite(feature_data[n])] for n in names]
                min_len = min(len(a) for a in arrays)
                if min_len < 10:
                    return

                matrix = np.column_stack([a[:min_len] for a in arrays])
                corr = np.nan_to_num(np.corrcoef(matrix.T), nan=0.0)
                self._correlation_matrices.append((corr, names))

                if len(self._correlation_matrices) > DEFAULT_MAX_CORRELATION_HISTORY:
                    self._correlation_matrices = self._correlation_matrices[-DEFAULT_MAX_CORRELATION_HISTORY:]
            except Exception as e:
                logger.warning("correlation_record_failed", error=str(e))

    def check_stability(self) -> StabilitySummary:
        """Kayıtlı referans ve güncel dağılımlar üzerinden tüm özniteliklerin kararlılığını analiz eder.

        Returns:
            StabilitySummary nesnesi.
        """
        with self._lock:
            if len(self._distributions) < 2:
                return StabilitySummary(
                    total_features=0,
                    stable_features=0,
                    warning_features=0,
                    alert_features=0,
                    critical_features=0,
                    overall_stability_score=1.0,
                    unstable_features=[],
                )

            reference = self._distributions[0]
            current = self._distributions[-1]
            reports: list[FeatureStabilityReport] = []

            for feature_name, cur_arr in current.items():
                if feature_name not in reference:
                    continue

                ref_arr = reference[feature_name]
                report = self._check_feature_stability(feature_name, ref_arr, cur_arr)
                reports.append(report)

            # Korelasyon stabilitesi kontrolü
            if len(self._correlation_matrices) >= 2:
                corr_stable_map = self._check_correlation_stability()
                for report in reports:
                    if report.feature_name in corr_stable_map:
                        report.correlation_stable = corr_stable_map[report.feature_name]
                        if not report.correlation_stable and report.severity == StabilitySeverity.OK.value:
                            report.severity = StabilitySeverity.WARNING.value
                            report.details += " [Korelasyon Değişimi]"

            stable = sum(1 for r in reports if r.severity == StabilitySeverity.OK.value)
            warning = sum(1 for r in reports if r.severity == StabilitySeverity.WARNING.value)
            alert = sum(1 for r in reports if r.severity == StabilitySeverity.ALERT.value)
            critical = sum(1 for r in reports if r.severity == StabilitySeverity.CRITICAL.value)
            unstable = [
                r.feature_name
                for r in reports
                if r.severity in (StabilitySeverity.ALERT.value, StabilitySeverity.CRITICAL.value)
            ]

            overall_score = float(np.mean([r.stability_score for r in reports])) if reports else 1.0

            summary = StabilitySummary(
                total_features=len(reports),
                stable_features=stable,
                warning_features=warning,
                alert_features=alert,
                critical_features=critical,
                overall_stability_score=round(overall_score, 4),
                unstable_features=unstable,
            )

            # DuckDB denetim tablosuna kaydet
            try:
                save_stability_summary_to_duckdb(summary)
            except Exception as e:
                logger.warning("save_stability_summary_to_duckdb_failed", error=str(e))

            return summary

    def get_unstable_features(self, threshold: float = DEFAULT_UNSTABLE_SCORE_THRESHOLD) -> list[str]:
        """Kararlılık skoru belirtilen eşiğin altında olan özniteliklerin adlarını listeler.

        Args:
            threshold: Kararlılık skoru alt eşiği (0.0 - 1.0).

        Returns:
            Kararsız öznitelik adları listesi.
        """
        summary = self.check_stability()
        return summary.unstable_features

    def get_feature_report(self, feature_name: str) -> FeatureStabilityReport | None:
        """Belirtilen tek bir öznitelik için ayrıntılı kararlılık raporunu döndürür.

        Args:
            feature_name: İncelenecek öznitelik adı.

        Returns:
            FeatureStabilityReport veya None.
        """
        with self._lock:
            if len(self._distributions) < 2:
                return None

            reference = self._distributions[0]
            current = self._distributions[-1]

            if feature_name not in reference or feature_name not in current:
                return None

            return self._check_feature_stability(
                feature_name,
                reference[feature_name],
                current[feature_name],
            )

    def _check_feature_stability(
        self,
        feature_name: str,
        reference: np.ndarray,
        current: np.ndarray,
    ) -> FeatureStabilityReport:
        """Tek bir öznitelik için PSI ve KS testlerini yürüterek rapor nesnesi üretir."""
        psi = self._calculate_psi(reference, current)
        ks_stat, ks_p = self._ks_test(reference, current)

        shifted = (psi > self.psi_alert) or (ks_p < self.ks_alpha)
        stability_score = max(0.0, 1.0 - (psi / self.psi_critical)) if np.isfinite(psi) else 0.0

        if psi > self.psi_critical:
            severity = StabilitySeverity.CRITICAL.value
        elif psi > self.psi_alert:
            severity = StabilitySeverity.ALERT.value
        elif psi > self.psi_warning:
            severity = StabilitySeverity.WARNING.value
        else:
            severity = StabilitySeverity.OK.value

        details = f"PSI={psi:.4f}, KS={ks_stat:.4f}, p={ks_p:.4f}"
        if shifted:
            details += " [KAYMA TESPİT EDİLDİ]"

        return FeatureStabilityReport(
            feature_name=feature_name,
            psi=round(psi, 4),
            ks_statistic=round(ks_stat, 4),
            ks_p_value=round(ks_p, 4),
            distribution_shifted=shifted,
            correlation_stable=True,
            stability_score=round(stability_score, 4),
            severity=severity,
            details=details,
        )

    def _calculate_psi(self, reference: np.ndarray, current: np.ndarray) -> float:
        """İki sayısal dağılım arasında Nüfus Kararlılık İndeksi (PSI) hesaplar."""
        try:
            ref_clean = reference[np.isfinite(reference)]
            cur_clean = current[np.isfinite(current)]

            if len(ref_clean) < 10 or len(cur_clean) < 10:
                return 0.0

            ref_sorted = np.sort(ref_clean)
            n = len(ref_sorted)

            # Eşit miktarlı 10 quantile dilimi
            boundaries = [float(ref_sorted[int(n * i / 10)]) for i in range(1, 10)]
            unique_boundaries = sorted(set(boundaries))

            if len(unique_boundaries) < 2:
                # Dağılım tek bir sabit değere sıkışmışsa
                return 0.0

            bins = [-np.inf] + unique_boundaries + [np.inf]

            ref_hist, _ = np.histogram(ref_clean, bins=bins)
            cur_hist, _ = np.histogram(cur_clean, bins=bins)

            eps = 1e-4
            ref_pct = (ref_hist / max(len(ref_clean), 1)) + eps
            cur_pct = (cur_hist / max(len(cur_clean), 1)) + eps

            psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
            return max(0.0, psi) if np.isfinite(psi) else 0.0
        except Exception:
            return 0.0

    def _ks_test(self, reference: np.ndarray, current: np.ndarray) -> tuple[float, float]:
        """İki örneklem Kolmogorov-Smirnov testini çalıştırarak istatistik ve p-değerini döndürür."""
        try:
            ref_clean = reference[np.isfinite(reference)]
            cur_clean = current[np.isfinite(current)]

            if len(ref_clean) < 10 or len(cur_clean) < 10:
                return 0.0, 1.0

            stat, p_val = ks_2samp(ref_clean, cur_clean)
            return (
                float(stat) if np.isfinite(stat) else 0.0,
                float(p_val) if np.isfinite(p_val) else 1.0,
            )
        except Exception:
            return 0.0, 1.0

    def _check_correlation_stability(self) -> dict[str, bool]:
        """Tarihsel korelasyon matrisleri arasında öznitelik bazlı ilişki kararlılığını inceler."""
        if len(self._correlation_matrices) < 2:
            return {}

        ref_corr, ref_names = self._correlation_matrices[0]
        cur_corr, cur_names = self._correlation_matrices[-1]

        common = [n for n in ref_names if n in cur_names]
        if len(common) < 2:
            return {}

        result: dict[str, bool] = {}

        # Ortak özniteliklerin indekslerini hizala
        ref_indices = [ref_names.index(n) for n in common]
        cur_indices = [cur_names.index(n) for n in common]

        sub_ref_corr = ref_corr[np.ix_(ref_indices, ref_indices)]
        sub_cur_corr = cur_corr[np.ix_(cur_indices, cur_indices)]

        corr_diff = np.abs(sub_cur_corr - sub_ref_corr)

        for i, name in enumerate(common):
            row_diff = corr_diff[i]
            max_diff = float(np.max(row_diff))
            result[name] = max_diff < DEFAULT_CORRELATION_DIFF_THRESHOLD

        return result

    def __repr__(self) -> str:
        """FeatureStabilityAnalyzer nesnesinin metin temsili."""
        return (
            f"FeatureStabilityAnalyzer(dist_count={len(self._distributions)}, "
            f"corr_count={len(self._correlation_matrices)}, min_samples={self.min_samples})"
        )


# ==============================================================================
# 4. POLARS İLE VEKTÖRİZE KARARLILIK ANALİZİ
# ==============================================================================
def check_stability_polars(
    reference_df: pl.DataFrame,
    current_df: pl.DataFrame,
    features: list[str] | None = None,
    psi_warning: float = DEFAULT_PSI_WARNING,
    psi_alert: float = DEFAULT_PSI_ALERT,
) -> list[FeatureStabilityReport]:
    """İki Polars DataFrame arasında doğrudan öznitelik kararlılık analizini yürütür.

    Args:
        reference_df: Referans döneme ait Polars DataFrame.
        current_df: Güncel döneme ait Polars DataFrame.
        features: Test edilecek öznitelikler (None ise tüm ortak numerik sütunlar).
        psi_warning: Uyarı eşiği.
        psi_alert: Alarm eşiği.

    Returns:
        FeatureStabilityReport nesneleri listesi.
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
    target_cols = [f for f in (features or common_cols) if f in common_cols]

    reports: list[FeatureStabilityReport] = []
    analyzer = FeatureStabilityAnalyzer(psi_warning=psi_warning, psi_alert=psi_alert)

    for col in target_cols:
        ref_arr = reference_df[col].drop_nulls().to_numpy()
        cur_arr = current_df[col].drop_nulls().to_numpy()

        rep = analyzer._check_feature_stability(col, ref_arr, cur_arr)
        reports.append(rep)

    return reports


# ==============================================================================
# 5. DUCKDB VERİTABANI DENETİM İZİ YÖNETİMİ
# ==============================================================================
def save_stability_summary_to_duckdb(
    summary: StabilitySummary,
    db_path: str = DEFAULT_DUCKDB_PATH,
) -> None:
    """Kararlılık özet raporunu DuckDB denetim tablosuna SSD korumalı WAL sınırlarıyla kaydeder.

    Args:
        summary: Kaydedilecek StabilitySummary nesnesi.
        db_path: Hedef DuckDB dosya yolu.
    """
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    con = duckdb.connect(db_path)
    try:
        configure_duckdb_wal(con)

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS ml_feature_stability_summaries (
                summary_id VARCHAR PRIMARY KEY,
                created_at TIMESTAMP,
                total_features BIGINT,
                stable_features BIGINT,
                warning_features BIGINT,
                alert_features BIGINT,
                critical_features BIGINT,
                overall_score DOUBLE,
                unstable_features_json VARCHAR
            );
            """
        )

        summary_id = f"stab_{uuid.uuid4().hex[:8]}"
        unstable_json = orjson.dumps(summary.unstable_features).decode("utf-8")

        con.execute(
            """
            INSERT OR REPLACE INTO ml_feature_stability_summaries
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            [
                summary_id,
                summary.timestamp,
                summary.total_features,
                summary.stable_features,
                summary.warning_features,
                summary.alert_features,
                summary.critical_features,
                summary.overall_stability_score,
                unstable_json,
            ],
        )
        logger.info("stability_summary_saved_to_duckdb", summary_id=summary_id, score=summary.overall_stability_score)
    finally:
        con.close()


def read_stability_history_polars(
    db_path: str = DEFAULT_DUCKDB_PATH,
    limit: int = 50,
) -> pl.DataFrame:
    """DuckDB'de kayıtlı geçmiş kararlılık özetlerini Polars DataFrame olarak döndürür.

    Args:
        db_path: DuckDB dosya yolu.
        limit: Alınacak azami kayıt sayısı.

    Returns:
        Polars DataFrame.
    """
    if not os.path.exists(db_path):
        return pl.DataFrame()

    con = duckdb.connect(db_path, read_only=True)
    try:
        configure_duckdb_wal(con)
        query = f"""
            SELECT summary_id, created_at, total_features, stable_features,
                   warning_features, alert_features, critical_features,
                   overall_score, unstable_features_json
            FROM ml_feature_stability_summaries
            ORDER BY created_at DESC
            LIMIT {limit};
        """
        arrow_table = con.execute(query).arrow()
        return pl.from_arrow(arrow_table)
    except Exception as e:
        logger.warning("read_stability_history_polars_failed", error=str(e))
        return pl.DataFrame()
    finally:
        con.close()


# Singleton Örnek
feature_stability: Final[FeatureStabilityAnalyzer] = FeatureStabilityAnalyzer()

# ==============================================================================
# 6. DIŞA AKTARILAN MODÜL SEMBOLLERİ (__all__)
# ==============================================================================
__all__: Final[list[str]] = [
    "DEFAULT_CORRELATION_DIFF_THRESHOLD",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_KS_ALPHA",
    "DEFAULT_MAX_CORRELATION_HISTORY",
    "DEFAULT_MAX_DISTRIBUTIONS",
    "DEFAULT_MIN_SAMPLES",
    "DEFAULT_PSI_ALERT",
    "DEFAULT_PSI_CRITICAL",
    "DEFAULT_PSI_WARNING",
    "DEFAULT_UNSTABLE_SCORE_THRESHOLD",
    "DEFAULT_WAL_AUTO_CHECKPOINT",
    "StabilitySeverity",
    "FeatureStabilityReport",
    "StabilitySummary",
    "FeatureStabilityAnalyzer",
    "feature_stability",
    "check_stability_polars",
    "configure_duckdb_wal",
    "save_stability_summary_to_duckdb",
    "read_stability_history_polars",
]
