# Bölüm 17 — Memory + Knowledge Graph

## Amaç

Sistemin geçmiş analizleri, şirket ilişkilerini ve olayları kaybedip her seferinde sıfırdan başlamasını önlemek.

**Kaynak:** Vector DB semantic search, Knowledge Graph entity relationships.

## Çalışma mantığı

```
Yeni Veri/Analiz → Entity+Event çıkarımı → Embedding →
Memory + Knowledge Graph → Geçmiş bilgilerle ilişkilendirme → Güncel analiz
```

### Örnek: Knowledge graph

```python
from services.intelligence.knowledge_graph import knowledge_graph

knowledge_graph.load_bist_defaults()
path = knowledge_graph.find_path("macro_OIL", "sector_ENERGY")
# path = ["macro_OIL", "sector_ENERGY"]

impacts = knowledge_graph.propagate_impact("macro_OIL", 0.5)
# sector_ENERGY: 0.5, sector_AVIATION: -0.3
```

## Temel prensip

Memory geçmişi saklar, Knowledge Graph ilişkileri saklar; karar güncel analiz motorları tarafından verilir.
