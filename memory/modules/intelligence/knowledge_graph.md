# intelligence/knowledge_graph

**Dosya:** `services/intelligence/knowledge_graph.py`
**Satır:** 216

## Açıklama

ALPHA BIST — Knowledge Graph v1.0

Entity ilişki ağı:
- Company ↔ Sector
- Company ↔ Supplier/Customer
- Company ↔ Person (CEO, yönetim kurulu)
- Company ↔ Event (KAP, haber)
- Company ↔ Macro Event
- pgvector ile semantic search

FAZ 10.1: Knowledge Graph

## Sınıflar (3)

- `Entity`
- `Relation`
- `KnowledgeGraph`

## Fonksiyonlar (10)

- `__init__()`
- `add_entity()`
- `add_relation()`
- `get_entity()`
- `get_relations()`
- `get_related_entities()`
- `find_path()`
- `propagate_impact()`
- `load_bist_defaults()`
- `get_stats()`

