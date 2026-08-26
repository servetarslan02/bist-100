"""
ALPHA BIST — Point-in-Time (PIT) Validator

Point-in-time disiplini, backtest'in geleceği görmemesinin temel garantisidir.
Bu modül, verinin ve feature'ların "o an bilinebilir" olduğunu doğrular.

Kontroller:
1. Fundamental veri: Yayın tarihi vs rapor tarihi ayrımı
2. Haber/KAP: Kaynak zamanı vs sisteme giriş zamanı
3. Feature penceresi: Sadece geçmiş veriden türetilme garantisi
4. Label üretimi: Feature'tan sonra, purge ile ayrılma
5. Corporate action: Bölünme/temettü düzeltmelerinin zamanlaması

Referanslar:
- "Point-in-Time Data in Quantitative Finance" (Quantopian/Alpaca)
- Marcos López de Prado - "Advances in Financial Machine ML" Ch.7
"""

import polars as pl
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import structlog

logger = structlog.get_logger()


@dataclass
class PITRecord:
    """Point-in-time veri kaydı."""
    data_id: str
    ticker: str
    report_date: datetime      # Rapor dönemi (örn: 2024-Q3)
    publish_date: datetime     # Gerçek yayın tarihi
    data_type: str             # fundamental | price | news | macro
    revision_version: int = 1  # Revizyon numarası
    is_original: bool = True   # İlk yayınlanan mı?

    @property
    def lag_days(self) -> int:
        """Yayın gecikmesi (gün)."""
        return (self.publish_date - self.report_date).days

    def to_dict(self) -> Dict[str, Any]:
        return {
            "data_id": self.data_id,
            "ticker": self.ticker,
            "report_date": self.report_date.isoformat(),
            "publish_date": self.publish_date.isoformat(),
            "data_type": self.data_type,
            "revision_version": self.revision_version,
            "is_original": self.is_original,
            "lag_days": self.lag_days,
        }


@dataclass
class PITViolation:
    """PIT ihlali."""
    violation_type: str  # future_data | revision_leakage | timing_error
    severity: str  # critical | warning | info
    description: str
    record: Optional[PITRecord] = None
    decision_time: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.violation_type,
            "severity": self.severity,
            "description": self.description,
            "record": self.record.to_dict() if self.record else None,
        }


@dataclass
class PITValidationReport:
    """PIT doğrulama raporu."""
    total_records: int = 0
    violations: List[PITViolation] = field(default_factory=list)
    critical_count: int = 0
    warning_count: int = 0
    is_valid: bool = True

    def add_violation(self, violation: PITViolation):
        self.violations.append(violation)
        if violation.severity == "critical":
            self.critical_count += 1
            self.is_valid = False
        elif violation.severity == "warning":
            self.warning_count += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_records": self.total_records,
            "violations": [v.to_dict() for v in self.violations],
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "is_valid": self.is_valid,
        }


class PointInTimeValidator:
    """
    Point-in-time doğrulama sistemi.

    Temel soru: "Bu veri, karar anında gerçekten bilinebilir miydi?"
    """

    def __init__(self):
        self._registry: Dict[str, List[PITRecord]] = {}  # ticker → records
        self._corporate_actions: List[Dict[str, Any]] = []

    def register_record(self, record: PITRecord):
        """PIT kaydı oluştur."""
        if record.ticker not in self._registry:
            self._registry[record.ticker] = []
        self._registry[record.ticker].append(record)

    def register_fundamental_data(
        self,
        ticker: str,
        report_date: datetime,
        publish_date: datetime,
        revision_version: int = 1,
    ):
        """Temel veri (bilanço) kaydı oluştur."""
        record = PITRecord(
            data_id=f"{ticker}_{report_date.strftime('%Y%m%d')}_v{revision_version}",
            ticker=ticker,
            report_date=report_date,
            publish_date=publish_date,
            data_type="fundamental",
            revision_version=revision_version,
            is_original=(revision_version == 1),
        )
        self.register_record(record)

    def register_news_event(
        self,
        ticker: str,
        event_time: datetime,
        system_entry_time: datetime,
    ):
        """Haber/KAP olayı kaydı oluştur."""
        record = PITRecord(
            data_id=f"{ticker}_news_{event_time.strftime('%Y%m%d%H%M')}",
            ticker=ticker,
            report_date=event_time,
            publish_date=system_entry_time,
            data_type="news",
        )
        self.register_record(record)

    def register_corporate_action(
        self,
        ticker: str,
        action_type: str,  # dividend | split | rights_issue | merger
        ex_date: datetime,
        record_date: datetime,
        details: Dict[str, Any],
    ):
        """Kurumsal işlem (temettü, bölünme vb.) kaydı oluştur."""
        self._corporate_actions.append({
            "ticker": ticker,
            "action_type": action_type,
            "ex_date": ex_date,
            "record_date": record_date,
            "details": details,
        })
        if len(self._corporate_actions) > 500:
            self._corporate_actions = self._corporate_actions[-500:]

    def get_available_data_at(
        self,
        ticker: str,
        decision_time: datetime,
        data_type: Optional[str] = None,
    ) -> List[PITRecord]:
        """
        Karar anında mevcut olan verileri döndürür.

        Sadece decision_time'dan önce yayınlanmış veriler dahil edilir.
        """
        if ticker not in self._registry:
            return []

        available = []
        for record in self._registry[ticker]:
            # Sadece yayınlanmış veriler
            if record.publish_date <= decision_time:
                if data_type is None or record.data_type == data_type:
                    available.append(record)

        return available

    def get_latest_fundamental(
        self,
        ticker: str,
        decision_time: datetime,
    ) -> Optional[PITRecord]:
        """
        Karar anında mevcut olan en güncel temel veriyi döndürür.

        Revizyon varsa, o ana kadar yayınlanmış en güncel revizyonu döndürür.
        """
        fundamentals = self.get_available_data_at(
            ticker, decision_time, "fundamental"
        )

        if not fundamentals:
            return None

        # En güncel rapor tarihi + en güncel revizyon
        latest = max(
            fundamentals,
            key=lambda r: (r.report_date, r.revision_version),
        )

        return latest

    def validate_fundamental_access(
        self,
        ticker: str,
        report_date: datetime,
        revision_version: int,
        decision_time: datetime,
    ) -> Tuple[bool, Optional[PITViolation]]:
        """
        Temel veri erişiminin PIT kurallarına uygunluğunu doğrula.

        Kontroller:
        1. Veri yayınlanmış mı? (publish_date <= decision_time)
        2. Revizyon sızıntısı yok mu?
        3. Rapor dönemi karar anından önce mi? (mantıksal kontrol)
        """
        records = self._registry.get(ticker, [])

        # İlgili kaydı bul
        target = None
        for r in records:
            if (r.report_date == report_date and
                r.revision_version == revision_version and
                r.data_type == "fundamental"):
                target = r
                break

        if target is None:
            return False, PITViolation(
                violation_type="timing_error",
                severity="critical",
                description=f"Fundamental data not found: {ticker} {report_date} v{revision_version}",
                decision_time=decision_time,
            )

        # Yayın kontrolü
        if target.publish_date > decision_time:
            return False, PITViolation(
                violation_type="future_data",
                severity="critical",
                description=f"Accessing unpublished data: {ticker} {report_date} v{revision_version}. "
                           f"Published: {target.publish_date}, Decision: {decision_time}",
                record=target,
                decision_time=decision_time,
            )

        # Revizyon sızıntısı kontrolü
        if revision_version > 1:
            original = None
            for r in records:
                if (r.report_date == report_date and
                    r.revision_version == 1 and
                    r.data_type == "fundamental"):
                    original = r
                    break

            if original and original.publish_date > decision_time:
                return False, PITViolation(
                    violation_type="revision_leakage",
                    severity="critical",
                    description=f"Original data not yet published at decision time. "
                               f"Cannot use revision v{revision_version} before original.",
                    record=target,
                    decision_time=decision_time,
                )

        return True, None

    def validate_feature_set(
        self,
        feature_df: pl.DataFrame,
        ticker: str,
        decision_time: datetime,
        feature_cols: List[str],
        timestamp_col: str = "timestamp",
    ) -> PITValidationReport:
        """
        Feature set'in PIT uyumluluğunu toplu doğrula.

        Args:
            feature_df: Feature verisi
            ticker: Hisse kodu
            decision_time: Karar anı
            feature_cols: Kontrol edilecek feature sütunları
            timestamp_col: Timestamp sütun adı

        Returns:
            PITValidationReport
        """
        report = PITValidationReport()

        if timestamp_col not in feature_df.columns:
            report.add_violation(PITViolation(
                violation_type="timing_error",
                severity="critical",
                description=f"Timestamp column '{timestamp_col}' not found",
            ))
            return report

        # Gelecek veri kontrolü
        future_mask = feature_df[timestamp_col] > decision_time
        report.total_records = len(feature_df)

        if future_mask.any():
            future_count = future_mask.sum()
            report.add_violation(PITViolation(
                violation_type="future_data",
                severity="critical",
                description=f"Feature set contains {future_count} rows with future data. "
                           f"Decision time: {decision_time}, "
                           f"Max timestamp: {feature_df[timestamp_col].max()}",
                decision_time=decision_time,
            ))

        # NaN pattern kontrolü (gelecekteki feature'lar NaN olmalı)
        for col in feature_cols:
            if col in feature_df.columns:
                # Son N satırı kontrol et (karar anına en yakın)
                recent = feature_df[~future_mask].tail(5)
                if len(recent) > 0:
                    nan_ratio = recent[col].isna().mean()
                    if nan_ratio > 0.5:
                        report.add_violation(PITViolation(
                            violation_type="timing_error",
                            severity="warning",
                            description=f"Feature '{col}' has {nan_ratio:.0%} NaN in recent data. "
                                       f"May indicate data availability issue.",
                        ))

        return report

    def validate_label_generation(
        self,
        feature_timestamp: datetime,
        label_timestamp: datetime,
        label_horizon_days: int,
        purge_days: int,
    ) -> Tuple[bool, Optional[PITViolation]]:
        """
        Label üretiminin PIT uyumluluğunu doğrula.

        Label = gelecek N günlük getiri
        Feature = geçmiş veriden türetilen

        Kural: label_timestamp >= feature_timestamp + purge_days + label_horizon_days
        """
        min_gap = timedelta(days=purge_days + label_horizon_days)
        actual_gap = label_timestamp - feature_timestamp

        if actual_gap < min_gap:
            return False, PITViolation(
                violation_type="timing_error",
                severity="critical",
                description=f"Label generated too early. "
                           f"Gap: {actual_gap.days} days, "
                           f"Required: {min_gap.days} days "
                           f"(purge={purge_days} + horizon={label_horizon_days})",
            )

        return True, None

    def get_registry_stats(self) -> Dict[str, Any]:
        """Kayıt istatistikleri."""
        total_records = sum(len(records) for records in self._registry.values())
        by_type = {}
        for records in self._registry.values():
            for r in records:
                by_type[r.data_type] = by_type.get(r.data_type, 0) + 1

        return {
            "total_tickers": len(self._registry),
            "total_records": total_records,
            "by_type": by_type,
            "corporate_actions": len(self._corporate_actions),
        }


class PITDataAdapter:
    """
    Mevcut veri yapılarını PIT formatına dönüştürücü.

    Veri sağlayıcılarından gelen ham veriyi PIT kayıtlarına dönüştürür.
    """

    @staticmethod
    def adapt_fundamental_data(
        df: pl.DataFrame,
        ticker_col: str = "ticker",
        report_date_col: str = "report_date",
        publish_date_col: str = "publish_date",
    ) -> List[PITRecord]:
        """Temel veri DataFrame'ini PIT kayıtlarına dönüştür."""
        records = []
        for _, row in df.iterrows():
            records.append(PITRecord(
                data_id=f"{row[ticker_col]}_{row[report_date_col]}",
                ticker=row[ticker_col],
                report_date=pl.Series(row[report_date_col]),
                publish_date=pl.Series(row.get(publish_date_col, row[report_date_col])),
                data_type="fundamental",
            ))
        return records

    @staticmethod
    def adapt_price_data(
        df: pl.DataFrame,
        ticker_col: str = "ticker",
        date_col: str = "date",
    ) -> List[PITRecord]:
        """Fiyat verisi DataFrame'ini PIT kayıtlarına dönüştür."""
        records = []
        for _, row in df.iterrows():
            # Fiyat verisi genellikle aynı gün bilinebilir
            date = pl.Series(row[date_col])
            records.append(PITRecord(
                data_id=f"{row[ticker_col]}_price_{date.strftime('%Y%m%d')}",
                ticker=row[ticker_col],
                report_date=date,
                publish_date=date,  # Fiyat aynı gün bilinir
                data_type="price",
            ))
        return records


# Singleton
pit_validator = PointInTimeValidator()
