# Bölüm 16 — AI Agent Orkestrasyonu

## Amaç

Önceki bölümlerdeki analiz motorlarını yöneten, gerektiğinde paralel çalıştıran ve sonuçları birleştiren AI koordinasyon katmanı.

---

## Kullanılacak sistemler

- Agent Orchestrator
- Research Agent
- Technical Agent
- Fundamental Agent
- News/KAP Agent
- Macro Agent
- Risk Agent
- Portfolio Agent
- Scenario Agent
- Backtest Agent
- Audit Agent
- Synthesis Agent
- Tool/Permission Manager
- Agent Memory

---

## Çalışma mantığı

```
Kullanıcı İsteği
    ↓
Agent Orchestrator
    ↓
Görevleri Parçala
    ↓
┌──────────────┬──────────────┬──────────────┐
Technical    Fundamental   News/KAP     Macro
    ↓            ↓             ↓           ↓
└──────────────┴──────────────┴──────────────┘
    ↓
Risk / Portfolio
    ↓
Cross-Check
    ↓
Synthesis Agent
    ↓
Final Analysis
```

---

## Nasıl kullanılacak?

Örneğin:

> "BIST'te şu anda en iyi fırsatları bul."

Orchestrator bunu tek AI'ya yaptırmak yerine görevlere böler:

- Technical → teknik fırsatları bul
- Fundamental → kaliteli şirketleri bul
- News/KAP → güncel catalystleri bul
- Macro → piyasa koşullarını değerlendir
- Risk → riskleri hesapla
- Portfolio → portföy etkisini hesapla

Sonra sonuçlar Synthesis Agent tarafından birleştirilir.

---

## Agent'lar birbirine körü körüne güvenmez

Örneğin Fundamental Agent:

> "Şirket çok güçlü."

derken News Agent:

> "Yeni ciddi risk var."

diyorsa sistem bunu çelişki olarak işaretler ve tekrar doğrular.

---

## Agent yetkileri

Her agent sadece izin verilen araçları kullanabilir.

Örneğin:

- Research Agent → veri/haber okuyabilir
- Risk Agent → risk hesaplayabilir
- Portfolio Agent → portföy simülasyonu yapabilir
- Audit Agent → doğrulama yapabilir

**Bir agent'ın başka bir agent'ın yetkisini devralmasına izin verilmez.**

---


---

**Kaynak:** AI Agents — tool access control. Output validation. Hallucination detection. Fallback chain.


### Örnek: Agent orchestrator

```python
# services/agents/agent_system.py
from services.agents.agent_system import agent_orchestrator

result = await agent_orchestrator.run_research_pipeline(
    ticker="THYAO",
    context={"features": features, "market_state": state},
)
# result["results"]["TECHNICAL"] = {direction: "LONG", confidence: 0.8}
# result["results"]["FUNDAMENTAL"] = {direction: "LONG", confidence: 0.7}
# result["results"]["SYNTHESIS"] = {direction: "LONG", confidence: 0.75}
# result["overall_direction"] = "LONG"
```

## Çıktı

```
Agents Used:         8
Evidence:            42
Agreements:          31
Conflicts:           7
Unverified Claims:   2
Final Confidence:    %84
```

---

## Kritik prensip

**AI agent'lar hesaplama motorlarının yerine geçmez.**

Örneğin Monte Carlo'yu AI kafasından tahmin etmez; gerçek Monte Carlo Engine'i çalıştırır.

Agent'ın görevi:

> doğru sistemi doğru zamanda çalıştırmak, sonuçları anlamlandırmak, karşılaştırmak ve açıklamak.

**Bu katman sistemin beyni/orkestratörü, diğer motorlar ise hesaplama ve veri altyapısıdır.**
