"""Evidence backed company relationship graph foundation."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class EntityRelation:
    """Şirket ve varlıklar arası kanıtlı ilişki modeli."""
    source: str
    relation: str
    target: str
    effective_at: datetime
    evidence_id: str

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return f"EntityRelation({self.source!r} --{self.relation}--> {self.target!r})"

    def __post_init__(self) -> None:
        """İlişki zaman damgası ve kanıt kimliği doğrulaması yapar."""
        if not self.evidence_id:
            raise ValueError("relations require evidence")
        if self.effective_at.tzinfo is None:
            raise ValueError("effective_at must be timezone aware")


class EntityGraph:
    """Kanıt destekli şirket ilişkileri çizge modeli."""

    def __init__(self) -> None:
        """İlişkiler kümesini ilklendirir."""
        self._relations: set[EntityRelation] = set()

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return f"EntityGraph(relations_count={len(self._relations)})"

    def add(self, relation: EntityRelation) -> None:
        """Çizgeye yeni bir ilişki ekler."""
        self._relations.add(relation)

    def relations_at(self, entity: str, as_of: datetime) -> tuple[EntityRelation, ...]:
        """Belirtilen varlığa ait ve geçerlilik tarihi geçmiş ilişkileri döndürür."""
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone aware")
        return tuple(
            item
            for item in self._relations
            if item.effective_at <= as_of and (item.source == entity or item.target == entity)
        )
