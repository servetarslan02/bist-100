# Intelligence Modülü — Güncel Durum Raporu

**Tarih:** 2026-08-21
**Analiz:** Kod tabanı envanteri

---

## Genel Durum

| Metrik | Değer |
|--------|-------|
| Modül sayısı | 37 |
| Toplam satır | ~11,643 |
| Sınıf sayısı | 97 |
| Fonksiyon sayısı | 331 |
| Test sayısı | 83 |
| Pipeline fazı | 5 (Context → Analysis → Forecast → Fusion → Knowledge) |

---

## Modül Olgunluk Durumu

| Modül | Durum | Not |
|-------|-------|-----|
| pipeline.py | ✅ TAM | 5 fazlı sequential pipeline |
| parallel_pipeline.py | ✅ TAM | Async paralel pipeline |
| regime.py | ✅ TAM | 11 rejim, skor bazlı + HMM hibrit |
| hmm_regime.py | ✅ TAM | GaussianHMM 4 rejim |
| forecasting.py | ✅ TAM | Multi-horizon (1/5/20/60/120 gün) |
| monte_carlo.py | ✅ TAM | GBM, 10K simülasyon |
| advanced_monte_carlo.py | ✅ TAM | Jump-diffusion, Heston, t-dist |
| signal_fusion.py | ✅ TAM | 10 sinyal, rejim-aware |
| spec_engine.py | ✅ TAM | Anomaly + evidence + regime + EV + risk |
| trade_planner.py | ✅ TAM | Entry/stop/target, ATR bazlı |
| world_state.py | ✅ TAM | 10 latent factor |
| llm_agent.py | ✅ TAM | ReAct döngüsü, tool calls |
| llm_client.py | ✅ TAM | Gemini API, function calling |
| knowledge_graph.py | ✅ TAM | Entity-relation, BFS |
| research_memory.py | ✅ TAM | RAG, lineage tracking |
| confidence_calibrator.py | ✅ TAM | Brier, ECE, Platt scaling |
| factor_engine.py | ✅ TAM | Value/Momentum/Quality/Size/LowVol |
| impact_engine.py | ✅ TAM | 50+ propagation rule |
| kap_extractor.py | ✅ TAM | LLM Agent tabanlı extraction |
| news_pipeline.py | ✅ TAM | Entity → Event → Impact zinciri |
| valuation/engine.py | ✅ TAM | Multiples + DCF |

---

## Bilinen Sınırlamalar

| Sınırlama | Öncelik | Açıklama |
|-----------|---------|----------|
| HMM soğuk başlangıç | P1 | 63 günden az veri ile eğitilemez |
| LLM mock modu | P1 | Gemini API anahtarı yoksa mock döner |
| SHAP optimizasyonu | P2 | sklearn yoksa devre dışı |
| GMM opsiyonel | P2 | sklearn yoksa çalışmaz |
| Numba JIT | P2 | advanced_monte_carlo Numba gerektirir |
| Knowledge Graph soğuk | P2 | Varsayılan BIST entity'leri yüklü |
| DCF varsayılanları | P2 | WACC=%45, terminal growth=%15 |
| News duplication basit | P2 | MD5 hash tabanlı |
| Research memory in-memory | P2 | Restart sonrası sıfırlanır |
