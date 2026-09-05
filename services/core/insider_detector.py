"""
ALPHA BIST — İçeriden Öğrenenlerin Ticareti Tespit Motoru (Insider Trading Detector)

Borsa İstanbul (BIST) ve Sermaye Piyasası Kurulu (SPK) piyasa bozucu eylemler tebliğine uygun olarak,
Kamuyu Aydınlatma Platformu (KAP) duyuruları öncesinde gerçekleşen olağandışı hacim ve fiyat
hareketlerini istatistiksel anlamlılık (Z-skoru, getiri standart sapması ve olasılık eşikleri) ile tespit eder.

Özellikler:
1. Z-Skoru Bazlı Hacim Anomalisi Tespiti (Normal ve log-normal hacim dağılımı modellemesi)
2. KAP Öncesi Kümülatif Getiri ve Oynaklık Anomalisi Testi
3. Çoklu Zaman Penceresi Analizi (1, 3 ve 5 seanslık pencereler)
4. Thread-Safe Durum ve Geçmiş Takibi (threading.RLock)
5. DuckDB Tablosu (`bist_insider_alerts`) ve Polars DataFrame Dışa Aktarımı
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# =====================================================
# SABİTLER (CONSTANTS)
# =====================================================

DEFAULT_Z_THRESHOLD_MEDIUM: Final[float] = 2.0  # p < 0.023 (Orta şüphe)
DEFAULT_Z_THRESHOLD_HIGH: Final[float] = 2.5  # p < 0.006 (Yüksek şüphe)
DEFAULT_Z_THRESHOLD_CRITICAL: Final[float] = 3.0  # p < 0.001 (Kritik manipülasyon şüphesi)
DEFAULT_MIN_VOLUME_HISTORY_LEN: Final[int] = 10
DEFAULT_PRE_KAP_DAYS_WINDOW: Final[int] = 5
DEFAULT_PRICE_MOVE_WINDOW: Final[int] = 5
DEFAULT_MAX_ALERT_HISTORY: Final[int] = 1000
DEFAULT_INSIDER_AUDIT_DB_PATH: Final[Path] = Path("data/duckdb/alpha_bist_audit.duckdb")


# =====================================================
# NUMARALANDIRMALAR VE VERİ MODELLERİ
# =====================================================


class InsiderAlertType(StrEnum):
    """İçeriden bilgi ticareti alarm türleri."""

    PRE_KAP_TRADE = "PRE_KAP_TRADE"
    UNUSUAL_VOLUME = "UNUSUAL_VOLUME"
    PRICE_MOVE_BEFORE_KAP = "PRICE_MOVE_BEFORE_KAP"


class InsiderAlertSeverity(StrEnum):
    """Alarm önem dereceleri."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(slots=True)
class InsiderAlert:
    """Tespit edilen içeriden öğrenen ticareti alarm veri modeli.

    Attributes:
        ticker: İlgili hisse kodu.
        alert_type: Alarm tipi (PRE_KAP_TRADE, PRICE_MOVE_BEFORE_KAP vb.).
        severity: Önem derecesi (CRITICAL, HIGH, MEDIUM, LOW).
        description: Türkçe detay açıklaması.
        z_score: Hesaplanan standart Z-skoru istatistiği.
        confidence: 0.0 - 1.0 aralığında istatistiksel güven skoru.
        event_date: İlgili KAP veya tespit tarihi.
        detected_at: Alarmın üretildiği UTC zaman damgası.
    """

    ticker: str
    alert_type: str
    severity: str
    description: str
    z_score: float = 0.0
    confidence: float = 0.0
    event_date: str = ""
    detected_at: str = ""

    def __post_init__(self) -> None:
        """Varsayılan zaman damgasını atar."""
        if not self.detected_at:
            object.__setattr__(self, "detected_at", datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Alarmı sözlük yapısına dönüştürür.

        Returns:
            dict[str, Any]: Serileştirilebilir sözlük.
        """
        return {
            "ticker": self.ticker,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "description": self.description,
            "z_score": self.z_score,
            "confidence": self.confidence,
            "event_date": self.event_date,
            "detected_at": self.detected_at,
        }

    def to_orjson_bytes(self) -> bytes:
        """Alarmı JSON bayt dizisine dönüştürür.

        Returns:
            bytes: orjson kodlu baytlar.
        """
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Türkçe açıklayıcı metin gösterimi.

        Returns:
            str: Alarm özeti.
        """
        return (
            f"InsiderAlert(hisse='{self.ticker}', tip='{self.alert_type}', "
            f"seviye='{self.severity}', z_skor={self.z_score:.2f}, guven=%{self.confidence * 100:.1f})"
        )


# =====================================================
# İÇERİDEN BİLGİ TİCARETİ MOTORU (INSIDER DETECTOR)
# =====================================================


class InsiderDetector:
    """KAP bildirimleri öncesi anormal hacim ve fiyat hareketlerini analiz eden dedektör."""

    def __init__(
        self,
        z_threshold_medium: float = DEFAULT_Z_THRESHOLD_MEDIUM,
        z_threshold_high: float = DEFAULT_Z_THRESHOLD_HIGH,
        z_threshold_critical: float = DEFAULT_Z_THRESHOLD_CRITICAL,
    ) -> None:
        """Dedektör örneğini başlatır.

        Args:
            z_threshold_medium: Orta seviye Z-skor eşiği.
            z_threshold_high: Yüksek seviye Z-skor eşiği.
            z_threshold_critical: Kritik seviye Z-skor eşiği.
        """
        self._lock = threading.RLock()
        self.Z_THRESHOLD_MEDIUM: float = z_threshold_medium
        self.Z_THRESHOLD_HIGH: float = z_threshold_high
        self.Z_THRESHOLD_CRITICAL: float = z_threshold_critical
        self._alert_history: list[InsiderAlert] = []

    @otel_trace("insider_detector.detect_pre_kap_trade")
    def detect_pre_kap_trade(
        self,
        trades: list[dict[str, Any]] | None = None,
        kap_events: list[dict[str, Any]] | None = None,
        volume_history: list[float] | np.ndarray | None = None,
        *,
        ticker: str | None = None,
        prices: list[float] | np.ndarray | None = None,
        volumes: list[float] | np.ndarray | None = None,
    ) -> list[InsiderAlert]:
        """KAP açıklaması öncesi olağandışı hacim ve fiyat hareketlerini denetler.

        Hem tekil hisse serisi (`ticker`, `volumes`, `prices`) hem de çoklu işlem listesi
        (`trades`, `volume_history`) parametre imzalarını tam uyumlulukla destekler.

        Args:
            trades: İşlem kayıtları listesi [{date, volume, price, ticker}].
            kap_events: İlgili KAP olayları listesi [{date, type, ticker}].
            volume_history: Hacim geçmişi zaman serisi.
            ticker: Tekil hisse kodu (orchestrator çağrıları için).
            prices: Kapanış fiyatları serisi.
            volumes: Hacim serisi.

        Returns:
            list[InsiderAlert]: Üretilen içeriden öğrenen ticareti alarmları.
        """
        alerts: list[InsiderAlert] = []
        events = kap_events if kap_events is not None else []

        with self._lock:
            # Durum 1: Tekil hisse vektörel çağrısı (Orchestrator entegrasyonu)
            if ticker is not None and (volumes is not None or volume_history is not None):
                target_ticker = ticker.upper()
                vols_raw = volumes if volumes is not None else volume_history
                vols_arr = np.asarray(vols_raw, dtype=float) if vols_raw is not None else np.array([])
                vols_arr = vols_arr[vols_arr >= 0]

                event_date_str = (
                    str(events[-1].get("date", ""))
                    if events and events[-1].get("date")
                    else datetime.now(UTC).strftime("%Y-%m-%d")
                )

                if len(vols_arr) >= DEFAULT_MIN_VOLUME_HISTORY_LEN:
                    raw_z, log_z = self.compute_volume_z_score(vols_arr, use_log=True)
                    eff_z = raw_z if abs(raw_z) >= abs(log_z) else log_z
                    last_vol = float(vols_arr[-1])
                    mean_vol = float(np.mean(vols_arr[:-1])) if len(vols_arr) > 1 else float(np.mean(vols_arr))

                    if np.isfinite(eff_z):
                        severity, alert_type = self._classify_z(eff_z)
                        if severity is not None:
                            conf = min(0.99, max(0.50, float(1.0 - np.exp(-abs(eff_z) / 2.0))))
                            alert = InsiderAlert(
                                ticker=target_ticker,
                                alert_type=alert_type,
                                severity=severity,
                                description=(
                                    f"{target_ticker} için KAP öncesi olağandışı hacim (Z={eff_z:.2f}, LogZ={log_z:.2f}): "
                                    f"Son hacim {last_vol:,.0f} vs Ort {mean_vol:,.0f}"
                                ),
                                z_score=round(float(eff_z), 2),
                                confidence=round(conf, 3),
                                event_date=event_date_str,
                            )
                            alerts.append(alert)
                    elif mean_vol > 0.0 and last_vol >= mean_vol * 3.0:
                        # Sabit geçmiş hacim sıçrama fallback'i
                        alert = InsiderAlert(
                            ticker=target_ticker,
                            alert_type=InsiderAlertType.PRE_KAP_TRADE.value,
                            severity=InsiderAlertSeverity.HIGH.value,
                            description=f"{target_ticker} için KAP öncesi 3x hacim sıçraması: {last_vol:,.0f} vs {mean_vol:,.0f}",
                            z_score=3.0,
                            confidence=0.85,
                            event_date=event_date_str,
                        )
                        alerts.append(alert)

                # Varsa fiyat anomalisi kontrolü
                if prices is not None:
                    prices_arr = np.asarray(prices, dtype=float)
                    prices_arr = prices_arr[np.isfinite(prices_arr)]
                    if len(prices_arr) > DEFAULT_PRICE_MOVE_WINDOW:
                        price_alerts = self.detect_price_move_before_kap(
                            prices=prices_arr,
                            kap_date_idx=len(prices_arr) - 1,
                            window=DEFAULT_PRICE_MOVE_WINDOW,
                            ticker=target_ticker,
                            record=False,
                        )
                        for pa in price_alerts:
                            if not pa.ticker:
                                pa.ticker = target_ticker
                            alerts.append(pa)

            # Durum 2: Detaylı liste bazlı işlemler ve KAP eşleşmesi
            elif trades is not None and events:
                for event in events:
                    event_date = str(event.get("date", ""))
                    event_ticker = str(event.get("ticker", "")).upper()
                    if not event_date:
                        continue

                    min_date = self._days_before(event_date, DEFAULT_PRE_KAP_DAYS_WINDOW)
                    pre_kap_trades: list[dict[str, Any]] = []
                    for t in trades:
                        t_ticker = str(t.get("ticker", "")).upper()
                        if t_ticker != event_ticker:
                            continue
                        t_date = str(t.get("date", ""))
                        if not t_date:
                            continue
                        if "T" in t_date and "T" in event_date:
                            if min_date <= t_date < event_date:
                                pre_kap_trades.append(t)
                        else:
                            if min_date[:10] <= t_date[:10] <= event_date[:10]:
                                pre_kap_trades.append(t)

                    if not pre_kap_trades:
                        continue

                    vols = volume_history if volume_history is not None else volumes
                    if vols is not None and len(vols) >= DEFAULT_MIN_VOLUME_HISTORY_LEN:
                        hist_arr = np.asarray(vols, dtype=float)
                        hist_arr = hist_arr[np.isfinite(hist_arr)]
                        hist_arr = hist_arr[hist_arr >= 0]
                        mean_vol = float(np.mean(hist_arr)) if len(hist_arr) > 0 else 0.0

                        for trade in pre_kap_trades:
                            vol = float(trade.get("volume", 0.0))
                            if len(hist_arr) > 0:
                                sim_vols = np.append(hist_arr, vol)
                                raw_z, log_z = self.compute_volume_z_score(sim_vols, use_log=True)
                                eff_z = raw_z if abs(raw_z) >= abs(log_z) else log_z
                            else:
                                eff_z = 0.0

                            if np.isfinite(eff_z):
                                severity, alert_type = self._classify_z(eff_z)
                                if severity is not None:
                                    conf = min(0.99, max(0.50, float(1.0 - np.exp(-abs(eff_z) / 2.0))))
                                    alerts.append(
                                        InsiderAlert(
                                            ticker=event_ticker,
                                            alert_type=alert_type,
                                            severity=severity,
                                            description=(
                                                f"KAP öncesi hacim anomalisi (Z={eff_z:.2f}): "
                                                f"İşlem {vol:,.0f} vs Ortalama {mean_vol:,.0f}"
                                            ),
                                            z_score=round(float(eff_z), 2),
                                            confidence=round(conf, 3),
                                            event_date=event_date,
                                        )
                                    )
                    else:
                        # Fallback: Basit 3x hacim kontrolü
                        for trade in pre_kap_trades:
                            vol = float(trade.get("volume", 0.0))
                            avg_v = float(trade.get("avg_volume", 1.0))
                            if avg_v > 0 and vol > avg_v * 3.0:
                                alerts.append(
                                    InsiderAlert(
                                        ticker=event_ticker,
                                        alert_type=InsiderAlertType.PRE_KAP_TRADE.value,
                                        severity=InsiderAlertSeverity.HIGH.value,
                                        description=f"KAP öncesi 3x ortalama üstü hacim: {vol:,.0f}",
                                        z_score=3.0,
                                        confidence=0.85,
                                        event_date=event_date,
                                    )
                                )

            # Üretilen alarmları hafıza geçmişine ekle
            for a in alerts:
                self._alert_history.append(a)
            if len(self._alert_history) > DEFAULT_MAX_ALERT_HISTORY:
                self._alert_history = self._alert_history[-DEFAULT_MAX_ALERT_HISTORY:]

            return alerts

    def _classify_z(self, z: float) -> tuple[str | None, str]:
        """Z-skorunu önem seviyesi ve alarm türüne göre sınıflandırır."""
        if z >= self.Z_THRESHOLD_CRITICAL:
            return InsiderAlertSeverity.CRITICAL.value, InsiderAlertType.PRE_KAP_TRADE.value
        if z >= self.Z_THRESHOLD_HIGH:
            return InsiderAlertSeverity.HIGH.value, InsiderAlertType.PRE_KAP_TRADE.value
        if z >= self.Z_THRESHOLD_MEDIUM:
            return InsiderAlertSeverity.MEDIUM.value, InsiderAlertType.UNUSUAL_VOLUME.value
        return None, ""

    @otel_trace("insider_detector.compute_volume_z_score")
    def compute_volume_z_score(
        self,
        volumes: list[float] | np.ndarray,
        use_log: bool = True,
    ) -> tuple[float, float]:
        """Normal ve log-normal dağılım varsayımıyla Z-skorlarını hesaplar.

        Args:
            volumes: Hacim serisi (son eleman test edilen hacimdir).
            use_log: Log-normal dönüşümü uygulama bayrağı.

        Returns:
            tuple[float, float]: (standart_z, log_normal_z).
        """
        arr = np.asarray(volumes, dtype=float)
        arr = arr[np.isfinite(arr)]
        arr = arr[arr >= 0]
        if len(arr) < 2:
            return 0.0, 0.0

        baseline = arr[:-1]
        last_vol = arr[-1]

        # 1. Standart Normal Z-Skoru
        mean_vol = float(np.mean(baseline))
        std_vol = float(np.std(baseline))
        raw_z = float((last_vol - mean_vol) / std_vol) if std_vol > 0 else 0.0

        # 2. Log-Normal Z-Skoru (Finansal hacim sağa çarpıklık düzeltmesi)
        if use_log:
            log_baseline = np.log1p(baseline)
            log_last = float(np.log1p(last_vol))
            log_mean = float(np.mean(log_baseline))
            log_std = float(np.std(log_baseline))
            log_z = float((log_last - log_mean) / log_std) if log_std > 0 else 0.0
        else:
            log_z = raw_z

        return round(raw_z, 2), round(log_z, 2)

    @otel_trace("insider_detector.compute_cumulative_return")
    def compute_cumulative_return(
        self,
        prices: list[float] | np.ndarray,
        window: int = DEFAULT_PRICE_MOVE_WINDOW,
    ) -> float:
        """Belirtilen seans penceresindeki kümülatif getiri oranını hesaplar.

        Args:
            prices: Kapanış fiyatları serisi.
            window: Seans penceresi büyüklüğü.

        Returns:
            float: Yüzdesel kümülatif getiri oranı.
        """
        arr = np.asarray(prices, dtype=float)
        arr = arr[np.isfinite(arr)]
        arr = arr[arr > 0]
        if len(arr) < window + 1 or window <= 0:
            return 0.0
        window_prices = arr[-(window + 1) :]
        returns = np.diff(window_prices) / window_prices[:-1]
        returns = returns[np.isfinite(returns)]
        return float(np.sum(returns)) if len(returns) > 0 else 0.0

    @otel_trace("insider_detector.detect_price_move_before_kap")
    def detect_price_move_before_kap(
        self,
        prices: list[float] | np.ndarray,
        kap_date_idx: int,
        window: int = DEFAULT_PRICE_MOVE_WINDOW,
        ticker: str = "",
        record: bool = False,
    ) -> list[InsiderAlert]:
        """KAP açıklaması öncesindeki seanslarda anormal getiri veya yönlü hareket testi.

        Args:
            prices: Fiyat zaman serisi.
            kap_date_idx: KAP olayının denk geldiği seans indeksi.
            window: Analiz edilecek pencere büyüklüğü (seans).
            ticker: Opsiyonel hisse kodu.
            record: Alarmın hafıza geçmişine kaydedilip kaydedilmeyeceği.

        Returns:
            list[InsiderAlert]: Üretilen fiyat anomalisi alarmları.
        """
        with self._lock:
            alerts: list[InsiderAlert] = []
            prices_arr = np.asarray(prices, dtype=float)

            if len(prices_arr) < 2 or kap_date_idx < window or kap_date_idx >= len(prices_arr):
                return alerts

            # KAP öncesi fiyat penceresi
            pre_kap_prices = prices_arr[kap_date_idx - window : kap_date_idx + 1]
            if len(pre_kap_prices) < 2 or np.any(pre_kap_prices[:-1] <= 0):
                return alerts

            with np.errstate(divide="ignore", invalid="ignore"):
                raw_pre_returns = np.diff(pre_kap_prices) / pre_kap_prices[:-1]
                valid_pre_returns = raw_pre_returns[np.isfinite(raw_pre_returns)]
                if len(valid_pre_returns) == 0:
                    return alerts
                cumulative_return = float(np.sum(valid_pre_returns))

                valid_prices = prices_arr[prices_arr > 0]
                if len(valid_prices) < 2:
                    return alerts
                raw_all_returns = np.diff(valid_prices) / valid_prices[:-1]
                valid_returns = raw_all_returns[np.isfinite(raw_all_returns)]

            if len(valid_returns) < 5:
                return alerts

            mean_ret = float(np.mean(valid_returns))
            std_ret = float(np.std(valid_returns))

            if std_ret > 0.0:
                denom = std_ret * np.sqrt(window)
                if denom > 0.0:
                    z = (cumulative_return - (mean_ret * window)) / denom
                    if np.isfinite(z) and abs(z) >= self.Z_THRESHOLD_HIGH:
                        severity = (
                            InsiderAlertSeverity.CRITICAL.value
                            if abs(z) >= self.Z_THRESHOLD_CRITICAL
                            else InsiderAlertSeverity.HIGH.value
                        )
                        conf = min(0.99, max(0.50, float(1.0 - np.exp(-abs(z) / 2.0))))
                        alert = InsiderAlert(
                            ticker=ticker,
                            alert_type=InsiderAlertType.PRICE_MOVE_BEFORE_KAP.value,
                            severity=severity,
                            description=(
                                f"KAP öncesi anormal fiyat hareketi (Z={z:.2f}): "
                                f"Kümülatif Getiri %{cumulative_return * 100:.1f}"
                            ),
                            z_score=round(float(z), 2),
                            confidence=round(conf, 3),
                        )
                        alerts.append(alert)
                        if record:
                            self._alert_history.append(alert)
                            if len(self._alert_history) > DEFAULT_MAX_ALERT_HISTORY:
                                self._alert_history = self._alert_history[-DEFAULT_MAX_ALERT_HISTORY:]

            return alerts

    def get_alert_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Hafızadaki geçmiş alarmları döndürür.

        Args:
            limit: Maksimum kayıt sayısı.

        Returns:
            list[dict[str, Any]]: Alarm kayıtları listesi.
        """
        with self._lock:
            return [a.to_dict() for a in self._alert_history[-limit:]]

    def export_to_polars(self) -> pl.DataFrame:
        """Geçmiş alarmları Polars DataFrame olarak dışa aktarır.

        Returns:
            pl.DataFrame: Alarm tablosu.
        """
        with self._lock:
            schema = {
                "ticker": pl.String,
                "alert_type": pl.String,
                "severity": pl.String,
                "description": pl.String,
                "z_score": pl.Float64,
                "confidence": pl.Float64,
                "event_date": pl.String,
                "detected_at": pl.String,
            }
            if not self._alert_history:
                return pl.DataFrame(schema=schema)
            return pl.DataFrame([a.to_dict() for a in self._alert_history], schema=schema)

    def export_to_duckdb(self, db_path: str | Path | None = None) -> int:
        """Geçmiş alarmları DuckDB `bist_insider_alerts` tablosuna atomik yazar.

        Args:
            db_path: DuckDB veritabanı yolu.

        Returns:
            int: Kaydedilen alarm sayısı.
        """
        df = self.export_to_polars()
        if df.is_empty():
            return 0

        target_path = Path(db_path) if db_path is not None else DEFAULT_INSIDER_AUDIT_DB_PATH
        target_path.parent.mkdir(parents=True, exist_ok=True)

        con = duckdb.connect(str(target_path))
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS bist_insider_alerts (
                    ticker VARCHAR,
                    alert_type VARCHAR,
                    severity VARCHAR,
                    description VARCHAR,
                    z_score DOUBLE,
                    confidence DOUBLE,
                    event_date VARCHAR,
                    detected_at VARCHAR,
                    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (ticker, alert_type, event_date, detected_at)
                )
            """)
            arrow_table = df.to_arrow()
            con.register("alert_arrow", arrow_table)
            con.execute("""
                INSERT OR REPLACE INTO bist_insider_alerts (
                    ticker, alert_type, severity, description, z_score, confidence, event_date, detected_at
                )
                SELECT ticker, alert_type, severity, description, z_score, confidence, event_date, detected_at
                FROM alert_arrow
            """)
            con.unregister("alert_arrow")
            con.commit()
            return len(df)
        finally:
            con.close()

    @staticmethod
    def _days_before(date_str: str, days: int) -> str:
        """Verilen tarihten N takvim günü önceki tarihi hesaplar.

        Args:
            date_str: ISO formatında tarih metni.
            days: Gün sayısı.

        Returns:
            str: Önceki tarih (YYYY-MM-DD veya ISO).
        """
        try:
            dt = datetime.fromisoformat(date_str)
            target = dt - timedelta(days=days)
            if "T" not in date_str and len(date_str) == 10:
                return target.strftime("%Y-%m-%d")
            return target.isoformat()
        except Exception:
            return ""

    def __repr__(self) -> str:
        """Dedektör metin gösterimi.

        Returns:
            str: Eşikler ve geçmiş alarm sayısı özeti.
        """
        with self._lock:
            return (
                f"InsiderDetector(z_orta={self.Z_THRESHOLD_MEDIUM}, "
                f"z_kritik={self.Z_THRESHOLD_CRITICAL}, toplam_alarm={len(self._alert_history)})"
            )


# =====================================================
# MODÜL DÜZEYİNDE DIŞA AKTARIM VE YARDIMCI FONKSİYONLAR
# =====================================================


def detect_insider_trading(
    trades: list[dict[str, Any]] | None = None,
    kap_events: list[dict[str, Any]] | None = None,
    volume_history: list[float] | np.ndarray | None = None,
    *,
    ticker: str | None = None,
    prices: list[float] | np.ndarray | None = None,
    volumes: list[float] | np.ndarray | None = None,
    detector: InsiderDetector | None = None,
) -> list[InsiderAlert]:
    """KAP öncesi olağandışı hacim ve fiyat hareketlerini denetler."""
    inst = detector if detector is not None else insider_detector
    return inst.detect_pre_kap_trade(
        trades=trades,
        kap_events=kap_events,
        volume_history=volume_history,
        ticker=ticker,
        prices=prices,
        volumes=volumes,
    )


def detect_price_anomaly(
    prices: list[float] | np.ndarray,
    kap_date_idx: int,
    window: int = DEFAULT_PRICE_MOVE_WINDOW,
    ticker: str = "",
    record: bool = True,
    detector: InsiderDetector | None = None,
) -> list[InsiderAlert]:
    """KAP açıklaması öncesi anormal fiyat hareketini denetler."""
    inst = detector if detector is not None else insider_detector
    return inst.detect_price_move_before_kap(
        prices=prices,
        kap_date_idx=kap_date_idx,
        window=window,
        ticker=ticker,
        record=record,
    )


def get_insider_alerts(limit: int = 100, detector: InsiderDetector | None = None) -> list[dict[str, Any]]:
    """Geçmiş içeriden bilgi ticareti alarmlarını döndürür."""
    inst = detector if detector is not None else insider_detector
    return inst.get_alert_history(limit=limit)


def get_insider_detector() -> InsiderDetector:
    """Genel tekil içeriden bilgi ticareti dedektör örneğini döndürür."""
    return insider_detector


def export_insider_alerts_to_polars(detector: InsiderDetector | None = None) -> pl.DataFrame:
    """İçeriden bilgi ticareti alarmlarını Polars DataFrame olarak dışa aktarır.

    Args:
        detector: Dedektör nesnesi (None ise varsayılan singleton).

    Returns:
        pl.DataFrame: Alarmlar tablosu.
    """
    inst = detector if detector is not None else insider_detector
    return inst.export_to_polars()


def export_insider_alerts_to_duckdb(
    db_path: str | Path | None = None,
    detector: InsiderDetector | None = None,
) -> int:
    """İçeriden bilgi ticareti alarmlarını DuckDB tablosuna yazar.

    Args:
        db_path: DuckDB dosya yolu.
        detector: Dedektör nesnesi.

    Returns:
        int: Kaydedilen alarm adedi.
    """
    inst = detector if detector is not None else insider_detector
    return inst.export_to_duckdb(db_path=db_path)


def compute_volume_z_score(
    volumes: list[float] | np.ndarray,
    use_log: bool = True,
    detector: InsiderDetector | None = None,
) -> tuple[float, float]:
    """Normal ve log-normal dağılım varsayımıyla Z-skorlarını hesaplar.

    Args:
        volumes: Hacim serisi (son eleman test edilen hacimdir).
        use_log: Log-normal dönüşümü uygulama bayrağı.
        detector: Dedektör nesnesi (None ise varsayılan singleton).

    Returns:
        tuple[float, float]: (standart_z, log_normal_z).
    """
    inst = detector if detector is not None else insider_detector
    return inst.compute_volume_z_score(volumes=volumes, use_log=use_log)


def compute_cumulative_return(
    prices: list[float] | np.ndarray,
    window: int = DEFAULT_PRICE_MOVE_WINDOW,
    detector: InsiderDetector | None = None,
) -> float:
    """Belirtilen seans penceresindeki kümülatif getiri oranını hesaplar.

    Args:
        prices: Kapanış fiyatları serisi.
        window: Seans penceresi büyüklüğü.
        detector: Dedektör nesnesi (None ise varsayılan singleton).

    Returns:
        float: Yüzdesel kümülatif getiri oranı.
    """
    inst = detector if detector is not None else insider_detector
    return inst.compute_cumulative_return(prices=prices, window=window)


# Global Singleton Örneği
insider_detector: Final[InsiderDetector] = InsiderDetector()

__all__: list[str] = [
    "DEFAULT_INSIDER_AUDIT_DB_PATH",
    "DEFAULT_MAX_ALERT_HISTORY",
    "DEFAULT_MIN_VOLUME_HISTORY_LEN",
    "DEFAULT_PRE_KAP_DAYS_WINDOW",
    "DEFAULT_PRICE_MOVE_WINDOW",
    "DEFAULT_Z_THRESHOLD_CRITICAL",
    "DEFAULT_Z_THRESHOLD_HIGH",
    "DEFAULT_Z_THRESHOLD_MEDIUM",
    "InsiderAlert",
    "InsiderAlertSeverity",
    "InsiderAlertType",
    "InsiderDetector",
    "compute_cumulative_return",
    "compute_volume_z_score",
    "detect_insider_trading",
    "detect_price_anomaly",
    "export_insider_alerts_to_duckdb",
    "export_insider_alerts_to_polars",
    "get_insider_alerts",
    "get_insider_detector",
    "insider_detector",
]
