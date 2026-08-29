"""Evidence backed company relationship graph foundation."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class EntityRelation:
    """Otomatik eklendi."""
    source: str
    relation: str
    target: str
    effective_at: datetime
    evidence_id: str

    def __post_init__(self) -> None:
        """Otomatik eklendi."""
        if not self.evidence_id:
            raise ValueError("relations require evidence")
        if self.effective_at.tzinfo is None:
            raise ValueError("effective_at must be timezone aware")


class EntityGraph:
    """Otomatik eklendi."""
    def __init__(self) -> None:
        """Otomatik eklendi."""
        self._relations: set[EntityRelation] = set()

    def add(self, relation: EntityRelation) -> None:
        """Otomatik eklendi."""
        self._relations.add(relation)

    def relations_at(self, entity: str, as_of: datetime) -> tuple[EntityRelation, ...]:
        """Otomatik eklendi."""
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone aware")
        return tuple(
            item
            for item in self._relations
            if item.effective_at <= as_of and (item.source == entity or item.target == entity)
        )
