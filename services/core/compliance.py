"""ALPHA BIST — Kurumsal SPK Mevzuat ve BIST Uyumluluk Motoru (Compliance Engine).

Bu modül, Sermaye Piyasası Kurulu (SPK) tebliğleri ve Borsa İstanbul (BIST) düzenlemeleri
çerçevesinde tüm emir, işlem ve portföy hareketlerinin yasal uyumluluğunu denetler:

1. SPK Özel Durumlar Tebliği (II-15.1 Madde 12) Ortaklık Payı ve Oy Hakkı Bildirim Eşikleri:
   - Sermaye veya toplam oy haklarının %5, %10, %15, %20, %25, %33, %50, %67, %95
     oranlarına ulaşılması veya bu oranların altına düşülmesi halinde KAP bildirimi.
2. SPK Pay Alım Teklifi Tebliği (II-26.1):
   - %50 ve üzeri oy hakkı veya yönetim kontrolü kazanımlarında Zorunlu Pay Alım Teklifi eşiği.
3. SPK Yatırım Fonlarına İlişkin Esaslar Tebliği (III-52.1 Madde 18):
   - Portföy yoğunlaşma (konsantrasyon) sınırı: Tek bir ihraççının payları portföyün %10'unu aşamaz.
4. Algoritmik ve Yüksek Frekanslı İşlemler (HFT) SPK Düzenlemeleri:
   - Günlük 1.000+ emir iletimi bildirimi.
   - Günlük hisse işlem hacminin %5'ini aşan algoritmik işlemler bildirimi.
   - Emir / İşlem Oranı (Order-to-Trade Ratio - OTR) manipülasyon ve piyasa bozucu eylem denetimi.
5. Açığa Satış ve Depo Şartı / Yukarı Adım Kuralı (Up-tick Rule) Denetimleri.
6. İçeriden Öğrenenlerin Ticareti (Insider Trading) ve Finansal Tablo Sessiz Dönem (Blackout Period) Guard'ı.
7. DuckDB Destekli Yasal Denetim Günlüğü (Compliance Audit Trail) ve Polars Entegrasyonu.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# ==============================================================================
# MEVZUAT VE UYUMLULUK SABİTLERİ (SPK & BIST)
# ==============================================================================

# SPK II-15.1 Madde 12 uyarınca mülkiyet ve oy hakkı bildirim eşikleri
SPK_SHARE_NOTIFICATION_THRESHOLDS: Final[tuple[float, ...]] = (
    0.05,  # %5
    0.10,  # %10
    0.15,  # %15
    0.20,  # %20
    0.25,  # %25
    0.33,  # %33 (üçte bir)
    0.50,  # %50 (yönetim kontrolü)
    0.67,  # %67 (üçte iki)
    0.95,  # %95 (azınlık hakları / satma hakkı)
)

# SPK II-26.1 Yönetim Kontrolü ve Zorunlu Pay Alım Teklifi Eşiği
MANDATORY_TENDER_OFFER_THRESHOLD: Final[float] = 0.50

# SPK III-52.1 Fon Portföyü Tek İhraççı Konsantrasyon Limiti
DEFAULT_PORTFOLIO_CONCENTRATION_LIMIT: Final[float] = 0.10  # %10

# BIST Algoritmik Trading Bildirim Eşikleri
DEFAULT_ALGO_ORDER_THRESHOLD: Final[int] = 1000  # Günde 1000+ emir
DEFAULT_ALGO_VOLUME_THRESHOLD: Final[float] = 0.05  # Günlük piyasa hacminin %5'i
DEFAULT_MAX_OTR_THRESHOLD: Final[float] = 50.0  # Maksimum Emir/İşlem Oranı (OTR)
DEFAULT_MIN_OTR_EVALUATION_ORDERS: Final[int] = 100  # OTR değerlendirmesi için taban emir sayısı

# BIST Açığa Satış ve Yukarı Adım Kuralı (Up-tick Rule) Varsayılanı
DEFAULT_UPTICK_RULE_ACTIVE: Final[bool] = True

# DuckDB Denetim İzi Veritabanı Yolu
DEFAULT_COMPLIANCE_DB_PATH: Final[str] = "data/compliance_audit.duckdb"


class ComplianceAction(StrEnum):
    """Uyumluluk denetim aksiyon türleri."""

    OK = "OK"  # İşlem tamamen uygun, ek işlem gerekmez.
    NOTIFY = "NOTIFY"  # İşlem gerçekleştirilebilir ancak SPK/KAP bildirimi zorunludur.
    WARN = "WARN"  # Risk veya konsantrasyon eşiği uyarısı, onay gerektirebilir.
    BLOCK = "BLOCK"  # İşlem kesinlikle durdurulur (fail-closed mevzuat engeli).


@dataclass(slots=True)
class ComplianceResult:
    """Uyumluluk denetim sonucu veri modeli.

    Attributes:
        action: Aksiyon durumu ("OK", "NOTIFY", "WARN", "BLOCK").
        notification_required: SPK veya BIST'e bildirim verilmesi zorunlu mu.
        violation: Mevzuat veya kural ihlali oluştu mu.
        reason: Sonucun yasal veya operasyonel gerekçesi.
        details: Denetime ait sayısal ve teknik detaylar sözlüğü.
        timestamp: Denetimin yapıldığı UTC zaman damgası.
    """

    action: str = ComplianceAction.OK.value
    notification_required: bool = False
    violation: bool = False
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Geriye dönük uyumluluk ve serileştirme için sözlük temsili üretir.

        Returns:
            dict[str, Any]: Serileştirilebilir denetim detayları.
        """
        return {
            "action": self.action,
            "notification_required": self.notification_required,
            "violation": self.violation,
            "reason": self.reason,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }

    def to_orjson_bytes(self) -> bytes:
        """Denetim sonucunu yüksek hızlı orjson ikili formatında döndürür.

        Returns:
            bytes: JSON çıktısı baytları.
        """
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Nesnenin okunabilir hata ayıklama temsilini döndürür."""
        return (
            f"ComplianceResult(action={self.action!r}, violation={self.violation}, "
            f"notify={self.notification_required}, reason={self.reason!r})"
        )


class ComplianceChecker:
    """Sermaye Piyasası Kurulu (SPK) ve Borsa İstanbul (BIST) Kurumsal Uyumluluk Motoru.

    Tüm hisse alım/satım, portföy ağırlığı, ortaklık payı, algoritmik işlem ve açığa satış
    akışlarını fail-closed prensibiyle denetler.
    """

    # Geriye dönük uyumluluk sabitleri (Önceki kodla uyum)
    NOTIFICATION_THRESHOLD: Final[float] = 0.05
    MANDATORY_BID_THRESHOLD: Final[float] = 0.10
    BLOCKING_MINORITY: Final[float] = 0.20
    ALGO_TRADING_ORDER_THRESHOLD: Final[int] = DEFAULT_ALGO_ORDER_THRESHOLD
    ALGO_TRADING_VOLUME_THRESHOLD: Final[float] = DEFAULT_ALGO_VOLUME_THRESHOLD

    def __init__(self, db_path: str = DEFAULT_COMPLIANCE_DB_PATH) -> None:
        """ComplianceChecker motorunu başlatır ve DuckDB denetim tablosunu hazırlar.

        Args:
            db_path: Yasal denetim kayıtlarının saklanacağı DuckDB dosya yolu.
        """
        self._db_path = db_path
        self._lock = threading.RLock()
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._blackout_calendar: dict[str, list[tuple[date, date]]] = {}
        self._init_db()

    def __enter__(self) -> ComplianceChecker:
        """Context manager giriş protokolü."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager çıkış protokolü ile bağlantıyı güvenli kapatır."""
        self.close()

    def _init_db(self) -> None:
        """DuckDB denetim tablosunu oluşturur ve eşzamanlı erişime hazırlar."""
        try:
            db_file = Path(self._db_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            self._conn = duckdb.connect(str(db_file))
            with self._lock:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS compliance_audit_log (
                        id BIGINT PRIMARY KEY,
                        timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                        ticker VARCHAR NOT NULL,
                        check_type VARCHAR NOT NULL,
                        action VARCHAR NOT NULL,
                        notification_required BOOLEAN NOT NULL,
                        violation BOOLEAN NOT NULL,
                        reason VARCHAR NOT NULL,
                        details_json VARCHAR NOT NULL
                    );
                    CREATE SEQUENCE IF NOT EXISTS seq_compliance_audit_id START 1;
                    """
                )
            logger.info("compliance_audit_store_hazirlandi", db_path=self._db_path)
        except Exception as exc:
            logger.error("compliance_db_baslatma_hatasi", error=str(exc), path=self._db_path)
            self._conn = None

    def close(self) -> None:
        """DuckDB bağlantısını güvenli şekilde kapatır."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception as exc:
                    logger.debug("compliance_db_kapatma_hatasi", error=str(exc))
                finally:
                    self._conn = None

    def _persist_audit(
        self,
        ticker: str,
        check_type: str,
        result: ComplianceResult,
    ) -> None:
        """Uyumluluk denetim sonucunu kalıcı DuckDB günlüğüne yazar."""
        if self._conn is None:
            return

        with self._lock:
            try:
                details_json = orjson.dumps(result.details).decode("utf-8")
                self._conn.execute(
                    """
                    INSERT INTO compliance_audit_log (
                        id, timestamp, ticker, check_type, action,
                        notification_required, violation, reason, details_json
                    ) VALUES (
                        nextval('seq_compliance_audit_id'), ?, ?, ?, ?, ?, ?, ?, ?
                    );
                    """,
                    [
                        result.timestamp,
                        ticker,
                        check_type,
                        result.action,
                        result.notification_required,
                        result.violation,
                        result.reason,
                        details_json,
                    ],
                )
            except Exception as exc:
                logger.warning("compliance_audit_yazilamadi", ticker=ticker, error=str(exc))

    @otel_trace("compliance.check_spk_compliance")
    def check_spk_compliance(
        self,
        action: str,
        ticker: str,
        amount: float,
        portfolio_value: float,
        current_position_pct: float = 0.0,
        company_capital: float | None = None,
        is_fund: bool = False,
    ) -> ComplianceResult:
        """SPK ve BIST mevzuatı uyumluluk denetimi (Fail-Closed).

        Args:
            action: İşlem yönü ("BUY", "SELL", "HOLD").
            ticker: İlgili pay kodu (örn. "THYAO", "GARAN").
            amount: İşlem parasal tutarı (TRY).
            portfolio_value: Toplam portföy net aktif değeri (TRY).
            current_position_pct: Mevcut pozisyonun portföydeki oranı (0.0 - 1.0).
            company_capital: İsteğe bağlı olarak şirketin ödenmiş sermayesi (TRY).
            is_fund: İşlemi gerçekleştiren tarafın bir Yatırım Fonu olup olmadığı.

        Returns:
            ComplianceResult: Denetim kararı ve detayları.
        """
        clean_action = str(action).strip().upper()
        clean_ticker = str(ticker).strip().upper()

        details: dict[str, Any] = {
            "ticker": clean_ticker,
            "action": clean_action,
            "amount": amount,
            "portfolio_value": portfolio_value,
            "current_position_pct": current_position_pct,
            "company_capital": company_capital,
            "is_fund": is_fund,
        }

        # 1. Sayısal Güvenlik ve IEEE 754 Sınır Doğrulamaları
        if (
            math.isnan(amount)
            or math.isinf(amount)
            or math.isnan(portfolio_value)
            or math.isinf(portfolio_value)
            or math.isnan(current_position_pct)
            or math.isinf(current_position_pct)
        ):
            res = ComplianceResult(
                action=ComplianceAction.BLOCK.value,
                violation=True,
                reason="Geçersiz sayısal değer (NaN veya Sonsuz tespit edildi)",
                details=details,
            )
            self._persist_audit(clean_ticker, "SPK_NUMERICAL_GUARD", res)
            return res

        if portfolio_value <= 0:
            res = ComplianceResult(
                action=ComplianceAction.BLOCK.value,
                violation=True,
                reason=f"Geçersiz portföy değeri: {portfolio_value} TRY (İşlem onaylanamaz)",
                details=details,
            )
            self._persist_audit(clean_ticker, "PORTFOLIO_VALUE_GUARD", res)
            return res

        if amount < 0:
            res = ComplianceResult(
                action=ComplianceAction.BLOCK.value,
                violation=True,
                reason=f"Negatif işlem tutarı geçersiz: {amount} TRY",
                details=details,
            )
            self._persist_audit(clean_ticker, "AMOUNT_NEGATIVE_GUARD", res)
            return res

        if not (0.0 <= current_position_pct <= 1.0):
            res = ComplianceResult(
                action=ComplianceAction.BLOCK.value,
                violation=True,
                reason=f"Geçersiz mevcut pozisyon yüzdesi: %{current_position_pct * 100:.2f} (0.0 - 1.0 aralığında olmalıdır)",
                details=details,
            )
            self._persist_audit(clean_ticker, "POSITION_PCT_RANGE_GUARD", res)
            return res

        if company_capital is not None:
            if math.isnan(company_capital) or math.isinf(company_capital) or company_capital <= 0:
                res = ComplianceResult(
                    action=ComplianceAction.BLOCK.value,
                    violation=True,
                    reason=f"Geçersiz şirket sermayesi değeri: {company_capital}",
                    details=details,
                )
                self._persist_audit(clean_ticker, "COMPANY_CAPITAL_GUARD", res)
                return res

        if amount == 0 or clean_action == "HOLD":
            res = ComplianceResult(
                action=ComplianceAction.OK.value,
                reason="İşlem tutarı sıfır veya emir HOLD",
                details=details,
            )
            self._persist_audit(clean_ticker, "SPK_HOLD", res)
            return res

        # 2. Portföy İçi Pozisyon Ağırlığı Hesaplaması
        trade_weight = amount / portfolio_value
        if clean_action == "BUY":
            new_position_pct = current_position_pct + trade_weight
        elif clean_action == "SELL":
            new_position_pct = max(0.0, current_position_pct - trade_weight)
        else:
            res = ComplianceResult(
                action=ComplianceAction.BLOCK.value,
                violation=True,
                reason=f"Tanınmayan işlem yönü: {clean_action}",
                details=details,
            )
            self._persist_audit(clean_ticker, "UNKNOWN_ACTION", res)
            return res

        details["new_position_pct"] = round(new_position_pct, 6)

        # 3. SPK Yatırım Fonları Tebliği (III-52.1) Tek Pay Konsantrasyon Kontrolü (%10)
        if is_fund and clean_action == "BUY" and new_position_pct > DEFAULT_PORTFOLIO_CONCENTRATION_LIMIT:
            res = ComplianceResult(
                action=ComplianceAction.BLOCK.value,
                violation=True,
                reason=(
                    f"SPK III-52.1 Fon Konsantrasyon Sınırı Aşıldı: %{new_position_pct * 100:.2f} "
                    f"(Yasal Fon Sınırı: %{DEFAULT_PORTFOLIO_CONCENTRATION_LIMIT * 100:.0f})"
                ),
                details=details,
            )
            self._persist_audit(clean_ticker, "FUND_CONCENTRATION_LIMIT", res)
            return res

        # 4. Şirket Sermayesi / Oy Hakkı Eşikleri (SPK II-15.1 & II-26.1)
        if company_capital is not None and company_capital > 0:
            current_shares_pct = (current_position_pct * portfolio_value) / company_capital
            new_shares_pct = (new_position_pct * portfolio_value) / company_capital
            details["company_ownership_pct"] = round(new_shares_pct, 6)

            # SPK II-26.1 Yönetim Kontrolü / Zorunlu Pay Alım Teklifi (%50)
            if new_shares_pct >= MANDATORY_TENDER_OFFER_THRESHOLD and current_shares_pct < MANDATORY_TENDER_OFFER_THRESHOLD:
                res = ComplianceResult(
                    action=ComplianceAction.BLOCK.value,
                    notification_required=True,
                    violation=True,
                    reason=(
                        f"SPK II-26.1 Zorunlu Pay Alım Teklifi Eşiği Aşıldı: "
                        f"Şirket payı %{new_shares_pct * 100:.2f} (Eşik: %50)"
                    ),
                    details=details,
                )
                self._persist_audit(clean_ticker, "SPK_MANDATORY_TENDER", res)
                return res

            # SPK II-15.1 Bildirim Eşikleri Kontrolü (%5, %10, %15, %20, %25, %33, %50, %67, %95)
            for threshold in SPK_SHARE_NOTIFICATION_THRESHOLDS:
                crossed_up = current_shares_pct < threshold <= new_shares_pct
                crossed_down = new_shares_pct < threshold <= current_shares_pct
                if crossed_up or crossed_down:
                    yon_str = "aşılması" if crossed_up else "altına düşülmesi"
                    res = ComplianceResult(
                        action=ComplianceAction.NOTIFY.value,
                        notification_required=True,
                        reason=f"SPK II-15.1 %{threshold * 100:.0f} ortaklık payı eşiğinin {yon_str}: %{new_shares_pct * 100:.2f}",
                        details=details,
                    )
                    self._persist_audit(clean_ticker, "SPK_SHARE_THRESHOLD", res)
                    return res

        # 5. Fallback: Şirket Sermayesi Bilinmiyorsa Portföy Eşikleri Üzerinden Kontrol
        if clean_action == "BUY":
            # %10 Portföy konsantrasyon eşiği kontrolü
            if new_position_pct >= self.MANDATORY_BID_THRESHOLD and current_position_pct < self.MANDATORY_BID_THRESHOLD:
                res = ComplianceResult(
                    action=ComplianceAction.BLOCK.value,
                    notification_required=True,
                    violation=True,
                    reason=f"SPK %10 tek hisse portföy konsantrasyon eşiği aşıldı: %{new_position_pct * 100:.1f}",
                    details=details,
                )
                self._persist_audit(clean_ticker, "FALLBACK_10_PCT_BLOCK", res)
                return res

            # %5 Portföy bildirim eşiği kontrolü
            if new_position_pct >= self.NOTIFICATION_THRESHOLD and current_position_pct < self.NOTIFICATION_THRESHOLD:
                res = ComplianceResult(
                    action=ComplianceAction.NOTIFY.value,
                    notification_required=True,
                    reason=f"SPK %5 bildirim yükümlülüğü eşiği: %{new_position_pct * 100:.1f}",
                    details=details,
                )
                self._persist_audit(clean_ticker, "FALLBACK_5_PCT_NOTIFY", res)
                return res
        else:
            # SELL: %5 altına düşüş bildirimi
            if current_position_pct >= self.NOTIFICATION_THRESHOLD and new_position_pct < self.NOTIFICATION_THRESHOLD:
                res = ComplianceResult(
                    action=ComplianceAction.NOTIFY.value,
                    notification_required=True,
                    reason=f"SPK %5 bildirim eşiği altına düşüş: %{new_position_pct * 100:.1f}",
                    details=details,
                )
                self._persist_audit(clean_ticker, "FALLBACK_5_PCT_SELL_NOTIFY", res)
                return res

        res = ComplianceResult(action=ComplianceAction.OK.value, details=details)
        self._persist_audit(clean_ticker, "SPK_PASSED", res)
        return res

    @otel_trace("compliance.check_algo_trading_notification")
    def check_algo_trading_notification(
        self,
        daily_order_count: int,
        daily_volume_pct: float,
    ) -> ComplianceResult:
        """Algoritmik ve yüksek frekanslı işlem (HFT) bildirim denetimi.

        SPK ve BIST düzenlemelerine göre:
        - Günde 1.000 veya daha fazla emir ileten algoritmik sistemler SPK'ya bildirilmeli.
        - Günlük piyasa hacminin %5'ini aşan işlemler bildirim yükümlülüğü doğurur.

        Args:
            daily_order_count: Gün içinde iletilen toplam emir sayısı.
            daily_volume_pct: Günlük piyasa hacmine kıyasla işlem oranı (0.0 - 1.0).

        Returns:
            ComplianceResult: Bildirim zorunluluğu ve denetim durumu.
        """
        # Sayısal sınır kontrolleri
        if math.isnan(daily_volume_pct) or math.isinf(daily_volume_pct):
            daily_volume_pct = 0.0

        safe_order_count = max(0, int(daily_order_count))
        safe_volume_pct = max(0.0, float(daily_volume_pct))

        details = {
            "daily_order_count": safe_order_count,
            "daily_volume_pct": safe_volume_pct,
            "order_threshold": self.ALGO_TRADING_ORDER_THRESHOLD,
            "volume_threshold": self.ALGO_TRADING_VOLUME_THRESHOLD,
        }

        if safe_order_count >= self.ALGO_TRADING_ORDER_THRESHOLD:
            res = ComplianceResult(
                action=ComplianceAction.NOTIFY.value,
                notification_required=True,
                reason=(
                    f"Algoritmik trading bildirimi: {safe_order_count} emir/gün "
                    f"(SPK eşiği: {self.ALGO_TRADING_ORDER_THRESHOLD})"
                ),
                details=details,
            )
            self._persist_audit("SYS_ALGO", "ALGO_ORDER_COUNT", res)
            return res

        if safe_volume_pct >= self.ALGO_TRADING_VOLUME_THRESHOLD:
            res = ComplianceResult(
                action=ComplianceAction.NOTIFY.value,
                notification_required=True,
                reason=(
                    f"Algoritmik trading bildirimi: Hacim payı %{safe_volume_pct * 100:.1f} "
                    f"(SPK eşiği: %{self.ALGO_TRADING_VOLUME_THRESHOLD * 100:.0f})"
                ),
                details=details,
            )
            self._persist_audit("SYS_ALGO", "ALGO_VOLUME_SHARE", res)
            return res

        res = ComplianceResult(action=ComplianceAction.OK.value, details=details)
        self._persist_audit("SYS_ALGO", "ALGO_PASSED", res)
        return res

    @otel_trace("compliance.check_order_to_trade_ratio")
    def check_order_to_trade_ratio(
        self,
        order_count: int,
        trade_count: int,
        max_otr: float = DEFAULT_MAX_OTR_THRESHOLD,
        ticker: str = "SYS",
    ) -> ComplianceResult:
        """BIST Emir / İşlem Oranı (OTR) manipülasyon ve piyasa bozucu eylem denetimi.

        Borsa İstanbul kurallarına göre orantısız emir iletimi ve iptali (spoofing/quote stuffing)
        riskine karşı OTR sınırlandırılmıştır.

        Args:
            order_count: Toplam iletilen/değiştirilen emir sayısı.
            trade_count: Gerçekleşen işlem sayısı.
            max_otr: Müsaade edilen maksimum OTR eşiği (varsayılan: 50.0).
            ticker: Pay veya enstrüman kodu.

        Returns:
            ComplianceResult: OTR uyumluluk sonucu.
        """
        safe_orders = max(0, int(order_count))
        safe_trades = max(0, int(trade_count))
        safe_max_otr = DEFAULT_MAX_OTR_THRESHOLD if (math.isnan(max_otr) or math.isinf(max_otr) or max_otr <= 0) else max_otr

        effective_trades = max(1, safe_trades)
        current_otr = safe_orders / effective_trades

        details = {
            "ticker": ticker,
            "order_count": safe_orders,
            "trade_count": safe_trades,
            "otr": round(current_otr, 2),
            "max_otr": safe_max_otr,
        }

        if current_otr > safe_max_otr and safe_orders >= DEFAULT_MIN_OTR_EVALUATION_ORDERS:
            res = ComplianceResult(
                action=ComplianceAction.WARN.value,
                violation=True,
                reason=f"BIST OTR (Emir/İşlem Oranı) Sınırı Aşıldı: {current_otr:.1f} (Maks: {safe_max_otr:.1f})",
                details=details,
            )
            self._persist_audit(ticker, "OTR_VIOLATION", res)
            return res

        res = ComplianceResult(action=ComplianceAction.OK.value, details=details)
        self._persist_audit(ticker, "OTR_PASSED", res)
        return res

    @otel_trace("compliance.check_short_sale_uptick")
    def check_short_sale_uptick(
        self,
        ticker: str,
        order_price: float,
        last_price: float,
        prev_price: float,
        is_short_sale: bool = True,
    ) -> ComplianceResult:
        """BIST Açığa Satış ve Yukarı Adım Kuralı (Up-tick Rule) denetimi.

        Borsa İstanbul düzenlemelerine göre açığa satış işlemi, son gerçekleşen işlem
        fiyatından daha yüksek bir fiyattan veya son işlem fiyatı önceki fiyattan yüksekse
        (sıfır-artı adım) son işlem fiyatından gerçekleştirilebilir.

        Args:
            ticker: Pay kodu.
            order_price: İletilmek istenen emir fiyatı.
            last_price: Son gerçekleşen işlem fiyatı.
            prev_price: Son işlemden bir önceki işlem fiyatı.
            is_short_sale: Emrin açığa satış emri olup olmadığı.

        Returns:
            ComplianceResult: Emir iletim izin kararı.
        """
        clean_ticker = (ticker or "").strip().upper()
        details = {
            "ticker": clean_ticker,
            "order_price": order_price,
            "last_price": last_price,
            "prev_price": prev_price,
            "is_short_sale": is_short_sale,
        }

        # Açığa satış değilse kontrol gerekmez
        if not is_short_sale:
            return ComplianceResult(action=ComplianceAction.OK.value, details=details)

        # Fiyat geçerlilik kontrolleri
        if (
            math.isnan(order_price)
            or math.isinf(order_price)
            or order_price <= 0
            or math.isnan(last_price)
            or math.isinf(last_price)
            or last_price <= 0
            or math.isnan(prev_price)
            or math.isinf(prev_price)
            or prev_price <= 0
        ):
            res = ComplianceResult(
                action=ComplianceAction.BLOCK.value,
                violation=True,
                reason=f"Geçersiz fiyat bilgisiyle açığa satış emri iletilemez: emir={order_price}, son={last_price}",
                details=details,
            )
            self._persist_audit(clean_ticker, "SHORT_SALE_INVALID_PRICE", res)
            return res

        # BIST Yukarı Adım Kuralı Denetimi:
        # 1. order_price > last_price -> Tamamen uygun (Yukarı adım).
        # 2. order_price == last_price -> Sadece last_price > prev_price ise uygun (Sıfır-artı adım).
        # 3. order_price < last_price -> Kesinlikle yasak (Aşağı adım).
        eps = 1e-4
        if order_price > last_price + eps:
            res = ComplianceResult(
                action=ComplianceAction.OK.value,
                reason="Yukarı adım kuralına uygun açığa satış (order_price > last_price)",
                details=details,
            )
            self._persist_audit(clean_ticker, "UPTICK_PASSED", res)
            return res

        if abs(order_price - last_price) <= eps:
            if last_price > prev_price + eps:
                res = ComplianceResult(
                    action=ComplianceAction.OK.value,
                    reason="Sıfır-artı adım kuralına uygun açığa satış (order_price == last_price > prev_price)",
                    details=details,
                )
                self._persist_audit(clean_ticker, "ZERO_PLUS_TICK_PASSED", res)
                return res
            else:
                res = ComplianceResult(
                    action=ComplianceAction.BLOCK.value,
                    violation=True,
                    reason=(
                        f"BIST Yukarı Adım Kuralı İhlali: {clean_ticker} son işlem fiyatı ({last_price:.2f}) "
                        f"önceki fiyata ({prev_price:.2f}) göre artmamışken son fiyattan açığa satış yapılamaz."
                    ),
                    details=details,
                )
                self._persist_audit(clean_ticker, "UPTICK_BLOCKED", res)
                return res

        # order_price < last_price durumu
        res = ComplianceResult(
            action=ComplianceAction.BLOCK.value,
            violation=True,
            reason=(
                f"BIST Yukarı Adım Kuralı İhlali: {clean_ticker} açığa satış emir fiyatı ({order_price:.2f}) "
                f"son işlem fiyatından ({last_price:.2f}) düşük olamaz."
            ),
            details=details,
        )
        self._persist_audit(clean_ticker, "UPTICK_LOWER_PRICE_BLOCKED", res)
        return res

    def register_blackout_period(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> None:
        """Bilanço dönemi veya içsel bilgi öncesi işlem yasağı (Sessiz Dönem) tanımlar.

        Args:
            ticker: Pay kodu.
            start_date: Yasak başlangıç tarihi.
            end_date: Yasak bitiş tarihi.

        Raises:
            ValueError: Ticker boşsa veya geçersizse.
        """
        clean_ticker = (ticker or "").strip().upper()
        if not clean_ticker:
            raise ValueError("Hisse kodu (ticker) boş olamaz.")

        # Tarih sıralama güvencesi
        if start_date > end_date:
            start_date, end_date = end_date, start_date

        with self._lock:
            if clean_ticker not in self._blackout_calendar:
                self._blackout_calendar[clean_ticker] = []
            self._blackout_calendar[clean_ticker].append((start_date, end_date))
        logger.info(
            "sessiz_donem_kaydedildi",
            ticker=clean_ticker,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
        )

    def check_insider_trading_window(
        self,
        ticker: str,
        check_date: date | None = None,
    ) -> ComplianceResult:
        """SPK II-15.1 İçeriden Bilgi Ticareti Sessiz Dönem kontrolü.

        Args:
            ticker: Pay kodu.
            check_date: Denetlenecek tarih (None ise bugün).

        Returns:
            ComplianceResult: İşlem izni sonucu.
        """
        clean_ticker = str(ticker).strip().upper()
        target_date = check_date or datetime.now(UTC).date()

        with self._lock:
            periods = self._blackout_calendar.get(clean_ticker, [])

        for start_dt, end_dt in periods:
            if start_dt <= target_date <= end_dt:
                res = ComplianceResult(
                    action=ComplianceAction.BLOCK.value,
                    violation=True,
                    reason=(
                        f"SPK II-15.1 Sessiz Dönem (Blackout Period) Engeli: "
                        f"{clean_ticker} için {start_dt} - {end_dt} arası işlem yapılamaz."
                    ),
                    details={
                        "ticker": clean_ticker,
                        "date": target_date.isoformat(),
                        "period_start": start_dt.isoformat(),
                        "period_end": end_dt.isoformat(),
                    },
                )
                self._persist_audit(clean_ticker, "BLACKOUT_BLOCKED", res)
                return res

        res = ComplianceResult(
            action=ComplianceAction.OK.value,
            details={"ticker": clean_ticker, "date": target_date.isoformat()},
        )
        return res

    def export_audit_to_polars(self, limit: int = 1000) -> pl.DataFrame:
        """Kalıcı denetim izini sıfır kopyalı Polars DataFrame olarak dışa aktarır (GEMINI.md Kural 2).

        Args:
            limit: Getirilecek maksimum kayıt adedi.

        Returns:
            pl.DataFrame: Denetim kayıtları tablosu.
        """
        return self.query_audit_duckdb(limit=limit)

    def query_audit_duckdb(
        self,
        ticker: str | None = None,
        check_type: str | None = None,
        limit: int = 1000,
    ) -> pl.DataFrame:
        """DuckDB'de saklanan denetim kayıtlarını filtrelenmiş Polars DataFrame olarak döner.

        Args:
            ticker: İsteğe bağlı hisse senedi filtresi.
            check_type: İsteğe bağlı denetim tipi filtresi.
            limit: Maksimum döndürülecek satır sayısı.

        Returns:
            pl.DataFrame: Sorgu sonucu tablosu.
        """
        empty_schema = {
            "id": pl.Int64,
            "timestamp": pl.Datetime("us", "UTC"),
            "ticker": pl.Utf8,
            "check_type": pl.Utf8,
            "action": pl.Utf8,
            "notification_required": pl.Boolean,
            "violation": pl.Boolean,
            "reason": pl.Utf8,
            "details_json": pl.Utf8,
        }

        if self._conn is None:
            return pl.DataFrame(schema=empty_schema)

        with self._lock:
            try:
                query = """
                    SELECT id, timestamp, ticker, check_type, action,
                           notification_required, violation, reason, details_json
                    FROM compliance_audit_log
                """
                params: list[Any] = []
                conditions: list[str] = []

                if ticker:
                    conditions.append("ticker = ?")
                    params.append(ticker.strip().upper())
                if check_type:
                    conditions.append("check_type = ?")
                    params.append(check_type.strip())

                if conditions:
                    query += " WHERE " + " AND ".join(conditions)

                query += " ORDER BY id DESC LIMIT ?"
                params.append(max(1, limit))

                arrow_table = self._conn.execute(query, params).arrow()
                return pl.from_arrow(arrow_table)  # type: ignore[return-value]
            except Exception as exc:
                logger.error("compliance_audit_duckdb_sorgu_hatasi", error=str(exc))
                return pl.DataFrame(schema=empty_schema)

    def __repr__(self) -> str:
        """Motorun okunabilir durum temsilini döndürür."""
        return (
            f"ComplianceChecker(db_path={self._db_path!r}, "
            f"conn_active={self._conn is not None})"
        )


# Global tekil nesne (Singleton)
compliance_checker: Final[ComplianceChecker] = ComplianceChecker()


# ==============================================================================
# MODÜL SEVİYESİNDE KOLAYLIK FONKSİYONLARI (CONVENIENCE HELPERS)
# ==============================================================================

def check_spk_compliance(
    action: str,
    ticker: str,
    amount: float,
    portfolio_value: float,
    current_position_pct: float = 0.0,
    company_capital: float | None = None,
    is_fund: bool = False,
) -> ComplianceResult:
    """Modül seviyesinde doğrudan SPK ve BIST mevzuatı uyumluluk denetimi.

    Args:
        action: İşlem yönü ("BUY", "SELL", "HOLD").
        ticker: İlgili pay kodu.
        amount: İşlem parasal tutarı (TRY).
        portfolio_value: Toplam portföy net aktif değeri (TRY).
        current_position_pct: Mevcut pozisyon oranı (0.0 - 1.0).
        company_capital: İsteğe bağlı şirketin ödenmiş sermayesi (TRY).
        is_fund: İşlemi yapan tarafın Yatırım Fonu olup olmadığı.

    Returns:
        ComplianceResult: Denetim kararı.
    """
    return compliance_checker.check_spk_compliance(
        action=action,
        ticker=ticker,
        amount=amount,
        portfolio_value=portfolio_value,
        current_position_pct=current_position_pct,
        company_capital=company_capital,
        is_fund=is_fund,
    )


def check_algo_trading_notification(
    daily_order_count: int,
    daily_volume_pct: float,
) -> ComplianceResult:
    """Modül seviyesinde algoritmik ve HFT işlem bildirim denetimi.

    Args:
        daily_order_count: Günlük iletilen emir sayısı.
        daily_volume_pct: Günlük piyasa hacim payı (0.0 - 1.0).

    Returns:
        ComplianceResult: Bildirim kararı.
    """
    return compliance_checker.check_algo_trading_notification(
        daily_order_count=daily_order_count,
        daily_volume_pct=daily_volume_pct,
    )


def check_order_to_trade_ratio(
    order_count: int,
    trade_count: int,
    max_otr: float = DEFAULT_MAX_OTR_THRESHOLD,
    ticker: str = "SYS",
) -> ComplianceResult:
    """Modül seviyesinde BIST Emir / İşlem Oranı (OTR) denetimi.

    Args:
        order_count: Toplam emir sayısı.
        trade_count: Gerçekleşen işlem sayısı.
        max_otr: Müsaade edilen maksimum OTR eşiği.
        ticker: İlgili pay kodu.

    Returns:
        ComplianceResult: OTR denetim kararı.
    """
    return compliance_checker.check_order_to_trade_ratio(
        order_count=order_count,
        trade_count=trade_count,
        max_otr=max_otr,
        ticker=ticker,
    )


def check_short_sale_uptick(
    ticker: str,
    order_price: float,
    last_price: float,
    prev_price: float,
    is_short_sale: bool = True,
) -> ComplianceResult:
    """Modül seviyesinde BIST Açığa Satış Yukarı Adım Kuralı (Up-tick Rule) denetimi.

    Args:
        ticker: Pay kodu.
        order_price: İletilmek istenen emir fiyatı.
        last_price: Son gerçekleşen işlem fiyatı.
        prev_price: Önceki işlem fiyatı.
        is_short_sale: Emrin açığa satış emri olup olmadığı.

    Returns:
        ComplianceResult: Yukarı adım izin kararı.
    """
    return compliance_checker.check_short_sale_uptick(
        ticker=ticker,
        order_price=order_price,
        last_price=last_price,
        prev_price=prev_price,
        is_short_sale=is_short_sale,
    )


def register_blackout_period(
    ticker: str,
    start_date: date,
    end_date: date,
) -> None:
    """Modül seviyesinde sessiz dönem (blackout period) kaydeder.

    Args:
        ticker: Pay kodu.
        start_date: Başlangıç tarihi.
        end_date: Bitiş tarihi.
    """
    compliance_checker.register_blackout_period(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
    )


def check_insider_trading_window(
    ticker: str,
    check_date: date | None = None,
) -> ComplianceResult:
    """Modül seviyesinde içeriden bilgi ticareti sessiz dönem denetimi.

    Args:
        ticker: Pay kodu.
        check_date: Denetlenecek tarih.

    Returns:
        ComplianceResult: Denetim kararı.
    """
    return compliance_checker.check_insider_trading_window(
        ticker=ticker,
        check_date=check_date,
    )


def export_compliance_audit_to_polars(limit: int = 1000) -> pl.DataFrame:
    """Modül seviyesinde denetim günlüğünü Polars DataFrame olarak dışa aktarır.

    Args:
        limit: Maksimum satır sayısı.

    Returns:
        pl.DataFrame: Denetim verileri.
    """
    return compliance_checker.export_audit_to_polars(limit=limit)


def query_compliance_audit_duckdb(
    ticker: str | None = None,
    check_type: str | None = None,
    limit: int = 1000,
) -> pl.DataFrame:
    """Modül seviyesinde filtrelenmiş denetim verilerini DuckDB'den sorgular.

    Args:
        ticker: İsteğe bağlı pay kodu.
        check_type: İsteğe bağlı denetim türü.
        limit: Maksimum satır sayısı.

    Returns:
        pl.DataFrame: Filtrelenmiş denetim tablosu.
    """
    return compliance_checker.query_audit_duckdb(
        ticker=ticker,
        check_type=check_type,
        limit=limit,
    )


__all__: Final[list[str]] = [
    "DEFAULT_ALGO_ORDER_THRESHOLD",
    "DEFAULT_ALGO_VOLUME_THRESHOLD",
    "DEFAULT_COMPLIANCE_DB_PATH",
    "DEFAULT_MAX_OTR_THRESHOLD",
    "DEFAULT_MIN_OTR_EVALUATION_ORDERS",
    "DEFAULT_PORTFOLIO_CONCENTRATION_LIMIT",
    "DEFAULT_UPTICK_RULE_ACTIVE",
    "MANDATORY_TENDER_OFFER_THRESHOLD",
    "SPK_SHARE_NOTIFICATION_THRESHOLDS",
    "ComplianceAction",
    "ComplianceChecker",
    "ComplianceResult",
    "check_algo_trading_notification",
    "check_insider_trading_window",
    "check_order_to_trade_ratio",
    "check_short_sale_uptick",
    "check_spk_compliance",
    "compliance_checker",
    "export_compliance_audit_to_polars",
    "query_compliance_audit_duckdb",
    "register_blackout_period",
]
