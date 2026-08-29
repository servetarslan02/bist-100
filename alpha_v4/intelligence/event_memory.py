"""Event intelligence memory primitives.

Events are stored as evidence-backed observations. This layer does not
produce trading signals; it only preserves what happened and what is known.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

import orjson


@dataclass(frozen=True)
class EventObservation:
    """Otomatik eklendi."""
    event_type: str
    entity_id: str
    observed_at: datetime
    effective_at: datetime
    evidence_id: str
    payload: dict

    def event_id(self) -> str:
        """Otomatik eklendi."""
        body = {
            "event_type": self.event_type,
            "entity_id": self.entity_id,
            "observed_at": self.observed_at.isoformat(),
            "effective_at": self.effective_at.isoformat(),
            "evidence_id": self.evidence_id,
            "payload": self.payload,
        }
        return sha256(orjson.dumps(body, option=orjson.OPT_SORT_KEYS).decode()).hexdigest()

    def validate(self) -> None:
        """Otomatik eklendi."""
        if not self.evidence_id:
            raise ValueError("event requires evidence")
        if self.observed_at.tzinfo != UTC:
            raise ValueError("observed_at must be UTC")
        if self.effective_at > self.observed_at:
            raise ValueError("future information cannot be effective before observation")
