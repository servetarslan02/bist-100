# Bölüm 17 — Memory + Knowledge Graph

## Amaç

Sistemin geçmiş analizleri, şirket ilişkilerini ve olayları kaybedip her seferinde sıfırdan başlamasını önlemek.

**Kaynak:** Atlan (2026) Vector DB vs Knowledge Graph, arXiv Graph-based Agent Memory (2026), Verdantix Enterprise Graph Technology.

---

## Kullanılacak sistemler

- Research Memory
- Long-Term Memory
- Vector Database
- Embeddings
- Knowledge Graph
- Entity / Relationship Store
- Historical Event Store
- Prediction & Outcome Memory

---

## Çalışma mantığı

```
Yeni Veri/Analiz → Entity+Event çıkarımı → Embedding →
Memory + Knowledge Graph → Geçmiş bilgilerle ilişkilendirme → Güncel analiz
```

---

## 1. Memory Türleri

**Araştırma bulgusu:** Atlan (2026) — "Knowledge graphs model typed entity relationships and enable deterministic multi-hop traversal. Most production enterprise agents use both vector DB and knowledge graph."

### Memory türleri:
- **Vector DB:** Semantic similarity search (anlam bazlı arama)
- **Knowledge Graph:** Entity relationships (ilişki bazlı)
- **Session Memory:** Kısa süreli bağlam
- **Long-term Memory:** Kalıcı bilgi

---

## 2. Knowledge Graph

### Örnek: Entity ve ilişki

```python
# services/intelligence/knowledge_graph.py
from services.intelligence.knowledge_graph import knowledge_graph

knowledge_graph.load_bist_defaults()

# İlişki zinciri
path = knowledge_graph.find_path("macro_OIL", "sector_ENERGY")
# path = ["macro_OIL", "sector_ENERGY"]

# Etki yayılımı
impacts = knowledge_graph.propagate_impact("macro_OIL", 0.5)
# sector_ENERGY: 0.5, sector_AVIATION: -0.3
```

---

## 3. Research Memory

### Örnek: Geçmiş araştırma kaydı

```python
from services.intelligence.research_memory import research_memory, ResearchRecord

research_memory.add_record(ResearchRecord(
    record_id="R001", ticker="THYAO", date="2026-08-15",
    thesis="Momentum strong", evidence=["volume spike", "breakout"],
    risks=["high volatility"], prediction={"return": 5.0, "prob": 0.7},
))

history = research_memory.get_ticker_history("THYAO")
# history[0]: {date: "2026-08-15", thesis: "Momentum strong", ...}
```

---

## 4. Data Lineage

### Örnek: Veri izleme

```python
from services.intelligence.research_memory import data_lineage

data_lineage.add_node(LineageNode("raw_data", "price_THYAO", "2026-08-15T10:00:00"))
data_lineage.add_node(LineageNode("feature", "rsi_THYAO", "2026-08-15T10:00:01",
    parent_ids=["raw_data:price_THYAO"]))

forward = data_lineage.trace_forward("raw_data", "price_THYAO")
# forward: [{type: "raw_data", id: "price_THYAO"}, {type: "feature", id: "rsi_THYAO"}]
```

---


## Çıktı

```
Relevant Past Events:        14
Similar Historical Cases:     6
Previous Predictions:         9
Prediction Accuracy History: %72
Related Entities:             23
Memory Confidence:            %91
```

## Temel prensip

**Memory** geçmişi saklar, **Knowledge Graph** ilişkileri saklar; **karar güncel analiz motorları tarafından verilir**.
