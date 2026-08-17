# Agent Sistem Dokümanı — Nihai Mimari

**Tarih:** 2026-08-18
**Referanslar:** TradingAgents (TauricResearch 2025), arXiv Multi-Agent Finance (2026), OpenAI Multi-Agent Portfolio (2025), RMATS (2026)

---

## 1. Mevcut Durum

### Mevcut Agent Roller
```
RESEARCH, NEWS, MACRO, FUNDAMENTAL, TECHNICAL, RISK, PORTFOLIO, SCENARIO, BACKTEST, SYNTHESIS
```

### Mevcut Yapı
- `AgentRole` — 10 rol enum
- `AgentTask` — Görev tanımı
- `AgentResult` — Sonuç + confidence + evidence
- `AgentToolRegistry` — Tool erişim kontrolü
- `AIOutputValidator` — Hallucination protection
- `AIFallback` — LLM yoksa rule-based
- `BaseAgent` — LLM çağrı + validation + fallback
- `AgentOrchestrator` — Pipeline yönetimi (sıralı)

### Eksikler
- Paralel agent çalıştırma yok
- Agent debate/consensus mekanizması yok
- Agent memory/hafıza yok
- Agent self-evaluation yok
- Champion-challenger agent sistemi yok
- Agent drift detection yok
- Dynamic tool assignment yok
- Agent communication protocol yok

---

## 2. Nihai Agent Mimarisi

### 2.1 Agent Katmanları

```
┌─────────────────────────────────────────────────────────┐
│                 ORCHESTRATOR LAYER                       │
│  Pipeline Manager │ Conflict Resolver │ Task Scheduler   │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┼────────────────────────────────┐
│                 SYNTHESIS LAYER                          │
│  Research Manager │ Final Decision │ Explanation Engine  │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┼────────────────────────────────┐
│                 ANALYSIS LAYER                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ Valuation│  │Forecasting│  │ Monte    │              │
│  │ Agent    │  │ Agent    │  │ Carlo    │              │
│  └──────────┘  └──────────┘  └──────────┘              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ Scenario │  │ Event    │  │ Factor   │              │
│  │ Agent    │  │ Study    │  │ Agent    │              │
│  └──────────┘  └──────────┘  └──────────┘              │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┼────────────────────────────────┐
│                 RESEARCH LAYER                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │Technical │  │Fundament.│  │  News    │              │
│  │ Agent    │  │ Agent    │  │  Agent   │              │
│  └──────────┘  └──────────┘  └──────────┘              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │  Macro   │  │Sentiment │  │  KAP     │              │
│  │  Agent   │  │  Agent   │  │  Agent   │              │
│  └──────────┘  └──────────┘  └──────────┘              │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┼────────────────────────────────┐
│                 DECISION LAYER                           │
│  Signal Fusion │ Ranking │ Trade Planning               │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┼────────────────────────────────┐
│                 RISK LAYER                               │
│  Risk Gate │ Compliance │ Position Sizing │ Hedging      │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┼────────────────────────────────┐
│                 PORTFOLIO LAYER                          │
│  Execution │ Rebalancing │ Accounting │ Reconciliation  │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┼────────────────────────────────┐
│                 LEARNING LAYER                           │
│  Outcome Tracker │ Drift Detector │ Model Evolution     │
│  Performance Attribution │ Feedback Loop                │
└─────────────────────────────────────────────────────────┘
```

---

### 2.2 Agent Türleri ve Sorumlulukları

#### RESEARCH LAYER (6 Agent)

| Agent | Görev | Input | Output | Tool Erişimi |
|-------|-------|-------|--------|---------------|
| **Technical Agent** | Teknik analiz, pattern tespiti | OHLCV, indicators | direction, score, patterns | read_market_data, run_technical_analysis |
| **Fundamental Agent** | Bilanço analizi, değerleme | Financials, ratios | F-Score, M-Score, Z-Score, valuation | read_fundamentals, run_valuation |
| **News Agent** | Haber analizi, sentiment | News articles | sentiment, impact, events | read_news, read_kap |
| **Macro Agent** | Makro etki analizi | Macro data, rates | macro_score, regime_impact | read_macro_data, read_world_state |
| **Sentiment Agent** | Sosyal medya, KAP sentiment | Social data, KAP | sentiment_score, manipulation_alert | read_social, read_kap |
| **KAP Agent** | KAP açıklaması derin analiz | KAP events | event_type, impact, catalyst | read_kap, run_nlp |

#### ANALYSIS LAYER (6 Agent)

| Agent | Görev | Input | Output |
|-------|-------|-------|--------|
| **Valuation Agent** | DCF, çarpan, senaryo | Financials, market data | fair_value, upside, margin_of_safety |
| **Forecasting Agent** | Çoklu ufuk tahmin | Features, returns | 1D/5D/20D forecast, probability |
| **Monte Carlo Agent** | Simülasyon | Returns, volatility, correlation | P10/P50/P90, VaR, CVaR |
| **Scenario Agent** | Senaryo analizi | Macro shocks | portfolio_impact, sector_impact |
| **Event Study Agent** | Olay etki analizi | Events, returns | CAR, significance, impact_score |
| **Factor Agent** | Faktör skorları | Financials | F-Score, M-Score, Z-Score, factor_exposure |

#### DECISION LAYER (3 Agent)

| Agent | Görev | Input | Output |
|-------|-------|-------|--------|
| **Signal Fusion Agent** | Sinyal birleştirme | Tüm agent sonuçları | fused_score, direction, confidence |
| **Ranking Agent** | Cross-sectional sıralama | Universe features | ranked_opportunities |
| **Trade Planner Agent** | İşlem planı | Decision, risk | entry, stop, target, position_size |

#### RISK LAYER (4 Agent)

| Agent | Görev | Input | Output |
|-------|-------|-------|--------|
| **Risk Gate Agent** | Pre-trade risk kontrolü | Order, portfolio | allowed, reason |
| **Compliance Agent** | SPK uyumluluk | Order, limits | notification, violation |
| **Position Sizing Agent** | Pozisyon boyutu | Risk, capital, volatility | position_size |
| **Hedging Agent** | Hedge önerisi | Portfolio, beta | hedge_ratio, contracts |

#### PORTFOLIO LAYER (3 Agent)

| Agent | Görev | Input | Output |
|-------|-------|-------|--------|
| **Execution Agent** | Emir yürütme | Order, market | fill, slippage, commission |
| **Rebalancing Agent** | Portföy dengeleme | Portfolio, targets | rebalance_orders |
| **Accounting Agent** | Muhasebe | Trades, prices | P&L, equity, drawdown |

#### LEARNING LAYER (4 Agent)

| Agent | Görev | Input | Output |
|-------|-------|-------|--------|
| **Outcome Tracker Agent** | Sonuç takibi | Predictions, actuals | prediction_error, accuracy |
| **Drift Detector Agent** | Model bozulma tespiti | Performance history | drift_alert, degraded_models |
| **Model Evolution Agent** | Kontrollü model güncelleme | Drift, new data | champion_challenger_result |
| **Attribution Agent** | Performans attribüsyonu | Portfolio, trades | alpha, factor_contribution |

#### SYNTHESIS LAYER (2 Agent)

| Agent | Görev | Input | Output |
|-------|-------|-------|--------|
| **Research Manager Agent** | Tüm research sonuçlarını sentezle | Tüm agent çıktıları | overall_assessment, confidence |
| **Explanation Agent** | Kararın nedenini açıkla | Decision, evidence | human_readable_report |

---

### 2.3 Agent İletişim Protokolü

```python
# Agent mesaj formatı
@dataclass
class AgentMessage:
    sender: AgentRole
    receiver: AgentRole
    task_id: str
    correlation_id: str
    message_type: str  # REQUEST, RESPONSE, DEBATE, ALERT
    payload: Dict[str, Any]
    timestamp: datetime
    priority: str  # LOW, NORMAL, HIGH, CRITICAL
```

### 2.4 Agent Debate Mekanizması

```
Technical Agent: "LONG" (confidence: 0.7)
Fundamental Agent: "SHORT" (confidence: 0.6)
Macro Agent: "NEUTRAL" (confidence: 0.5)

→ Conflict Resolver:
  - Ağırlıklı oy (confidence × reliability)
  - Çelişki analizi
  - Research Manager nihai karar verir
```

### 2.5 Agent Memory

```python
class AgentMemory:
    """Her agent'ın kendi hafızası."""
    task_history: List[AgentTask]        # Geçmiş görevler
    outcome_history: List[AgentResult]   # Geçmiş sonuçlar
    accuracy_by_regime: Dict[str, float] # Rejime göre doğruluk
    learned_patterns: List[Dict]         # Öğrenilen kalıplar
    last_evaluation: datetime            # Son değerlendirme
```

### 2.6 Agent Self-Evaluation

```
Her agent periyodik olarak:
1. Geçmiş tahminlerini gerçek sonuçlarla karşılaştır
2. Hangi koşullarda başarılı/başarısız olduğunu analiz et
3. Confidence kalibrasyonunu kontrol et
4. Drift tespiti yap
5. Gerekirse model/prompt güncelleme öner
```

---

## 3. TradingAgents Karşılaştırması

| TradingAgents | Bizim Sistem | Fark |
|---------------|-------------|------|
| Research Manager | Research Manager Agent | ✅ Aynı |
| Trader | Trade Planner Agent | ✅ Aynı |
| Portfolio Manager | Portfolio Agent | ✅ Aynı |
| Risk Management Team | Risk Gate + Compliance | ✅ Aynı |
| Bull/Bear Researcher Debate | Agent Debate Mechanism | ⚠️ Bizde eksik |
| LangGraph Workflow | Orchestrator Pipeline | ⚠️ Bizde basit |
| Structured Output | AIOutputValidator | ✅ Aynı |
| Checkpoint Resume | Event Replay + Recovery | ✅ Aynı |

---

## 4. Uygulama Planı

### Faz 1: Paralel Agent Çalıştırma
- Agent'ları asyncio.gather ile paralel çalıştır
- Task queue (asyncio.Queue) ile job dağıtımı

### Faz 2: Agent Debate
- Bull/Bear researcher mekanizması
- Conflict resolver
- Confidence-weighted consensus

### Faz 3: Agent Memory
- Her agent için task history
- Regime-based accuracy tracking
- Learned patterns

### Faz 4: Agent Self-Evaluation
- Periyodik accuracy check
- Confidence calibration
- Drift detection

### Faz 5: Dynamic Tool Assignment
- Runtime'da tool erişimi değiştirme
- Regime-based tool priority

### Faz 6: Champion-Challenger
- Yeni agent versiyonu eskiyle karşılaştır
- Shadow mode
- Promote/rollback

---

## 5. Hedef Agent Sayısı

| Katman | Agent Sayısı |
|--------|-------------|
| Research | 6 |
| Analysis | 6 |
| Decision | 3 |
| Risk | 4 |
| Portfolio | 3 |
| Learning | 4 |
| Synthesis | 2 |
| **TOPLAM** | **28** |
