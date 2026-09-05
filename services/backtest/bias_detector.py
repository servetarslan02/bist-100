"""
ALPHA BIST — Look-Ahead Bias Dedektörü

Tasarım İlkeleri:
1. Her feature/label/signal için timestamp doğrulama
2. Gelecek veri kullanımı tespiti (data leakage detection)
3. Feature hesaplama penceresi ile label penceresi çakışma kontrolü
4. Walk-forward fold sınırlarında leakage guard
5. Otomatik raporlama ve uyarı sistemi

Referanslar:
- "Advances in Financial Machine Learning" (Marcos López de Prado) - Bölüm 7
- arXiv Momentum-Gated Framework (2026) - bias prevention protocols
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import polars as pl
import structlog

logger = structlog.get_logger(__name__)

# =====================================================================
# SABİTLER (MAGIC NUMBER TEMİZLİĞİ)
# =====================================================================
DEFAULT_LABEL_HORIZON_DAYS: int = 5
DEFAULT_FEATURE_WINDOW_DAYS: int = 20
DEFAULT_PURGE_DAYS: int = 5
DEFAULT_ROLLING_TOLERANCE: float = 1e-10


@dataclass
class BiasViolation:
    """Tek bir bias ihlali kaydı.

    Her tespit edilen ihlal bu yapı ile raporlanır.
    Türler: look_ahead, label_leakage, feature_leakage, fold_leakage
    """

    violation_type: str  # look_ahead | label_leakage | feature_leakage | fold_leakage
    severity: str  # critical | warning | info
    timestamp: datetime
    feature_name: str | None
    description: str
    data_point: dict[str, Any] | None = None

    def __repr__(self) -> str:
        """BiasViolation okunabilir temsili."""
        return (
            f"BiasViolation("
            f"type={self.violation_type!r}, "
            f"severity={self.severity!r}, "
            f"feature={self.feature_name!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        """İhlali sözlük formatında döndürür.

        Returns:
            İhlal bilgilerini içeren sözlük
        """
        return {
            "type": self.violation_type,
            "severity": self.severity,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "feature": self.feature_name,
            "description": self.description,
        }


@dataclass
class BiasReport:
    """Bias tespit raporu.

    Tek bir doğrulama çalıştırmasından çıkan tüm ihlalleri
    ve istatistikleri tutar.
    """

    total_checks: int = 0
    violations: list[BiasViolation] = field(default_factory=list)
    critical_count: int = 0
    warning_count: int = 0
    is_clean: bool = True

    def __repr__(self) -> str:
        """BiasReport okunabilir temsili."""
        return (
            f"BiasReport("
            f"checks={self.total_checks}, "
            f"critical={self.critical_count}, "
            f"warning={self.warning_count}, "
            f"clean={self.is_clean})"
        )

    def add_violation(self, violation: BiasViolation) -> None:
        """Bias ihlalini rapora ekler.

        Args:
            violation: Eklenecek BiasViolation nesnesi
        """
        self.violations.append(violation)
        if violation.severity == "critical":
            self.critical_count += 1
            self.is_clean = False
        elif violation.severity == "warning":
            self.warning_count += 1

    def to_dict(self) -> dict[str, Any]:
        """Raporu sözlük formatında döndürür.

        Returns:
            Rapor istatistiklerini ve ihlalleri içeren sözlük
        """
        return {
            "total_checks": self.total_checks,
            "violations": [v.to_dict() for v in self.violations],
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "is_clean": self.is_clean,
        }


class LookAheadBiasDetector:
    """
    Look-ahead bias tespit sistemi.

    Kontrol mekanizmaları:
    1. Timestamp monotonicity - feature'lar sadece geçmiş veriden türetilmeli
    2. Window boundary - hareketli ortalama/pencere hesaplamalarında gelecek veri sızıntısı
    3. Label-feature alignment - label penceresi feature penceresine sızıntı yapmamalı
    4. Data revision - revize edilmiş verinin orijinal tarihte kullanılmaması
    """

    def __init__(self) -> None:
        """Look-ahead bias dedektörünü başlatır."""
        self.violations: list[BiasViolation] = []
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        """LookAheadBiasDetector okunabilir temsili."""
        with self._lock:
            critical = sum(1 for v in self.violations if v.severity == "critical")
            total = len(self.violations)
        return (
            f"LookAheadBiasDetector("
            f"violations={total}, "
            f"critical={critical})"
        )

    def _record(self, report: BiasReport, violation: BiasViolation) -> None:
        """İhlali hem rapora hem dedektör geçmişine kaydeder.

        Args:
            report: Güncel BiasReport nesnesi
            violation: Kaydedilecek BiasViolation nesnesi
        """
        report.add_violation(violation)
        with self._lock:
            self.violations.append(violation)

    def validate_feature_timestamps(
        self,
        feature_df: pl.DataFrame,
        feature_name: str,
        decision_timestamp: datetime,
        timestamp_col: str = "timestamp",
    ) -> BiasReport:
        """
        Feature'ların sadece karar anına kadar olan veriden türetildiğini doğrula.

        Args:
            feature_df: Feature verisi
            feature_name: Feature adı
            decision_timestamp: Karar anı
            timestamp_col: Timestamp sütun adı

        Returns:
            BiasReport nesnesi
        """
        report = BiasReport()

        if timestamp_col not in feature_df.columns:
            self._record(
                report,
                BiasViolation(
                    violation_type="look_ahead",
                    severity="critical",
                    timestamp=decision_timestamp,
                    feature_name=feature_name,
                    description=(
                        f"Zaman damgası sütunu '{timestamp_col}' "
                        f"feature verisinde bulunamadı"
                    ),
                ),
            )
            return report

        # Gelecekteki verileri kontrol et (Polars vektörel filtreleme)
        future_data = feature_df.filter(pl.col(timestamp_col) > decision_timestamp)
        report.total_checks = len(feature_df)

        if len(future_data) > 0:
            self._record(
                report,
                BiasViolation(
                    violation_type="look_ahead",
                    severity="critical",
                    timestamp=decision_timestamp,
                    feature_name=feature_name,
                    description=(
                        f"Feature, karar anından sonra {len(future_data)} "
                        f"veri noktası içeriyor. "
                        f"En ileri zaman damgası: {future_data[timestamp_col].max()}"
                    ),
                    data_point={"future_rows": len(future_data)},
                ),
            )

        return report

    def validate_rolling_window(
        self,
        data: pl.DataFrame,
        window_size: int,
        feature_name: str,
        value_col: str = "close",
        timestamp_col: str = "timestamp",
    ) -> BiasReport:
        """
        Rolling window hesaplamasının gelecek veri kullanmadığını doğrula.

        Polars vektörel operasyonlarla gerçekleştirilir.
        Her veri noktası için, o noktanın window hesaplamasında sadece
        kendisinden önceki verilerin kullanıldığını kontrol eder.

        Beklenen değer: shift(1).rolling_mean(window_size)
        Gerçek değer: DataFrame'deki rolling_mean sütunu

        Args:
            data: Ham fiyat/veri DataFrame'i
            window_size: Rolling pencere boyutu
            feature_name: Kontrol edilen feature adı
            value_col: Değer sütun adı
            timestamp_col: Timestamp sütun adı

        Returns:
            BiasReport nesnesi
        """
        report = BiasReport()
        report.total_checks = len(data)

        if len(data) < window_size + 1:
            return report

        if "rolling_mean" not in data.columns:
            return report

        data = data.sort(timestamp_col)

        # Vektörel hesaplama: beklenen rolling mean (sadece geçmiş veri ile)
        # shift(1) ile mevcut değer hariç tutulur, ardından rolling_mean
        # hesaplanır — böylece her satırda sadece önceki window_size değer
        # kullanılmış olur.
        expected_col = "__expected_rolling_mean__"
        diff_col = "__rolling_diff__"

        computed = data.with_columns(
            pl.col(value_col)
            .shift(1)
            .rolling_mean(window_size)
            .alias(expected_col),
        ).with_columns(
            (pl.col("rolling_mean") - pl.col(expected_col))
            .abs()
            .alias(diff_col),
        )

        # Fark 1e-10'dan büyük olan ihlalleri filtrele
        violations_df = computed.filter(
            pl.col(diff_col).is_not_null()
            & pl.col(expected_col).is_not_null()
            & (pl.col(diff_col) > 1e-10)
        )

        for row in violations_df.iter_rows(named=True):
            expected_val = float(row[expected_col])
            actual_val = float(row["rolling_mean"])
            ts = row[timestamp_col]

            self._record(
                report,
                BiasViolation(
                    violation_type="look_ahead",
                    severity="critical",
                    timestamp=ts,
                    feature_name=feature_name,
                    description=(
                        f"Rolling window gelecek veri kullanıyor. "
                        f"Beklenen: {expected_val:.4f}, "
                        f"Gerçek: {actual_val:.4f}"
                    ),
                ),
            )

        return report

    def validate_label_feature_alignment(
        self,
        label_horizon_days: int,
        feature_window_days: int,
        purge_days: int,
    ) -> BiasReport:
        """
        Label ve feature pencerelerinin çakışmadığını doğrula.

        Label = gelecek N günlük getiri (forward return)
        Feature = geçmiş M günlük veriden türetilen
        Purge = label ve feature arasındaki güvenlik boşluğu

        Kural: purge_days >= label_horizon_days (minimum)

        Args:
            label_horizon_days: Label ufkunun gün sayısı
            feature_window_days: Feature penceresinin gün sayısı
            purge_days: Purge boşluğu (gün)

        Returns:
            BiasReport nesnesi
        """
        report = BiasReport()
        report.total_checks = 1

        min_purge = label_horizon_days
        if purge_days < min_purge:
            self._record(
                report,
                BiasViolation(
                    violation_type="label_leakage",
                    severity="critical",
                    timestamp=datetime.now(UTC),
                    feature_name="purge_validation",
                    description=(
                        f"Purge günleri ({purge_days}) < label ufku "
                        f"({label_horizon_days}). Label sızıntısını önlemek "
                        f"için minimum purge {min_purge} gün olmalıdır."
                    ),
                ),
            )
        else:
            logger.info(
                "label_feature_hizalama: purge=%s, horizon=%s",
                purge_days,
                label_horizon_days,
            )

        return report

    def validate_fold_boundaries(
        self,
        train_end: datetime,
        test_start: datetime,
        purge_days: int,
        embargo_days: int,
        label_horizon_days: int,
    ) -> BiasReport:
        """
        Walk-forward fold sınırlarında leakage kontrolü.

        Kontroller:
        1. Train-test arasında purge gap var mı?
        2. Purge gap label horizon'dan büyük mü?
        3. Embargo period doğru uygulanmış mı?
        4. Test başlangıcı train bitişinden sonra mı?

        Args:
            train_end: Eğitim döneminin bitiş tarihi
            test_start: Test döneminin başlangıç tarihi
            purge_days: Gerekli purge süresi (gün)
            embargo_days: Embargo süresi (gün)
            label_horizon_days: Label ufkunun gün sayısı

        Returns:
            BiasReport nesnesi
        """
        report = BiasReport()
        report.total_checks = 4

        # 1. Test starts after train ends
        if test_start <= train_end:
            self._record(
                report,
                BiasViolation(
                    violation_type="fold_leakage",
                    severity="critical",
                    timestamp=train_end,
                    feature_name="fold_boundary",
                    description=(
                        f"Test başlangıcı ({test_start}) <= eğitim bitişi "
                        f"({train_end}). Test, eğitim döneminden sonra "
                        f"başlamalıdır."
                    ),
                ),
            )

        # 2. Purge gap exists
        actual_gap = (test_start - train_end).days
        if actual_gap < purge_days:
            self._record(
                report,
                BiasViolation(
                    violation_type="fold_leakage",
                    severity="critical",
                    timestamp=train_end,
                    feature_name="purge_gap",
                    description=(
                        f"Gerçek boşluk ({actual_gap} gün) < gerekli purge "
                        f"({purge_days} gün). Label sızıntısını önlemek için "
                        f"purge boşluğu yetersiz."
                    ),
                ),
            )

        # 3. Purge covers label horizon
        if actual_gap < label_horizon_days:
            self._record(
                report,
                BiasViolation(
                    violation_type="fold_leakage",
                    severity="critical",
                    timestamp=train_end,
                    feature_name="purge_vs_horizon",
                    description=(
                        f"Purge boşluğu ({actual_gap} gün) < label ufku "
                        f"({label_horizon_days} gün). Eğitim döneminin "
                        f"label'ı test dönemine sızabilir."
                    ),
                ),
            )

        # 4. Embargo check (informational)
        if embargo_days > 0:
            logger.info(
                "embargo_suresi: gun=%s, test_baslangic=%s",
                embargo_days,
                test_start.isoformat(),
            )

        return report

    def validate_data_revision_integrity(
        self,
        data: pl.DataFrame,
        report_date_col: str = "report_date",
        revision_col: str | None = "revision_version",
    ) -> BiasReport:
        """
        Revize edilmiş verinin orijinal tarihte kullanılmadığını doğrula.

        Finansal veriler (özellikle bilanço) zaman içinde revize edilebilir.
        Backtest, veriyi sadece yayınlandığı tarihte biliyor olmalı.

        Args:
            data: Kontrol edilecek veri DataFrame'i
            report_date_col: Rapor tarihi sütun adı
            revision_col: Revizyon sütun adı (None ise kontrol edilmez)

        Returns:
            BiasReport nesnesi
        """
        report = BiasReport()

        if report_date_col not in data.columns:
            report.total_checks = 0
            return report

        report.total_checks = len(data)

        if revision_col and revision_col in data.columns:
            # Birden fazla revizyon varsa, sadece ilki kullanılmalı
            for name, group in data.group_by(report_date_col):
                if len(group) > 1:
                    self._record(
                        report,
                        BiasViolation(
                            violation_type="look_ahead",
                            severity="warning",
                            timestamp=datetime.now(UTC),
                            feature_name="data_revision",
                            description=(
                                f"Rapor tarihi {name} için birden fazla "
                                f"revizyon bulundu. Backtest'te sadece ilk "
                                f"(as-reported) versiyon kullanılmalıdır."
                            ),
                            data_point={
                                "report_date": str(name),
                                "revisions": len(group),
                            },
                        ),
                    )

        return report

    def get_summary(self) -> dict[str, Any]:
        """Toplam bias tespit özeti.

        Returns:
            violation istatistiklerini ve detaylarını içeren sözlük
        """
        critical = sum(1 for v in self.violations if v.severity == "critical")
        warnings = sum(1 for v in self.violations if v.severity == "warning")

        return {
            "total_violations": len(self.violations),
            "critical": critical,
            "warnings": warnings,
            "is_clean": critical == 0,
            "violations": [v.to_dict() for v in self.violations],
        }


class BiasDetectorMiddleware:
    """
    Backtest engine'e entegre edilebilen bias detection middleware.

    Her backtest çalıştırmasında otomatik olarak bias kontrolü yapar
    ve sonuçları raporlar.
    """

    def __init__(self, strict_mode: bool = True) -> None:
        """Bias detection middleware'ini başlatır.

        Args:
            strict_mode: True ise critical ihlal varsa backtest durdurulur
        """
        self.detector = LookAheadBiasDetector()
        self.strict_mode = strict_mode
        self.enabled = True

    def __repr__(self) -> str:
        """BiasDetectorMiddleware okunabilir temsili."""
        return (
            f"BiasDetectorMiddleware("
            f"strict={self.strict_mode}, "
            f"enabled={self.enabled}, "
            f"violations={len(self.detector.violations)})"
        )

    def pre_scan_check(
        self,
        available_data: pl.DataFrame,
        decision_timestamp: datetime,
        label_horizon_days: int = 5,
        feature_window_days: int = 20,
        purge_days: int = 5,
    ) -> tuple[bool, BiasReport]:
        """
        Tarama öncesi bias kontrolü.

        Args:
            available_data: Mevcut veri DataFrame'i
            decision_timestamp: Karar anı
            label_horizon_days: Label ufkunun gün sayısı
            feature_window_days: Feature penceresinin gün sayısı
            purge_days: Purge boşluğu (gün)

        Returns:
            (is_safe, report) çifti. is_safe=True ise devam edilebilir.
        """
        if not self.enabled:
            return True, BiasReport()

        combined_report = BiasReport()

        # 1. Timestamp validation
        for col in available_data.columns:
            if col.endswith("_score") or col.endswith("_feature"):
                report = self.detector.validate_feature_timestamps(
                    available_data, col, decision_timestamp
                )
                combined_report.total_checks += report.total_checks
                for v in report.violations:
                    combined_report.add_violation(v)

        # 2. Label-feature alignment
        alignment_report = self.detector.validate_label_feature_alignment(
            label_horizon_days, feature_window_days, purge_days
        )
        combined_report.total_checks += alignment_report.total_checks
        for v in alignment_report.violations:
            combined_report.add_violation(v)

        is_safe = not (self.strict_mode and combined_report.critical_count > 0)

        if not is_safe:
            logger.error(
                "bias_kontrol_basarisiz: critical=%s",
                combined_report.critical_count,
            )

        return is_safe, combined_report

    def fold_check(
        self,
        train_end: datetime,
        test_start: datetime,
        purge_days: int,
        embargo_days: int,
        label_horizon_days: int,
    ) -> tuple[bool, BiasReport]:
        """Walk-forward fold bias kontrolü.

        Args:
            train_end: Eğitim döneminin bitiş tarihi
            test_start: Test döneminin başlangıç tarihi
            purge_days: Gerekli purge süresi (gün)
            embargo_days: Embargo süresi (gün)
            label_horizon_days: Label ufkunun gün sayısı

        Returns:
            (is_safe, report) çifti. is_safe=True ise devam edilebilir.
        """
        if not self.enabled:
            return True, BiasReport()

        report = self.detector.validate_fold_boundaries(
            train_end, test_start, purge_days, embargo_days, label_horizon_days
        )

        is_safe = not (self.strict_mode and report.critical_count > 0)
        return is_safe, report


# Singleton
bias_detector_middleware = BiasDetectorMiddleware()

__all__ = [
    "BiasViolation",
    "BiasReport",
    "LookAheadBiasDetector",
    "BiasDetectorMiddleware",
    "bias_detector_middleware",
    "DEFAULT_LABEL_HORIZON_DAYS",
    "DEFAULT_FEATURE_WINDOW_DAYS",
    "DEFAULT_PURGE_DAYS",
    "DEFAULT_ROLLING_TOLERANCE",
]
