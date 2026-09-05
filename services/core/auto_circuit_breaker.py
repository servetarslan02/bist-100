"""ALPHA BIST — Otomatik Devre Kesici Tetikleme Motoru (Auto Circuit Breaker Engine).

Bu modül, Borsa İstanbul (BIST) pay piyasası ve endeks devre kesici kurallarını
gerçek zamanlı fiyat akışları üzerinde otomatik olarak denetler ve tetikler:
- Pay bazında devre kesici (Pazar bazlı dinamik eşikler: Yıldız Pazar, Ana Pazar, Alt Pazar)
- Endekse Bağlı Devre Kesici Sistemi (EBDKS: BIST-100 endeksi düşüş eşiği ve ardışık seviyeler)
- Günlük tetikleme ve seans durumu takip döngüsü
- Eşzamanlı (thread-safe) olay kuyruğu ve durum raporlaması

Referans: Borsa İstanbul Pay Piyasası Prosedürü ve Ağustos 2025 Düzenlemeleri.
"""

from __future__ import annotations

import functools
import math
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

import structlog
from opentelemetry import trace

from services.core.market_session_fsm import BISTMarketPhase, bist_session_fsm

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.auto_circuit_breaker")

DEFAULT_EVENT_QUEUE_MAXLEN: int = 1000

F = TypeVar("F", bound=Callable[..., Any])


def otel_trace(span_name: str) -> Callable[[F], F]:
    """Bir metodu OpenTelemetry span içine alan dekoratör.

    Args:
        span_name: Oluşturulacak span'in açıklayıcı adı.

    Returns:
        Dekore edilmiş fonksiyon/metot sarmalayıcısı.
    """

    def decorator(func: F) -> F:
        """Hedef fonksiyonu OTel span ile sarmalar."""

        @functools.wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            """Span bağlamı altında fonksiyonu yürütür."""
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


@dataclass
class CircuitBreakerEvent:
    """Devre kesici tetikleme olayı veri modeli."""

    ticker: str
    event_type: str  # "PAY_BAZINDA" | "EBDKS"
    trigger_price: float
    reference_price: float
    change_pct: float
    threshold_pct: float
    triggered_at: datetime
    duration_minutes: int
    feature_code: str | None = None
    market_phase: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Olay verilerini serileştirilebilir sözlük biçimine dönüştürür.

        Returns:
            Devre kesici olayına ait alanları içeren sözlük.
        """
        return {
            "ticker": self.ticker,
            "event_type": self.event_type,
            "trigger_price": self.trigger_price,
            "reference_price": self.reference_price,
            "change_pct": round(self.change_pct, 2),
            "threshold_pct": self.threshold_pct,
            "triggered_at": self.triggered_at.isoformat(),
            "duration_minutes": self.duration_minutes,
            "feature_code": self.feature_code,
            "market_phase": self.market_phase,
        }

    def __repr__(self) -> str:
        """Devre kesici olayının okunabilir temsilini döner."""
        return (
            f"<CircuitBreakerEvent(ticker='{self.ticker}', tip='{self.event_type}', "
            f"degisim=%{self.change_pct:.2f}, esik=%{self.threshold_pct:.2f})>"
        )


class AutoCircuitBreakerEngine:
    """Otomatik devre kesici tetikleme ve takip motoru.

    Her fiyat güncellemesinde:
    1. Pay bazında devre kesici eşiklerini kontrol eder.
    2. BIST-100 endeks değişimini izler (EBDKS).
    3. Eşik aşıldığında BIST Seans FSM üzerinden otomatik tetikler.
    """

    def __init__(self, queue_limit: int = DEFAULT_EVENT_QUEUE_MAXLEN) -> None:
        """Devre kesici motorunu başlatır.

        Args:
            queue_limit: Olay kuyruğunda saklanacak maksimum olay adedi.
        """
        self._lock: threading.Lock = threading.Lock()
        self._events: deque[CircuitBreakerEvent] = deque(maxlen=queue_limit)
        self._triggered_today: dict[str, list[float]] = {}  # ticker -> [threshold_pct, ...]
        self._bist100_reference: float = 0.0  # Önceki gün kapanış değeri
        self._bist100_current: float = 0.0
        self._ebdks_triggered_today: int = 0

    def set_bist100_reference(self, reference_price: float) -> None:
        """BIST-100 referans fiyatını (önceki gün kapanışı) belirler.

        Args:
            reference_price: Pozitif BIST-100 baz referans fiyatı.
        """
        if reference_price <= 0 or math.isnan(reference_price) or math.isinf(reference_price):
            logger.warning("gecersiz_bist100_referans_fiyati", referans=reference_price)
            return

        with self._lock:
            self._bist100_reference = reference_price

    @otel_trace("auto_circuit_breaker.update_bist100_price")
    def update_bist100_price(self, current_price: float) -> CircuitBreakerEvent | None:
        """BIST-100 güncel endeks değerini günceller ve EBDKS eşik kontrolü yapar.

        Args:
            current_price: Güncel BIST-100 endeks değeri.

        Returns:
            Eşik aşılıp EBDKS tetiklenirse CircuitBreakerEvent, aksi halde None.
        """
        if current_price <= 0 or math.isnan(current_price) or math.isinf(current_price):
            return None

        with self._lock:
            self._bist100_current = current_price
            ref_price = self._bist100_reference
            triggered_count = self._ebdks_triggered_today

        if ref_price <= 0:
            return None

        # Piyasa açık değilse kontrol etme
        phase = bist_session_fsm.get_phase()
        if phase == BISTMarketPhase.CLOSED:
            return None

        change_pct = ((current_price / ref_price) - 1.0) * 100.0

        # EBDKS: BIST-100 %6 veya daha fazla düşüş
        threshold_pct = bist_session_fsm.EBDKS_THRESHOLD_PCT
        if change_pct <= -threshold_pct:
            # Bugün zaten tetiklendi mi kontrol et (ilk tetikleme veya ek %2 düşüş)
            should_trigger = False
            if triggered_count == 0:
                should_trigger = True
            elif triggered_count > 0 and change_pct <= -(threshold_pct + (triggered_count * 2.0)):
                should_trigger = True

            if should_trigger:
                feature_code: str | None = None
                bist_session_fsm.trigger_ebdks(feature_code=feature_code)

                event = CircuitBreakerEvent(
                    ticker="BIST-100",
                    event_type="EBDKS",
                    trigger_price=current_price,
                    reference_price=ref_price,
                    change_pct=change_pct,
                    threshold_pct=threshold_pct,
                    triggered_at=bist_session_fsm.now_istanbul(),
                    duration_minutes=bist_session_fsm.EBDKS_DEFAULT_DURATION,
                    feature_code=feature_code,
                    market_phase=phase.value,
                )

                with self._lock:
                    self._events.append(event)
                    self._ebdks_triggered_today += 1
                    current_count = self._ebdks_triggered_today

                logger.warning(
                    "ebdks_otomatik_tetiklendi",
                    degisim_yuzdesi=f"{change_pct:.2f}%",
                    esik=f"%{threshold_pct}",
                    guncel_fiyat=current_price,
                    referans_fiyat=ref_price,
                    gunluk_tetiklenme_sayisi=current_count,
                )
                return event

        return None

    @otel_trace("auto_circuit_breaker.check_pay_circuit_breaker")
    def check_pay_circuit_breaker(
        self,
        ticker: str,
        current_price: float,
        reference_price: float,
        market_type: str = "ana",
    ) -> CircuitBreakerEvent | None:
        """Hisse payı bazında devre kesici tetikleme kontrolü gerçekleştirir.

        Args:
            ticker: BIST hisse kodu (örn. 'EREGL').
            current_price: Güncel işlem fiyatı.
            reference_price: İlgili hissenin baz/kapanış referans fiyatı.
            market_type: Pazar segmenti ('yildiz', 'ana', 'alt').

        Returns:
            Eşik aşılıp devre kesici devreye girerse CircuitBreakerEvent, aksi halde None.
        """
        if reference_price <= 0 or current_price <= 0:
            return None
        if math.isnan(current_price) or math.isnan(reference_price):
            return None
        if math.isinf(current_price) or math.isinf(reference_price):
            return None

        # Piyasa kapalıysa devre kesici tetiklenmez
        phase = bist_session_fsm.get_phase()
        if phase == BISTMarketPhase.CLOSED:
            return None

        change_pct = ((current_price / reference_price) - 1.0) * 100.0

        # Pazar bazında eşikleri al
        thresholds = bist_session_fsm.CIRCUIT_BREAKER_THRESHOLDS.get(
            market_type, bist_session_fsm.CIRCUIT_BREAKER_THRESHOLDS["ana"]
        )

        with self._lock:
            triggered_thresholds = list(self._triggered_today.get(ticker, []))

        for threshold in thresholds:
            if change_pct <= -threshold and threshold not in triggered_thresholds:
                # FSM üzerinde hisse devre kesicisini tetikle
                bist_session_fsm.trigger_circuit_breaker(ticker)

                event = CircuitBreakerEvent(
                    ticker=ticker,
                    event_type="PAY_BAZINDA",
                    trigger_price=current_price,
                    reference_price=reference_price,
                    change_pct=change_pct,
                    threshold_pct=threshold,
                    triggered_at=bist_session_fsm.now_istanbul(),
                    duration_minutes=bist_session_fsm.CIRCUIT_BREAKER_DURATION_MINUTES,
                    market_phase=phase.value,
                )

                with self._lock:
                    self._events.append(event)
                    if ticker not in self._triggered_today:
                        self._triggered_today[ticker] = []
                    self._triggered_today[ticker].append(threshold)

                logger.warning(
                    "pay_devre_kesici_tetiklendi",
                    ticker=ticker,
                    degisim_yuzdesi=f"{change_pct:.2f}%",
                    esik=f"%{threshold}",
                    guncel_fiyat=current_price,
                    referans_fiyat=reference_price,
                    pazar_tipi=market_type,
                )
                return event

        return None

    def reset_daily(self) -> None:
        """Günlük tetikleme sayaçlarını ve EBDKS durumunu sıfırlar (seans sonu çağrılır)."""
        with self._lock:
            self._triggered_today.clear()
            self._ebdks_triggered_today = 0
            bist_session_fsm.clear_ebdks()

        logger.info("devre_kesici_gunluk_sayaclari_sifirlandi")

    def get_events_today(self) -> list[dict[str, Any]]:
        """Günün gerçekleşen tüm devre kesici olaylarını sözlük listesi olarak döner.

        Returns:
            Olayların sözlük listesi.
        """
        with self._lock:
            events = list(self._events)
        return [e.to_dict() for e in events]

    def get_status(self) -> dict[str, Any]:
        """Devre kesici motorunun anlık durum özetini döner.

        Returns:
            EBDKS ve hisse devre kesici metriklerini içeren durum sözlüğü.
        """
        with self._lock:
            ref = self._bist100_reference
            curr = self._bist100_current
            change = round(((curr / ref) - 1.0) * 100.0, 2) if ref > 0 and curr > 0 and not math.isnan(curr) else 0.0
            return {
                "ebdks_triggered_today": self._ebdks_triggered_today,
                "bist100_reference": ref,
                "bist100_current": curr,
                "bist100_change_pct": change,
                "pay_circuit_breakers_today": len(self._triggered_today),
                "total_events_today": len(self._events),
                "ebdks_active": bist_session_fsm.is_ebdks_active(),
                "ebdks_late_session": bist_session_fsm.is_ebdks_late_session(),
            }

    def __repr__(self) -> str:
        """Devre kesici motorunun durum temsilini döner."""
        with self._lock:
            return (
                f"<AutoCircuitBreakerEngine(ebdks_tetiklenme={self._ebdks_triggered_today}, "
                f"hisse_sayisi={len(self._triggered_today)}, toplam_olay={len(self._events)})>"
            )


# Singleton örneği
auto_circuit_breaker = AutoCircuitBreakerEngine()

__all__ = [
    "DEFAULT_EVENT_QUEUE_MAXLEN",
    "AutoCircuitBreakerEngine",
    "CircuitBreakerEvent",
    "auto_circuit_breaker",
    "otel_trace",
]
