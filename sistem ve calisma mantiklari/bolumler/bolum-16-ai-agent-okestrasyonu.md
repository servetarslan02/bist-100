# Bölüm 16 — AI Agent Orkestrasyonu

## Amaç

Önceki bölümlerdeki analiz motorlarını yöneten, gerektiğinde paralel çalıştıran ve sonuçları birleştiren AI koordinasyon katmanı.

**Kaynak:** Agent orchestrator, tool access control, output validation.

## Çalışma mantığı

```
Kullanıcı İsteği → Agent Orchestrator → Görevleri Parçala →
Technical + Fundamental + News/KAP + Macro → Risk/Portfolio →
Cross-Check → Synthesis Agent → Final Analysis
```

### Örnek: Agent orchestrator

```python
from services.agents.agent_system import agent_orchestrator

result = await agent_orchestrator.run_research_pipeline("THYAO", context)
# results["TECHNICAL"]: {direction: "LONG", confidence: 0.8}
# results["SYNTHESIS"]: {direction: "LONG", confidence: 0.75}
```

## Temel prensip

AI agent'lar hesaplama motorlarının yerine geçmez; doğru sistemi doğru zamanda çalıştırmak ve sonuçları anlamlandırmak.
