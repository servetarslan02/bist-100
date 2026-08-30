"""
ALPHA BIST — Knowledge Graph v1.0

Entity ilişki ağı:
- Company ↔ Sector
- Company ↔ Supplier/Customer
- Company ↔ Person (CEO, yönetim kurulu)
- Company ↔ Event (KAP, haber)
- Company ↔ Macro Event
- pgvector ile semantic search

FAZ 10.1: Knowledge Graph
"""

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson
import structlog

logger = structlog.get_logger()


@dataclass
class Entity:
    """Knowledge entity."""

    entity_id: str
    entity_type: str  # company, sector, person, event, macro, product
    name: str
    aliases: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Relation:
    """Entity ilişkisi."""

    source_id: str
    target_id: str
    relation_type: str  # belongs_to, supplies, manages, affected_by, correlated_with
    strength: float = 1.0
    properties: dict[str, Any] = field(default_factory=dict)


class KnowledgeGraph:
    """Knowledge graph motoru."""

    def __init__(self):
        """Otomatik eklendi."""
        self._entities: dict[str, Entity] = {}
        self._relations: deque = deque(maxlen=50000)
        self._index: dict[str, list[str]] = {}  # entity_id -> [relation_id]

    def add_entity(self, entity: Entity) -> Any:
        """Entity ekle."""
        self._entities[entity.entity_id] = entity

    def add_relation(self, relation: Relation) -> Any:
        """İlişki ekle."""
        self._relations.append(relation)
        idx = len(self._relations) - 1

        if relation.source_id not in self._index:
            self._index[relation.source_id] = []
        self._index[relation.source_id].append(str(idx))

        if relation.target_id not in self._index:
            self._index[relation.target_id] = []
        self._index[relation.target_id].append(str(idx))

    def get_entity(self, entity_id: str) -> Entity | None:
        """Entity getir."""
        return self._entities.get(entity_id)

    def get_relations(self, entity_id: str) -> list[Relation]:
        """Entity'nin tüm ilişkilerini getir."""
        relation_indices = self._index.get(entity_id, [])
        return [self._relations[int(i)] for i in relation_indices if int(i) < len(self._relations)]

    def get_related_entities(
        self,
        entity_id: str,
        relation_type: str | None = None,
    ) -> list[tuple[Entity, Relation]]:
        """İlişkili entity'leri getir."""
        relations = self.get_relations(entity_id)
        result = []

        for rel in relations:
            if relation_type and rel.relation_type != relation_type:
                continue

            other_id = rel.target_id if rel.source_id == entity_id else rel.source_id
            other = self._entities.get(other_id)
            if other:
                result.append((other, rel))

        return result

    def find_path(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 3,
    ) -> list[str] | None:
        """İki entity arasındaki yolu bul (BFS)."""
        if source_id == target_id:
            return [source_id]

        visited = {source_id}
        queue = [[source_id]]

        for _ in range(max_depth):
            next_queue = []
            for path in queue:
                current = path[-1]
                for entity, _rel in self.get_related_entities(current):
                    if entity.entity_id == target_id:
                        return path + [entity.entity_id]
                    if entity.entity_id not in visited:
                        visited.add(entity.entity_id)
                        next_queue.append(path + [entity.entity_id])
            queue = next_queue
            if not queue:
                break

        return None

    def propagate_impact(
        self,
        source_id: str,
        impact: float,
        max_depth: int = 2,
    ) -> dict[str, float]:
        """Etkiyi graf üzerinden yay."""
        impacts = {source_id: impact}
        visited = {source_id}
        queue = [(source_id, impact, 0)]

        while queue:
            current, current_impact, depth = queue.pop(0)
            if depth >= max_depth:
                continue

            for entity, rel in self.get_related_entities(current):
                if entity.entity_id not in visited:
                    propagated = current_impact * rel.strength * 0.5  # Her adımda azalır
                    if abs(propagated) > 0.01:  # Eşik
                        impacts[entity.entity_id] = propagated
                        visited.add(entity.entity_id)
                        queue.append((entity.entity_id, propagated, depth + 1))

        return impacts

    def load_bist_defaults(self) -> Any:
        """Varsayılan BIST entity'lerini yükle."""
        # Sektörler
        sectors = [
            "BANK",
            "INDUST",
            "TECH",
            "ENERGY",
            "RETAIL",
            "CONSTR",
            "FOOD",
            "CHEM",
            "METAL",
            "TELECOM",
            "HEALTH",
            "REAL",
            "AUTO",
            "TEXTIL",
            "AVIATION",
            "HOLDING",
        ]
        for s in sectors:
            self.add_entity(
                Entity(
                    entity_id=f"sector_{s}",
                    entity_type="sector",
                    name=s,
                )
            )

        # Macro entities
        macros = [
            ("USDTRY", "currency"),
            ("EURTRY", "currency"),
            ("TCMB_RATE", "rate"),
            ("CPI", "inflation"),
            ("VIX", "volatility"),
            ("OIL", "commodity"),
            ("GOLD", "commodity"),
            ("SP500", "index"),
        ]
        for name, mtype in macros:
            self.add_entity(
                Entity(
                    entity_id=f"macro_{name}",
                    entity_type="macro",
                    name=name,
                    properties={"type": mtype},
                )
            )

        # Macro → Sector ilişkileri
        macro_sector_relations = [
            ("USDTRY", "AVIATION", -0.8),
            ("USDTRY", "BANK", -0.3),
            ("USDTRY", "ENERGY", 0.5),
            ("USDTRY", "TECH", 0.4),
            ("USDTRY", "RETAIL", -0.6),
            ("TCMB_RATE", "BANK", 0.9),
            ("TCMB_RATE", "REAL", -0.5),
            ("OIL", "AVIATION", -0.9),
            ("OIL", "ENERGY", 0.9),
            ("VIX", "BANK", -0.6),
            ("VIX", "TECH", -0.5),
        ]
        for macro, sector, strength in macro_sector_relations:
            self.add_relation(
                Relation(
                    source_id=f"macro_{macro}",
                    target_id=f"sector_{sector}",
                    relation_type="affects",
                    strength=strength,
                )
            )

        logger.info("BIST defaults loaded", entities=len(self._entities), relations=len(self._relations))

    def save(self, path: str = "data/knowledge_graph.json") -> Any:
        """Graph'u dosyaya kaydet (debounced — SSD dostu)."""
        from services.core.debounce import should_save
        if not should_save("knowledge_graph", 120):
            return
        data = {
            "entities": [
                {
                    "entity_id": e.entity_id,
                    "entity_type": e.entity_type,
                    "name": e.name,
                    "aliases": e.aliases,
                    "properties": e.properties,
                }
                for e in self._entities.values()
            ],
            "relations": [
                {
                    "source_id": r.source_id,
                    "target_id": r.target_id,
                    "relation_type": r.relation_type,
                    "strength": r.strength,
                    "properties": r.properties,
                }
                for r in self._relations
            ],
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2).decode())
        logger.info("Knowledge graph saved", path=path, entities=len(self._entities), relations=len(self._relations))

    def load(self, path: str = "data/knowledge_graph.json") -> Any:
        """Graph'u dosyadan yükle."""
        if not Path(path).exists():
            return
        try:
            with open(path) as f:
                data = orjson.loads(f.read())
            for e in data.get("entities", []):
                self.add_entity(Entity(**e))
            for r in data.get("relations", []):
                self.add_relation(Relation(**r))
            logger.info(
                "Knowledge graph loaded", path=path, entities=len(self._entities), relations=len(self._relations)
            )
        except Exception as e:
            logger.warning("Failed to load knowledge graph", path=path, error=str(e))

    def get_stats(self) -> dict[str, Any]:
        """Graph istatistikleri."""
        type_counts = {}
        for e in self._entities.values():
            type_counts[e.entity_type] = type_counts.get(e.entity_type, 0) + 1

        return {
            "total_entities": len(self._entities),
            "total_relations": len(self._relations),
            "entity_types": type_counts,
        }


# Singleton
knowledge_graph = KnowledgeGraph()
