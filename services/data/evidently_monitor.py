"""ALPHA BIST — Veri Kalitesi ve Özellik Sürüklenmesi İzleme Motoru (Evidently Data Monitor).

Bu modül, BIST-100 hisse senedi piyasası veri boru hatlarında (ingestion pipeline)
veri bütünlüğünü (OHLCV ilişkileri, sıfır ve negatif fiyat kontrolleri) denetler;
referans veri kümesi ile güncel veri kümesi arasındaki dağılım kaymalarını (feature drift)
Kolmogorov-Smirnov (KS) testi ve Population Stability Index (PSI) algoritmalarıyla ölçerek
otomatik geçiş/blokaj kararları (Data Quality Gate) üretir ve DuckDB denetim tablosuna kaydeder.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog
from scipy import stats

logger = structlog.get_logger(__name__)

# ==============================================================================
# Yapılandırma ve Eşik Sabitleri
# ==============================================================================

DEFAULT_PSI_THRESHOLD: Final[float] = 0.20
DEFAULT_KS_ALPHA: Final[float] = 0.05
DEFAULT_EVIDENTLY_DB_PATH: Final[str] = "data/evidently_audit.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"


# ==============================================================================
# DuckDB WAL ve orjson Yardımcıları
# ==============================================================================


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir nesneyi orjson ile ikili bayt dizisine dönüştürür.

    Args:
        val: Serileştirilecek veri veya nesne.

    Returns:
        bytes: orjson kodlanmış baytlar.
    """
    if hasattr(val, "to_dict"):
        val = val.to_dict()
    return orjson.dumps(val, default=str)


# ==============================================================================
# Veri Modelleri
# ==============================================================================


@dataclass(slots=True)
class QualityCheckResult:
    """Tekil veri kalitesi kontrol sonucu.

    Attributes:
        check_name: Kontrol adı (örn: high_greater_equal_low).
        status: Kontrol durumu ('PASS', 'WARN', 'FAIL').
        metric_value: Ölçülen ihlal sayısı veya metrik değeri.
        threshold: İzin verilen maksimum eşik değeri.
        message: Açıklayıcı durum mesajı.
    """

    check_name: str
    status: str
    metric_value: float
    threshold: float
    message: str

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return {
            "check_name": self.check_name,
            "status": self.status,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "message": self.message,
        }

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisine dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return f"QualityCheckResult(kontrol='{self.check_name}', durum='{self.status}', deger={self.metric_value})"


@dataclass(slots=True)
class DriftCheckResult:
    """Tekil feature drift kontrol sonucu.

    Attributes:
        feature_name: Özellik adı.
        drift_score: Drift skoru (PSI veya p-value).
        method: Kullanılan istatistiksel test ('KS_TEST', 'PSI').
        is_drifted: Dağılımda anlamlı kayma var mı.
        severity: Kayma şiddeti ('NONE', 'MODERATE', 'SEVERE').
        reference_mean: Referans veri ortalaması.
        current_mean: Güncel veri ortalaması.
    """

    feature_name: str
    drift_score: float
    method: str
    is_drifted: bool
    severity: str
    reference_mean: float
    current_mean: float

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return {
            "feature_name": self.feature_name,
            "drift_score": self.drift_score,
            "method": self.method,
            "is_drifted": self.is_drifted,
            "severity": self.severity,
            "reference_mean": self.reference_mean,
            "current_mean": self.current_mean,
        }

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisine dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return (
            f"DriftCheckResult(ozellik='{self.feature_name}', kayma={self.is_drifted}, "
            f"siddet='{self.severity}', skor={self.drift_score})"
        )


@dataclass(slots=True)
class DataQualityReport:
    """Kapsamlı Veri Kalitesi ve Drift Değerlendirme Raporu.

    Attributes:
        is_pipeline_allowed: Pipeline'ın çalışmasına izin veriliyor mu.
        overall_score: Genel veri kalitesi skoru (0 - 100).
        quality_checks: Veri kalitesi kontrolleri listesi.
        drift_checks: Özellik drift kontrolleri listesi.
        failed_checks_count: Başarısız kalite kontrol sayısı.
        drifted_features_count: Kayma tespit edilen özellik sayısı.
        timestamp: Rapor üretim zaman damgası (ISO 8601 UTC).
    """

    is_pipeline_allowed: bool
    overall_score: float
    quality_checks: list[QualityCheckResult]
    drift_checks: list[DriftCheckResult]
    failed_checks_count: int
    drifted_features_count: int
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return {
            "is_pipeline_allowed": self.is_pipeline_allowed,
            "overall_score": self.overall_score,
            "quality_checks": [q.to_dict() for q in self.quality_checks],
            "drift_checks": [d.to_dict() for d in self.drift_checks],
            "failed_checks_count": self.failed_checks_count,
            "drifted_features_count": self.drifted_features_count,
            "timestamp": self.timestamp,
        }

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisine dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def export_to_polars(self) -> pl.DataFrame:
        """Rapor özetini tek satırlık Polars DataFrame olarak döner."""
        return pl.DataFrame(
            {
                "timestamp": [self.timestamp],
                "is_pipeline_allowed": [self.is_pipeline_allowed],
                "overall_score": [self.overall_score],
                "failed_checks_count": [self.failed_checks_count],
                "drifted_features_count": [self.drifted_features_count],
            }
        )

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        durum = "ONAYLANDI" if self.is_pipeline_allowed else "BLOKE"
        return (
            f"DataQualityReport(durum='{durum}', skor={self.overall_score:.1f}, "
            f"hatali_kalite={self.failed_checks_count}, kayan_ozellik={self.drifted_features_count})"
        )


# ==============================================================================
# İzleyici Motor Sınıfı
# ==============================================================================


class EvidentlyDataMonitor:
    """Evidently AI ve Great Expectations prensiplerine tam uyumlu izleme motoru."""

    def __init__(
        self,
        psi_threshold: float = DEFAULT_PSI_THRESHOLD,
        ks_alpha: float = DEFAULT_KS_ALPHA,
    ) -> None:
        """EvidentlyDataMonitor başlatıcı.

        Args:
            psi_threshold: PSI testi için kritik kayma eşiği.
            ks_alpha: Kolmogorov-Smirnov p-değeri güvenilirlik eşiği.
        """
        self.psi_threshold = psi_threshold
        self.ks_alpha = ks_alpha
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            return f"EvidentlyDataMonitor(psi_esik={self.psi_threshold}, ks_alpha={self.ks_alpha})"

    def to_dict(self) -> dict[str, Any]:
        """İzleyici yapılandırmasını sözlük olarak döner."""
        with self._lock:
            return {
                "psi_threshold": self.psi_threshold,
                "ks_alpha": self.ks_alpha,
            }

    def to_orjson_bytes(self) -> bytes:
        """İzleyici yapılandırmasını ikili orjson baytlarına dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def audit_ohlcv_integrity(self, df_dict: dict[str, list[float]]) -> list[QualityCheckResult]:
        """OHLCV temel finansal kurallarını denetler."""
        with self._lock:
            results: list[QualityCheckResult] = []

            opens = np.array(df_dict.get("open", []))
            highs = np.array(df_dict.get("high", []))
            lows = np.array(df_dict.get("low", []))
            closes = np.array(df_dict.get("close", []))
            volumes = np.array(df_dict.get("volume", []))

            if len(closes) == 0:
                return [QualityCheckResult("empty_data", "FAIL", 0.0, 1.0, "Boş veri seti")]

            # 1. High >= Low
            hl_violations = int(np.sum(highs < lows))
            results.append(
                QualityCheckResult(
                    check_name="high_greater_equal_low",
                    status="PASS" if hl_violations == 0 else "FAIL",
                    metric_value=float(hl_violations),
                    threshold=0.0,
                    message=f"High < Low ihlali: {hl_violations} adet",
                )
            )

            # 2. High Extremum Check (High >= Open & Close)
            h_open_close_violations = int(np.sum((highs < opens) | (highs < closes)))
            results.append(
                QualityCheckResult(
                    check_name="high_is_maximum",
                    status="PASS" if h_open_close_violations == 0 else "FAIL",
                    metric_value=float(h_open_close_violations),
                    threshold=0.0,
                    message=f"High barın tepesinde değil: {h_open_close_violations} adet",
                )
            )

            # 3. Low Extremum Check (Low <= Open & Close)
            l_open_close_violations = int(np.sum((lows > opens) | (lows > closes)))
            results.append(
                QualityCheckResult(
                    check_name="low_is_minimum",
                    status="PASS" if l_open_close_violations == 0 else "FAIL",
                    metric_value=float(l_open_close_violations),
                    threshold=0.0,
                    message=f"Low barın tabanında değil: {l_open_close_violations} adet",
                )
            )

            # 4. Volume Non-negative
            vol_violations = int(np.sum(volumes < 0))
            results.append(
                QualityCheckResult(
                    check_name="non_negative_volume",
                    status="PASS" if vol_violations == 0 else "FAIL",
                    metric_value=float(vol_violations),
                    threshold=0.0,
                    message=f"Negatif hacim: {vol_violations} adet",
                )
            )

            # 5. Non-zero Price
            zero_prices = int(np.sum(closes <= 0))
            results.append(
                QualityCheckResult(
                    check_name="positive_price",
                    status="PASS" if zero_prices == 0 else "FAIL",
                    metric_value=float(zero_prices),
                    threshold=0.0,
                    message=f"Sıfır veya negatif fiyat: {zero_prices} adet",
                )
            )

            return results

    def audit_ohlcv_polars(self, df: pl.DataFrame) -> list[QualityCheckResult]:
        """Polars DataFrame formatındaki OHLCV verilerini doğrudan denetler."""
        if df.is_empty():
            return [QualityCheckResult("empty_data", "FAIL", 0.0, 1.0, "Boş veri seti")]

        col_map = {c.lower(): c for c in df.columns}
        df_dict = {
            "open": df[col_map["open"]].to_list() if "open" in col_map else [],
            "high": df[col_map["high"]].to_list() if "high" in col_map else [],
            "low": df[col_map["low"]].to_list() if "low" in col_map else [],
            "close": df[col_map["close"]].to_list() if "close" in col_map else [],
            "volume": df[col_map["volume"]].to_list() if "volume" in col_map else [],
        }
        return self.audit_ohlcv_integrity(df_dict)

    def compute_ks_drift(
        self,
        reference: np.ndarray,
        current: np.ndarray,
        feature_name: str,
    ) -> DriftCheckResult:
        """Kolmogorov-Smirnov iki örneklem drift testi uygular."""
        if len(reference) < 5 or len(current) < 5:
            return DriftCheckResult(feature_name, 1.0, "KS_TEST", False, "NONE", 0.0, 0.0)

        _, p_value = stats.ks_2samp(reference, current)
        is_drifted = bool(p_value < self.ks_alpha)
        severity = "SEVERE" if p_value < 0.01 else ("MODERATE" if is_drifted else "NONE")

        return DriftCheckResult(
            feature_name=feature_name,
            drift_score=round(float(p_value), 5),
            method="KS_TEST",
            is_drifted=is_drifted,
            severity=severity,
            reference_mean=round(float(np.mean(reference)), 4),
            current_mean=round(float(np.mean(current)), 4),
        )

    def compute_psi(
        self,
        reference: np.ndarray,
        current: np.ndarray,
        feature_name: str,
        num_buckets: int = 10,
    ) -> DriftCheckResult:
        """Population Stability Index (PSI) hesabı yapar."""
        if len(reference) < 10 or len(current) < 10:
            return DriftCheckResult(feature_name, 0.0, "PSI", False, "NONE", 0.0, 0.0)

        quantiles = np.linspace(0, 100, num_buckets + 1)
        bins = np.percentile(reference, quantiles)
        bins = np.unique(bins)
        if len(bins) < 2:
            return DriftCheckResult(
                feature_name,
                0.0,
                "PSI",
                False,
                "NONE",
                float(np.mean(reference)),
                float(np.mean(current)),
            )

        ref_counts, _ = np.histogram(reference, bins=bins)
        cur_counts, _ = np.histogram(current, bins=bins)

        ref_pct = np.clip(ref_counts / len(reference), 1e-4, 1.0)
        cur_pct = np.clip(cur_counts / len(current), 1e-4, 1.0)

        psi_val = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
        is_drifted = bool(psi_val > self.psi_threshold)
        severity = "SEVERE" if psi_val > 0.25 else ("MODERATE" if psi_val > 0.10 else "NONE")

        return DriftCheckResult(
            feature_name=feature_name,
            drift_score=round(psi_val, 4),
            method="PSI",
            is_drifted=is_drifted,
            severity=severity,
            reference_mean=round(float(np.mean(reference)), 4),
            current_mean=round(float(np.mean(current)), 4),
        )

    def generate_full_audit(
        self,
        ohlcv_data: dict[str, list[float]],
        ref_features: dict[str, np.ndarray],
        cur_features: dict[str, np.ndarray],
    ) -> DataQualityReport:
        """Tüm kontrolleri çalıştırıp karar kapısı (Gate) raporu oluşturur."""
        with self._lock:
            q_results = self.audit_ohlcv_integrity(ohlcv_data)
            d_results: list[DriftCheckResult] = []

            for feat_name, ref_arr in ref_features.items():
                if feat_name in cur_features:
                    cur_arr = cur_features[feat_name]
                    d_results.append(self.compute_ks_drift(ref_arr, cur_arr, feat_name))

            failed_q = sum(1 for q in q_results if q.status == "FAIL")
            drifted_f = sum(1 for d in d_results if d.is_drifted and d.severity == "SEVERE")

            is_allowed = (failed_q == 0) and (drifted_f <= len(d_results) // 2)
            score = max(0.0, 100.0 - (failed_q * 25.0) - (drifted_f * 10.0))

            return DataQualityReport(
                is_pipeline_allowed=is_allowed,
                overall_score=round(score, 1),
                quality_checks=q_results,
                drift_checks=d_results,
                failed_checks_count=failed_q,
                drifted_features_count=drifted_f,
            )


# Global Singleton
data_monitor: EvidentlyDataMonitor = EvidentlyDataMonitor()


# ==============================================================================
# DuckDB Kalıcılık ve Yardımcı Fonksiyonlar
# ==============================================================================


def export_report_to_duckdb(
    report: DataQualityReport,
    db_path: str = DEFAULT_EVIDENTLY_DB_PATH,
) -> int:
    """Veri kalitesi ve drift raporunu DuckDB denetim tablosuna kaydeder.

    Args:
        report: Kaydedilecek DataQualityReport nesnesi.
        db_path: DuckDB dosya yolu.

    Returns:
        int: Eklenen kayıt sayısı (1).
    """
    target_file = Path(db_path)
    target_file.parent.mkdir(parents=True, exist_ok=True)

    row_id = uuid.uuid4().hex
    row = (
        row_id,
        datetime.now(UTC),
        report.is_pipeline_allowed,
        report.overall_score,
        report.failed_checks_count,
        report.drifted_features_count,
        orjson.dumps([q.to_dict() for q in report.quality_checks]).decode("utf-8"),
        orjson.dumps([d.to_dict() for d in report.drift_checks]).decode("utf-8"),
    )

    try:
        with duckdb.connect(str(target_file)) as conn:
            configure_duckdb_wal(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evidently_audit_log (
                    id VARCHAR PRIMARY KEY,
                    created_at TIMESTAMP,
                    is_pipeline_allowed BOOLEAN,
                    overall_score DOUBLE,
                    failed_checks_count INTEGER,
                    drifted_features_count INTEGER,
                    quality_checks_json VARCHAR,
                    drift_checks_json VARCHAR
                )
                """
            )
            conn.execute(
                """
                INSERT INTO evidently_audit_log (
                    id, created_at, is_pipeline_allowed, overall_score,
                    failed_checks_count, drifted_features_count,
                    quality_checks_json, drift_checks_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
        logger.info("evidently_raporu_duckdb_kaydedildi", id=row_id, yol=str(target_file))
        return 1
    except Exception as exc:
        logger.error("evidently_rapor_kayit_hatasi", hata=str(exc))
        return 0


def read_evidently_audit_from_duckdb(
    db_path: str = DEFAULT_EVIDENTLY_DB_PATH,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB denetim tablosunu doğrudan Polars DataFrame olarak sorgular.

    Args:
        db_path: DuckDB dosya yolu.
        limit: Maksimum kayıt sayısı.

    Returns:
        pl.DataFrame: Denetim geçmişi tablosu.
    """
    path_obj = Path(db_path)
    schema: dict[str, pl.DataType] = {
        "id": pl.Utf8,
        "created_at": pl.Datetime,
        "is_pipeline_allowed": pl.Boolean,
        "overall_score": pl.Float64,
        "failed_checks_count": pl.Int64,
        "drifted_features_count": pl.Int64,
        "quality_checks_json": pl.Utf8,
        "drift_checks_json": pl.Utf8,
    }
    if not path_obj.exists():
        return pl.DataFrame(schema=schema)

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            tbl_check = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'evidently_audit_log'"
            ).fetchone()
            if not tbl_check or tbl_check[0] == 0:
                return pl.DataFrame(schema=schema)

            query = (
                "SELECT id, created_at, is_pipeline_allowed, overall_score, "
                "failed_checks_count, drifted_features_count, quality_checks_json, drift_checks_json "
                "FROM evidently_audit_log ORDER BY created_at DESC LIMIT ?"
            )
            return conn.execute(query, [max(1, int(limit))]).pl()
    except Exception as exc:
        logger.warning("duckdb_evidently_audit_okuma_hatasi", db_path=db_path, hata=str(exc))
        return pl.DataFrame(schema=schema)


def clear_evidently_audit_duckdb(db_path: str = DEFAULT_EVIDENTLY_DB_PATH) -> None:
    """DuckDB denetim tablosunu temizler.

    Args:
        db_path: DuckDB dosya yolu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return
    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.execute("DROP TABLE IF EXISTS evidently_audit_log;")
    except Exception as exc:
        logger.error("duckdb_evidently_audit_temizleme_hatasi", db_path=db_path, hata=str(exc))


__all__: Final[list[str]] = [
    # Sabitler
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_EVIDENTLY_DB_PATH",
    "DEFAULT_KS_ALPHA",
    "DEFAULT_PSI_THRESHOLD",
    "DEFAULT_WAL_SIZE",
    # Modeller
    "DataQualityReport",
    "DriftCheckResult",
    "QualityCheckResult",
    # Motor ve Singleton
    "EvidentlyDataMonitor",
    "data_monitor",
    # Yardımcı Fonksiyonlar
    "clear_evidently_audit_duckdb",
    "configure_duckdb_wal",
    "export_report_to_duckdb",
    "read_evidently_audit_from_duckdb",
    "to_orjson_bytes",
]
