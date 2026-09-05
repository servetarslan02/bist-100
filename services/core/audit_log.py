"""ALPHA BIST — Denetim Kaydı ve Karar İzlenebilirliği (Audit Log) Modülü.

Bu modül, sistem genelindeki tüm kritik kararların, risk kontrollerinin, emir/dolum olaylarının
ve durum değişikliklerinin değişmez (immutable) ve denetlenebilir bir zaman serisi günlüğünü
(audit trail) tutar.

Özellikler:
- Karar silsilesi (lineage tracking: RAW_DATA -> FEATURE -> SIGNAL -> DECISION -> RISK -> ORDER -> FILL)
- Çift indeksleme ile hisse bazlı emir ve dolumların tam silsile takibi
- Bellek içi halka tamponu (ring buffer) ve sınırlı indeks boyutuyla bellek sızıntısı koruması
- DuckDB ve orjson entegrasyonu ile SPK denetim izi kalıcılığı
- OpenTelemetry span izleme ve thread-safe eşzamanlılık koruması
"""

from __future__ import annotations

import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import duckdb
import orjson
import structlog
from opentelemetry import metrics, trace

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.audit_log")
meter = metrics.get_meter("alpha-bist.audit_log")

DEFAULT_MAX_ENTRIES: int = 5000
DEFAULT_ENTITY_INDEX_LIMIT: int = 500
MAX_INDEXED_ENTITIES: int = 1000


@dataclass(slots=True)
class AuditEntry:
    """Değişmez (immutable) denetim kaydı veri modeli."""

    audit_id: str
    action: str  # DECISION, RISK_CHECK, ORDER, FILL, STATE_CHANGE, CONFIG_CHANGE
    entity_type: str  # ticker, portfolio, order, fill, model, config
    entity_id: str
    actor: str  # system, decision_engine, risk_engine, user, order_service
    details: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str = ""
    parent_audit_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Denetim kaydını sözlük biçimine dönüştürür.

        Returns:
            dict[str, Any]: Serileştirilebilir anahtar-değer sözlüğü.
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
            f"AuditEntry(id={self.audit_id!r}, aksiyon={self.action!r}, "
            f"varlik={self.entity_type + ':' + self.entity_id!r}, aktor={self.actor!r})"
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

    def _prune_index_if_needed(self) -> None:
        """İndeks sözlüğü kapasiteyi aştığında boşalmış veya en eski anahtarları temizler."""
        if len(self._index) > MAX_INDEXED_ENTITIES:
            keys_to_remove = [k for k, v in self._index.items() if len(v) == 0]
            for k in keys_to_remove:
                del self._index[k]
            # Hala fazlaysa en eski anahtarların bir kısmını düşür
            if len(self._index) > MAX_INDEXED_ENTITIES:
                overflow_keys = list(self._index.keys())[: len(self._index) - MAX_INDEXED_ENTITIES]
                for k in overflow_keys:
                    del self._index[k]

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

        # Emir ve dolum kayıtları için ikincil hisse indeksi (Lineage onarımı)
        secondary_key: str | None = None
        if entry.entity_type in {"order", "fill"} and isinstance(entry.details, dict):
            rel_ticker = entry.details.get("ticker")
            if rel_ticker:
                secondary_key = f"ticker:{rel_ticker}"

        with self._lock:
            self._entries.append(entry)

            if key not in self._index:
                self._index[key] = deque(maxlen=self._entity_limit)
            self._index[key].append(entry)

            if secondary_key:
                if secondary_key not in self._index:
                    self._index[secondary_key] = deque(maxlen=self._entity_limit)
                self._index[secondary_key].append(entry)

            self._prune_index_if_needed()

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
            list[dict[str, Any]]: Varlığa ait denetim kayıtları sözlük listesi.
        """
        key = f"{entity_type}:{entity_id}"
        with self._lock:
            entries = list(self._index.get(key, []))
        return [entry.to_dict() for entry in entries]

    def get_decision_lineage(self, ticker: str) -> list[dict[str, Any]]:
        """Bir hisse sembolü için tam karar silsilesini mantıksal ve kronolojik sırada getirir.

        Sıralama: RAW_DATA -> FEATURE -> SIGNAL -> DECISION -> RISK_CHECK -> ORDER -> FILL

        Args:
            ticker: BIST hisse sembolü.

        Returns:
            list[dict[str, Any]]: Mantıksal aşama önceliğine göre sıralanmış denetim kayıtları.
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
        history.sort(
            key=lambda x: (
                x.get("correlation_id", ""),
                action_order.get(x.get("action", ""), 99),
                x.get("timestamp", ""),
            )
        )
        return history

    def get_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Sistem genelindeki en güncel denetim kayıtlarını döner.

        Args:
            limit: Döndürülecek maksimum kayıt sayısı (varsayılan: 50).

        Returns:
            list[dict[str, Any]]: Yeniden eskiye doğru sıralı denetim kayıtları özeti.
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
                "details": e.details,
            }
            for e in reversed(recent_entries)
        ]

    def get_stats(self) -> dict[str, Any]:
        """Denetim kaydı sistem istatistiklerini hesaplar.

        Returns:
            dict[str, Any]: Toplam kayıt sayısı, aksiyon dağılımı ve takip edilen varlık sayısı.
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

    def export_to_duckdb(self, db_path: str = "data/audit.duckdb") -> int:
        """Mevcut denetim kayıtlarını DuckDB tablosuna kalıcı olarak yazar.

        Args:
            db_path: Hedef DuckDB dosya yolu.

        Returns:
            int: Veritabanına aktarılan kayıt sayısı.
        """
        with self._lock:
            entries = list(self._entries)

        if not entries:
            return 0

        conn = duckdb.connect(database=db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_trail (
                    audit_id VARCHAR PRIMARY KEY,
                    action VARCHAR NOT NULL,
                    entity_type VARCHAR NOT NULL,
                    entity_id VARCHAR NOT NULL,
                    actor VARCHAR NOT NULL,
                    details_json VARCHAR,
                    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                    correlation_id VARCHAR,
                    parent_audit_id VARCHAR
                );
                """
            )
            for e in entries:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO audit_trail VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    [
                        e.audit_id,
                        e.action,
                        e.entity_type,
                        e.entity_id,
                        e.actor,
                        orjson.dumps(e.details).decode("utf-8"),
                        e.timestamp,
                        e.correlation_id,
                        e.parent_audit_id,
                    ],
                )
            logger.info("audit_log_duckdb_aktarildi", adet=len(entries), db_path=db_path)
            return len(entries)
        finally:
            conn.close()

    def clear(self) -> None:
        """Test amaçlı tüm bellek içi denetim kayıtlarını ve indekslerini sıfırlar."""
        with self._lock:
            self._entries.clear()
            self._index.clear()

    def _generate_id(self) -> str:
        """Benzersiz ve güvenli tekil denetim kimliği üretir.

        Returns:
            str: 16 karakterlik onaltılık tekil kimlik dizesi.
        """
        return uuid.uuid4().hex[:16]

    def __repr__(self) -> str:
        """Denetim yöneticisinin durum temsilini döner."""
        with self._lock:
            return (
                f"AuditLog(toplam_kayit={len(self._entries)}, "
                f"takip_edilen_varlik={len(self._index)}, max_kapasite={self._max_entries})"
            )


# Singleton örneği
audit_log = AuditLog()

__all__ = [
    "DEFAULT_ENTITY_INDEX_LIMIT",
    "DEFAULT_MAX_ENTRIES",
    "MAX_INDEXED_ENTITIES",
    "AuditEntry",
    "AuditLog",
    "audit_log",
    "otel_trace",
]

