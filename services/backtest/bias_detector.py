"""
ALPHA BIST — Look-Ahead Bias Detector

Tasarım İlkeleri:
1. Her feature/label/signal için timestamp validation
2. Gelecek veri kullanımı tespiti (data leakage detection)
3. Feature hesaplama penceresi ile label penceresi çakışma kontrolü
4. Walk-forward fold sınırlarında leakage guard
5. Otomatik raporlama ve uyarı sistemi

Referanslar:
- "Advances in Financial Machine Learning" (Marcos López de Prado) - Ch.7
- arXiv Momentum-Gated Framework (2026) - bias prevention protocols
"""

import numpy as np
import polars as pl
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class BiasViolation:
    """Tek bir bias ihlali kaydı."""
    violation_type: str  # look_ahead | label_leakage | feature_leakage | fold_leakage
    severity: str  # critical | warning | info
    timestamp: datetime
    feature_name: Optional[str]
    description: str
    data_point: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.violation_type,
            "severity": self.severity,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "feature": self.feature_name,
            "description": self.description,
        }


@dataclass
class BiasReport:
    """Bias tespit raporu."""
    total_checks: int = 0
    violations: List[BiasViolation] = field(default_factory=list)
    critical_count: int = 0
    warning_count: int = 0
    is_clean: bool = True

    def add_violation(self, violation: BiasViolation):
        self.violations.append(violation)
        if violation.severity == "critical":
            self.critical_count += 1
            self.is_clean = False
        elif violation.severity == "warning":
            self.warning_count += 1

    def to_dict(self) -> Dict[str, Any]:
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

    def __init__(self):
        self.violations: List[BiasViolation] = []

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
            BiasReport
        """
        report = BiasReport()

        if timestamp_col not in feature_df.columns:
            report.add_violation(BiasViolation(
                violation_type="look_ahead",
                severity="critical",
                timestamp=decision_timestamp,
                feature_name=feature_name,
                description=f"Timestamp column '{timestamp_col}' not found in feature data",
            ))
            return report

        # Gelecekteki verileri kontrol et
        future_data = feature_df[feature_df[timestamp_col] > decision_timestamp]
        report.total_checks = len(feature_df)

        if len(future_data) > 0:
            report.add_violation(BiasViolation(
                violation_type="look_ahead",
                severity="critical",
                timestamp=decision_timestamp,
                feature_name=feature_name,
                description=f"Feature contains {len(future_data)} data points after decision time. "
                           f"Max future timestamp: {future_data[timestamp_col].max()}",
                data_point={"future_rows": len(future_data)},
            ))

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

        Her veri noktası için, o noktanın window hesaplamasında sadece
        kendisinden önceki verilerin kullanıldığını kontrol eder.
        """
        report = BiasReport()
        report.total_checks = len(data)

        if len(data) < window_size + 1:
            return report

        data = data.sort(timestamp_col)

        for i in range(window_size, len(data)):
            # Bu noktanın window'u data[i-window_size:i] olmalı
            # Eğer data[i-window_size:i+1] kullanılmışsa → leakage
            window_values = data[value_col][i - window_size:i]
            data[value_col][i]

            # Rolling mean hesapla (sadece geçmiş veri ile)
            expected_mean = window_values.mean()

            # Gerçek rolling değeri kontrol et
            if "rolling_mean" in data.columns:
                actual_mean = data["rolling_mean"][i]
                if not np.isnan(actual_mean) and not np.isnan(expected_mean):
                    diff = abs(actual_mean - expected_mean)
                    if diff > 1e-10:
                        report.add_violation(BiasViolation(
                            violation_type="look_ahead",
                            severity="critical",
                            timestamp=data[timestamp_col][i],
                            feature_name=feature_name,
                            description=f"Rolling window at index {i} uses future data. "
                                       f"Expected: {expected_mean:.4f}, Got: {actual_mean:.4f}",
                        ))

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
        """
        report = BiasReport()
        report.total_checks = 1

        min_purge = label_horizon_days
        if purge_days < min_purge:
            report.add_violation(BiasViolation(
                violation_type="label_leakage",
                severity="critical",
                timestamp=datetime.now(timezone.utc),
                feature_name="purge_validation",
                description=f"Purge days ({purge_days}) < label horizon ({label_horizon_days}). "
                           f"Minimum purge should be {min_purge} days to prevent label leakage.",
            ))
        else:
            logger.info("Label-feature alignment OK",
                       purge=purge_days, horizon=label_horizon_days)

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
        """
        report = BiasReport()
        report.total_checks = 4

        # 1. Test starts after train ends
        if test_start <= train_end:
            report.add_violation(BiasViolation(
                violation_type="fold_leakage",
                severity="critical",
                timestamp=train_end,
                feature_name="fold_boundary",
                description=f"Test start ({test_start}) <= train end ({train_end}). "
                           f"Test must start after training period.",
            ))

        # 2. Purge gap exists
        actual_gap = (test_start - train_end).days
        if actual_gap < purge_days:
            report.add_violation(BiasViolation(
                violation_type="fold_leakage",
                severity="critical",
                timestamp=train_end,
                feature_name="purge_gap",
                description=f"Actual gap ({actual_gap} days) < required purge ({purge_days} days). "
                           f"Purge gap insufficient to prevent label leakage.",
            ))

        # 3. Purge covers label horizon
        if actual_gap < label_horizon_days:
            report.add_violation(BiasViolation(
                violation_type="fold_leakage",
                severity="critical",
                timestamp=train_end,
                feature_name="purge_vs_horizon",
                description=f"Purge gap ({actual_gap} days) < label horizon ({label_horizon_days} days). "
                           f"Label from training period may leak into test period.",
            ))

        # 4. Embargo check (informational)
        if embargo_days > 0:
            logger.info("Embargo period configured",
                       embargo_days=embargo_days,
                       test_start=test_start.isoformat())

        return report

    def validate_data_revision_integrity(
        self,
        data: pl.DataFrame,
        report_date_col: str = "report_date",
        revision_col: Optional[str] = "revision_version",
    ) -> BiasReport:
        """
        Revize edilmiş verinin orijinal tarihte kullanılmadığını doğrula.

        Finansal veriler (özellikle bilanço) zaman içinde revize edilebilir.
        Backtest, veriyi sadece yayınlandığı tarihte biliyor olmalı.
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
                    report.add_violation(BiasViolation(
                        violation_type="look_ahead",
                        severity="warning",
                        timestamp=datetime.now(timezone.utc),
                        feature_name="data_revision",
                        description=f"Multiple revisions found for report date {name}. "
                                   f"Only the first (as-reported) version should be used in backtest.",
                        data_point={"report_date": str(name), "revisions": len(group)},
                    ))

        return report

    def get_summary(self) -> Dict[str, Any]:
        """Toplam bias tespit özeti."""
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

    def __init__(self, strict_mode: bool = True):
        """
        Args:
            strict_mode: True ise critical ihlal varsa backtest durdurulur
        """
        self.detector = LookAheadBiasDetector()
        self.strict_mode = strict_mode
        self.enabled = True

    def pre_scan_check(
        self,
        available_data: pl.DataFrame,
        decision_timestamp: datetime,
        label_horizon_days: int = 5,
        feature_window_days: int = 20,
        purge_days: int = 5,
    ) -> Tuple[bool, BiasReport]:
        """
        Tarama öncesi bias kontrolü.

        Returns:
            (is_safe, report): is_safe=True ise devam edilebilir
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
            logger.error("Bias check FAILED - blocking scan",
                        critical=combined_report.critical_count)

        return is_safe, combined_report

    def fold_check(
        self,
        train_end: datetime,
        test_start: datetime,
        purge_days: int,
        embargo_days: int,
        label_horizon_days: int,
    ) -> Tuple[bool, BiasReport]:
        """Walk-forward fold bias kontrolü."""
        if not self.enabled:
            return True, BiasReport()

        report = self.detector.validate_fold_boundaries(
            train_end, test_start, purge_days, embargo_days, label_horizon_days
        )

        is_safe = not (self.strict_mode and report.critical_count > 0)
        return is_safe, report
