# Bölüm 16 — AI Agent Orkestrasyonu

## Amaç

Önceki bölümlerdeki analiz motorlarını yöneten, gerektiğinde paralel çalıştıran ve sonuçları birleştiren AI koordinasyon katmanı.

**Kaynak:** ScienceDirect (2026) TRiSM for Agentic AI, arXiv Multi-Agent Orchestration (2026), IMF (2026) Agentic AI in Finance.

---

## Kullanılacak sistemler

- Agent Orchestrator
- Research/Technical/Fundamental/News/Macro/Risk/Portfolio/Scenario/Backtest/Audit Agent
- Synthesis Agent
- Tool/Permission Manager
- Agent Memory

---

## Çalışma mantığı

```
Kullanıcı İsteği → Agent Orchestrator → Görevleri Parçala →
┌──────────────┬──────────────┬──────────────┐
Technical    Fundamental   News/KAP     Macro
    ↓            ↓             ↓           ↓
└──────────────┴──────────────┴──────────────┘
    ↓
Risk / Portfolio → Cross-Check → Synthesis → Final Analysis
```

---

## 1. Agent Yetkileri

**Araştırma bulgusu:** IMF (2026) — "Platforms integrating agents with multiple tools/APIs; weak access controls."

Her agent sadece izin verilen araçları kullanabilir.

### Örnek: Tool erişim kontrolü

```python
# services/agents/agent_system.py
from services.agents.agent_system import AgentToolRegistry, AgentRole

AgentToolRegistry.can_access(AgentRole.RESEARCH, "read_market_data")  # True
AgentToolRegistry.can_access(AgentRole.NEWS, "calculate_risk")  # False
```

---

## 2. Output Validation

### Örnek: Hallucination detection

```python
from services.agents.agent_system import AIOutputValidator

validation = AIOutputValidator.validate(
    '{"direction": "LONG", "confidence": 75, "reasoning": "Strong momentum"}')
# valid: True, confidence normalized to 0.75
```

---

## 3. Fallback Chain

```
Primary LLM → Secondary LLM → Rule-based → NO_TRADE
```

### Örnek: Rule-based fallback

```python
from services.agents.agent_system import AIFallback

result = AIFallback.rule_based_analysis(
    {"roc_5d": 5, "volume_zscore": 3, "rsi_14": 55}, "THYAO")
# direction: LONG, confidence: 0.65, source: rule_based_fallback
```

---

## 4. Agent Orchestrator

### Örnek: Research pipeline

```python
from services.agents.agent_system import agent_orchestrator

result = await agent_orchestrator.run_research_pipeline("THYAO", context)
# results["TECHNICAL"]: direction=LONG, confidence=0.8
# results["FUNDAMENTAL"]: direction=LONG, confidence=0.7
# results["SYNTHESIS"]: direction=LONG, confidence=0.75
```

---


## Çıktı

```
Agents Used:         8
Evidence:            42
Agreements:          31
Conflicts:           7
Unverified Claims:   2
Final Confidence:    %84
```

## Temel prensip

> "Agentic AI systems built upon LLMs and deployed in multi-agent configurations are redefining intelligence, autonomy, collaboration." — ScienceDirect TRiSM (2026)

AI agent'lar hesaplama motorlarının yerine geçmez; **doğru sistemi doğru zamanda çalıştırmak ve sonuçları anlamlandırmak**.
