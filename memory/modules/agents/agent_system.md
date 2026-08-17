# agents/agent_system

**Dosya:** `services/agents/agent_system.py`
**Satır:** 532

## Açıklama

ALPHA BIST — AI Agent System v1.0

Görev bazlı AI ajanları:
- Agent Orchestrator (pipeline yönetimi)
- Agent Tool System (erişim kontrolü)
- AI Output Validation (hallucination protection)
- AI Fallback (LLM down → rule-based)
- Prompt Versioning

FAZ 7: AI Agent System

## Sınıflar (8)

- `AgentRole`
- `AgentTask`
- `AgentResult`
- `AgentToolRegistry`
- `AIOutputValidator`
- `AIFallback`
- `BaseAgent`
- `AgentOrchestrator`

## Fonksiyonlar (7)

- `can_access()`
- `validate()`
- `rule_based_analysis()`
- `__init__()`
- `__init__()`
- `register_agent()`
- `get_recent_results()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `core/config`

