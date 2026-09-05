"""ALPHA BIST — Denetim Kaydı ve Karar İzlenebilirliği (Audit Log) Modülü.

Bu modül, sistem genelindeki tüm kritik kararların, risk kontrollerinin, emir/dolum olaylarının
ve durum değişikliklerinin değişmez (immutable) ve denetlenebilir bir zaman serisi günlüğünü
(audit trail) tutar.

Özellikler:
- Karar silsilesi (lineage tracking: RAW_DATA -> FEATURE -> SIGNAL -> DECISION -> RISK -> ORDER -> FILL)
- Risk motoru onay ve red kontrolleri
- BIST emir ve dolum yaşam döngüsü
- Sistem ve yapılandırma durumu değişimleri
- Eşzamanlı (thread-safe) bellek içi halka tamponu (ring buffer) ve varlık indeksi
"""

from __future__ import annotations

import functools
import threading
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

import structlog
from opentelemetry import metrics, trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.audit_log")
meter = metrics.get_meter("alpha-bist.audit_log")

DEFAULT_MAX_ENTRIES: int = 5000
DEFAULT_ENTITY_INDEX_LIMIT: int = 500

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
class AuditEntry:
    """Değişmez (immutable) denetim kaydı veri modeli."""

    audit_id: str
    action: str  # DECISION, RISK_CHECK, ORDER, FILL, STATE_CHANGE, CONFIG_CHANGE
    entity_type: str  # ticker, portfolio, order, model, config
    entity_id: str
    actor: str  # system, decision_engine, risk_engine, user
    details: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str = ""
    parent_audit_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Denetim kaydını sözlük biçimine dönüştürür.

        Returns:
            Serileştirilebilir anahtar-değer sözlüğü.
        """
        return {
            "audit_id": self.audit_id,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "actor": self.actor,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "parent_audit_id": self.parent_audit_id,
        }

    def __repr__(self) -> str:
        """Denetim kaydının açıklayıcı temsilini döner."""
        return (
            f"<AuditEntry(id='{self.audit_id}', aksiyon='{self.action}', "
            f"varlik='{self.entity_type}:{self.entity_id}', aktor='{self.actor}')>"
        )


class AuditLog:
    """Değişmez denetim kaydı yöneticisi (Audit Log).

    Sistemde alınan tüm kararların geriye dönük tam zincirini takip eder:
    RAW_DATA -> FEATURE -> SIGNAL -> DECISION -> RISK -> ORDER -> FILL
    """

    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        entity_limit: int = DEFAULT_ENTITY_INDEX_LIMIT,
    ) -> None:
        """Denetim kaydı yöneticisini başlatır.

        Args:
            max_entries: Sistem genelinde tutulacak maksimum denetim kaydı sayısı.
            entity_limit: Varlık başına tutulacak maksimum denetim kaydı sayısı.
        """
        self._max_entries: int = max_entries
        self._entity_limit: int = entity_limit
        self._lock: threading.Lock = threading.Lock()
        self._entries: deque[AuditEntry] = deque(maxlen=max_entries)
        self._index: dict[str, deque[AuditEntry]] = {}

    @otel_trace("audit_log.log")
    def log(self, entry: AuditEntry) -> None:
        """Denetim kaydı ekler (yalnızca sona ekleme / append-only).

        Args:
            entry: Kaydedilecek AuditEntry nesnesi.

        Raises:
            ValueError: entry geçerli bir AuditEntry değilse veya eksik alan içeriyorsa.
        """
        if not isinstance(entry, AuditEntry):
            raise ValueError("Kaydedilecek nesne AuditEntry tipinde olmalıdır.")
        if not entry.audit_id or not entry.action:
            raise ValueError("AuditEntry 'audit_id' ve 'action' alanları boş olamaz.")

        key = f"{entry.entity_type}:{entry.entity_id}"

        with self._lock:
            self._entries.append(entry)
            if key not in self._index:
                self._index[key] = deque(maxlen=self._entity_limit)
            self._index[key].append(entry)

        logger.debug(
            "denetim_kaydi_eklendi",
            aksiyon=entry.action,
            varlik=key,
            aktor=entry.actor,
            audit_id=entry.audit_id,
        )

    @otel_trace("audit_log.log_decision")
    def log_decision(
        self,
        ticker: str,
        action: str,
        direction: str,
        confidence: float,
        reasons: list[str],
        risks: list[str],
        correlation_id: str = "",
    ) -> None:
        """Model veya kural bazlı karar kaydını günlüğe ekler.

        Args:
            ticker: BIST hisse sembolü (örn. 'THYAO').
            action: Alınan karar türü (örn. 'BUY', 'SELL', 'HOLD').
            direction: Karar yönü ('LONG', 'SHORT', 'NEUTRAL').
            confidence: Güven skoru (0.0 - 1.0).
            reasons: Kararın arkasındaki gerekçeler listesi.
            risks: Tespit edilen risk unsurları listesi.
            correlation_id: İlişkili işlem korelasyon kimliği.
        """
        self.log(
            AuditEntry(
                audit_id=self._generate_id(),
                action="DECISION",
                entity_type="ticker",
                entity_id=ticker,
                actor="decision_engine",
                details={
                    "action": action,
                    "direction": direction,
                    "confidence": confidence,
                    "reasons": reasons,
                    "risks": risks,
                },
                correlation_id=correlation_id,
            )
        )

    @otel_trace("audit_log.log_risk_check")
    def log_risk_check(
        self,
        ticker: str,
        approved: bool,
        checks: list[dict[str, Any]],
        correlation_id: str = "",
    ) -> None:
        """Risk denetim motoru kontrol sonucunu kaydeder.

        Args:
            ticker: BIST hisse sembolü.
            approved: Risk kontrollerinden geçip geçmediği bilgisi.
            checks: Gerçekleştirilen risk parametre kontrolleri detayları.
            correlation_id: İlişkili işlem korelasyon kimliği.
        """
        self.log(
            AuditEntry(
                audit_id=self._generate_id(),
                action="RISK_CHECK",
                entity_type="ticker",
                entity_id=ticker,
                actor="risk_engine",
                details={
                    "approved": approved,
                    "checks": checks,
                },
                correlation_id=correlation_id,
            )
        )

    @otel_trace("audit_log.log_order")
    def log_order(
        self,
        order_id: str,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        order_type: str,
        correlation_id: str = "",
    ) -> None:
        """BIST emir iletimi kaydını günlüğe ekler.

        Args:
            order_id: Tekil BIST emir kimliği.
            ticker: BIST hisse sembolü.
            side: Emir yönü ('BUY' / 'SELL').
            quantity: Emir adedi.
            price: Emir fiyatı.
            order_type: Emir tipi ('LIMIT', 'MARKET', vb.).
            correlation_id: İlişkili işlem korelasyon kimliği.
        """
        self.log(
            AuditEntry(
                audit_id=self._generate_id(),
                action="ORDER",
                entity_type="order",
                entity_id=order_id,
                actor="order_service",
                details={
                    "ticker": ticker,
                    "side": side,
                    "quantity": quantity,
                    "price": price,
                    "order_type": order_type,
                },
                correlation_id=correlation_id,
            )
        )

    @otel_trace("audit_log.log_fill")
    def log_fill(
        self,
        fill_id: str,
        order_id: str,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        commission: float,
        correlation_id: str = "",
    ) -> None:
        """Emir dolum (fill) kaydını günlüğe ekler.

        Args:
            fill_id: Gerçekleşen dolum kimliği.
            order_id: İlgili BIST emir kimliği.
            ticker: BIST hisse sembolü.
            side: Dolum yönü ('BUY' / 'SELL').
            quantity: Gerçekleşen dolum adedi.
            price: Gerçekleşen dolum fiyatı.
            commission: Ödenen komisyon tutarı.
            correlation_id: İlişkili işlem korelasyon kimliği.
        """
        self.log(
            AuditEntry(
                audit_id=self._generate_id(),
                action="FILL",
                entity_type="fill",
                entity_id=fill_id,
                actor="execution_simulator",
                details={
                    "order_id": order_id,
                    "ticker": ticker,
                    "side": side,
                    "quantity": quantity,
                    "price": price,
                    "commission": commission,
                },
                correlation_id=correlation_id,
            )
        )

    @otel_trace("audit_log.log_state_change")
    def log_state_change(
        self,
        entity_type: str,
        entity_id: str,
        old_value: Any,
        new_value: Any,
        reason: str,
    ) -> None:
        """Sistem durum değişikliği kaydını günlüğe ekler.

        Args:
            entity_type: Varlık türü (örn. 'circuit_breaker', 'feed').
            entity_id: Varlık kimliği.
            old_value: Değişiklik öncesi durum değeri.
            new_value: Değişiklik sonrası yeni durum değeri.
            reason: Durum değişikliğinin gerekçesi.
        """
        self.log(
            AuditEntry(
                audit_id=self._generate_id(),
                action="STATE_CHANGE",
                entity_type=entity_type,
                entity_id=entity_id,
                actor="system",
                details={
                    "old": str(old_value),
                    "new": str(new_value),
                    "reason": reason,
                },
            )
        )

    @otel_trace("audit_log.log_config_change")
    def log_config_change(
        self,
        config_key: str,
        old_value: Any,
        new_value: Any,
        actor: str = "user",
    ) -> None:
        """Sistem yapılandırma parametresi değişim kaydını günlüğe ekler.

        Args:
            config_key: Değiştirilen parametrenin anahtar adı.
            old_value: Eski yapılandırma değeri.
            new_value: Yeni yapılandırma değeri.
            actor: Değişikliği gerçekleştiren aktör (varsayılan: 'user').
        """
        self.log(
            AuditEntry(
                audit_id=self._generate_id(),
                action="CONFIG_CHANGE",
                entity_type="config",
                entity_id=config_key,
                actor=actor,
                details={
                    "old": str(old_value),
                    "new": str(new_value),
                },
            )
        )

    def get_entity_history(
        self,
        entity_type: str,
        entity_id: str,
    ) -> list[dict[str, Any]]:
        """Belirli bir varlığın tüm denetim geçmişini getirir.

        Args:
            entity_type: Varlık türü (örn. 'ticker', 'order').
            entity_id: Varlık tekil kimliği.

        Returns:
            Varlığa ait denetim kayıtları sözlük listesi.
        """
        key = f"{entity_type}:{entity_id}"
        with self._lock:
            entries = list(self._index.get(key, []))
        return [entry.to_dict() for entry in entries]

    def get_decision_lineage(self, ticker: str) -> list[dict[str, Any]]:
        """Bir hisse sembolü için tam karar silsilesini mantıksal işlem sırasına göre getirir.

        Sıralama: RAW_DATA -> FEATURE -> SIGNAL -> DECISION -> RISK_CHECK -> ORDER -> FILL

        Args:
            ticker: BIST hisse sembolü.

        Returns:
            Mantıksal aşama önceliğine göre sıralanmış denetim kayıtları.
        """
        history = self.get_entity_history("ticker", ticker)

        action_order: dict[str, int] = {
            "RAW_DATA": 0,
            "FEATURE": 1,
            "SIGNAL": 2,
            "DECISION": 3,
            "RISK_CHECK": 4,
            "ORDER": 5,
            "FILL": 6,
        }
        history.sort(key=lambda x: action_order.get(x.get("action", ""), 99))
        return history

    def get_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Sistem genelindeki en güncel denetim kayıtlarını döner.

        Args:
            limit: Döndürülecek maksimum kayıt sayısı (varsayılan: 50).

        Returns:
            Yeniden eskiye doğru sıralı denetim kayıtları özeti.
        """
        with self._lock:
            recent_entries = list(self._entries)[-limit:]
        return [
            {
                "audit_id": e.audit_id,
                "action": e.action,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "actor": e.actor,
                "timestamp": e.timestamp.isoformat(),
            }
            for e in reversed(recent_entries)
        ]

    def get_stats(self) -> dict[str, Any]:
        """Denetim kaydı sistem istatistiklerini hesaplar.

        Returns:
            Toplam kayıt sayısı, aksiyon dağılımı ve takip edilen varlık sayısını içeren sözlük.
        """
        with self._lock:
            total_entries = len(self._entries)
            tracked_entities = len(self._index)
            action_counts: dict[str, int] = {}
            for e in self._entries:
                action_counts[e.action] = action_counts.get(e.action, 0) + 1

        return {
            "total_entries": total_entries,
            "action_counts": action_counts,
            "tracked_entities": tracked_entities,
        }

    def _generate_id(self) -> str:
        """Benzersiz ve güvenli tekil denetim kimliği üretir.

        Returns:
            16 karakterlik onaltılık tekil kimlik dizesi.
        """
        return uuid.uuid4().hex[:16]

    def __repr__(self) -> str:
        """Denetim yöneticisinin durum temsilini döner."""
        with self._lock:
            return (
                f"<AuditLog(toplam_kayit={len(self._entries)}, "
                f"takip_edilen_varlik={len(self._index)}, max_kapasite={self._max_entries})>"
            )


# Singleton örneği
audit_log = AuditLog()

__all__ = [
    "DEFAULT_ENTITY_INDEX_LIMIT",
    "DEFAULT_MAX_ENTRIES",
    "AuditEntry",
    "AuditLog",
    "audit_log",
    "otel_trace",
]
