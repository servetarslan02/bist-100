# INTELLIGENCE — Yapay Zeka ve Analiz Motoru

## Giriş

Intelligence servisi, ALPHA BIST sisteminin "beyni"dir. Piyasa verilerini alır, çoklu analiz motorlarından geçirir, LLM (Gemini) ile derinlemesine yorumlar ve nihai alım/satım kararları üretir. 35+ Python modülünden oluşan bu servis, rejim tespitinden Monte Carlo simülasyonuna, KAP haber analizinden knowledge graph'a kadar geniş bir yelpazeyi kapsar.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────┐
│                    INTELLIGENCE SERVICE                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  main.py     │  │  pipeline.py │  │ parallel_pipeline.py │  │
│  │  (Event Bus  │  │  (Sequential │  │  (Async Parallel     │  │
│  │   Consumer)  │  │   5 Phase)   │  │   5 Phase)           │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                      │              │
│  ┌──────┴─────────────────┴──────────────────────┴───────────┐  │
│  │              PHASE 1: CONTEXT                              │  │
│  │  ┌─────────────┐ ┌──────────────┐ ┌───────────────────┐  │  │
│  │  │ regime.py   │ │ world_state  │ │ macro_sensitivity │  │  │
│  │  │ (11 rejim)  │ │ (10 latent   │ │ (sektör-makro     │  │  │
│  │  │             │ │  factor)     │ │  hassasiyet)      │  │  │
│  │  └──────┬──────┘ └──────┬───────┘ └────────┬──────────┘  │  │
│  │         │               │                   │             │  │
│  │  ┌──────┴───────┐                               │         │  │
│  │  │ hmm_regime   │                               │         │  │
│  │  │ (GaussianHMM │                               │         │  │
│  │  │  4 rejim)    │                               │         │  │
│  │  └──────────────┘                               │         │  │
│  └─────────────────────────────────────────────────┘         │  │
│                                                               │  │
│  ┌──────────────────────────────────────────────────────────┐ │  │
│  │              PHASE 2: ANALYSIS                            │ │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐ │ │  │
│  │  │ analysis_    │ │ evidence_    │ │ impact_engine    │ │ │  │
│  │  │ engines.py   │ │ engine.py    │ │ (50+ propagation │ │ │  │
│  │  │ (9 motor)    │ │ (claim       │ │  rule)           │ │ │  │
│  │  │              │ │  verify)     │ │                  │ │ │  │
│  │  └──────────────┘ └──────────────┘ └──────────────────┘ │ │  │
│  │  ┌──────────────┐ ┌──────────────┐                      │ │  │
│  │  │ kap_         │ │ kap_llm_     │                      │ │  │
│  │  │ extractor.py │ │ extractor.py │                      │ │  │
│  │  │ (LLM+RAG)    │ │ (v3.0 KG)   │                      │ │  │
│  │  └──────────────┘ └──────────────┘                      │ │  │
│  └──────────────────────────────────────────────────────────┘ │  │
│                                                               │  │
│  ┌──────────────────────────────────────────────────────────┐ │  │
│  │              PHASE 3: FORECAST                            │ │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐ │ │  │
│  │  │ forecasting  │ │ monte_carlo  │ │ advanced_mc      │ │ │  │
│  │  │ (multi-      │ │ (GBM,        │ │ (jump-diffusion, │ │ │  │
│  │  │  horizon)    │ │  10K sim)    │ │  Heston, t-dist) │ │ │  │
│  │  └──────────────┘ └──────────────┘ └──────────────────┘ │ │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐ │ │  │
│  │  │ ensemble_    │ │ probability  │ │ scenario.py      │ │ │  │
│  │  │ forecast.py  │ │ (Brier,      │ │ (stress test,    │ │ │  │
│  │  │ (LGBM+XGB+   │ │  calibration)│ │  breaking point) │ │ │  │
│  │  │  heuristic)  │ │              │ │                  │ │ │  │
│  │  └──────────────┘ └──────────────┘ └──────────────────┘ │ │  │
│  │  ┌──────────────┐                                       │ │  │
│  │  │ prediction_  │                                       │ │  │
│  │  │ layer.py     │                                       │ │  │
│  │  │ (A+/A/B/C/D) │                                       │ │  │
│  │  └──────────────┘                                       │ │  │
│  └──────────────────────────────────────────────────────────┘ │  │
│                                                               │  │
│  ┌──────────────────────────────────────────────────────────┐ │  │
│  │              PHASE 4: FUSION                              │ │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐ │ │  │
│  │  │ signal_      │ │ ml_signal_   │ │ spec_engine.py   │ │ │  │
│  │  │ fusion.py    │ │ fusion.py    │ │ (anomaly+evidence│ │ │  │
│  │  │ (10 sinyal,  │ │ (SHAP-based, │ │  +regime+EV+     │ │ │  │
│  │  │  rejim-aware)│ │  regime-     │ │  risk+similarity │ │ │  │
│  │  │              │ │  specific)   │ │  -penalty)       │ │ │  │
│  │  └──────────────┘ └──────────────┘ └──────────────────┘ │ │  │
│  │  ┌──────────────┐ ┌──────────────┐                      │ │  │
│  │  │ trade_       │ │ confidence_  │                      │ │  │
│  │  │ planner.py   │ │ calibrator   │                      │ │  │
│  │  │ (entry/exit, │ │ (Brier, ECE, │                      │ │  │
│  │  │  scenarios)  │ │  Platt)      │                      │ │  │
│  │  └──────────────┘ └──────────────┘                      │ │  │
│  └──────────────────────────────────────────────────────────┘ │  │
│                                                               │  │
│  ┌──────────────────────────────────────────────────────────┐ │  │
│  │              PHASE 5: KNOWLEDGE                           │ │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐ │ │  │
│  │  │ knowledge_   │ │ research_    │ │ news_pipeline.py │ │ │  │
│  │  │ graph.py     │ │ memory.py    │ │ (LLM Agent       │ │ │  │
│  │  │ (entity-     │ │ (RAG,        │ │  tabanlı)        │ │ │  │
│  │  │  relation)   │ │  lineage)    │ │                  │ │ │  │
│  │  └──────────────┘ └──────────────┘ └──────────────────┘ │ │  │
│  └──────────────────────────────────────────────────────────┘ │  │
│                                                               │  │
│  ┌──────────────────────────────────────────────────────────┐ │  │
│  │              LLM SUBSYSTEM                                │ │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐ │ │  │
│  │  │ llm_agent.py │ │ llm_client   │ │ llm_context_     │ │ │  │
│  │  │ (ReAct loop, │ │ (Gemini API, │ │ builder.py       │ │ │  │
│  │  │  tool calls, │ │  function    │ │ (RAG motoru,     │ │ │  │
│  │  │  regime      │ │  calling)    │ │  context paketi) │ │ │  │
│  │  │  override)   │ │              │ │                  │ │ │  │
│  │  └──────────────┘ └──────────────┘ └──────────────────┘ │ │  │
│  │  ┌──────────────┐ ┌──────────────┐                      │ │  │
│  │  │ llm_tools.py │ │ gemini_      │                      │ │  │
│  │  │ (10 araç:    │ │ service.py   │                      │ │  │
│  │  │  world_state,│ │ (agentic     │                      │ │  │
│  │  │  KG, regime, │ │  tool calls) │                      │ │  │
│  │  │  override)   │ │              │                      │ │  │
│  │  └──────────────┘ └──────────────┘                      │ │  │
│  └──────────────────────────────────────────────────────────┘ │  │
│                                                               │  │
│  ┌──────────────────────────────────────────────────────────┐ │  │
│  │              VALUATION                                    │ │  │
│  │  ┌──────────────────────────────────────────────────┐    │ │  │
│  │  │ valuation/engine.py                               │    │ │  │
│  │  │ (Multiples P/E-P/B-EV/EBITDA, DCF,               │    │ │  │
│  │  │  Bear/Base/Bull senaryoları, WACC=%45)            │    │ │  │
│  │  └──────────────────────────────────────────────────┘    │ │  │
│  └──────────────────────────────────────────────────────────┘ │  │
└─────────────────────────────────────────────────────────────────┘
```

## Neden Bu Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| **5 Fazlı Pipeline** | Bağımsız modüller paralel, bağımlı olanlar sıralı çalışır. Phase 1 (context) → Phase 2 (analysis) → Phase 3 (forecast) → Phase 4 (fusion) → Phase 5 (knowledge) sırası mantıksal bağımlılıkları takip eder. |
| **Hem Sync hem Async Pipeline** | Orchestrator senkron pipeline kullanır; LLM ve I/O-bound işlemler async pipeline ile paralelleştirilir. |
| **11 Rejim (Regime Engine)** | BIST'e özgü rejimler (MOMENTUM_EXPANSION, CRISIS, RECOVERY vb.) klasik 4 rejimden daha zengin. Skor bazlı + HMM hibrit yaklaşım. |
| **HMM + Skor + GMM Ensemble** | Tek yöntem yetersiz. HMM matematiksel, skor yorumlanabilir, GMM hızlı. Ağırlıklı oylama ile birleşir. |
| **LLM Agent (ReAct Döngüsü)** | LLM sadece text üretmez; araç çağırarak (world state, KG, research memory) bağlam zenginleştirir ve rejim override yapabilir. |
| **SPEC Engine** | Anormal davranış + kanıt + rejim uyumu + beklenen değer + risk asimetrisi + tarihsel benzerlik - penalty. Tek skorla conviction ölçümü. |
| **Monte Carlo (GBM + Jump-Diffusion + Heston)** | Basit GBM yetersiz; fat tails ve stochastic vol için advanced modeller. Numba JIT ile performans. |
| **Knowledge Graph** | Sektör-şirket-makro etki ağı. BFS ile yol bulma, impact propagation. Varsayılan BIST entity'leri yüklü. |
| **Research Memory (RAG)** | LLM her analizini hafızaya yazar. Gelecek analizlerde geçmiş bağlam olarak kullanılır. Data lineage takibi. |
| **Confidence Calibrator** | Model %90 güven dediyse gerçekten %90 olmalı. Brier score, ECE, overconfidence detection. Rejim bazlı kalibrasyon. |

## Uçtan Uca Veri Akışı

```
Event Bus (anomaly.detected / signal.generated / kap.event)
    │
    ▼
IntelligenceService._on_anomaly() / _on_signal() / _on_kap_event()
    │
    ├─► _build_context() ──► Redis (features, market_state, world_state)
    │                        PostgreSQL (signals, predictions, positions)
    │                        Knowledge Graph (entity relations)
    │                        Research Memory (geçmiş analizler)
    │
    ├─► _analyze_with_llm() ──► Gemini API (function calling)
    │       │
    │       ├─► llm_tools.execute("get_world_state")
    │       ├─► llm_tools.execute("get_knowledge_graph")
    │       ├─► llm_tools.execute("get_research_memory")
    │       └─► llm_tools.execute("override_regime")  [kritik durumlarda]
    │
    └─► Redis'e kaydet + Event Bus'a publish

═══════════════════════════════════════════════════

Orchestrator → IntelligencePipeline.run(ticker, features, market_data, regime)
    │
    ├─► Phase 1: Context
    │   ├─► WorldStateManager.current_state → global_risk_appetite
    │   ├─► MacroSensitivityEngine.get_company_sensitivity()
    │   └─► FactorEngine.compute_factor_scores()
    │
    ├─► Phase 2: Analysis
    │   ├─► PriceActionEngine.detect_patterns()
    │   ├─► EvidenceVerificationEngine.extract_claims()
    │   ├─► ImpactEngine.propagate()
    │   └─► KAPExtractor.extract()
    │
    ├─► Phase 3: Forecast
    │   ├─► ForecastingEngine.compute_forecasts() → [1d, 5d, 20d, 60d, 120d]
    │   ├─► MonteCarloEngine.simulate_price_paths() → VaR, CVaR, percentiles
    │   ├─► ProbabilityEngine.compute_return_distribution()
    │   └─► ScenarioEngine.run_scenario()
    │
    ├─► Phase 4: Fusion
    │   ├─► SignalFusionEngine.fuse_signals() → 10 sinyal ağırlıklı birleştirme
    │   ├─► SPECEngine.compute_spec() → conviction skoru
    │   └─► TradePlanner.create_plan() → entry/stop/target/position size
    │
    └─► Phase 5: Knowledge
        ├─► KnowledgeGraph.search_entities()
        └─► ResearchMemory.get_ticker_history()
```

## Dosya Bazlı Sorumluluk Tablosu

| Dosya | Sorumluluk | Kritik Bağımlılık |
|-------|-----------|-------------------|
| `main.py` | Event Bus consumer, LLM entegrasyonu, anomaly/signal/KAP handler | `llm_client`, `world_state`, `spec_engine` |
| `pipeline.py` | Sequential 5-faz pipeline, 16 modül orchestrator | Tüm modüller |
| `parallel_pipeline.py` | Async paralel pipeline, `asyncio.gather` ile phase'ler | Tüm modüller |
| `regime.py` | 11 rejim, skor bazlı, HMM hibrit, macro regime entegrasyonu, LLM override | `hmm_regime`, `macro.regime_detector` |
| `hmm_regime.py` | GaussianHMM ile 4 rejim (BULL/BEAR/HIGH_VOL/LOW_VOL), rolling 63 gün | `hmmlearn` (opsiyonel) |
| `ensemble_forecast.py` | LightGBM + XGBoost + Heuristic + Statistical + Momentum ensemble | Rejime göre ağırlık |
| `forecasting.py` | Multi-horizon tahmin (1/5/20/60/120 gün), heuristic fallback | — |
| `forecasting_utils.py` | NewsImpactEngine, NewsDuplicationEngine, EventTimelineEngine | — |
| `monte_carlo.py` | GBM simülasyonu, 10K path, VaR/CVaR, portfolio-level MC | `numpy` |
| `advanced_monte_carlo.py` | Jump-diffusion (Merton), Student-t (fat tails), Heston-lite (stochastic vol) | `numba` |
| `llm_agent.py` | ReAct döngüsü, haber/KAP/signal analizi, rejim override, hafıza yazma | `llm_client`, `llm_tools`, `llm_context_builder` |
| `llm_client.py` | Gemini API istemcisi, function calling, structured output, mock fallback | `google-genai` / `google-generativeai` |
| `llm_context_builder.py` | RAG motoru: WorldState + KG + ResearchMemory + Features → context paketi | Tüm singleton'lar |
| `llm_tools.py` | 10 araç şeması + uygulaması (get_world_state, override_regime, store_analysis vb.) | Tüm singleton'lar |
| `confidence_calibrator.py` | Brier score, ECE, overconfidence detection, Platt scaling, rejim bazlı | — |
| `factor_engine.py` | Value/Momentum/Quality/Size/LowVol faktör skorları, portföy maruziyeti, Piotroski/Beneish/Altman | `services.factors` |
| `signal_fusion.py` | 10 sinyal birleştirme, rejime göre ağırlık, çelişki tespiti, self-check | — |
| `ml_signal_fusion.py` | SHAP-based ağırlık optimizasyonu, rejime göre dinamik ağırlık | `sklearn`, `shap` (opsiyonel) |
| `spec_engine.py` | SPEC = anomaly + evidence + regime + EV + risk_asymmetry + similarity - penalty | — |
| `trade_planner.py` | Entry/stop/target, ATR bazlı, senaryolar (bull/base/bear), Kelly pozisyon büyüklüğü | — |
| `world_state.py` | 10 latent factor (global_risk_appetite, usd_strength, vix_level vb.), event-driven update, decay | — |
| `prediction_layer.py` | Multi-horizon prediction, quality grading (A+/A/B/C/D), ensemble+calibration entegrasyonu | — |
| `evidence_engine.py` | Claim extraction, source verification, hallucination detection, evidence scoring | — |
| `impact_engine.py` | 50+ propagation rule, event → asset impact, sector chain, world state delta | — |
| `kap_extractor.py` | KAP bildirim sınıflandırma, LLM Agent tabanlı extraction, sector chain impact | `llm_agent` |
| `kap_llm_extractor.py` | KAP + LLM v3.0, knowledge graph construction, agentic factor discovery | — |
| `news_pipeline.py` | Haber → LLM Agent → Entity → Event → World State → Impact zinciri | `llm_agent` |
| `knowledge_graph.py` | Entity-relation ağı, BFS yol bulma, impact propagation, BIST defaults | — |
| `research_memory.py` | RAG hafızası, ticker geçmişi, data lineage (forward/backward trace) | — |
| `scenario.py` | 9 önceden tanımlı senaryo (2008, 2020 COVID vb.), breaking point analizi | — |
| `probability.py` | Getiri dağılımı, hit rate, calibration, Brier score, heuristic olasılık | — |
| `macro_sensitivity.py` | Sektör-makro hassasiyet matrisi, dinamik rolling korelasyon güncelleme | — |
| `analysis_engines.py` | 9 motor: PriceAction, SupportResistance, Volume, Sector, RelativeStrength, Correlation, Drawdown, PositionRisk, ModelRisk, DataConfidence, PortfolioOptimization | — |
| `gemini_service.py` | Agentic Gemini 3.7, gerçek zamanlı sistem araçları (stock metrics, MC, macro state) | Gemini API |
| `valuation/engine.py` | Multiples (P/E, P/B, EV/EBITDA), DCF (WACC=%45), Bear/Base/Bull senaryoları | — |

## Tasarım İlkeleri ve Kırmızı Çizgiler

### İlkeler
1. **Graceful Fallback**: Her modül çalışamazsa mock/default değer döner, sistem çökmez.
2. **Singleton Pattern**: Tüm motorlar singleton — tek instance, paylaşımlı state.
3. **Rejime Duyarlılık**: Ağırlıklar, skorlar, stratejiler rejime göre değişir.
4. **LLM Son Söz Değil**: LLM bir sinyal kaynağıdır, nihai karar değil. Confidence < 0.80 ise rejim override reddedilir.
5. **NaN/None Güvenliği**: `_safe()` fonksiyonu ile tüm sayısal değerler korunur.
6. **Config-Driven**: Hardcoded eşik yok. `SPECConfig`, `MacroConfig` gibi Pydantic modelleri.

### Kırmızı Çizgiler
- ❌ LLM'e asla doğrudan trading emri verdirilmez — sadece analiz ve yorum.
- ❌ Confidence < 0.80 iken rejim override yapılamaz.
- ❌ Aynı haberin 10 kaynaktan kopyalanması 10 bağımsız evidence sayılmaz (ağırlıklı consensus).
- ❌ Warm-up döneminde edge padding kullanılmaz — mean padding ile trend sızıntısı önlenir.
- ❌ Portföy Monte Carlo'da korelasyon matrisi pozitif tanımlı değilse diagonal kullanılır.

## Bilinen Sınırlamalar

| Sınırlama | Açıklama |
|-----------|---------|
| **HMM soğuk başlangıç** | 63 günden az veri ile HMM eğitilemez, rule-based fallback devreye girer. |
| **LLM mock modu** | Gemini API anahtarı yoksa tüm LLM analizleri mock döner. |
| **SHAP optimizasyonu** | `sklearn` yoksa SHAP-based ağırlık optimizasyonu devre dışı, rejim override kullanılır. |
| **GMM opsiyonel** | `sklearn` yoksa GMM rejim tespiti çalışmaz, 2 yöntemle ensemble yapılır. |
| **Numba JIT** | `advanced_monte_carlo.py` Numba gerektirir; yoksa GBM fallback. |
| **Knowledge Graph soğuk** | Varsayılan BIST entity'leri yüklü ama şirket-specific ilişkiler manuel eklenmeli. |
| **DCF varsayılanları** | WACC=%45, terminal growth=%15 — Türkiye enflasyon ortamına uygun ama şirket-specific değil. |
| **News duplication basit** | MD5 hash tabanlı — anlam benzerliği yakalanmaz. |
| **Backtest PIT** | `research_memory` in-memory — restart sonrası sıfırlanır. |

## Cross-Reference

- **Market State** → `regime.py` içinde `services.macro.regime_detector` import edilir; macro regime skorları intelligence rejim skorlarına %15 ağırlıkla katılır.
- **Market State** → `world_state.py` → `WorldStateManager` market_state servisi tarafından `world_state.changed` event'i ile güncellenir.
- **Macro** → `macro_sensitivity.py` → `SECTOR_MACRO_SENSITIVITY` matrisi macro servisiyle paylaşılır.
- **Macro** → `regime.py` → `macro_regime_detector.detect_regime()` çağrılır.
- **Orchestrator** → `pipeline.py` → `IntelligencePipeline.run()` veya `run_full_intelligence()` çağrılır.
- **Event Bus** → `main.py` → `anomaly.detected`, `signal.generated`, `kap.event` topic'lerini dinler.
- **Redis** → Features, market_state, world_state, AI analysis sonuçları Redis'te saklanır (TTL: 3600s).
- **PostgreSQL** → Signals, predictions, positions, knowledge_entities tablolarından veri çeker.
