"""Evidence backed company relationship graph foundation.

Kurumsal Varlık İlişkileri ve Tedarik Zinciri / Holding Bağları Çizge Modeli:
- Point-in-Time (PIT) Varlık İlişkileri (Tedarikçi, Müşteri, İştirak, Ortak Girişim)
- Çok Dereceli Yayılma (Multi-Hop Propagation): Şok dalgalarının ilişkili şirketlere iletimi
- Kanıt Tabanlı İlişki Ağırlıkları (Edge Weights) ve Doğrulama
"""

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class EntityRelation:
    """Şirket ve varlıklar arası kanıtlı ilişki modeli."""
    source: str
    relation: str  # SUPPLIER_OF, SUBSIDIARY_OF, PARENT_OF, CUSTOMER_OF, COMPETITOR_OF
    target: str
    effective_at: datetime
    evidence_id: str
    weight: float = 1.0
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict, hash=False)

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return f"EntityRelation({self.source!r} --[{self.relation}:{self.weight:.2f}]--> {self.target!r})"

    def __post_init__(self) -> None:
        """İlişki zaman damgası ve kanıt kimliği doğrulaması yapar."""
        if not self.evidence_id:
            raise ValueError("relations require evidence")
        if self.effective_at.tzinfo is None:
            raise ValueError("effective_at must be timezone aware")

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        res = asdict(self)
        res["effective_at"] = self.effective_at.isoformat()
        return res


class EntityGraph:
    """Kanıt destekli şirket ilişkileri ve bulaşma (contagion) çizge motoru."""

    def __init__(self) -> None:
        """İlişkiler kümesini ve arama indeksini ilklendirir."""
        self._relations: set[EntityRelation] = set()
        self._adjacency: dict[str, list[EntityRelation]] = defaultdict(list)

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return f"EntityGraph(relations_count={len(self._relations)}, nodes_count={len(self._adjacency)})"

    def add(self, relation: EntityRelation) -> None:
        """Çizgeye yeni bir ilişki ekler."""
        if relation not in self._relations:
            self._relations.add(relation)
            self._adjacency[relation.source].append(relation)

    def relations_at(self, entity: str, as_of: datetime) -> tuple[EntityRelation, ...]:
        """Belirtilen varlığa ait ve geçerlilik tarihi geçmiş ilişkileri döndürür."""
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone aware")

        return tuple(
            item
            for item in self._relations
            if item.effective_at <= as_of and (item.source == entity or item.target == entity)
        )

    def get_connected_entities(
        self,
        entity: str,
        as_of: datetime,
        relation_type: str | None = None,
    ) -> list[str]:
        """Belirtilen varlıkla doğrudan bağlantılı olan tüm şirket kodlarını listeler."""
        valid_rels = self.relations_at(entity=entity, as_of=as_of)
        connected: set[str] = set()
        for r in valid_rels:
            if relation_type is None or r.relation == relation_type:
                target_node = r.target if r.source == entity else r.source
                connected.add(target_node)
        return sorted(connected)

    def find_shock_transmission_path(
        self,
        source_entity: str,
        max_depth: int = 2,
        as_of: datetime | None = None,
    ) -> dict[str, float]:
        """Bir hissede başlayan negatif/pozitif şokun çizge üzerindeki etki yayılımını (contagion) hesaplar."""
        as_of_dt = as_of or datetime.now(datetime.timezone.utc)
        impact_map: dict[str, float] = {source_entity: 1.0}
        queue: deque[tuple[str, int, float]] = deque([(source_entity, 0, 1.0)])
        visited: set[str] = {source_entity}

        while queue:
            curr_entity, depth, curr_weight = queue.popleft()
            if depth >= max_depth:
                continue

            rels = self.relations_at(curr_entity, as_of=as_of_dt)
            for r in rels:
                neighbor = r.target if r.source == curr_entity else r.source
                if neighbor not in visited:
                    visited.add(neighbor)
                    decayed_impact = curr_weight * r.weight * 0.60  # Her derecede %40 sönümleme
                    impact_map[neighbor] = round(decayed_impact, 4)
                    queue.append((neighbor, depth + 1, decayed_impact))

        return impact_map


entity_graph = EntityGraph()

__all__ = [
    "EntityGraph",
    "EntityRelation",
    "entity_graph",
]
