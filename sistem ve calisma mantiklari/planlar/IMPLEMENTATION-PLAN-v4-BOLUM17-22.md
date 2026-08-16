# Uygulama Planı v4 — Bölüm 17-22

## Durum Özeti

| Bölüm | Konu | Mevcut Kod | Durum |
|-------|------|-----------|-------|
| 17 | Memory + Knowledge Graph | `intelligence/knowledge_graph.py`, `intelligence/research_memory.py` | ✅ |
| 18 | Kanıt Doğrulama | `intelligence/evidence_engine.py` | ✅ |
| 19 | Güvenlik + RBAC | `core/security.py`, `core/audit_log.py` | ✅ |
| 20 | Sistem Altyapısı | `core/infrastructure.py`, `core/event_bus.py`, `core/database.py` | ✅ |
| 21 | Hata Yönetimi | `core/circuit_breaker.py`, `core/recovery.py`, `core/state_recovery.py` | ✅ |
| 22 | Gözlemleme + Audit | `core/observability.py`, `core/audit_log.py` | ✅ |

**Sonuç:** 6 bölümün TAMAMI mevcut kodda implemente edilmiş.

---

## AŞAMA 1: Kod Doğrulama (Bölüm 17-22)

### 17. Memory + Knowledge Graph

| # | Kontrol | Dosya | Fonksiyon | Test |
|---|---------|-------|-----------|------|
| 17.1 | KnowledgeGraph sınıfı | `intelligence/knowledge_graph.py` | `class KnowledgeGraph` | ✅ |
| 17.2 | load_bist_defaults() | `intelligence/knowledge_graph.py` | Varsayılan entity'ler yükleniyor mu? | ❓ |
| 17.3 | find_path() | `intelligence/knowledge_graph.py` | Entity'den entity'ye yol buluyor mu? | ❓ |
| 17.4 | propagate_impact() | `intelligence/knowledge_graph.py` | Etki yayılımı çalışıyor mu? | ❓ |
| 17.5 | add_entity() | `intelligence/knowledge_graph.py` | Yeni entity ekleniyor mu? | ❓ |
| 17.6 | add_relation() | `intelligence/knowledge_graph.py` | İlişki ekleniyor mu? | ❓ |
| 17.7 | ResearchRecord sınıfı | `intelligence/research_memory.py` | `class ResearchRecord` | ✅ |
| 17.8 | add_record() | `intelligence/research_memory.py` | Araştırma kaydı ekleniyor mu? | ❓ |
| 17.9 | get_ticker_history() | `intelligence/research_memory.py` | Geçmiş getiriliyor mu? | ❓ |
| 17.10 | LineageNode sınıfı | `intelligence/research_memory.py` | `class LineageNode` | ✅ |
| 17.11 | add_node() (lineage) | `intelligence/research_memory.py` | Veri düğümü ekleniyor mu? | ❓ |
| 17.12 | trace_forward() | `intelligence/research_memory.py` | İleriye doğru izleme çalışıyor mu? | ❓ |
| 17.13 | trace_backward() | `intelligence/research_memory.py` | Geriye doğru izleme çalışıyor mu? | ❓ |

**Test senaryosu:**
```python
# Knowledge Graph
knowledge_graph.load_bist_defaults()
path = knowledge_graph.find_path("macro_OIL", "sector_ENERGY")
assert "sector_ENERGY" in path

impacts = knowledge_graph.propagate_impact("macro_OIL", 0.5)
assert "sector_ENERGY" in impacts
assert impacts["sector_ENERGY"] > 0

# Research Memory
research_memory.add_record(ResearchRecord(
    record_id="R001", ticker="THYAO", date="2026-08-15",
    thesis="Momentum strong", evidence=["volume spike"],
    risks=["high volatility"], prediction={"return": 5.0}))
history = research_memory.get_ticker_history("THYAO")
assert len(history) > 0

# Data Lineage
data_lineage.add_node(LineageNode("raw_data", "price_THYAO", "2026-08-15T10:00:00"))
data_lineage.add_node(LineageNode("feature", "rsi_THYAO", "2026-08-15T10:00:01",
    parent_ids=["raw_data:price_THYAO"]))
forward = data_lineage.trace_forward("raw_data", "price_THYAO")
assert len(forward) == 2
```

---

### 18. Kanıt Doğrulama

| # | Kontrol | Dosya | Fonksiyon | Test |
|---|---------|-------|-----------|------|
| 18.1 | EvidenceVerificationEngine | `intelligence/evidence_engine.py` | `class EvidenceVerificationEngine` | ✅ |
| 18.2 | ClaimType enum | `intelligence/evidence_engine.py` | FACT, INFERENCE, PREDICTION, OPINION | ✅ |
| 18.3 | SourceReliability enum | `intelligence/evidence_engine.py` | PRIMARY, SECONDARY, TERTIARY | ✅ |
| 18.4 | Claim sınıfı | `intelligence/evidence_engine.py` | `class Claim` | ✅ |
| 18.5 | VerifiedClaim sınıfı | `intelligence/evidence_engine.py` | `class VerifiedClaim` | ✅ |
| 18.6 | _classify_claim() | `intelligence/evidence_engine.py` | Claim tipi sınıflandırılıyor mu? | ❓ |
| 18.7 | verify_claim() | `intelligence/evidence_engine.py` | Claim doğrulanıyor mu? | ❓ |
| 18.8 | detect_hallucination() | `intelligence/evidence_engine.py` | Hallucination tespit ediliyor mu? | ❓ |
| 18.9 | _compute_evidence_score() | `intelligence/evidence_engine.py` | Evidence score hesaplanıyor mu? | ❓ |

**Test senaryosu:**
```python
# Claim sınıflandırma
claim_type = evidence_engine._classify_claim("KAP açıklandı")
assert claim_type == ClaimType.FACT

claim_type = evidence_engine._classify_claim("Tahminime göre yükselecek")
assert claim_type == ClaimType.PREDICTION

# Claim doğrulama
claim = Claim(claim_id="C1", text="Şirket yeni sözleşme imzaladı",
    source="kap.org.tr", source_type=SourceReliability.PRIMARY)
result = evidence_engine.verify_claim(claim)
assert result.verification_result == VerificationResult.VERIFIED
assert result.evidence_score > 80

# Hallucination tespiti
halluc = evidence_engine.detect_hallucination(
    "THYAO 500 TL olacak", {})
assert halluc["hallucination_detected"] == True
```

---

### 19. Güvenlik + RBAC

| # | Kontrol | Dosya | Fonksiyon | Test |
|---|---------|-------|-----------|------|
| 19.1 | Role enum | `core/security.py` | ADMIN, ANALYST, VIEWER | ✅ |
| 19.2 | Permission enum | `core/security.py` | RUN_BACKTEST, LIVE_EXECUTION, vb. | ✅ |
| 19.3 | User sınıfı | `core/security.py` | `class User` | ✅ |
| 19.4 | check_permission() | `core/security.py` | Yetki kontrolü çalışıyor mu? | ❓ |
| 19.5 | authz_service | `core/security.py` | Authorization servisi çalışıyor mu? | ❓ |
| 19.6 | AuditLog | `core/audit_log.py` | `class AuditLog` | ✅ |
| 19.7 | log() / log_decision() | `core/audit_log.py` | Aksiyon loglanıyor mu? | ❓ |
| 19.8 | get_recent() / get_entity_history() | `core/audit_log.py` | Log getiriliyor mu? | ❓ |

**Test senaryosu:**
```python
# RBAC
user = User(user_id="1", username="analyst", role=Role.ANALYST)
assert authz_service.check_permission(user, Permission.RUN_BACKTEST) == True
assert authz_service.check_permission(user, Permission.LIVE_EXECUTION) == False

# Audit
audit_log.log_decision(ticker="THYAO", decision="BUY", confidence=0.8, reasoning="Strong momentum")
entries = audit_log.get_recent(limit=10)
assert len(entries) > 0

# AuditEntry
entry = AuditEntry(entry_id="A001", timestamp=datetime.now(), user="analyst",
    action="BUY", ticker="THYAO", details={"lot": 100})
audit_log.log(entry)
history = audit_log.get_entity_history("THYAO")
assert len(history) > 0
```

---

### 20. Sistem Altyapısı

| # | Kontrol | Dosya | Fonksiyon | Test |
|---|---------|-------|-----------|------|
| 20.1 | EventOrchestrator | `core/infrastructure.py` | `class EventOrchestrator` | ✅ |
| 20.2 | dispatch() | `core/infrastructure.py` | Event dispatch çalışıyor mu? | ❓ |
| 20.3 | CacheSystem | `core/infrastructure.py` | `class CacheSystem` | ✅ |
| 20.4 | set() / get() | `core/infrastructure.py` | Cache okuma/yazma çalışıyor mu? | ❓ |
| 20.5 | JobQueue | `core/infrastructure.py` | `class JobQueue` | ✅ |
| 20.6 | enqueue() / dequeue() | `core/infrastructure.py` | Kuyruk çalışıyor mu? | ❓ |
| 20.7 | InternalEventBus | `core/event_bus.py` | `class InternalEventBus` | ✅ |
| 20.8 | publish() / subscribe() | `core/event_bus.py` | Pub/sub çalışıyor mu? | ❓ |
| 20.9 | DevDatabase | `core/database_dev.py` | `class DevDatabase` | ✅ |
| 20.10 | ch_execute() / ch_query_df() | `core/database.py` | ClickHouse çalışıyor mu? | ❓ |

**Test senaryosu:**
```python
# Event dispatch
await event_orchestrator.dispatch("kap.new", {"ticker": "THYAO"})

# Cache
cache_system.set("market_state", {"risk": "low"}, ttl_seconds=300)
cached = cache_system.get("market_state")
assert cached["risk"] == "low"

# Job queue
job_id = job_queue.enqueue("backtest", {"strategy": "momentum"}, priority="HIGH")
job = job_queue.dequeue()
assert job["job_id"] == job_id
```

---

### 21. Hata Yönetimi

| # | Kontrol | Dosya | Fonksiyon | Test |
|---|---------|-------|-----------|------|
| 21.1 | CircuitBreaker sınıfı | `core/circuit_breaker.py` | `class CircuitBreaker` | ✅ |
| 21.2 | can_execute() | `core/circuit_breaker.py` | Durum kontrolü çalışıyor mu? | ❓ |
| 21.3 | record_failure() | `core/circuit_breaker.py` | Hata kaydediliyor mu? | ❓ |
| 21.4 | record_success() | `core/circuit_breaker.py` | Başarı kaydediliyor mu? | ❓ |
| 21.5 | State machine | `core/circuit_breaker.py` | CLOSED→OPEN→HALF_OPEN geçişi? | ❓ |
| 21.6 | RetryPolicy sınıfı | `core/circuit_breaker.py` | `class RetryPolicy` | ✅ |
| 21.7 | Exponential backoff | `core/circuit_breaker.py` | 1s→2s→4s bekleme? | ❓ |
| 21.8 | Recovery | `core/recovery.py` | `def recover` | ✅ |
| 21.9 | State Recovery | `core/state_recovery.py` | State kaydetme/geri yükleme? | ❓ |

**Test senaryosu:**
```python
# Circuit breaker state machine
cb = CircuitBreaker(name="yfinance", failure_threshold=5)
assert cb.can_execute() == True  # CLOSED

for _ in range(5):
    cb.record_failure()
assert cb.can_execute() == False  # OPEN

# 60 saniye sonra HALF_OPEN
cb.state = "HALF_OPEN"
assert cb.can_execute() == True
cb.record_success()
assert cb.state == "CLOSED"

# Retry
retry = RetryPolicy(max_retries=3, base_delay=1.0)
assert retry.max_retries == 3
```

---

### 22. Gözlemleme + Audit

| # | Kontrol | Dosya | Fonksiyon | Test |
|---|---------|-------|-----------|------|
| 22.1 | HealthChecker | `core/observability.py` | `class HealthChecker` | ✅ |
| 22.2 | register() | `core/observability.py` | Bileşen kayıt ediliyor mu? | ❓ |
| 22.3 | update_status() | `core/observability.py` | Durum güncelleniyor mu? | ❓ |
| 22.4 | check_all() | `core/observability.py` | Tüm sağlık kontrolü çalışıyor mu? | ❓ |
| 22.5 | PrometheusMetrics | `core/observability.py` | `class PrometheusMetrics` | ✅ |
| 22.6 | inc() | `core/observability.py` | Counter artırılıyor mu? | ❓ |
| 22.7 | observe() | `core/observability.py` | Histogram gözlemi çalışıyor mu? | ❓ |
| 22.8 | set_gauge() | `core/observability.py` | Gauge ayarlanıyor mu? | ❓ |
| 22.9 | Structured logging | `core/logging.py` | structlog çalışıyor mu? | ❓ |
| 22.10 | AuditLog entegrasyonu | `core/audit_log.py` | Karar audit zinciri tam mı? | ❓ |

**Test senaryosu:**
```python
# Health check
health_checker.register("database")
health_checker.update_status("database", "HEALTHY")
result = health_checker.check_all()
assert result["overall"] == "HEALTHY"
assert result["components"]["database"] == "HEALTHY"

# Metrics
prometheus_metrics.inc("decisions_total", labels={"action": "BUY"})
prometheus_metrics.observe("api_latency_ms", 150)
prometheus_metrics.set_gauge("portfolio_equity", 112450)

# Structured logging
logger = structlog.get_logger()
logger.info("Decision made", ticker="THYAO", action="BUY", confidence=0.8)
```

---

## AŞAMA 2: Test Yazma (Bölüm 17-22)

### Test dosyaları:

```
tests/test_intelligence/
├── test_knowledge_graph.py     # Bölüm 17
├── test_research_memory.py     # Bölüm 17
├── test_data_lineage.py        # Bölüm 17
├── test_evidence_engine.py     # Bölüm 18

tests/test_core/
├── test_security.py            # Bölüm 19
├── test_audit_log.py           # Bölüm 19
├── test_infrastructure.py      # Bölüm 20
├── test_event_bus.py           # Bölüm 20
├── test_circuit_breaker.py     # Bölüm 21
├── test_recovery.py            # Bölüm 21
├── test_observability.py       # Bölüm 22
```

---

## AŞAMA 3: Entegrasyon Testleri (Bölüm 17-22)

| # | Zincir | Adımlar |
|---|--------|---------|
| E6 | Agent → Evidence → Audit | Agent çalıştır → claim doğrula → audit logla |
| E7 | Event → Circuit Breaker → Recovery | Event → hata → circuit breaker → recovery |
| E8 | Health → Alert → State Recovery | Sağlık kontrolü → uyarı → state kurtarma |
| E9 | Knowledge Graph → Memory → Lineage | Entity → memory → lineage izleme |
| E10 | Security → Permission → Audit | Yetki kontrolü → işlem → audit trail |

---

## AŞAMA 4: Yeni Modül Gereksinimleri (Bölüm 17-22)

Bölüm 17-22 için **yeni modül gerekmiyor**. Tüm gereksinimler mevcut kodda var.

Ancak şu eklemeler gerekebilir:

| # | Ek | Gerekçe |
|---|-----|---------|
| 1 | Vector DB entegrasyonu | Semantic search (Bölüm 17'de dokümante edildi) |
| 2 | Embedding service | Text → vector dönüşümü (Bölüm 17) |
| 3 | No-Trade Gate implementasyonu | Risk+veri+model+portföy kontrolü (Bölüm 19) |
| 4 | System State Machine | STARTING→READY→DEGRADED→FAILED (Bölüm 19) |
| 5 | Dead Letter Queue | Başarısız işlerin saklanması (Bölüm 21) |
| 6 | Event Replay | Event'lerin tekrar çalıştırılması (Bölüm 20) |

---

## Uygulama Sırası

```
GÜN 1: Aşama 1 (17-19 modül doğrulama)
GÜN 2: Aşama 1 (20-22 modül doğrulama)
GÜN 3: Aşama 2 (Test yazma — intelligence + security)
GÜN 4: Aşama 2 (Test yazma — infrastructure + observability)
GÜN 5: Aşama 3 (Entegrasyon testleri)
GÜN 6: Aşama 4 (Vector DB, No-Trade Gate, DLQ eklemeleri)
```

---

## Başarı Kriterleri

- [ ] Knowledge Graph: find_path() ve propagate_impact() çalışıyor
- [ ] Research Memory: add_record() ve get_ticker_history() çalışıyor
- [ ] Data Lineage: trace_forward() ve trace_backward() çalışıyor
- [ ] Evidence Engine: verify_claim() ve detect_hallucination() çalışıyor
- [ ] Security: RBAC check_permission() çalışıyor
- [ ] Infrastructure: cache, queue, event_bus çalışıyor
- [ ] Circuit Breaker: CLOSED→OPEN→HALF_OPEN state machine çalışıyor
- [ ] Observability: health_check, metrics, structured logging çalışıyor
- [ ] 11+ test dosyası yazıl
- [ ] add_relation() (add_relationship değil) çalışıyor
- [ ] log() / log_decision() (log_action değil) çalışıyor
- [ ] get_recent() (get_entries değil) çalışıyor
- [ ] 5 entegrasyon zinciri çalışıyor
