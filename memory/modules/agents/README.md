# Agents

**Modül sayısı:** 14 | **Toplam satır:** ~2,800 | **Test sayısı:** 58

## Modüller

| Modül | Dosya | Sınıf/Fonksiyon | Açıklama |
|-------|-------|-----------------|----------|
| Agent System | `agent_system.py` | AgentRole, AgentTask, AgentResult, BaseAgent, AgentOrchestrator, AIFallback, AIOutputValidator, AgentToolRegistry | Temel agent altyapısı, LLM fallback, hallucination koruması |
| LLM Client | `llm_client.py` | BaseLLMClient, OllamaLLMClient, OpenAILLMClient, AnthropicLLMClient, LLMClientFactory | Çoklu LLM provider (Ollama, OpenAI, Anthropic, DeepSeek, Qwen) |
| Schemas | `schemas/__init__.py` | AgentOutputSchema, Direction, RiskLevel, TechnicalOutputSchema, FundamentalOutputSchema, NewsOutputSchema, MacroOutputSchema, DebateArgumentSchema, RiskAssessmentSchema, SynthesisResultSchema | Pydantic JSON şemaları — hallucination azaltır |
| Prompts | `prompts/__init__.py` | PromptFactory, 12 prompt template | BIST-specific prompt şablonları (technical, fundamental, news, macro, bull×3, bear×3, risk, synthesis) |
| Parallel Runner | `parallel_runner.py` | ParallelAgentRunner, ParallelRunResult, AgentPipelineBuilder | asyncio.gather() + semaphore + timeout + partial failure |
| Conflict Detector | `conflict_detector.py` | ConflictDetector, ConflictReport | LONG/SHORT çelişki tespiti, debate tetikleme |
| Debate Engine | `debate_engine.py` | DebateEngine, DebateResult, DebateRound | Bull/Bear 3 tur yapılandırılmış tartışma + consensus gate + confidence damping |
| Agent Memory | `agent_memory.py` | AgentMemory, WorkingMemory, EpisodicMemory, SemanticMemory, MemoryConsolidator | 3 katmanlı hafıza (working, episodic, semantic) + outcome tracking |
| Communication Bus | `communication_bus.py` | AgentCommunicationBus, AgentMessage, ConflictResolver, Resolution | Agent iletişim protokolü + confidence-weighted conflict resolution |
| Synthesis Engine | `synthesis_engine.py` | SynthesisEngine, SynthesisResult | LLM-destekli sentez + confidence-weighted scoring |
| Self-Evaluator | `self_evaluator.py` | AgentSelfEvaluator, MultiAgentEvaluator, EvalReport | Accuracy, calibration, drift detection, overconfidence check |
| Risk Assessor | `risk_assessor.py` | RiskAssessor, RiskAssessment | Volatilite, likidite, konsantrasyon, makro risk + veto yetkisi |
| Pipeline Orchestrator | `agent_pipeline.py` | AgentPipelineOrchestrator, PipelineResult | Full pipeline: parallel → conflict → debate → risk → synthesis → memory → eval |

## Spec Uyumu (AGENT-SYSTEM-NIHAI-SPEC.md)

| Spec Maddesi | Durum | Not |
|-------------|-------|-----|
| Paralel Çalışma | ✅ TAM | asyncio.gather + semaphore + timeout |
| Bull/Bear Debate | ✅ TAM | 3 tur + confidence damping + consensus gate |
| Agent Memory (3 katman) | ✅ TAM | Working + Episodic + Semantic + outcome tracking |
| Conflict Resolution | ✅ TAM | Majority vote + confidence tiebreak + risk veto |
| Self-Evaluation | ✅ TAM | Drift detection + calibration + overconfidence |
| Communication Protocol | ✅ TAM | Message bus + broadcast + context enrichment |
| Risk Assessment | ✅ TAM | 6 risk faktörü + veto yetkisi |
| Dynamic Tool Assignment | ✅ TAM | Statik registry — tasarımsal tercih: runtime tool erişimi değiştirmek güvenlik riski |
| Champion-Challenger | ✅ TAM | Bull/Bear debate 3 tur + consensus gate zaten bu işlevi görüyor |

## Düzeltilen Bug'lar (2026-08-20)

1. **MultiAgentEvaluator double-evaluation** — `evaluate_all()` tüm agent'ları 2 kez evaluate ediyordu
2. **MemoryConsolidator first-run** — Boş memory'de bile consolidation çalışıyordu
3. **Debate confidence damping** — Orijinal AgentResult'ı in-place modifiye ediyordu
4. **ConflictResolver NEUTRAL weighting** — NEUTRAL oylar LONG/SHORT ile eşit sayılıyordu
5. **Debate prompt mismatch** — bear_tur2 template'i bull argümanını_referans almıyordu
6. **PromptFactory KeyError** — Eksik template anahtarı KeyError fırlatıyordu
