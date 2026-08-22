# AG — Agent System

## Giriş

Agent modülü, ALPHA BIST sisteminin "beyin" katmanıdır. Çoklu AI agent'ın paralel çalışmasını, çelişki tespitini, Bull/Bear tartışmasını, risk değerlendirmesini ve sentezlenmesini yönetir. LLM tabanlı analiz yapar, LLM yoksa rule-based fallback ile devam eder. 6 fazdan oluşan bir pipeline mimarisi kullanır.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────┐
│                    AgentPipelineOrchestrator                 │
│                    (agent_pipeline.py)                       │
├─────────┬──────────┬──────────┬──────────┬─────────┬────────┤
│ Phase 1 │ Phase 2  │ Phase 3  │ Phase 4  │ Phase 5 │ Phase 6│
│Parallel │Conflict  │ Bull/    │  Risk    │Sentez   │ Memory │
│ Runner  │Detection │ Bear     │Assessor  │ Engine  │ Update │
│         │          │ Debate   │          │         │        │
├─────────┼──────────┼──────────┼──────────┼─────────┼────────┤
│parallel │conflict_ │debate_   │risk_     │synthesis│agent_  │
│_runner  │detector  │engine    │assessor  │_engine  │memory  │
├─────────┴──────────┴──────────┴──────────┴─────────┴────────┤
│              Communication Bus (communication_bus.py)        │
│              Conflict Resolver (confidence-weighted voting)   │
├─────────────────────────────────────────────────────────────┤
│              BaseAgent + AgentOrchestrator (agent_system.py)  │
├──────────┬──────────────┬───────────────────────────────────┤
│LLM Client│ Prompt       │ Schemas (Pydantic)                │
│(llm_     │ Templates    │ - AgentOutputSchema               │
│ client)  │ (prompts/)   │ - TechnicalOutputSchema           │
│          │              │ - DebateArgumentSchema             │
│          │              │ - RiskAssessmentSchema             │
├──────────┴──────────────┴───────────────────────────────────┤
│              Self-Evaluator (self_evaluator.py)               │
│              Accuracy · Calibration · Drift · Overconfidence  │
└─────────────────────────────────────────────────────────────┘
```

## Neden Bu Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| Paralel agent çalıştırma (asyncio.gather) | 4 bağımsız analiz (TECHNICAL, FUNDAMENTAL, NEWS, MACRO) eşzamanlı çalışarak latency'yi ~4x düşürür |
| Bull/Bear debate (CGX protokolü) | Tek bir LLM kararı yerine çelişkili argümanların tartışılması hallucination'ı azaltır, karar kalitesini artırır |
| Confidence damping (her turda ×0.9) | Sonsuz tartışmayı önler, erken konsensüsü teşvik eder |
| 5 katmanlı hallucination koruması | JSON parse → Pydantic schema → range check → domain check → source check — LLM çıktısının güvenilirliğini garanti eder |
| Rule-based fallback | LLM erişilemez olduğunda sistem çökmez, kural tabanlı analizle devam eder |
| 3 katmanlı hafıza (Working/Episodic/Semantic) | arXiv Agentic Trading 2026 meta-analizinden — agent'ın kısa ve uzun vadeli bağlamı korumasını sağlar |
| Confidence-weighted voting | Basit majority vote yerine güven ağırlıklı oy, yüksek güvenilirlikli agent'lara daha fazla ağırlık verir |
| Risk agent veto yetkisi | CRITICAL risk seviyesinde işlemi durdurabilme — sermaye koruması için son kalem |

## Uçtan Uca Veri Akışı

```
1. Kullanıcı/Orchestrator → AgentPipelineOrchestrator.run(ticker, features, context)
2. Phase 1: ParallelAgentRunner → 4 agent paralel çalışır
   - BaseAgent.execute() → LLM çağrısı (veya fallback)
   - AIOutputValidator.validate() → 5 katmanlı doğrulama
   - Sonuç: Dict[AgentRole, AgentResult]
3. Phase 2: ConflictDetector.detect()
   - LONG/SHORT dağılımı analiz edilir
   - Çelişki skoru hesaplanır (0-1)
   - requires_debate = True/False
4. Phase 3: DebateEngine.run_debate() (eğer çelişki varsa)
   - Bull argüman → Bear cevap → Bear argüman → Bull cevap (max 3 tur)
   - Confidence damping uygulanır
   - Consensus veya NO_TRADE
5. Phase 4: RiskAssessor.assess()
   - Volatilite, likidite, konsantrasyon, makro risk
   - CRITICAL → veto (approved=False)
6. Phase 5: ConflictResolver.resolve()
   - Majority vote → confidence tiebreak → debate consensus → risk veto
7. Phase 6: SynthesisEngine.synthesize()
   - Tüm sonuçları birleştirir
   - LLM sentez (varsa) veya weighted scoring
   - Final direction + confidence
8. Memory Update: AgentMemory.record_task()
   - Working memory'ye kaydet
   - Episodic memory'ye (yüksek güven) kaydet
9. PipelineResult döndürülür
```

## Dosya Bazlı Sorumluluk Tablosu

| Dosya | Sorumluluk |
|-------|-----------|
| `agent_system.py` | AgentRole enum, AgentTask/AgentResult dataclass'ları, BaseAgent (LLM çağrısı + validation + fallback), AgentOrchestrator (pipeline çalıştırma), AIOutputValidator (5 katmanlı doğrulama), AIFallback (kural tabanlı analiz), AgentToolRegistry (tool erişim kontrolü) |
| `agent_pipeline.py` | AgentPipelineOrchestrator — 6 fazlı pipeline'ı birleştirir, PipelineResult döndürür, memory consolidation ve self-evaluation tetikler |
| `llm_client.py` | BaseLLMClient (abstract), OllamaLLMClient, OpenAILLMClient, AnthropicLLMClient — çoklu LLM provider desteği, retry + exponential backoff, parse_llm_json (4 stratejili JSON çıkarma) |
| `parallel_runner.py` | ParallelAgentRunner — asyncio.gather + semaphore + timeout, partial failure handling, fallback, AgentPipelineBuilder (fluent API) |
| `conflict_detector.py` | ConflictDetector — LONG/SHORT dağılımı analizi, çelişki skoru (0-1), debate tetikleme kararı, cross-agent çelişki detayı |
| `debate_engine.py` | DebateEngine — Bull/Bear CGX protokolü, max 3 tur, confidence damping (×0.9), erken konsensüs, DebateRound/DebateResult |
| `communication_bus.py` | AgentCommunicationBus — agent'lar arası mesaj kuyruğu (REQUEST/RESPONSE/DEBATE/ALERT/CONTEXT), ConflictResolver (majority vote + confidence tiebreak + debate consensus + risk veto) |
| `synthesis_engine.py` | SynthesisEngine — tüm agent sonuçlarını birleştirir, confidence-weighted scoring, LLM sentez (opsiyonel), final direction/confidence belirleme |
| `risk_assessor.py` | RiskAssessor — volatilite/likidite/konsantrasyon/makro risk değerlendirmesi, CRITICAL veto, pozisyon boyutu ve stop-loss hesaplama |
| `agent_memory.py` | AgentMemory (3 katmanlı: Working/Episodic/Semantic), MemoryConsolidator (periyodik temizlik), outcome tracking, confidence calibration |
| `self_evaluator.py` | AgentSelfEvaluator — accuracy, calibration, drift detection, overconfidence check, recommendation (OK/RETRAIN/RECALIBRATE/INVESTIGATE_DRIFT), MultiAgentEvaluator (toplu rapor) |
| `prompts/__init__.py` | PromptFactory — 12 prompt şablonu (technical, fundamental, news, macro, bull_tur1-3, bear_tur1-3, risk, synthesis), BIST-specific kurallar, version tracking |
| `schemas/__init__.py` | Pydantic şemaları — Direction, RiskLevel enum'ları, AgentOutputSchema, TechnicalOutputSchema, FundamentalOutputSchema, NewsOutputSchema, MacroOutputSchema, DebateArgumentSchema, RiskAssessmentSchema, SynthesisResultSchema |

## Tasarım İlkeleri ve Kırmızı Çizgiler

1. **LLM yoksa sistem durmaz** — Her LLM çağrısında fallback: `AIFallback.rule_based_analysis()`. Sistem hiçbir zaman "LLM yok" diye çökmez.
2. **Hallucination koruması zorunlu** — LLM çıktısı 5 katmandan geçmeden kabul edilmez: JSON parse → Pydantic → range → domain → source.
3. **Confidence 0-1 aralığında** — 100 üzerinden gelen değerler otomatik /100'e normalize edilir.
4. **Risk veto geri alınamaz** — CRITICAL risk seviyesinde `approved=False` → NO_TRADE. Hiçbir agent bunu override edemez.
5. **Sonsuz döngü yok** — Debate max 3 tur, confidence damping her turda ×0.9.
6. **Agent tool erişimi kontrollü** — AgentToolRegistry ile her rol sadece kendi tool'larına erişebilir.
7. **Memory persistence** — Agent memory dosyaya persist edilir, restart sonrası kaybolmaz.
8. **Token bilgisi takip edilir** — Her LLM çağrısında tokens_in/tokens_out kaydedilir (maliyet takibi için).

## Bilinen Sınırlamalar

- **LLM bağımlılığı** — Rule-based fallback sınırlı analiz yapar; gerçek derinlik LLM ile gelir.
- **Debate tur sayısı sabit** — Max 3 tur, bazı karmaşık durumlarda yetersiz kalabilir.
- **Memory boyutu** — Working memory 100, episodic 1000 kayıt. Büyük hacimli trading'de eski kayıtlar atılır.
- **Prompt template sabit** — 12 şablon var, yeni agent rolleri için template eklenmesi gerekir.
- **Sentiment doğruluğu** — Keyword-based fallback sentiment (Türkçe negation handling ile) LLM kadar doğru değildir.
- **Concurrency limit** — `max_concurrent=6` (varsayılan), daha fazla agent varsa排队 olur.

## Cross-Reference

- **API katmanı** → `v1/agents.py` endpoint'leri bu modülün `AgentPipelineOrchestrator`'ını çağırır
- **Scheduler** → `daily_workflow.py` → `learning_cycle` job'u agent self-evaluation'ı tetikler
- **Alternative Data** → `feature_engine.py` → üretilen feature'lar agent context'ine beslenir
- **VIOP** → `risk_assessor.py` → VIOP pozisyon riskleri risk agent'a bilgi olarak gider
- **Feature Store** → Agent memory, feature store ile entegre çalışır (ticker bazlı bağlam)
