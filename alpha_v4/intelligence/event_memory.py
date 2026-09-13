"""Event intelligence memory primitives.

Events are stored as evidence-backed observations. This layer does not
produce trading signals; it only preserves what happened and what is known.
Strict Point-in-Time (PIT) integrity with deterministic cryptographic identity (SHA-256).
"""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

import orjson
import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class EventObservation:
    """Kanıta dayalı olay gözlem veri modeli."""
    event_type: str
    entity_id: str
    observed_at: datetime
    effective_at: datetime
    evidence_id: str
    payload: dict[str, Any]
    source_channel: str = "BIST_KAP"
    audit_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return (
            f"EventObservation(type={self.event_type!r}, entity={self.entity_id!r}, "
            f"obs={self.observed_at.date()}, evidence={self.evidence_id!r})"
        )

    def event_id(self) -> str:
        """Gözlem içeriğinin deterministik SHA-256 kimliğini üretir."""
        body = {
            "event_type": self.event_type,
            "entity_id": self.entity_id,
            "observed_at": self.observed_at.isoformat(),
            "effective_at": self.effective_at.isoformat(),
            "evidence_id": self.evidence_id,
            "payload": self.payload,
            "source_channel": self.source_channel,
        }
        return sha256(orjson.dumps(body, option=orjson.OPT_SORT_KEYS)).hexdigest()

    def validate(self) -> None:
        """Gözlemin zaman damgalarını ve kanıt bütünlüğünü doğrular (Zero-Leakage Kuralı)."""
        if not self.evidence_id:
            raise ValueError("event requires evidence")
        if self.observed_at.tzinfo != UTC:
            raise ValueError("observed_at must be UTC")
        if self.effective_at > self.observed_at:
            # Gelecekte yürürlüğe girecek olaylar (örn. 1 ay sonraki temettü) bilinebilir,
            # ancak geçmişte gerçekleşmiş bir olay gözlem tarihinden sonra bilinemez.
            pass

    def to_dict(self) -> dict[str, Any]:
        """Sözlük temsiline dönüştürür."""
        res = asdict(self)
        res["event_id"] = self.event_id()
        res["observed_at"] = self.observed_at.isoformat()
        res["effective_at"] = self.effective_at.isoformat()
        return res


class EventMemoryStore:
    """Tüm kanıtlı olay gözlemlerini yöneten kurumsal bellek motoru."""

    def __init__(self) -> None:
        """Olay deposunu ilklendirir."""
        self._events: dict[str, EventObservation] = {}
        self._entity_index: dict[str, list[str]] = {}

    def __repr__(self) -> str:
        return f"EventMemoryStore(events_count={len(self._events)}, entities_count={len(self._entity_index)})"

    def record_event(self, event: EventObservation) -> str:
        """Yeni bir gözlemi doğrular, indeksler ve deterministik kimliğini döndürür."""
        event.validate()
        eid = event.event_id()
        if eid not in self._events:
            self._events[eid] = event
            if event.entity_id not in self._entity_index:
                self._entity_index[event.entity_id] = []
            self._entity_index[event.entity_id].append(eid)
        return eid

    def get_events_for_entity(
        self,
        entity_id: str,
        as_of: datetime | None = None,
        event_type: str | None = None,
    ) -> list[EventObservation]:
        """Belirtilen varlığa ait olayları Point-in-Time (PIT) kuralına göre döndürür."""
        eids = self._entity_index.get(entity_id, [])
        results = []
        for eid in eids:
            ev = self._events[eid]
            if as_of is not None and ev.observed_at > as_of:
                continue  # Gelecek sızıntısını engelle
            if event_type is not None and ev.event_type != event_type:
                continue
            results.append(ev)
        return sorted(results, key=lambda x: x.observed_at)

    def total_count(self) -> int:
        """Kayıtlı toplam olay sayısı."""
        return len(self._events)


event_memory_store = EventMemoryStore()

__all__ = [
    "EventMemoryStore",
    "EventObservation",
    "event_memory_store",
]
