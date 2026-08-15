# Bölüm 14 — AI ve Agent Sistemi

## Amaç

AI'yı sistematik ve kontrollü kullanmak. "AI ne yapabilir, ne yapamaz?" sorusunun cevabı.

## Çalışma Mantığı

```
Görev → Agent seçimi → Tool erişimi → LLM çağrısı → Output validation → Sonuç
```

## Temel Prensip

AI sonucu tek başına emir olamaz. AI yalnızca **evidence, confidence, reasoning** üretir.

---

## 1. Agent Mimarisi

**Agent'lar:**
- Research Agent: Teknik + fundamental analiz
- News Agent: Haber + KAP analizi
- Macro Agent: Makro etki analizi
- Sentiment Agent: Sosyal medya analizi
- Risk Agent: Risk değerlendirmesi
- Synthesis Agent: Tüm sonuçları birleştir

**Durum:** ✅ Çalışıyor

**Dosya:** `services/agents/agent_system.py`

---

## 2. Tool System

**Amaç:** Her agent yalnızca tanımlı araçlara erişebilir.

**Araçlar:**
- read_market_data
- read_news
- read_fundamentals
- run_technical_analysis
- run_valuation
- calculate_risk
- approve_decision / reject_decision

**Durum:** ✅ Çalışıyor

**Dosya:** `services/agents/agent_system.py`

---

## 3. Output Validation

**Kontroller:**
1. JSON parse
2. Schema validation
3. Range validation (confidence 0-1, price > 0)
4. Domain validation (makul değerler)
5. Source validation (var olmayan haberi kaynak gösterme)
6. Hallucination check

**Durum:** ✅ Çalışıyor

**Dosya:** `services/agents/agent_system.py`

---

## 4. AI Fallback

**Sıra:**
1. Primary LLM (Ollama Gemma)
2. Secondary LLM (DeepSeek, Qwen)
3. Rule-based fallback
4. NO_TRADE / DEGRADED

**Durum:** ✅ Çalışıyor (rule-based fallback)

**Dosya:** `services/agents/agent_system.py`

---

## 5. Prompt Versioning

**Amaç:** Her AI prediction için versiyon bilgisi saklar.

**Veri:**
- model_version
- prompt_version
- input_hash
- feature_version
- timestamp

**Durum:** ✅ Çalışıyor

**Dosya:** `services/agents/agent_system.py`

---

## 6. Loop Control

**Amaç:** Sonsuz döngüyü önler.

**Limitler:**
- Max steps: 10
- Max retries: 3
- Timeout: 120 saniye

**Durum:** ✅ Çalışıyor

**Dosya:** `services/agents/agent_system.py`
