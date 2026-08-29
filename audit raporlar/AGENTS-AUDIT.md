# AGENTS SERVİSİ — KOD BAZI DENETİM RAPORU

> **Tarih:** 2026-08-29  
> **Kapsam:** services/agents/ (14 dosya, 4781 satır)  
> **Yöntem:** Satır satır kod okuma

---

## 📋 DOSYA ENVANTERİ

| # | Dosya | Satır | Amaç |
|---|---|---|---|
| 1 | `__init__.py` | 117 | Package exports |
| 2 | `agent_memory.py` | 399 | 3 katmanlı hafıza (working/episodic/semantic) |
| 3 | `agent_pipeline.py` | 287 | Full pipeline orchestrator |
| 4 | `agent_system.py` | 523 | Core agent system (BaseAgent, Orchestrator, Validator, Fallback) |
| 5 | `communication_bus.py` | 219 | Agent'lar arası iletişim + conflict resolver |
| 6 | `conflict_detector.py` | 157 | Çelişki tespiti |
| 7 | `debate_engine.py` | 310 | Bull/Bear debate (CGX protokolü) |
| 8 | `llm_client.py` | 418 | LLM client abstraction (Ollama/OpenAI/Anthropic) |
| 9 | `parallel_runner.py` | 269 | Paralel agent çalıştırma |
| 10 | `risk_assessor.py` | 224 | Risk değerlendirme agent'ı |
| 11 | `self_evaluator.py` | 260 | Self-evaluation + drift detection |
| 12 | `synthesis_engine.py` | 287 | Sonuç sentezleme |
| 13 | `prompts/__init__.py` | 413 | Prompt templates (BIST-specific) |
| 14 | `schemas/__init__.py` | 198 | Pydantic JSON schemas |

---

## 🔴 KRİTİK SORUNLAR (K-1 → K-5)

> **Güncelleme (2026-08-29):** K-1, K-2, K-3, K-4, K-5 düzeltildi.

### K-1: RISK ASSESSMENT SCHEMA — approved DEFAULT TRUE (TEHLİKELİ) ✅ DÜZELTİLDİ

`schemas/__init__.py` satır ~155:
```python
class RiskAssessmentSchema(BaseModel):
    approved: bool = True  # ← TEHLİKELİ: LLM "approved" demezse otomatik onaylı
```

**Risk:** LLM çıktısında `approved` alanı yoksa, Pydantic validation geçer ve işlem otomatik onaylanır. Bu bir risk agent'ı için kabul edilemez.

**Düzeltme:** `approved: bool = False` olmalı (fail-closed).

---

### K-2: VALIDATE_AGENT_OUTPUT — BAŞARISIZ VALIDATION'DA TRUE DÖNÜYOR ✅ DÜZELTİLDİ

`schemas/__init__.py` satır ~190:
```python
def validate_agent_output(data, schema_class=None):
    try:
        parsed = schema_class(**data)
        return True, parsed.model_dump(), []
    except Exception as e:
        errors = [str(e)]
        if "direction" in data and data["direction"] in [d.value for d in Direction]:
            return True, data, errors  # ← HATA: validation başarısız ama True dönüyor
        return False, data, errors
```

**Risk:** Pydantic validation başarısız olsa bile, `direction` alanı geçerliyse `True` dönüyor. Bu, diğer alanların (confidence, score, risk_level) doğrulanmadan kabul edilmesi demek.

---

### K-3: PARALLEL RUNNER — SUCCESS/FALLBACK YANLIŞ EŞLEŞTİRME ✅ DÜZELTİLDİ

`parallel_runner.py` satır ~175:
```python
def _create_timeout_result(self, task, role):
    return AgentResult(
        success=self.enable_fallback,  # ← Fallback varsa success=True?
        ...
    )
```

**Risk:** Timeout olmuş bir agent'ın sonucu `success=True` olarak işaretleniyor (fallback varsa). Bu, timeout olmuş agent'ın başarılı gibi sayılmasına neden olur. Conflict detector ve synthesis engine bu sonucu "başarlı" olarak değerlendirir.

**Düzeltme:** `success=False` + `fallback_available=True` ayrı field olarak.

---

### K-4: COMMUNICATION BUS — MESAJ KUYRUĞU SINIRSIZ BÜYÜYOR ✅ DÜZELTİLDİ

`communication_bus.py`:
```python
def __init__(self):
    self._message_queue: dict[AgentRole, list[AgentMessage]] = {role: [] for role in AgentRole}
    self._message_log: list[AgentMessage] = []
```

**Risk:** `broadcast()` her çağrıldığında tüm roller için mesaj oluşturur. 12 rol × her broadcast = 12 mesaj. Sık kullanılırsa bellek şişer. `_message_log` 1000 ile sınırlı ama `_message_queue` sınırsız.

---

### K-5: LLM CLIENT — API KEY LOG SIZINTISI RİSKİ ✅ DÜZELTİLDİ

`llm_client.py`:
```python
@dataclass
class LLMConfig:
    api_key: str | None = None
```

**Risk:** `LLMConfig` bir dataclass. Eğer birisi `logger.info("config", config=config)` derse, `api_key` loglanır. Structlog dataclass'ları otomatik serileştirir.

**Düzeltme:** `api_key` field'ını `repr=False` ile gizle veya `__post_init__` ile maskele.

---

## 🟠 YAPISAL SORUNLAR (O-1 → O-8)

### O-1: AGENT_SYSTEM — run_agent_analysis HER SEFERİNDE YENİ ORCHESTRATOR OLUŞTURUYOR

```python
def run_agent_analysis(ticker, features, news=None):
    orch = AgentOrchestrator()  # ← Her seferinde yeni instance
```

Singleton `agent_orchestrator` var ama kullanılmıyor. Memory ve sonuçlar kaybolur.

### O-2: AGENT_PIPELINE — _update_memories SADECE TASK KAYDEDİYOR, OUTCOME KAYDETMİYOR ✅ DÜZELTİLDİ

```python
async def _update_memories(self, ticker, results, synthesis):
    for role, result in results.items():
        self._memories[role_name].record_task(...)  # Task kaydediliyor
        # Ama record_outcome çağrılmıyor!
```

Memory'nin en önemli özelliği outcome tracking. Ama pipeline outcome kaydetmiyor. Episodic memory'de doğruluk takibi yapılamaz.

### O-3: DEBATE ENGINE — BEAR ARGÜMANI YANLIŞ ATANIYOR

```python
# Son argümanları güncelle
bull_arg = round_result  # ← round_result hem bull hem bear sonucu
bear_arg = round_result  # ← Aynı şey!
```

`bull_arg` ve `bear_arg` aynı `round_result`'a işaret ediyor. Bir sonraki turda bear'a bull'ın argümanı yerine kendi argümanı verilir.

### O-4: SELF_EVALUATOR — OUTCOME DISTRIBUTION İKİ KEZ İTERE EDİYOR ✅ DÜZELTİLDİ

```python
def _outcome_distribution(self, memory):
    outcomes = memory.episodic.outcomes.values()  # Generator
    return {
        "total": len(list(outcomes)),  # ← Generator tüketildi
        "correct": sum(1 for o in outcomes if o["correct"]),  # ← Boş!
```

`outcomes.values()` bir generator. `len(list(outcomes))` onu tüketir. Sonraki `sum()` ifadeleri boş iterable üzerinde çalışır.

### O-5: SYNTHESIS ENGINE — _simple_majority BERABERLİĞİ HANDLE ETMİYOR ✅ DÜZELTİLDİ

```python
def _simple_majority(self, results):
    directions = {}
    for _role, result in valid.items():
        d = result.output.get("direction", "NEUTRAL")
        directions[d] = directions.get(d, 0) + 1
    max_dir = max(directions, key=directions.get)
```

2 LONG, 2 SHORT, 1 NEUTRAL durumunda `max_dir` = LONG (ilk bulunan). Ama bu beraberlik — NO_TRADE olmalı.

### O-6: RISK ASSESSOR — RISK SCORE FORMÜLÜ NEGATİF OLABİLİR

```python
def _calculate_max_position(self, risk_level, risk_score):
    base = {"LOW": 10.0, ...}.get(risk_level, 5.0)
    adjustment = max(0, (risk_score - 50) / 100)
    return round(max(1.0, base * (1 - adjustment)), 1)
```

`risk_score = 150` (mümkün, `min(100, risk_score)` yoksa) → `adjustment = 1.0` → `base * 0 = 0` → `max(1.0, 0) = 1.0`. Ama `risk_score` zaten `min(100, ...)` ile sınırlı, bu iyi.

### O-7: LLM CLIENT — parse_llm_json REGEX KIRILGAN

```python
json_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", content, re.DOTALL)
```

Bu regex iç içe geçmiş JSON'ları doğru çıkaramaz (3+ seviye). Ayrıca büyük metinlerde performans sorunu olabilir.

### O-8: PROMPT FACTORY — BROAD EXCEPTION HANDLER

```python
try:
    system_prompt = template["system"].format(**format_vars)
    user_prompt = template["user"].format(**format_vars)
except KeyError as e:
    ...
    # Eksik anahtarları boş string ile doldur ve tekrar dene
    all_keys = set(re.findall(r"\{(\w+)\}", template["system"] + template["user"]))
    for k in all_keys:
        format_vars.setdefault(k, "")
    system_prompt = template["system"].format(**format_vars)
```

Eksik anahtarlar boş string ile dolduruluyor. Bu, LLM'e eksik bağlam gönderilmesine neden olur. Daha iyi: eksik kritik alanlar için varsayılan değerler tanımla.

---

## 🟡 İYİLEŞTİRME ALANLARI (I-1 → I-6)

### I-1: MEMORY PERSISTENCE — ASYNC FILE I/O
`save()` ve `load()` senkron dosya I/O kullanıyor. Async context'te bu bloklayıcı olabilir.

### I-2: LLM CLIENT — CONNECTION POOLING
Her `chat()` çağrısında yeni `aiohttp.ClientSession()` oluşturuluyor. Connection pooling yok.

### I-3: AGENT ORCHESTRATOR — SONUÇ SINIRLAMA
`self._results` 1000 ile sınırlı ama bu bellek tüketimi hâlâ yüksek olabilir.

### I-4: CONFLICT DETECTOR — CROSS-AGENT ANALIZ PERFORMANSI
`detect_cross_agent_conflicts` O(n²) karmaşıklık. 12 agent = 66 karşılaştırma.

### I-5: DEBATE ENGINE — ERKEN KONSENSÜS KONTROLÜ
Erken konsensüs kontrolü sadece `bull_direction == bear_direction` yapıyor. Confidence farkı düşükse de konsensüs sayılabilir.

### I-6: RISK ASSESSOR — LLM ENTEGRASYONU OPSİYONEL
LLM risk değerlendirmesi var ama sadece veto kontrolü yapıyor. LLM'in risk skorunu da dahil etmeli.

---

## ✅ İYİ YAPILANLAR

1. **Pydantic schemas** — Hallucination koruması için iyi bir katman
2. **5 katmanlı AI output validation** — JSON parse → schema → range → domain → source
3. **Rule-based fallback** — LLM yoksa sistemin çökmemesi
4. **Confidence damping** — Debate'te her turda güven azaltılması
5. **Memory consolidation** — Periyodik temizleme mekanizması
6. **Tool registry** — Agent'ların erişebileceği araçların kontrolü
7. **Structured logging** — structlog ile tutarlı loglama
8. **Pydantic field validators** — Confidence normalization

---

## 📊 ÖZET

| Kategori | Sayı | Durum |
|---|---|---|
| Kritik sorun | 5 | ✅ 5/5 düzeltildi |
| Yapısal sorun | 8 | ✅ 3/8 düzeltildi (O-2, O-4, O-5) |
| İyileştirme | 6 | 🟡 Opsiyonel |
| İyi yapılan | 8 | ✅ Korunmalı |

**Genel skor: 8/10** — Kritik güvenlik sorunları düzeltildi, fail-closed yapıya geçildi.
