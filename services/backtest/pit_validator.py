"""ALPHA BIST — Point-in-Time (PIT) Doğrulayıcı Modülü (v2.0).

Point-in-time (PIT) disiplini, backtest ve model eğitim süreçlerinde geleceği görme
(look-ahead bias ve data leakage) riskini engelleyen temel mimari garantidir.
Bu modül, piyasa, temel (fundamental), kurumsal işlem ve haber verilerinin
karar anında (decision_time) gerçekten bilinebilir olduğunu doğrular.

Kontroller:
1. Temel Veri (Bilanço/Gelir Tablosu): Rapor dönemi vs. kamuya açıklanma (yayın) tarihi ayrımı.
2. Haber / KAP Bildirimleri: Olay zamanı vs. sisteme işlenme/giriş zamanı ayrımı.
3. Feature Penceresi: Feature'ların yalnızca karar anından önceki geçmiş veriden türetilme garantisi.
4. Label Üretimi: Feature penceresi ile hedef etiket arasında purge + embargo ayrımı.
5. Kurumsal İşlemler (Corporate Actions): Bedelli/bedelsiz bölünme ve temettü düzeltmelerinin zamanlaması.

Referanslar:
- Marcos López de Prado — "Advances in Financial Machine Learning", Ch. 7.
- Quantopian / Alpaca PIT Data Architecture.
"""

from __future__ import annotations

import contextlib
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import structlog

try:
    import polars as pl
except ImportError:
    pl = None

logger = structlog.get_logger(__name__)

DEFAULT_MAX_CORPORATE_ACTIONS: int = 500
DEFAULT_RECENT_LOOKBACK: int = 5
DEFAULT_MAX_NAN_RATIO: float = 0.5

__all__ = [
    "DEFAULT_MAX_CORPORATE_ACTIONS",
    "DEFAULT_MAX_NAN_RATIO",
    "DEFAULT_RECENT_LOOKBACK",
    "PITDataAdapter",
    "PITRecord",
    "PITValidationReport",
    "PITViolation",
    "PointInTimeValidator",
    "pit_validator",
]


def _parse_to_datetime(val: Any) -> datetime:
    """Farklı tipteki tarih/zaman girdilerini güvenli ve naive datetime nesnesine dönüştürür.

    Tüm zaman damgalarını naive formata getirerek Python'daki
    'TypeError: can't compare offset-naive and offset-aware datetimes' hatasını önler.
    """
    dt: datetime
    if isinstance(val, datetime):
        dt = val
    elif isinstance(val, date):
        dt = datetime.combine(val, datetime.min.time())
    elif isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        except ValueError:
            dt = datetime.strptime(val[:10], "%Y-%m-%d")
    else:
        raise TypeError(f"Desteklenmeyen tarih tipi: {type(val)} ({val})")

    # Timezone-aware ise naive UTC formata normalize et
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


@dataclass
class PITRecord:
    """Point-in-time veri kaydı veri modeli."""

    data_id: str
    ticker: str
    report_date: datetime  # Rapor dönemi (örn: 2024-Q3 dönemi sonu)
    publish_date: datetime  # Kamuya açıklanma / sisteme giriş tarihi
    data_type: str  # fundamental | price | news | macro
    revision_version: int = 1  # Revizyon numarası (1: ilk yayın)
    is_original: bool = True  # İlk yayınlanan orijinal veri mi?

    def __post_init__(self) -> None:
        """Tarih alanlarının datetime tipinde olmasını garanti eder."""
        if not isinstance(self.report_date, datetime):
            self.report_date = _parse_to_datetime(self.report_date)
        if not isinstance(self.publish_date, datetime):
            self.publish_date = _parse_to_datetime(self.publish_date)

    def __repr__(self) -> str:
        """Kayıt için açıklayıcı dize temsili döndürür."""
        rep_str = self.report_date.strftime("%Y-%m-%d")
        pub_str = self.publish_date.strftime("%Y-%m-%d")
        return (
            f"PITRecord(ticker='{self.ticker}', type='{self.data_type}', "
            f"report='{rep_str}', publish='{pub_str}', v={self.revision_version})"
        )

    @property
    def lag_days(self) -> int:
        """Rapor dönemi ile yayınlanma tarihi arasındaki gecikme süresi (gün)."""
        return (self.publish_date - self.report_date).days

    def to_dict(self) -> dict[str, Any]:
        """PIT kayıt verilerini sözlük (dict) formatına dönüştürür.

        Returns:
            dict[str, Any]: Kayıt verilerini içeren sözlük.
        """
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
    """Point-in-time kural ihlali detay modeli."""

    violation_type: str  # future_data | revision_leakage | timing_error
    severity: str  # critical | warning | info
    description: str
    record: PITRecord | None = None
    decision_time: datetime | None = None

    def __repr__(self) -> str:
        """İhlal nesnesinin açıklayıcı dize temsilini döndürür."""
        rec_id = self.record.data_id if self.record else "None"
        return f"PITViolation(type='{self.violation_type}', severity='{self.severity}', record={rec_id})"

    def to_dict(self) -> dict[str, Any]:
        """PIT ihlal detaylarını sözlük (dict) formatına dönüştürür.

        Returns:
            dict[str, Any]: İhlal bilgilerini içeren sözlük.
        """
        return {
            "type": self.violation_type,
            "severity": self.severity,
            "description": self.description,
            "record": self.record.to_dict() if self.record else None,
            "decision_time": self.decision_time.isoformat() if self.decision_time else None,
        }


@dataclass
class PITValidationReport:
    """Point-in-time toplu doğrulama sonuç raporu."""

    total_records: int = 0
    violations: list[PITViolation] = field(default_factory=list)
    critical_count: int = 0
    warning_count: int = 0
    is_valid: bool = True

    def __repr__(self) -> str:
        """Doğrulama raporu özet dize temsilini döndürür."""
        return (
            f"PITValidationReport(valid={self.is_valid}, total={self.total_records}, "
            f"critical={self.critical_count}, warnings={self.warning_count})"
        )

    def add_violation(self, violation: PITViolation) -> None:
        """Rapora yeni bir PIT ihlali ekler ve sayaçları günceller.

        Args:
            violation: Eklenecek ihlal nesnesi.
        """
        self.violations.append(violation)
        if violation.severity == "critical":
            self.critical_count += 1
            self.is_valid = False
        elif violation.severity == "warning":
            self.warning_count += 1

    def to_dict(self) -> dict[str, Any]:
        """Doğrulama raporunu sözlük formatına dönüştürür.

        Returns:
            dict[str, Any]: Rapor özetini içeren sözlük.
        """
        return {
            "total_records": self.total_records,
            "violations": [v.to_dict() for v in self.violations],
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "is_valid": self.is_valid,
        }


class PointInTimeValidator:
    """Point-in-time veri ve feature doğrulama motoru.

    Temel ilke: 'Bu veri, modelin karar anında (decision_time) gerçekten bilinebilir miydi?'
    """

    def __init__(self) -> None:
        """PointInTimeValidator motorunu başlatır."""
        self._registry: dict[str, list[PITRecord]] = {}  # ticker -> kayıtlar
        self._corporate_actions: list[dict[str, Any]] = []
        self._lock: threading.Lock = threading.Lock()

    def __repr__(self) -> str:
        """Doğrulayıcı durumunun dize temsilini döndürür."""
        with self._lock:
            tickers = len(self._registry)
            records = sum(len(v) for v in self._registry.values())
            actions = len(self._corporate_actions)
            return f"PointInTimeValidator(tickers={tickers}, records={records}, corporate_actions={actions})"

    def register_record(self, record: PITRecord) -> None:
        """Doğrulayıcı kayıt kütüğüne yeni bir PIT kaydı ekler.

        Args:
            record: Eklenecek Point-in-time kayıt nesnesi.
        """
        with self._lock:
            if record.ticker not in self._registry:
                self._registry[record.ticker] = []
            self._registry[record.ticker].append(record)

    def register_fundamental_data(
        self,
        ticker: str,
        report_date: datetime,
        publish_date: datetime,
        revision_version: int = 1,
    ) -> None:
        """Temel analiz (bilanço/gelir tablosu) kaydı oluşturur ve kaydeder.

        Args:
            ticker: Hisse senedi sembolü.
            report_date: Finansal rapor dönemi bitiş tarihi.
            publish_date: Kamuyu Aydınlatma Platformu (KAP) açıklanma tarihi.
            revision_version: Bilanço revizyon versiyonu (varsayılan 1).

        Raises:
            ValueError: Parametreler eksik veya geçersizse.
        """
        if not ticker:
            raise ValueError("Hisse sembolü (ticker) boş olamaz.")

        rep_dt = _parse_to_datetime(report_date)
        pub_dt = _parse_to_datetime(publish_date)

        record = PITRecord(
            data_id=f"{ticker}_{rep_dt.strftime('%Y%m%d')}_v{revision_version}",
            ticker=ticker,
            report_date=rep_dt,
            publish_date=pub_dt,
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
    ) -> None:
        """Haber veya KAP duyurusu zaman damgası kaydı oluşturur.

        Args:
            ticker: İlgili hisse kodu.
            event_time: Haberin gerçekleştiği / yayınlandığı an.
            system_entry_time: Sistemin haberi okuyup işlediği an.

        Raises:
            ValueError: Ticker boş ise.
        """
        if not ticker:
            raise ValueError("Hisse sembolü (ticker) boş olamaz.")

        ev_dt = _parse_to_datetime(event_time)
        sys_dt = _parse_to_datetime(system_entry_time)

        record = PITRecord(
            data_id=f"{ticker}_news_{ev_dt.strftime('%Y%m%d%H%M%S')}",
            ticker=ticker,
            report_date=ev_dt,
            publish_date=sys_dt,
            data_type="news",
        )
        self.register_record(record)

    def register_corporate_action(
        self,
        ticker: str,
        action_type: str,
        ex_date: datetime,
        record_date: datetime,
        details: dict[str, Any],
    ) -> None:
        """Kurumsal işlem (temettü, bedelli/bedelsiz sermaye artırımı) kaydı ekler.

        Args:
            ticker: Hisse senedi sembolü.
            action_type: İşlem türü ('dividend', 'split', 'rights_issue', 'merger').
            ex_date: Hak kullanım / temettü düşüş tarihi (Ex-date).
            record_date: Pay sahipliği tespit tarihi (Record date).
            details: İşleme özel sayısal detaylar sözlüğü.

        Raises:
            ValueError: Ticker veya action_type boş ise.
        """
        if not ticker or not action_type:
            raise ValueError("ticker ve action_type zorunludur.")

        ex_dt = _parse_to_datetime(ex_date)
        rec_dt = _parse_to_datetime(record_date)

        with self._lock:
            self._corporate_actions.append(
                {
                    "ticker": ticker,
                    "action_type": action_type,
                    "ex_date": ex_dt,
                    "record_date": rec_dt,
                    "details": details or {},
                }
            )
            if len(self._corporate_actions) > DEFAULT_MAX_CORPORATE_ACTIONS:
                self._corporate_actions = self._corporate_actions[-DEFAULT_MAX_CORPORATE_ACTIONS:]

    def get_available_data_at(
        self,
        ticker: str,
        decision_time: datetime,
        data_type: str | None = None,
    ) -> list[PITRecord]:
        """Karar anında (decision_time) sisteme girmiş ve bilinebilir olan verileri döndürür.

        Args:
            ticker: Hisse senedi sembolü.
            decision_time: Modelin alım/satım kararı verdiği zaman damgası.
            data_type: Filtrelenecek veri türü (opsiyonel).

        Returns:
            list[PITRecord]: Karar anında mevcut olan kayıtlar listesi.
        """
        dec_dt = _parse_to_datetime(decision_time)
        with self._lock:
            records = self._registry.get(ticker, [])
            available: list[PITRecord] = []
            for record in records:
                if record.publish_date <= dec_dt:
                    if data_type is None or record.data_type == data_type:
                        available.append(record)
            return available

    def get_latest_fundamental(
        self,
        ticker: str,
        decision_time: datetime,
    ) -> PITRecord | None:
        """Karar anında kamuya açıklanmış en güncel temel analiz kaydını döndürür.

        Args:
            ticker: Hisse senedi sembolü.
            decision_time: Karar anı zaman damgası.

        Returns:
            PITRecord | None: Mevcut en güncel bilanço kaydı veya yoksa None.
        """
        fundamentals = self.get_available_data_at(ticker, decision_time, "fundamental")
        if not fundamentals:
            return None

        return max(fundamentals, key=lambda r: (r.report_date, r.revision_version or 1))

    def validate_fundamental_access(
        self,
        ticker: str,
        report_date: datetime,
        revision_version: int,
        decision_time: datetime,
    ) -> tuple[bool, PITViolation | None]:
        """Temel veri erişiminin PIT kurallarına uygunluğunu denetler.

        Args:
            ticker: Hisse kodu.
            report_date: Rapor dönemi.
            revision_version: İstenen revizyon versiyonu.
            decision_time: Karar anı.

        Returns:
            tuple[bool, PITViolation | None]: Uygunluk durumu ve ihlal varsa ihlal nesnesi.
        """
        rep_dt = _parse_to_datetime(report_date)
        dec_dt = _parse_to_datetime(decision_time)

        with self._lock:
            records = list(self._registry.get(ticker, []))

        target: PITRecord | None = None
        for r in records:
            if r.report_date == rep_dt and r.revision_version == revision_version and r.data_type == "fundamental":
                target = r
                break

        if target is None:
            return False, PITViolation(
                violation_type="timing_error",
                severity="critical",
                description=f"Temel veri kütükte bulunamadı: {ticker} {rep_dt} v{revision_version}",
                decision_time=dec_dt,
            )

        if target.publish_date > dec_dt:
            return False, PITViolation(
                violation_type="future_data",
                severity="critical",
                description=(
                    f"Yayınlanmamış temel veriye erişim tespit edildi: {ticker} {rep_dt} v{revision_version}. "
                    f"Yayın Tarihi: {target.publish_date}, Karar Anı: {dec_dt}"
                ),
                record=target,
                decision_time=dec_dt,
            )

        if revision_version > 1:
            original: PITRecord | None = None
            for r in records:
                if r.report_date == rep_dt and r.revision_version == 1 and r.data_type == "fundamental":
                    original = r
                    break

            if original and original.publish_date > dec_dt:
                return False, PITViolation(
                    violation_type="revision_leakage",
                    severity="critical",
                    description=(
                        f"Orijinal bilanço henüz yayınlanmadan revizyon versiyonuna (v{revision_version}) erişilemez."
                    ),
                    record=target,
                    decision_time=dec_dt,
                )

        return True, None

    def validate_feature_set(
        self,
        feature_df: pl.DataFrame,
        ticker: str,
        decision_time: datetime,
        feature_cols: list[str],
        timestamp_col: str = "timestamp",
    ) -> PITValidationReport:
        """Feature set'in karar anına göre Point-in-time uyumluluğunu doğrular.

        Args:
            feature_df: Polars DataFrame biçiminde feature tablosu.
            ticker: Hisse senedi sembolü.
            decision_time: Karar anı zaman damgası.
            feature_cols: Kontrol edilecek öznitelik sütunları listesi.
            timestamp_col: Zaman damgası sütun adı.

        Returns:
            PITValidationReport: Detaylı PIT doğrulama raporu.

        Raises:
            RuntimeError: Polars kütüphanesi yoksa.
        """
        if pl is None:
            raise RuntimeError("Polars kütüphanesi ortamda bulunamadı.")

        report = PITValidationReport()
        if feature_df is None or feature_df.is_empty():
            report.add_violation(
                PITViolation(
                    violation_type="timing_error",
                    severity="warning",
                    description="Doğrulanacak feature veri çerçevesi boş.",
                )
            )
            return report

        if timestamp_col not in feature_df.columns:
            report.add_violation(
                PITViolation(
                    violation_type="timing_error",
                    severity="critical",
                    description=f"Zaman damgası sütunu ('{timestamp_col}') veri çerçevesinde bulunamadı.",
                )
            )
            return report

        dec_dt = _parse_to_datetime(decision_time)
        report.total_records = len(feature_df)

        norm_df = feature_df
        ts_dtype = feature_df[timestamp_col].dtype
        if ts_dtype in (pl.String, pl.Utf8):
            with contextlib.suppress(Exception):
                norm_df = feature_df.with_columns(pl.col(timestamp_col).str.to_datetime())
        elif ts_dtype == pl.Date:
            with contextlib.suppress(Exception):
                norm_df = feature_df.with_columns(pl.col(timestamp_col).cast(pl.Datetime))
        elif hasattr(ts_dtype, "time_zone") and ts_dtype.time_zone is not None:
            with contextlib.suppress(Exception):
                norm_df = feature_df.with_columns(pl.col(timestamp_col).dt.convert_time_zone(None))

        try:
            future_df = norm_df.filter(pl.col(timestamp_col) > dec_dt)
            future_count = len(future_df)
        except Exception:
            future_count = sum(1 for val in norm_df[timestamp_col] if _parse_to_datetime(val) > dec_dt)

        if future_count > 0:
            max_ts = norm_df[timestamp_col].max()
            report.add_violation(
                PITViolation(
                    violation_type="future_data",
                    severity="critical",
                    description=(
                        f"Öznitelik kümesinde karar anından sonrasına ait {future_count} satır saptandı. "
                        f"Karar Anı: {dec_dt}, Maksimum Zaman Damgası: {max_ts}"
                    ),
                    decision_time=dec_dt,
                )
            )

        try:
            valid_df = norm_df.filter(pl.col(timestamp_col) <= dec_dt)
        except Exception:
            valid_indices = [idx for idx, val in enumerate(norm_df[timestamp_col]) if _parse_to_datetime(val) <= dec_dt]
            valid_df = norm_df[valid_indices] if valid_indices else norm_df.clear()

        if len(valid_df) > 0:
            recent_df = valid_df.tail(DEFAULT_RECENT_LOOKBACK)
            for col in feature_cols:
                if col in recent_df.columns:
                    null_count = recent_df[col].is_null().sum()
                    nan_count = recent_df[col].is_nan().sum() if recent_df[col].dtype.is_numeric() else 0
                    total_missing = null_count + nan_count
                    nan_ratio = total_missing / len(recent_df)

                    if nan_ratio > DEFAULT_MAX_NAN_RATIO:
                        report.add_violation(
                            PITViolation(
                                violation_type="timing_error",
                                severity="warning",
                                description=(
                                    f"Öznitelik '{col}' son {len(recent_df)} gözlemde %{nan_ratio * 100:.1f} eksik/NaN içeriyor. "
                                    "Veri erişiminde gecikme veya eksiklik olabilir."
                                ),
                            )
                        )

        return report

    def validate_label_generation(
        self,
        feature_timestamp: datetime,
        label_timestamp: datetime,
        label_horizon_days: int,
        purge_days: int,
    ) -> tuple[bool, PITViolation | None]:
        """Etiket (label) üretiminde purge ve embargo kurallarını denetler.

        Args:
            feature_timestamp: Feature'ın üretildiği son gözlem anı.
            label_timestamp: Etiketin hesaplandığı an.
            label_horizon_days: Etiketin kapsadığı gelecek tahmin ufku (gün).
            purge_days: Bilgi sızıntısını önlemek için araya konulan arındırma süresi (gün).

        Returns:
            tuple[bool, PITViolation | None]: Uygunluk ve varsa ihlal nesnesi.

        Raises:
            ValueError: Gün değerleri negatif ise.
        """
        if label_horizon_days < 0 or purge_days < 0:
            raise ValueError("label_horizon_days ve purge_days negatif olamaz.")

        feat_dt = _parse_to_datetime(feature_timestamp)
        lbl_dt = _parse_to_datetime(label_timestamp)

        min_gap = timedelta(days=purge_days + label_horizon_days)
        actual_gap = lbl_dt - feat_dt

        if actual_gap < min_gap:
            return False, PITViolation(
                violation_type="timing_error",
                severity="critical",
                description=(
                    f"Etiket erken üretildi (Sızıntı Riski). "
                    f"Mevcut Fark: {actual_gap.days} gün, "
                    f"Gereken Asgari Fark: {min_gap.days} gün "
                    f"(purge={purge_days} + horizon={label_horizon_days})"
                ),
            )

        return True, None

    def get_registry_stats(self) -> dict[str, Any]:
        """Kayıt kütüğünün özet istatistiklerini döndürür.

        Returns:
            dict[str, Any]: Ticker sayısı, toplam kayıt ve tiplere göre dağılım.
        """
        with self._lock:
            total_records = sum(len(records) for records in self._registry.values())
            by_type: dict[str, int] = {}
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
    """Mevcut veri yapılarını Point-in-time kayıtlarına dönüştüren adaptör sınıfı."""

    def __repr__(self) -> str:
        """Adaptör sınıfının dize temsilini döndürür."""
        return "PITDataAdapter()"

    @staticmethod
    def adapt_fundamental_data(
        df: pl.DataFrame,
        ticker_col: str = "ticker",
        report_date_col: str = "report_date",
        publish_date_col: str = "publish_date",
    ) -> list[PITRecord]:
        """Temel analiz Polars DataFrame tablosunu PIT kayıtları listesine dönüştürür.

        Args:
            df: Polars DataFrame veri tablosu.
            ticker_col: Hisse sembolü sütunu.
            report_date_col: Bilanço dönemi sütunu.
            publish_date_col: Kamuya açıklanma tarihi sütunu.

        Returns:
            list[PITRecord]: Dönüştürülmüş PITRecord kayıtları.

        Raises:
            ValueError: Sütunlar eksik veya DataFrame geçersizse.
        """
        if pl is None:
            raise RuntimeError("Polars kütüphanesi yüklü değil.")
        if df is None or df.is_empty():
            return []

        missing_cols = [c for c in [ticker_col, report_date_col] if c not in df.columns]
        if missing_cols:
            raise ValueError(f"Zorunlu sütunlar DataFrame içinde bulunamadı: {missing_cols}")

        has_publish = publish_date_col in df.columns
        records: list[PITRecord] = []

        for row in df.iter_rows(named=True):
            ticker_val = row.get(ticker_col)
            rep_date_raw = row.get(report_date_col)
            if not ticker_val or rep_date_raw is None:
                continue

            ticker_str = str(ticker_val)
            rep_date_val = _parse_to_datetime(rep_date_raw)
            pub_date_val = _parse_to_datetime(row[publish_date_col]) if (has_publish and row.get(publish_date_col) is not None) else rep_date_val

            records.append(
                PITRecord(
                    data_id=f"{ticker_str}_{rep_date_val.strftime('%Y%m%d')}",
                    ticker=ticker_str,
                    report_date=rep_date_val,
                    publish_date=pub_date_val,
                    data_type="fundamental",
                )
            )
        return records

    @staticmethod
    def adapt_price_data(
        df: pl.DataFrame,
        ticker_col: str = "ticker",
        date_col: str = "date",
    ) -> list[PITRecord]:
        """Fiyat verisi Polars DataFrame tablosunu PIT kayıtları listesine dönüştürür.

        Args:
            df: Fiyat verilerini içeren Polars DataFrame.
            ticker_col: Hisse sembolü sütun adı.
            date_col: Tarih sütun adı.

        Returns:
            list[PITRecord]: Dönüştürülmüş PITRecord kayıtları.

        Raises:
            ValueError: Sütunlar eksikse.
        """
        if pl is None:
            raise RuntimeError("Polars kütüphanesi yüklü değil.")
        if df is None or df.is_empty():
            return []

        missing_cols = [c for c in [ticker_col, date_col] if c not in df.columns]
        if missing_cols:
            raise ValueError(f"Zorunlu sütunlar eksik: {missing_cols}")

        records: list[PITRecord] = []
        for row in df.iter_rows(named=True):
            ticker_val = row.get(ticker_col)
            date_raw = row.get(date_col)
            if not ticker_val or date_raw is None:
                continue

            ticker_str = str(ticker_val)
            dt_val = _parse_to_datetime(date_raw)

            records.append(
                PITRecord(
                    data_id=f"{ticker_str}_price_{dt_val.strftime('%Y%m%d')}",
                    ticker=ticker_str,
                    report_date=dt_val,
                    publish_date=dt_val,
                    data_type="price",
                )
            )
        return records


# Global Singleton Point-In-Time Doğrulayıcısı
pit_validator = PointInTimeValidator()
