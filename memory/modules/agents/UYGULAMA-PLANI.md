# 🚀 Agent System Nihai Mimari — Uygulama Planı

**Tarih:** 2026-08-18
**Hazırlayan:** AI Analiz (Araştırma + Kod Analizi)
**Kaynaklar:** TradingAgents (TauricResearch v0.3.1), CGX (MDPI 2026), Apex Quant (SSRN 2026), arXiv Agentic Trading (2026), RMATS (arXiv 2026)

---

## 📋 İçindekiler

1. [Araştırma Bulguları](#1-araştırma-bulguları)
2. [Mevcut Sistem Analizi](#2-mevcut-sistem-analizi)
3. [Entegrasyon Noktaları](#3-entegrasyon-noktaları)
4. [Genel Mimarİ Tasarım](#4-genel-mimari-tasarım)
5. [Faz Planı](#5-faz-planı)
6. [Test Stratejisi](#6-test-stratejisi)
7. [Risk ve Azaltma](#7-risk-ve-azaltma)

---

## 1. Araştırma Bulguları

### 1.1 TradingAgents (TauricResearch 2025-2026) — En Olgun Referans

**Kaynak:** https://github.com/tauricresearch/tradingagents (v0.3.1, Apache-2.0)

**Mimari:**
- LangGraph tabanlı DAG workflow (node'lar = agent'lar, edge'ler = iletişim)
- Structured-output agent'lar: Research Manager, Trader, Portfolio Manager
- LangGraph checkpoint resume (crash recovery)
- Persistent decision log (audit trail)
- Multi-provider LLM desteği (OpenAI, Anthropic, Google, Groq, Ollama, DeepSeek, Qwen)

**Agent Rolleri:**
| Agent | Görev |
|-------|-------|
| Fundamentals Agent | Bilanço, değerleme analizi |
| Sentiment Agent | Sosyal medya, haber sentiment |
| Technical Agent | Teknik analiz, pattern |
| Research Manager | Tüm research sonuçlarını sentezler, structured output |
| Trader | İşlem kararı (BUY/SELL/HOLD + gerekçe) |
| Risk Management | Risk guardians — veto yetkisi |
| Portfolio Manager | Pozisyon boyutu, rebalance |

**Dersler:**
- ✅ Structured output (JSON schema) — hallucination azaltır
- ✅ Checkpoint resume — pipeline crash'ten kurtulabilir
- ✅ Decision log — her karar izlenebilir
- ⚠️ LangGraph bağımlılığı — hafif alternatif gerekebilir
- ⚠️ ABD piyasası odaklı — BIST kuralları eklenmeli

### 1.2 CGX — Consensus-Gated Execution (MDPI 2026)

**Kaynak:** MDPI Electronics 15(15):3453

**Mimari:**
- Bull Agent + Bear Agent → 3 tur yapılandırılmış tartışma
- Her tur: argüman → karşı argüman → revize pozisyon
- Consensus Gate: anlaşma yoksa NO_TRADE
- Judge agent (opsiyonel) — tartışmayı değerlendirir

**Kritik Tasarım Kararları:**
- **Maksimum tur sayısı sabit (3)** — sonsuz döngü yok
- **Consensus = aynı yön** — değilse NO_TRADE
- **Confidence damping** — her turda confidence azalabilir (şüphe artar)
- **Structured debate format** — serbest metin değil, JSON argümanlar

### 1.3 Apex Quant (SSRN 2026)

**Kaynak:** SSRN 6354961

**Mimari:**
- Multi-agent debate framework
- Her agent kendi domain'inde uzman
- Çelişki tespit → tartışma → sentez
- Final karar tüm agent'ların ağırlıklı birleşimi

**Dersler:**
- ✅ Domain-specific agent'lar (teknik, fundamental, makro ayrı)
- ✅ Conflict detection pipeline'dan önce
- ✅ Weighted synthesis (confidence'a göre ağırlık)

### 1.4 arXiv Agentic Trading Meta-Analizi (2026)

**77 çalışmanın meta-analizi — En İyi Uygulama Pipeline:**

```
PERCEPTION → MEMORY → REASONING → ACTION → LEARNING → ADAPTATION
```

**Memory Mimarisi (3 katman):**
1. **Working Memory** — anlık bağlam (son 10 işlem, mevcut rejim)
2. **Episodic Memory** — geçmiş olaylar (KAP olayları, kazançlar, kayıplar)
3. **Semantic Memory** — bilgi grafiği (sektör ilişkileri, korelasyonlar)

**Dersler:**
- ✅ Memory consolidation periyodik yapılmalı
- ✅ Self-reflection: agent kendi kararını sorgulamalı
- ✅ Meta-learning: farklı rejimlerde farklı stratejiler

---

## 2. Mevcut Sistem Analizi

### 2.1 Dosya Yapısı (İlgili Dosyalar)

```
services/agents/
├── __init__.py
└── agent_system.py          # 532 satır — mevcut implementasyon

services/core/
├── orchestrator.py           # MasterOrchestrator — pipeline orkestrasyon
├── event_bus.py              # Redis Pub/Sub + Kafka — event-driven iletişim
├── event_schema.py           # CanonicalEvent — standart event formatı
├── config.py                 # Settings — LLM, DB, broker ayarları
├── decision_engine.py        # DecisionEngine — BUY/SELL/HOLD kararı
└── risk_gate.py              # RiskGate — veto yetkisi

services/intelligence/
├── signal_fusion.py          # SignalFusionEngine — sinyal birleştirme
├── regime.py                 # RegimeEngine — rejim tespiti
├── spec_engine.py            # SpecEngine — SPEC skoru
├── monte_carlo.py            # MonteCarloEngine — simülasyon
├── forecasting.py            # ForecastingEngine — tahmin
└── knowledge_graph.py        # KnowledgeGraph — bilgi grafiği

services/features/
├── seven_motors.py           # 9 motor, 100+ feature
└── calculator.py             # Feature calculator

services/learning/
├── continuous_learning.py    # Sürekli öğrenme
├── outcome_tracker.py        # Sonuç takibi
└── super_intelligence.py     # Üst zekâ katmanı
```

### 2.2 Mevcut Agent Sistemi (agent_system.py) — Güçlü ve Zayıf Yönler

**✅ Sağlam Temel:**
- `AgentRole` enum — 10 rol tanımlı
- `AgentTask` / `AgentResult` dataclass — iyi yapılandırılmış
- `AgentToolRegistry` — role-based erişim kontrolü
- `AIOutputValidator` — 5 katmanlı hallucination koruması (JSON, schema, range, domain, source)
- `AIFallback` — LLM yoksa rule-based analiz (momentum, RSI, volume, trend)
- `BaseAgent.execute()` — LLM → validate → fallback zinciri
- `_call_llm()` — Ollama entegrasyonu (system prompt, JSON parse, text extraction)
- Prompt versioning + input hash (audit trail)

**❌ Kritik Eksiklikler:**
1. `AgentOrchestrator` **sıralı** çalışıyor — paralel yok
2. `run_agent_analysis()` **stub** — hiçbir şey yapmıyor
3. `agent_orchestrator` singleton **initialize edilmemiş**
4. `_call_llm()` **hardcoded Ollama** — provider abstraction yok
5. **Bull/Bear debate** yok
6. **Agent memory** yok
7. **Conflict resolution** yok
8. **Self-evaluation** yok
9. **Agent communication** yok

### 2.3 Mevcut Entegrasyon Noktaları

| Nokta | Dosya | Ne Yapıyor | Agent Entegrasyonu |
|-------|-------|------------|-------------------|
| `MasterOrchestrator.run_full_pipeline()` | orchestrator.py | Tüm servisleri çalıştırır | Agent'lar buraya entegre olmalı |
| `SignalFusionEngine.fuse_signals()` | signal_fusion.py | Sinyalleri birleştirir | Agent sonuçları buraya girmeli |
| `DecisionEngine.decide()` | decision_engine.py | BUY/SELL/HOLD kararı | Agent sentezi buraya girmeli |
| `RiskGate.check_order()` | risk_gate.py | Risk kontrolü | Risk agent buraya entegre olmalı |
| `InternalEventBus` | event_bus.py | Redis Pub/Sub | Agent sonuçları event olarak publish edilmeli |
| `ContinuousLearning` | continuous_learning.py | Sürekli öğrenme | Agent memory buraya bağlanmalı |
| `OutcomeTracker` | outcome_tracker.py | Sonuç takibi | Agent self-evaluation buradan beslenmeli |

---

## 3. Entegrasyon Noktaları

### 3.1 Pipeline Entegrasyonu (Orchestrator)

```
MEVCUT:
  market_data → features → regime → signal_fusion → decision → risk → portfolio

HEDEF:
  market_data → features → regime → [AGENT PIPELINE] → signal_fusion → decision → risk → portfolio
                                    ↑
                                    Parallel Research → Conflict Detection →
                                    Bull/Bear Debate → Risk Assessment →
                                    Synthesis → Memory → Self-Evaluation
```

### 3.2 Event Bus Entegrasyonu

```python
# Agent sonuçları event olarak publish edilmeli
event_bus.publish("agent.analysis.completed", CanonicalEvent(
    event_type="agent.analysis.completed",
    payload={
        "ticker": ticker,
        "direction": synthesis.direction,
        "confidence": synthesis.confidence,
        "debate_result": debate_result,
        "agent_results": {r.role: r.output for r in results},
    }
))

# Decision engine bu event'i dinleyebilir
@event_bus.subscribe("agent.analysis.completed")
async def on_agent_analysis(event):
    # Signal fusion'a agent sonuçlarını ekle
    pass
```

### 3.3 Config Entegrasyonu

```python
# services/core/config.py'ya eklenecek
class AgentSettings(BaseModel):
    # Agent LLM
    agent_llm_provider: str = "ollama"  # ollama, openai, anthropic
    agent_llm_model: str = "gemma4:12b-q4_0"
    agent_llm_temperature: float = 0.3
    agent_llm_max_tokens: int = 2048

    # Debate
    debate_max_rounds: int = 3
    debate_consensus_threshold: float = 0.6
    debate_confidence_damping: float = 0.9  # her turda confidence azalır

    # Memory
    memory_max_task_history: int = 1000
    memory_max_outcome_history: int = 5000
    memory_consolidation_interval_hours: int = 24

    # Parallel
    agent_max_concurrent: int = 6
    agent_timeout_seconds: int = 120

    # Self-evaluation
    self_eval_interval_hours: int = 168  # haftalık
    self_eval_drift_threshold: float = 0.1
    self_eval_min_samples: int = 30
```

---

## 4. Genel Mimari Tasarım

### 4.1 Nihai Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│                     ALPHA BIST — AGENT PIPELINE v2.0                │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 1: PARALLEL RESEARCH (asyncio.gather)                 │   │
│  │                                                              │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │   │
│  │  │Technical │ │Fundament.│ │  News    │ │  Macro   │       │   │
│  │  │ Agent    │ │ Agent    │ │  Agent   │ │  Agent   │       │   │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘       │   │
│  │       └─────────────┴────────────┴─────────────┘             │   │
│  │                          ↓                                    │   │
│  │  ┌──────────────────────────────────────────────────────┐    │   │
│  │  │  AgentCommunicationBus — sonuçları topla             │    │   │
│  │  └──────────────────────────────────────────────────────┘    │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 2: CONFLICT DETECTION                                 │   │
│  │  - LONG sayısı vs SHORT sayısı                              │   │
│  │  - Çelişki var mı?                                          │   │
│  │  - Çelişki yoksa → PHASE 5 (Synthesis)                     │   │
│  │  - Çelişki varsa → PHASE 3 (Debate)                        │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 3: BULL/BEAR DEBATE (3 tur, CGX protokolü)           │   │
│  │                                                              │   │
│  │  Tur 1: Bull argüman → Bear karşı argüman                   │   │
│  │  Tur 2: Bear argüman → Bull karşı argüman                   │   │
│  │  Tur 3: Son pozisyonlar                                     │   │
│  │                                                              │   │
│  │  Consensus Gate: anlaşma yoksa NO_TRADE                     │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 4: RISK ASSESSMENT                                    │   │
│  │  - Risk agent tüm sonuçları değerlendirir                   │   │
│  │  - Volatilite, likidite, konsantrasyon kontrolü             │   │
│  │  - Risk veto yetkisi                                        │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 5: SYNTHESIS (Gelişmiş)                               │   │
│  │  - Conflict analysis                                        │   │
│  │  - Confidence-weighted sentez                               │   │
│  │  - Neden-sonuç açıklaması                                   │   │
│  │  - Final direction + confidence                             │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 6: MEMORY & LEARNING                                  │   │
│  │  - Working memory güncelle                                  │   │
│  │  - Episodic memory kaydet                                   │   │
│  │  - Semantic memory (knowledge graph) güncelle               │   │
│  │  - Outcome tracker'a gönder                                 │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ↓                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PHASE 7: SELF-EVALUATION (periyodik)                        │   │
│  │  - Accuracy check                                           │   │
│  │  - Confidence calibration                                   │   │
│  │  - Regime-based performans                                  │   │
│  │  - Drift detection                                          │   │
│  │  - Agent tuning önerileri                                   │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 Dosya Yapısı (Hedef)

```
services/agents/
├── __init__.py
├── agent_system.py              # MEVCUT — refactor edilecek
├── parallel_runner.py           # YENİ — Phase 1: asyncio.gather
├── conflict_detector.py         # YENİ — Phase 2: çelişki tespit
├── debate_engine.py             # YENİ — Phase 3: Bull/Bear debate
├── risk_assessor.py             # YENİ — Phase 4: Risk agent
├── synthesis_engine.py          # YENİ — Phase 5: Gelişmiş sentez
├── agent_memory.py              # YENİ — Phase 6: 3 katmanlı memory
├── self_evaluator.py            # YENİ — Phase 7: Self-evaluation
├── communication_bus.py         # YENİ — Agent iletişim protokolü
├── llm_client.py                # YENİ — Provider abstraction
├── prompts/                     # YENİ — Prompt şablonları
│   ├── __init__.py
│   ├── technical.py
│   ├── fundamental.py
│   ├── news.py
│   ├── macro.py
│   ├── bull.py
│   ├── bear.py
│   ├── risk.py
│   └── synthesis.py
└── schemas/                     # YENİ — JSON şemaları
    ├── __init__.py
    ├── agent_output.py
    ├── debate_argument.py
    └── synthesis_result.py
```

---

## 5. Faz Planı

### FAZ 0: Temel Altyapı (1-2 gün)

**Amaç:** Mevcut kodu refactor et, temel altyapıyı hazırla.

#### 0.1 — LLM Client Abstraction
```
Dosya: services/agents/llm_client.py
```
- [ ] `BaseLLMClient` abstract class oluştur
- [ ] `OllamaLLMClient` — mevcut `_call_llm()`'yi taşı
- [ ] `OpenAILLMClient` — OpenAI API desteği
- [ ] `AnthropicLLMClient` — Claude API desteği
- [ ] `LLMClientFactory` — config'den provider seçimi
- [ ] Retry mekanizması (exponential backoff)
- [ ] Timeout yönetimi
- [ ] Token counting + maliyet takibi

**Gerekçe:** `_call_llm()` hardcoded Ollama — multi-provider desteklenmeli. TradingAgents'ta 10+ provider var.

#### 0.2 — JSON Schema Tanımları
```
Dosya: services/agents/schemas/
```
- [ ] `AgentOutputSchema` — direction, confidence, score, reasoning, reasons, risks
- [ ] `DebateArgumentSchema` — position, evidence, counterarguments, confidence
- [ ] `SynthesisResultSchema` — final_direction, confidence, agent_summary, conflict_analysis
- [ ] `AgentMessageSchema` — sender, receiver, type, payload, timestamp
- [ ] Pydantic model'ler ile validation

**Gerekçe:** Structured output hallucination'ı azaltır (TradingAgents deneyimi).

#### 0.3 — Prompt Şablonları
```
Dosya: services/agents/prompts/
```
- [ ] `TechnicalPrompt` — teknik analiz promptu (RSI, MACD, trend, pattern)
- [ ] `FundamentalPrompt` — fundamental analiz promptu (PE, PB, FCF, bilanço)
- [ ] `NewsPrompt` — haber/KAP analiz promptu (sentiment, olay etkisi)
- [ ] `MacroPrompt` — makro analiz promptu (rejim, faiz, kur, enflasyon)
- [ ] `BullPrompt` — bull argüman promptu (yükseliş tezi)
- [ ] `BearPrompt` — bear argüman promptu (düşüş tezi)
- [ ] `RiskPrompt` — risk değerlendirme promptu
- [ ] `SynthesisPrompt` — sentez promptu (tüm sonuçları birleştir)
- [ ] Version tracking (v1, v2, ...)
- [ ] BIST-specific kurallar (açığa satış yasağı, fiyat limitleri, BIST-100 endeksi)

**Gerekçe:** Prompt kalitesi doğrudan çıktı kalitesini etkiler. Standartlaştırma gerekli.

#### 0.4 — Mevcut Kod Refactor
```
Dosya: services/agents/agent_system.py
```
- [ ] `run_agent_analysis()` stub'ını gerçek implementasyona çevir
- [ ] `agent_orchestrator` singleton'ını initialize et
- [ ] `_call_llm()`'yi `LLMClient`'a yönlendir
- [ ] `BaseAgent.execute()`'ı async yap (zaten async ama gerçekten await yok)
- [ ] Test'leri güncelle

**Teslimat:** `pytest tests/test_agent_faz0.py` — tüm testler yeşil

---

### FAZ 1: Paralel Çalışma (2-3 gün)

**Amaç:** Agent'ları paralel çalıştır, toplam süreyi minimize et.

#### 1.1 — Parallel Runner
```
Dosya: services/agents/parallel_runner.py
```
```python
class ParallelAgentRunner:
    """Agent'ları paralel çalıştırır."""

    def __init__(self, max_concurrent: int = 6, timeout: int = 120):
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def run_agents(
        self,
        agents: Dict[AgentRole, BaseAgent],
        tasks: Dict[AgentRole, AgentTask],
        llm_client: Optional[BaseLLMClient] = None,
    ) -> Dict[AgentRole, AgentResult]:
        """Tüm agent'ları paralel çalıştır."""

        async def _run_one(role: AgentRole, agent: BaseAgent, task: AgentTask):
            async with self._semaphore:
                return await asyncio.wait_for(
                    agent.execute(task, llm_client),
                    timeout=self.timeout
                )

        # asyncio.gather ile paralel
        results = await asyncio.gather(
            *[_run_one(role, agents[role], tasks[role]) for role in agents],
            return_exceptions=True
        )

        # Sonuçları eşle
        agent_results = {}
        for role, result in zip(agents.keys(), results):
            if isinstance(result, Exception):
                logger.error("Agent failed", role=role, error=str(result))
                agent_results[role] = AgentResult(
                    task_id=tasks[role].task_id,
                    agent_role=role,
                    ticker=tasks[role].ticker,
                    success=False,
                    output={},
                    confidence=0.0,
                    evidence=[],
                    reasoning="",
                    model_version="",
                    prompt_version="",
                    input_hash="",
                    duration_ms=0,
                    error=str(result),
                )
            else:
                agent_results[role] = result

        return agent_results
```

**Tasarım Kararları:**
- `asyncio.gather(return_exceptions=True)` — bir agent çökse diğerleri devam eder
- `asyncio.Semaphore(max_concurrent)` — LLM rate limit'e çarpmamak için
- `asyncio.wait_for(timeout)` — takılan agent'ı kes

#### 1.2 — Orchestrator Entegrasyonu
```
Dosya: services/core/orchestrator.py (değişiklik)
```
- [ ] `MasterOrchestrator.run_full_pipeline()`'a agent pipeline ekle
- [ ] Mevcut `signal_fusion` yerine veya onun yanında agent sonuçlarını kullan
- [ ] Feature'lar hazır olduktan sonra agent'ları tetikle
- [ ] Agent sonuçlarını `PipelineReport`'a ekle

**Entegrasyon Noktası:**
```python
# orchestrator.py — run_full_pipeline() içinde

# ... mevcut feature hesaplama ...

# === AGENT PIPELINE (YENİ) ===
from services.agents.parallel_runner import ParallelAgentRunner
from services.agents.agent_system import AgentRole, BaseAgent, AgentTask

runner = ParallelAgentRunner(max_concurrent=6, timeout=120)
agents = {role: BaseAgent(role) for role in [
    AgentRole.TECHNICAL, AgentRole.FUNDAMENTAL,
    AgentRole.NEWS, AgentRole.MACRO
]}
tasks = {role: AgentTask(...) for role in agents}

agent_results = await runner.run_agents(agents, tasks, llm_client)
# agent_results'ı signal_fusion'a veya doğrudan decision_engine'e besle
```

#### 1.3 — Partial Failure Handling
- [ ] Başarısız agent için fallback (rule-based)
- [ ] Kısmi sonuçlarla devam etme (3/4 agent başarılı = devam)
- [ ] Hata logları + monitoring

**Teslimat:** `pytest tests/test_agent_faz1.py` — paralel çalıştığını doğrula

---

### FAZ 2: Bull/Bear Debate (3-4 gün)

**Amaç:** Çelişkili sinyalleri yapılandırılmış tartışmayla çöz.

#### 2.1 — Conflict Detector
```
Dosya: services/agents/conflict_detector.py
```
```python
class ConflictDetector:
    """Agent sonuçları arasında çelişki tespit eder."""

    def detect(self, results: Dict[AgentRole, AgentResult]) -> ConflictReport:
        directions = {}
        for role, result in results.items():
            if not result.success:
                continue
            direction = result.output.get("direction", "NEUTRAL")
            if direction not in directions:
                directions[direction] = []
            directions[direction].append(role)

        long_count = len(directions.get("LONG", []))
        short_count = len(directions.get("SHORT", []))

        has_conflict = long_count > 0 and short_count > 0
        is_unanimous = len(directions) == 1

        return ConflictReport(
            has_conflict=has_conflict,
            is_unanimous=is_unanimous,
            long_agents=directions.get("LONG", []),
            short_agents=directions.get("SHORT", []),
            neutral_agents=directions.get("NEUTRAL", []),
            requires_debate=has_conflict,
        )
```

#### 2.2 — Debate Engine (CGX Protokolü)
```
Dosya: services/agents/debate_engine.py
```
```python
class DebateEngine:
    """Bull/Bear debate — CGX protokolü (MDPI 2026)."""

    def __init__(self, max_rounds: int = 3, confidence_damping: float = 0.9):
        self.max_rounds = max_rounds
        self.confidence_damping = confidence_damping

    async def run_debate(
        self,
        bull_agent: BaseAgent,
        bear_agent: BaseAgent,
        context: Dict[str, Any],
        llm_client: Optional[BaseLLMClient] = None,
    ) -> DebateResult:
        """3 tur Bull/Bear tartışması."""
        history = []

        for round_num in range(self.max_rounds):
            # Bull argüman
            bull_prompt = self._create_bull_prompt(history, context)
            bull_task = AgentTask(
                task_id=f"bull-r{round_num}",
                agent_role=AgentRole.TECHNICAL,
                ticker=context.get("ticker", ""),
                prompt=bull_prompt,
                context=context,
            )
            bull_result = await bull_agent.execute(bull_task, llm_client)

            # Bear cevap
            bear_prompt = self._create_bear_prompt(bull_result, history, context)
            bear_task = AgentTask(
                task_id=f"bear-r{round_num}",
                agent_role=AgentRole.TECHNICAL,
                ticker=context.get("ticker", ""),
                prompt=bear_prompt,
                context=context,
            )
            bear_result = await bear_agent.execute(bear_task, llm_client)

            # Confidence damping
            bull_result.confidence *= self.confidence_damping ** round_num
            bear_result.confidence *= self.confidence_damping ** round_num

            history.append(DebateRound(
                round=round_num,
                bull_direction=bull_result.output.get("direction"),
                bull_confidence=bull_result.confidence,
                bull_reasoning=bull_result.reasoning,
                bear_direction=bear_result.output.get("direction"),
                bear_confidence=bear_result.confidence,
                bear_reasoning=bear_result.reasoning,
            ))

        # Consensus kontrolü
        final_bull = history[-1].bull_direction
        final_bear = history[-1].bear_direction

        if final_bull == final_bear:
            consensus = final_bull
            consensus_confidence = (
                history[-1].bull_confidence + history[-1].bear_confidence
            ) / 2
        else:
            consensus = "NO_TRADE"
            consensus_confidence = 0.0

        return DebateResult(
            consensus=consensus,
            consensus_confidence=round(consensus_confidence, 4),
            rounds=history,
            agreement=final_bull == final_bear,
            total_rounds=len(history),
        )
```

**CGX Protokolü Kuralları:**
1. **Maksimum 3 tur** — sonsuz döngü yok
2. **Structured output** — her argüman JSON formatında
3. **Confidence damping** — her turda `confidence *= 0.9` (şüphe artar)
4. **Consensus Gate** — anlaşma yoksa NO_TRADE
5. **NO_TRADE default** — belirsizlik varsa işlem yok

#### 2.3 — Bull/Bear Prompt Mühendisliği
```
Dosya: services/agents/prompts/bull.py, bear.py
```

**Bull Prompt (Tur 1):**
```
Sen bir BULL analyst'sin. {ticker} hissesi için YÜKSELİŞ argümanlarını sun.

Veriler:
- Fiyat: {price}
- RSI: {rsi}
- Son 5 gün getiri: {roc_5d}%
- Hacim z-score: {volume_zscore}
- Haber sentiment: {news_sentiment}

Kurallar:
- Sadece verilen verilere dayan
- Her argüman için kanıt göster
- JSON formatında yanıt ver

Format:
{
  "direction": "LONG",
  "confidence": 0.7,
  "reasoning": "...",
  "evidence": ["...", "..."],
  "risks": ["..."]
}
```

**Bear Prompt (Tur 1 — Bull'a cevap):**
```
Sen bir BEAR analyst'sin. {ticker} hissesi için DÜŞÜŞ argümanlarını sun.

Bull argümanı: {bull_reasoning}

Bu argümanları çürüterek DÜŞÜŞ tezini savun.
Kurallar:
- Bull'un her argümanını tek tek ele al
- Karşı kanıt göster
- JSON formatında yanıt ver
```

#### 2.4 — Orchestrator Entegrasyonu
- [ ] Conflict detection → debate gate
- [ ] Debate yoksa mevcut sentez akışı
- [ ] Debate varsa sonucu senteze besle

**Teslimat:** `pytest tests/test_agent_faz2.py` — debate sonucu consensus/no_trade

---

### FAZ 3: Agent Memory (3-4 gün)

**Amaç:** Agent'lar geçmiş deneyimlerinden öğrensin.

#### 3.1 — Agent Memory System
```
Dosya: services/agents/agent_memory.py
```

**3 Katmanlı Memory (arXiv Agentic Trading 2026):**

```python
class AgentMemory:
    """3 katmanlı agent hafızası."""

    def __init__(self, agent_role: AgentRole, max_history: int = 1000):
        self.agent_role = agent_role

        # 1. Working Memory — anlık bağlam
        self.working_memory = WorkingMemory(max_items=100)

        # 2. Episodic Memory — geçmiş olaylar
        self.episodic_memory = EpisodicMemory(max_items=max_history)

        # 3. Semantic Memory — bilgi grafiği
        self.semantic_memory = SemanticMemory()

    def record_task(self, task: AgentTask, result: AgentResult):
        """Görev kaydet (tüm katmanlara)."""
        # Working memory — son 100 görev
        self.working_memory.add(task, result)

        # Episodic memory — önemli olaylar
        if result.confidence > 0.7 or not result.success:
            self.episodic_memory.add(task, result)

    def record_outcome(self, task_id: str, actual_return: float, regime: str):
        """Sonuç kaydet — accuracy tracking."""
        self.episodic_memory.record_outcome(task_id, actual_return, regime)

    def get_context_for_task(self, ticker: str, regime: str) -> Dict:
        """Yeni görev için bağlam oluştur."""
        return {
            "recent_tasks": self.working_memory.get_recent(ticker, limit=5),
            "similar_events": self.episodic_memory.get_similar(ticker, regime),
            "learned_patterns": self.semantic_memory.get_patterns(ticker, regime),
            "accuracy_by_regime": self.episodic_memory.get_accuracy_by_regime(),
        }


class WorkingMemory:
    """Anlık bağlam — son N görev."""

    def __init__(self, max_items: int = 100):
        self.items: List[Dict] = []
        self.max_items = max_items

    def add(self, task: AgentTask, result: AgentResult):
        self.items.append({
            "task_id": task.task_id,
            "ticker": task.ticker,
            "direction": result.output.get("direction"),
            "confidence": result.confidence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if len(self.items) > self.max_items:
            self.items = self.items[-self.max_items:]

    def get_recent(self, ticker: str = None, limit: int = 10) -> List[Dict]:
        items = self.items
        if ticker:
            items = [i for i in items if i["ticker"] == ticker]
        return items[-limit:]


class EpisodicMemory:
    """Geçmiş olaylar — outcome tracking ile."""

    def __init__(self, max_items: int = 1000):
        self.episodes: List[Dict] = []
        self.outcomes: Dict[str, Dict] = {}  # task_id → outcome
        self.accuracy_by_regime: Dict[str, List[float]] = {}
        self.max_items = max_items

    def add(self, task: AgentTask, result: AgentResult):
        self.episodes.append({
            "task_id": task.task_id,
            "ticker": task.ticker,
            "direction": result.output.get("direction"),
            "confidence": result.confidence,
            "reasoning": result.reasoning[:500],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if len(self.episodes) > self.max_items:
            self.episodes = self.episodes[-self.max_items:]

    def record_outcome(self, task_id: str, actual_return: float, regime: str):
        episode = next((e for e in self.episodes if e["task_id"] == task_id), None)
        if not episode:
            return

        predicted = episode["direction"]
        correct = (
            (predicted == "LONG" and actual_return > 0) or
            (predicted == "SHORT" and actual_return < 0)
        )

        self.outcomes[task_id] = {
            "predicted": predicted,
            "actual_return": actual_return,
            "correct": correct,
            "regime": regime,
        }

        if regime not in self.accuracy_by_regime:
            self.accuracy_by_regime[regime] = []
        self.accuracy_by_regime[regime].append(1.0 if correct else 0.0)

    def get_accuracy_by_regime(self) -> Dict[str, float]:
        return {
            regime: round(np.mean(scores), 4)
            for regime, scores in self.accuracy_by_regime.items()
            if scores
        }

    def get_similar(self, ticker: str, regime: str) -> List[Dict]:
        """Benzer olayları bul."""
        return [
            e for e in self.episodes
            if e["ticker"] == ticker
        ][-5:]


class SemanticMemory:
    """Bilgi grafiği — öğrenilen kalıplar."""

    def __init__(self):
        self.patterns: Dict[str, List[Dict]] = {}  # ticker → patterns
        self.regime_patterns: Dict[str, List[Dict]] = {}  # regime → patterns

    def add_pattern(self, ticker: str, regime: str, pattern: Dict):
        if ticker not in self.patterns:
            self.patterns[ticker] = []
        self.patterns[ticker].append(pattern)

        if regime not in self.regime_patterns:
            self.regime_patterns[regime] = []
        self.regime_patterns[regime].append(pattern)

    def get_patterns(self, ticker: str, regime: str) -> List[Dict]:
        ticker_patterns = self.patterns.get(ticker, [])
        regime_patterns = self.regime_patterns.get(regime, [])
        return ticker_patterns[-5:] + regime_patterns[-3:]
```

#### 3.2 — Memory Consolidation
```python
class MemoryConsolidator:
    """Periyodik memory consolidation — gereksiz bilgiyi temizle."""

    def __init__(self, consolidation_interval_hours: int = 24):
        self.interval = consolidation_interval_hours

    async def consolidate(self, memory: AgentMemory):
        """Memory'yi temizle ve özetle."""
        # 1. Eski working memory'yi episodic'e taşı
        old_items = memory.working_memory.get_older_than(hours=self.interval)
        for item in old_items:
            if item["confidence"] > 0.6:
                memory.episodic_memory.add_from_cache(item)

        # 2. Başarısız pattern'ları semantic memory'den kaldır
        memory.semantic_memory.prune_low_accuracy(threshold=0.4)

        # 3. Accuracy istatistiklerini güncelle
        memory.episodic_memory.update_statistics()
```

#### 3.3 — Outcome Tracker Entegrasyonu
- [ ] Mevcut `OutcomeTracker`'a agent outcome'larını ekle
- [ ] Agent memory ile learning loop arasında köprü
- [ ] Regime-based performans tracking

**Teslimat:** `pytest tests/test_agent_faz3.py` — memory kayıt/okuma/consolidation

---

### FAZ 4: Conflict Resolution & Synthesis (2-3 gün)

**Amaç:** Çelişkili sinyalleri akıllıca çöz, gelişmiş sentez yap.

#### 4.1 — Conflict Resolver
```
Dosya: services/agents/communication_bus.py (içinde)
```
```python
class ConflictResolver:
    """Agent çelişki çözümü — confidence-weighted voting."""

    def resolve(self, results: Dict[AgentRole, AgentResult]) -> Resolution:
        # Geçerli sonuçları filtrele
        valid = {r: res for r, res in results.items() if res.success}
        if not valid:
            return Resolution(direction="NO_TRADE", confidence=0, method="no_valid_results")

        # Yön bazlı gruplama
        direction_groups = {}
        for role, result in valid.items():
            direction = result.output.get("direction", "NEUTRAL")
            if direction not in direction_groups:
                direction_groups[direction] = []
            direction_groups[direction].append((role, result))

        # En çok oy alan yön
        vote_counts = {d: len(v) for d, v in direction_groups.items()}
        max_votes = max(vote_counts.values())
        top_directions = [d for d, v in vote_counts.items() if v == max_votes]

        if len(top_directions) == 1:
            # Net çoğunluk
            final = top_directions[0]
            confidences = [r.confidence for _, r in direction_groups[final]]
            confidence = np.mean(confidences)
            method = "majority_vote"
        else:
            # Beraberlik — confidence'a göre
            best_dir = None
            best_conf = 0
            for d in top_directions:
                avg_conf = np.mean([r.confidence for _, r in direction_groups[d]])
                if avg_conf > best_conf:
                    best_conf = avg_conf
                    best_dir = d
            final = best_dir
            confidence = best_conf * 0.8  # Beraberlik cezası
            method = "confidence_tiebreak"

        return Resolution(
            direction=final,
            confidence=round(confidence, 4),
            method=method,
            vote_distribution=vote_counts,
            conflict=len(top_directions) > 1,
        )
```

#### 4.2 — Gelişmiş Synthesis Engine
```
Dosya: services/agents/synthesis_engine.py
```
```python
class SynthesisEngine:
    """Tüm agent sonuçlarını birleştiren gelişmiş sentez."""

    async def synthesize(
        self,
        agent_results: Dict[AgentRole, AgentResult],
        debate_result: Optional[DebateResult],
        conflict_resolution: Resolution,
        agent_memory: AgentMemory,
        llm_client: Optional[BaseLLMClient] = None,
    ) -> SynthesisResult:
        """Gelişmiş sentez — LLM destekli."""

        # 1. Conflict analysis
        conflict_analysis = self._analyze_conflicts(agent_results)

        # 2. Confidence-weighted scoring
        weighted_score = self._weighted_score(agent_results)

        # 3. Memory-based adjustment
        memory_adjustment = self._memory_adjustment(
            agent_memory, agent_results
        )

        # 4. LLM synthesis (varsa)
        if llm_client:
            llm_synthesis = await self._llm_synthesize(
                agent_results, debate_result, conflict_analysis, llm_client
            )
        else:
            llm_synthesis = None

        # 5. Final decision
        if debate_result and not debate_result.agreement:
            final_direction = "NO_TRADE"
            final_confidence = 0.0
        else:
            final_direction = conflict_resolution.direction
            final_confidence = conflict_resolution.confidence

        return SynthesisResult(
            ticker=list(agent_results.values())[0].ticker if agent_results else "",
            final_direction=final_direction,
            final_confidence=final_confidence,
            weighted_score=weighted_score,
            conflict_analysis=conflict_analysis,
            debate_result=debate_result,
            memory_adjustment=memory_adjustment,
            llm_synthesis=llm_synthesis,
            agent_summary={
                role.value: {
                    "direction": r.output.get("direction"),
                    "confidence": r.confidence,
                    "success": r.success,
                }
                for role, r in agent_results.items()
            },
        )
```

#### 4.3 — Agent Communication Bus
```
Dosya: services/agents/communication_bus.py
```
```python
class AgentCommunicationBus:
    """Agent'lar arası iletişim."""

    def __init__(self):
        self._message_queue: Dict[AgentRole, List[AgentMessage]] = {
            role: [] for role in AgentRole
        }

    def send(self, message: AgentMessage):
        self._message_queue[message.receiver].append(message)

    def receive(self, role: AgentRole) -> List[AgentMessage]:
        messages = self._message_queue.get(role, [])
        self._message_queue[role] = []
        return messages

    def broadcast(self, sender: AgentRole, msg_type: str, payload: Dict):
        for role in AgentRole:
            if role != sender:
                self.send(AgentMessage(
                    sender=sender, receiver=role,
                    task_id="broadcast", message_type=msg_type,
                    payload=payload,
                ))

    def get_context_enrichment(self, role: AgentRole) -> Dict:
        """Bu agent için diğer agent'lardan gelen bağlamı topla."""
        messages = self.receive(role)
        return {
            "peer_insights": [
                {"from": m.sender.value, "data": m.payload}
                for m in messages if m.message_type == "CONTEXT"
            ],
            "alerts": [
                {"from": m.sender.value, "data": m.payload}
                for m in messages if m.message_type == "ALERT"
            ],
        }
```

**Teslimat:** `pytest tests/test_agent_faz4.py` — conflict resolution + synthesis

---

### FAZ 5: Self-Evaluation & Drift Detection (2-3 gün)

**Amaç:** Agent'lar kendi performanslarını değerlendirsin, drift tespit edilsin.

#### 5.1 — Self-Evaluator
```
Dosya: services/agents/self_evaluator.py
```
```python
class AgentSelfEvaluator:
    """Agent self-evaluation — periyodik performans kontrolü."""

    def __init__(
        self,
        drift_threshold: float = 0.1,
        min_samples: int = 30,
        calibration_bins: int = 5,
    ):
        self.drift_threshold = drift_threshold
        self.min_samples = min_samples
        self.calibration_bins = calibration_bins

    def evaluate(self, memory: AgentMemory, regime: str = None) -> EvalReport:
        """Agent performansını değerlendir."""

        # 1. Accuracy
        accuracy = memory.episodic_memory.get_accuracy(regime)

        # 2. Confidence calibration
        calibration = self._check_calibration(memory)

        # 3. Drift detection
        drift = self._detect_drift(memory)

        # 4. Overconfidence check
        overconfident = self._check_overconfidence(calibration)

        # 5. Recommendation
        recommendation = self._recommend(accuracy, drift, overconfident)

        return EvalReport(
            agent_role=memory.agent_role,
            accuracy=accuracy,
            calibration=calibration,
            drift_detected=drift,
            overconfident=overconfident,
            total_tasks=len(memory.episodic_memory.episodes),
            total_outcomes=len(memory.episodic_memory.outcomes),
            recommendation=recommendation,
        )

    def _check_calibration(self, memory: AgentMemory) -> Dict:
        """Confidence kalibrasyonu — beklenen vs gerçek doğruluk."""
        outcomes = memory.episodic_memory.outcomes
        if len(outcomes) < self.min_samples:
            return {"calibrated": False, "reason": "insufficient_data"}

        episodes = memory.episodic_memory.episodes
        bins = np.linspace(0, 1, self.calibration_bins + 1)
        calibration = []

        for i in range(len(bins) - 1):
            matching = [
                e for e in episodes
                if bins[i] <= e.get("confidence", 0) < bins[i+1]
                and e["task_id"] in outcomes
            ]
            if matching:
                avg_conf = np.mean([e["confidence"] for e in matching])
                actual_acc = np.mean([
                    outcomes[e["task_id"]]["correct"] for e in matching
                ])
                calibration.append({
                    "bin": f"{bins[i]:.1f}-{bins[i+1]:.1f}",
                    "avg_confidence": round(avg_conf, 4),
                    "actual_accuracy": round(actual_acc, 4),
                    "miscalibration": round(abs(avg_conf - actual_acc), 4),
                    "count": len(matching),
                })

        return {"calibrated": True, "calibration": calibration}

    def _detect_drift(self, memory: AgentMemory) -> bool:
        """Performans drift'i tespit et."""
        outcomes = memory.episodic_memory.outcomes
        if len(outcomes) < self.min_samples * 2:
            return False

        # Son N outcome vs önceki N outcome
        outcome_list = list(outcomes.values())
        recent = outcome_list[-self.min_samples:]
        previous = outcome_list[-self.min_samples*2:-self.min_samples]

        recent_acc = np.mean([o["correct"] for o in recent])
        previous_acc = np.mean([o["correct"] for o in previous])

        return abs(recent_acc - previous_acc) > self.drift_threshold

    def _check_overconfidence(self, calibration: Dict) -> bool:
        """Overconfidence kontrolü."""
        if not calibration.get("calibrated"):
            return False
        return any(
            c.get("miscalibration", 0) > 0.15
            for c in calibration.get("calibration", [])
        )

    def _recommend(self, accuracy: float, drift: bool, overconfident: bool) -> str:
        if accuracy < 0.45:
            return "RETRAIN"
        elif drift:
            return "INVESTIGATE_DRIFT"
        elif overconfident:
            return "RECALIBRATE"
        return "OK"
```

#### 5.2 — Learning Loop Entegrasyonu
- [ ] Agent self-evaluation sonuçlarını `ContinuousLearning`'e besle
- [ ] Drift tespit edilse alarm üret
- [ ] Agent-specific tuning önerileri

#### 5.3 — Monitoring Dashboard
- [ ] Agent accuracy grafikleri
- [ ] Confidence calibration heatmap
- [ ] Debate win/loss oranı
- [ ] Drift alert'leri

**Teslimat:** `pytest tests/test_agent_faz5.py` — self-evaluation + drift detection

---

### FAZ 6: Event Bus & Orchestrator Entegrasyonu (2-3 gün)

**Amaç:** Agent sistemini mevcut event-driven mimariye tam entegre et.

#### 6.1 — Event Schema Genişletme
```
Dosya: services/core/event_schema.py (değişiklik)
```
```python
# Yeni event type'ları
AGENT_ANALYSIS_COMPLETED = "agent.analysis.completed"
AGENT_DEBATE_COMPLETED = "agent.debate.completed"
AGENT_CONFLICT_DETECTED = "agent.conflict.detected"
AGENT_RISK_VETO = "agent.risk.veto"
AGENT_EVALUATION_COMPLETED = "agent.evaluation.completed"
AGENT_DRIFT_DETECTED = "agent.drift.detected"
```

#### 6.2 — Orchestrator Tam Entegrasyon
```
Dosya: services/core/orchestrator.py (değişiklik)
```
```python
# MasterOrchestrator.run_full_pipeline() içinde

# ... mevcut feature + regime hesaplama ...

# === AGENT PIPELINE (YENİ — FAZ 6) ===
from services.agents import (
    ParallelAgentRunner, ConflictDetector, DebateEngine,
    SynthesisEngine, AgentMemory, AgentSelfEvaluator
)

# 1. Parallel research
runner = ParallelAgentRunner()
agent_results = await runner.run_agents(agents, tasks, llm_client)

# 2. Conflict detection
conflict = ConflictDetector().detect(agent_results)

# 3. Debate (varsa)
debate_result = None
if conflict.requires_debate:
    debate_result = await DebateEngine().run_debate(
        bull_agent=BaseAgent(AgentRole.TECHNICAL),
        bear_agent=BaseAgent(AgentRole.TECHNICAL),
        context=context,
        llm_client=llm_client,
    )

# 4. Conflict resolution
resolution = ConflictResolver().resolve(agent_results)

# 5. Synthesis
synthesis = await SynthesisEngine().synthesize(
    agent_results, debate_result, resolution, memory, llm_client
)

# 6. Memory update
for role, result in agent_results.items():
    memories[role].record_task(tasks[role], result)

# 7. Event publish
event_bus.publish("agent.analysis.completed", CanonicalEvent(
    event_type="agent.analysis.completed",
    payload=synthesis.to_dict(),
))

# ... mevcut signal_fusion + decision_engine ...
```

#### 6.3 — Decision Engine Entegrasyonu
```
Dosya: services/core/decision_engine.py (değişiklik)
```
- [ ] Agent sentez sonucunu `DecisionInput`'a ekle
- [ ] Agent confidence'ı decision ağırlığına dahil et
- [ ] NO_TRADE → HOLD kararı

#### 6.4 — Risk Gate Entegrasyonu
```
Dosya: services/core/risk_gate.py (değişiklik)
```
- [ ] Agent risk assessment'ını risk gate'e besle
- [ ] Agent veto yetkisi (risk agent reddederse → işlem yok)

**Teslimat:** `pytest tests/test_agent_faz6.py` — end-to-end pipeline

---

### FAZ 7: Test, Kalibrasyon ve Production Hazırlığı (3-4 gün)

**Amaç:** Sistemi production-ready yap.

#### 7.1 — Kapsamlı Test Suite
```
Dosya: tests/test_agent_system.py (genişletme)
```
- [ ] Unit test'ler: her modül için
- [ ] Integration test'ler: pipeline akışı
- [ ] Debate test'leri: consensus/no_trade senaryoları
- [ ] Memory test'leri: kayıt/okuma/consolidation
- [ ] Self-evaluation test'leri: drift/overconfidence
- [ ] Edge case test'leri: tüm agent başarısız, tek agent, timeout
- [ ] Performance test'leri: paralel vs sıralı süre karşılaştırması

#### 7.2 — Backtest Entegrasyonu
- [ ] Agent kararlarını backtest engine'e ekle
- [ ] Agent vs non-agent performans karşılaştırması
- [ ] Debate kararlarının geriye dönük analizi

#### 7.3 — Paper Trading
- [ ] Agent pipeline'ı paper trading modunda çalıştır
- [ ] Gerçek zamanlı performans takibi
- [ ] Confidence kalibrasyonu ayarla

#### 7.4 — Monitoring & Alerting
- [ ] Grafana dashboard: agent accuracy, debate stats, drift alerts
- [ ] Prometheus metrics: agent_duration_ms, debate_rounds, conflict_rate
- [ ] Alert: drift tespit edilirse, accuracy < %45 düşerse

#### 7.5 — Dokümantasyon
- [ ] Agent system README güncelle
- [ ] Her modül için docstring
- [ ] Architecture diagram
- [ ] Runbook: troubleshooting

**Teslimat:** `pytest tests/test_agent_faz7.py` — tüm testler yeşil, backtest raporu

---

## 6. Test Stratejisi

### Test Piramidi

```
         ┌─────────────┐
         │  E2E Tests   │  ← 5 test (tam pipeline)
         ├─────────────┤
         │ Integration  │  ← 15 test (modül arası)
         ├─────────────┤
         │   Unit Tests │  ← 50+ test (her fonksiyon)
         └─────────────┘
```

### Her Faz İçin Test Kriterleri

| Faz | Test Dosyası | Min Test Sayısı | Kritik Test |
|-----|-------------|-----------------|-------------|
| 0 | test_agent_faz0.py | 10 | LLM client factory |
| 1 | test_agent_faz1.py | 8 | Paralel çalıştığını doğrula |
| 2 | test_agent_faz2.py | 12 | Consensus + NO_TRADE |
| 3 | test_agent_faz3.py | 10 | Memory kayıt/okuma |
| 4 | test_agent_faz4.py | 8 | Conflict resolution |
| 5 | test_agent_faz5.py | 8 | Drift detection |
| 6 | test_agent_faz6.py | 10 | End-to-end pipeline |
| 7 | test_agent_faz7.py | 15 | Backtest + performans |

---

## 7. Risk ve Azaltma

| Risk | Olasılık | Etki | Azaltma |
|------|----------|------|---------|
| LLM yavaş/erişilemez | Yüksek | Yüksek | Rule-based fallback (mevcut), timeout, retry |
| Debate sonsuz döngü | Düşük | Kritik | Max tur sayısı sabit (3) |
| Agent çelişki çözülemez | Orta | Yüksek | NO_TRADE default — belirsizlik = işlem yok |
| Memory şişmesi | Orta | Orta | Max history limit, periyodik consolidation |
| Paralel LLM rate limit | Yüksek | Yüksek | Semaphore, exponential backoff |
| Backtest overfitting | Orta | Yüksek | Walk-forward, purge+ embargo (mevcut) |
| Prompt injection | Düşük | Kritik | AIOutputValidator (mevcut), structured output |

---

## 📊 Zaman Özeti

| Faz | Süre | Bağımlılık | Teslimat |
|-----|------|------------|----------|
| **Faz 0** | 1-2 gün | Yok | LLM client, schema, prompt'lar, refactor |
| **Faz 1** | 2-3 gün | Faz 0 | Paralel çalıştırma |
| **Faz 2** | 3-4 gün | Faz 1 | Bull/Bear debate |
| **Faz 3** | 3-4 gün | Faz 1 | Agent memory |
| **Faz 4** | 2-3 gün | Faz 2+3 | Conflict resolution + synthesis |
| **Faz 5** | 2-3 gün | Faz 3 | Self-evaluation |
| **Faz 6** | 2-3 gün | Faz 4+5 | Event bus + orchestrator entegrasyon |
| **Faz 7** | 3-4 gün | Faz 6 | Test, kalibrasyon, production |
| **TOPLAM** | **18-24 gün** | | |

**Not:** Faz 2 ve Faz 3 paralel geliştirilebilir (bağımsız). Bu durumda toplam süre **15-20 gün**'e düşer.

---

## 🔑 Kritik Tasarım Kararları

1. **NO_TRADE default** — Belirsizlik varsa işlem yok (CGX prensibi)
2. **Confidence damping** — Debate'te her turda confidence azalır (şüphe artar)
3. **Rule-based fallback** — LLM yoksa sistem durmaz (mevcut AIFallback)
4. **Structured output** — Serbest metin değil JSON (hallucination azaltır)
5. **3 katmanlı memory** — Working/Episodic/Semantic (arXiv meta-analiz)
6. **Semaphore ile paralel** — LLM rate limit'e çarpmamak için
7. **Event-driven entegrasyon** — Mevcut Redis Pub/Sub mimarisine uyum
8. **Backtest-first** — Her faz için backtest kanıtı gerekli

---

## 📚 Referanslar

1. TradingAgents v0.3.1 — https://github.com/tauricresearch/tradingagents (Apache-2.0)
2. CGX — MDPI Electronics 15(15):3453, 2026
3. Apex Quant — SSRN 6354961, 2026
4. arXiv Agentic Trading Meta-Analiz — 2604.xxxx, 2026
5. RMATS — arXiv 2605.25311, 2026
