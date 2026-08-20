# Core Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** Temporal Error Handling Guide (2025), Azure Cloud Design Patterns, HFT System Design (Liu, 2026), Mevcut kod analizi (52 modül, 12,647 satır)

---

## 1. Mevcut Durum (Kod Analizi)

### Genel İstatistikler

| Metrik | Değer |
|--------|-------|
| Modül sayısı | 52 |
| Toplam satır | ~12,647 |
| Ortalama satır/modül | 243 |
| En büyük modül | orchestrator (424 satır) |
| En küçük modül | algo_notification (15 satır) |
| Test覆盖率 | 22/52 modülde test var |

### Modül Grupları

| Grup | Modül | Satır | Durum |
|------|-------|-------|-------|
| **Güvenlik** | security, compliance, short_selling, halt_monitor, gross_settlement, viop_monitor, price_limits, manipulation_detector, insider_detector, algo_notification | 1,050 | ⚠️ Çoğu yeni, test yok |
| **Karar & Risk** | decision_engine, risk_gate, fee_calculator, tax, canonical_scoring, regime_detector | 1,868 | ✅ İyi |
| **Veri Kalitesi** | data_quality, data_quality_v2, tradability_mask, pit_store, reconciliation, streaming_anomaly | 1,384 | ⚠️ v2 hala var |
| **Event & İletişim** | event_bus, event_schema, circuit_breaker, worker | 1,316 | ⚠️ DLQ yok |
| **Altyapı** | config, config_loader, config_watcher, database, database_dev, db_lock, infrastructure, logging, models, async_http, broker | 2,892 | ⚠️ Transaction zayıf |
| **Monitoring** | observability, monitoring, monitoring_security, production_metrics, alerting, alert_policy, grafana_provisioning, reporting, audit_log | 3,343 | ✅ İyi |
| **Kurtarma** | recovery, state_recovery | 406 | ⚠️ Deterministic yok |
| **Piyasa** | market_calendar, market_session | 386 | ✅ İyi |
| **Orkestrasyon** | orchestrator | 424 | ✅ İyi |
| **Model** | model_persistence | 201 | ✅ İyi |

---

## 2. Kritik Sorunlar (Kod Analizi)

### 2.1 Event Bus — Dead Letter Queue Yok

**Mevcut:** Event başarısız olursa retry var ama DLQ yok.
**Sorun:** Başarısız event'ler kaybolabilir.
**Çözüm:** DLQ ekle — başarısız event'leri sakla ve retry et.

```python
# Mevcut (event_bus.py:383)
self._processed_ids.add(event.event_id)
if len(self._processed_ids) > 50000:
    self._processed_ids = set(list(self._processed_ids)[-25000:])

# Eksik: Dead Letter Queue
class DeadLetterQueue:
    async def push(self, event: CanonicalEvent, error: str, retry_count: int):
        """Başarısız event'i DLQ'ya kaydet."""
        await dev_db.pg_execute(
            "INSERT INTO event_dlq (event_id, event_type, payload, error, retry_count) VALUES (?, ?, ?, ?, ?)",
            event.event_id, event.event_type, event.to_json(), error, retry_count
        )
    
    async def retry_failed(self, max_retries: int = 3):
        """DLQ'daki event'leri tekrar dene."""
        rows = await dev_db.pg_fetch(
            "SELECT * FROM event_dlq WHERE retry_count < ? ORDER BY created_at LIMIT 100", max_retries
        )
        for row in rows:
            # Retry logic
            pass
```

### 2.2 Database — Transaction Desteği Zayıf

**Mevcut:** `get_pg_transaction()` var ama çoğu yerde kullanılmıyor.
**Sorun:** Portfolio mutations atomic değil.
**Çözüm:** Tüm write operasyonlarında transaction kullan.

```python
# Mevcut (database.py:108)
async def get_pg_transaction():
    async with conn.transaction():
        yield conn

# Eksik: Portfolio write'lerinde kullanım
async def execute_buy(ticker, quantity, price):
    async with get_pg_transaction() as tx:
        await tx.execute("UPDATE positions SET ...")
        await tx.execute("UPDATE portfolios SET cash = ...")
        await tx.execute("INSERT INTO trade_history ...")
        # Hepsi atomic — biri başarısızsa hepsi rollback
```

### 2.3 Config — Runtime Reload Yok

**Mevcut:** Config başlangıçta yükleniyor, değişiklik için restart gerekiyor.
**Sorun:** Runtime'da config değişikliği yapılamıyor.
**Çözüm:** File watcher + callback mechanism.

```python
# Mevcut (config_watcher.py var ama config.py'de entegre değil)
# Eksik: Config change callback
class Settings(BaseSettings):
    _callbacks: List[Callable] = []
    
    def on_change(self, callback: Callable):
        self._callbacks.append(callback)
    
    def _notify_change(self, old_values: Dict, new_values: Dict):
        for callback in self._callbacks:
            callback(old_values, new_values)
```

### 2.4 Security — JWT Token Generation Yok

**Mevcut:** Password hashing var ama JWT token generation yok.
**Sorun:** API authentication için JWT gerekli.
**Çözüm:** JWT token generation ekle.

```python
# Mevcut (security.py:76)
user_id = hashlib.sha256(username.encode()).hexdigest()[:12]

# Eksik: JWT token generation
def generate_token(self, user: User) -> str:
    import jwt
    payload = {
        "sub": user.user_id,
        "role": user.role.value,
        "permissions": [p.value for p in ROLE_PERMISSIONS[user.role]],
        "exp": datetime.utcnow() + timedelta(hours=24),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
```

### 2.5 Circuit Breaker — Metrics Export Yok

**Mevcut:** Circuit breaker çalışıyor ama metrics export etmiyor.
**Sorun:** Monitoring'de circuit breaker durumu görünmüyor.
**Çözüm:** Prometheus metrics ekle.

```python
# Eksik: Circuit breaker metrics
class CircuitBreaker:
    def _export_metrics(self):
        return {
            "circuit_state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_time": self.last_failure_time,
        }
```

### 2.6 Data Quality v2 — Hala Var

**Mevcut:** `data_quality_v2.py` hala duruyor (deprecated olarak işaretlendi).
**Sorun:** Kafa karışıklığı, duplicate kod.
**Çözüm:** Tamamen sil, `data_quality.py`'deki `DataQualityChecker` kullan.

### 2.7 Audit Log — Immutability Garantisi Zayıf

**Mevcut:** `append-only` olarak işaretli ama DB seviyesinde garanti yok.
**Sorun:** Doğrudan DB müdahalesi ile audit log değiştirilebilir.
**Çözüm:** DB seviyesinde `UPDATE` ve `DELETE` yasakla.

```sql
-- Audit log tablosu için trigger
CREATE TRIGGER prevent_audit_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'Audit log records cannot be updated');
END;

CREATE TRIGGER prevent_audit_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'Audit log records cannot be deleted');
END;
```

---

## 3. Nihai Core Mimarisi (Araştırma Bazlı)

### 3.1 Event-Driven Architecture (Temporal, 2025)

```
┌─────────────────────────────────────────────────────────────┐
│                    EVENT BUS (Nihai)                         │
│                                                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│  │ Publisher  │  │ Consumer  │  │ DLQ       │              │
│  │ (Producers)│  │ (Workers) │  │ (Failed)  │              │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘              │
│        │               │              │                     │
│        └───────────────┼──────────────┘                     │
│                        ↓                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              EVENT STORE (Durable)                    │   │
│  │  - PostgreSQL event_ledger (idempotency)             │   │
│  │  - Redis Streams (real-time)                         │   │
│  │  - Dead Letter Queue (failed events)                 │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Features:                                                  │
│  - Idempotency (duplicate detection)                        │
│  - Ordering (sequence number)                               │
│  - Replay (from any point)                                  │
│  - DLQ (failed event retry)                                 │
│  - Metrics (publish/consume/fail counts)                    │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Database Layer (Nihai)

```
┌─────────────────────────────────────────────────────────────┐
│                    DATABASE LAYER                            │
│                                                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│  │ PostgreSQL│  │ ClickHouse│  │ Redis     │              │
│  │ (State)   │  │ (Analytics│  │ (Cache)   │              │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘              │
│        │               │              │                     │
│        └───────────────┼──────────────┘                     │
│                        ↓                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              CONNECTION MANAGER                       │   │
│  │  - Connection pool (min/max/idle)                    │   │
│  │  - Health check (ping/alive)                         │   │
│  │  - Retry policy (exponential backoff)                │   │
│  │  - Transaction helper (atomic operations)            │   │
│  │  - Migration runner (schema versioning)              │   │
│  │  - Query timeout (prevent slow queries)              │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Features:                                                  │
│  - ACID transactions                                        │
│  - Connection pooling                                       │
│  - Health monitoring                                        │
│  - Schema migration                                         │
│  - Query performance tracking                               │
│  - Graceful degradation (DB down → read-only mode)          │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 Security Layer (Nihai)

```
┌─────────────────────────────────────────────────────────────┐
│                    SECURITY LAYER                            │
│                                                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│  │ Auth      │  │ RBAC      │  │ Audit     │              │
│  │ (JWT)     │  │ (Roles)   │  │ (Logging) │              │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘              │
│        │               │              │                     │
│        └───────────────┼──────────────┘                     │
│                        ↓                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              AUTHENTICATION                           │   │
│  │  - JWT token generation/validation                   │   │
│  │  - API key management                                │   │
│  │  - Session management                                │   │
│  │  - Password hashing (bcrypt/pbkdf2)                  │   │
│  │  - Secret rotation                                   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              AUTHORIZATION                            │   │
│  │  - Role-based access control (RBAC)                  │   │
│  │  - Permission matrix                                 │   │
│  │  - API endpoint protection                           │   │
│  │  - Rate limiting                                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              AUDIT                                    │   │
│  │  - Immutable audit log (DB trigger)                  │   │
│  │  - WHO/WHAT/WHEN/WHY tracking                        │   │
│  │  - Compliance reporting                              │   │
│  │  - Anomaly detection                                 │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 3.4 Observability Layer (Nihai)

```
┌─────────────────────────────────────────────────────────────┐
│                    OBSERVABILITY LAYER                       │
│                                                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│  │ Logs      │  │ Metrics   │  │ Traces    │              │
│  │ (Struct.) │  │(Prometheus)│  │ (OTel)   │              │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘              │
│        │               │              │                     │
│        └───────────────┼──────────────┘                     │
│                        ↓                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              LOGGING                                  │   │
│  │  - Structured logging (JSON)                         │   │
│  │  - Log levels (DEBUG, INFO, WARN, ERROR)             │   │
│  │  - Correlation ID propagation                        │   │
│  │  - Secret redaction                                  │   │
│  │  - Log rotation                                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              METRICS                                  │   │
│  │  - Prometheus format                                 │   │
│  │  - Custom metrics (events, decisions, risk)          │   │
│  │  - Histogram (latency distribution)                  │   │
│  │  - Gauge (queue depth, connection pool)              │   │
│  │  - Counter (errors, retries, DLQ)                    │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              TRACING                                  │   │
│  │  - Distributed tracing (OpenTelemetry)               │   │
│  │  - Correlation ID chain                              │   │
│  │  - Span hierarchy (parent → child)                   │   │
│  │  - Performance bottleneck detection                  │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              ALERTING                                 │   │
│  │  - Threshold-based alerts                            │   │
│  │  - Anomaly detection alerts                          │   │
│  │  - Escalation rules                                  │   │
│  │  - Notification channels (email, Slack, webhook)     │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 3.5 Resilience Layer (Nihai)

```
┌─────────────────────────────────────────────────────────────┐
│                    RESILIENCE LAYER                          │
│                                                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│  │ Circuit   │  │ Retry     │  │ Timeout   │              │
│  │ Breaker   │  │ Policy    │  │ Manager   │              │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘              │
│        │               │              │                     │
│        └───────────────┼──────────────┘                     │
│                        ↓                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              CIRCUIT BREAKER                         │   │
│  │  States: CLOSED → OPEN → HALF_OPEN → CLOSED         │   │
│  │  - Failure threshold (5 failures → OPEN)             │   │
│  │  - Timeout (60s → HALF_OPEN)                         │   │
│  │  - Success threshold (3 → CLOSED)                    │   │
│  │  - Metrics export (state, counts)                    │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              RETRY POLICY                            │   │
│  │  - Exponential backoff (1s, 2s, 4s, 8s)             │   │
│  │  - Max retries (configurable)                        │   │
│  │  - Jitter (prevent thundering herd)                  │   │
│  │  - Retry budget (prevent infinite retry)             │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              TIMEOUT MANAGER                         │   │
│  │  - Per-operation timeout                             │   │
│  │  - Global timeout                                    │   │
│  │  - Graceful cancellation                             │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              GRACEFUL DEGRADATION                    │   │
│  │  - FULL → DEGRADED → READ_ONLY → RECOVERY           │   │
│  │  - Feature flags (disable non-critical features)     │   │
│  │  - Fallback responses (cached data)                  │   │
│  │  - Health check integration                          │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Eksik Modüller (Nihai)

### 4.1 Dead Letter Queue (DLQ)

```python
class DeadLetterQueue:
    """Başarısız event'ler için DLQ."""
    
    async def push(self, event: CanonicalEvent, error: str, retry_count: int):
        """Event'i DLQ'ya kaydet."""
        await dev_db.pg_execute(
            "INSERT INTO event_dlq (event_id, event_type, payload, error, retry_count, created_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            event.event_id, event.event_type, event.to_json(), error, retry_count
        )
    
    async def retry_failed(self, max_retries: int = 3) -> int:
        """DLQ'daki event'leri tekrar dene."""
        rows = await dev_db.pg_fetch(
            "SELECT * FROM event_dlq WHERE retry_count < ? AND next_retry_at <= CURRENT_TIMESTAMP ORDER BY created_at LIMIT 100",
            max_retries
        )
        retried = 0
        for row in rows:
            try:
                event = CanonicalEvent.from_json(row["payload"])
                await event_bus.publish(event.event_type, event)
                await dev_db.pg_execute("DELETE FROM event_dlq WHERE id = ?", row["id"])
                retried += 1
            except Exception as e:
                await dev_db.pg_execute(
                    "UPDATE event_dlq SET retry_count = retry_count + 1, error = ?, next_retry_at = CURRENT_TIMESTAMP + INTERVAL '5 minutes' WHERE id = ?",
                    str(e), row["id"]
                )
        return retried
    
    async def get_stats(self) -> Dict:
        """DLQ istatistikleri."""
        total = await dev_db.pg_fetchval("SELECT COUNT(*) FROM event_dlq")
        pending = await dev_db.pg_fetchval("SELECT COUNT(*) FROM event_dlq WHERE retry_count < 3")
        return {"total": total, "pending": pending}
```

### 4.2 JWT Token Manager

```python
class JWTManager:
    """JWT token yönetimi."""
    
    def generate_token(self, user_id: str, role: str, permissions: List[str], expires_hours: int = 24) -> str:
        import jwt
        payload = {
            "sub": user_id,
            "role": role,
            "permissions": permissions,
            "exp": datetime.utcnow() + timedelta(hours=expires_hours),
            "iat": datetime.utcnow(),
        }
        return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    
    def validate_token(self, token: str) -> Dict:
        import jwt
        try:
            return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise AuthenticationError("Token expired")
        except jwt.InvalidTokenError:
            raise AuthenticationError("Invalid token")
    
    def refresh_token(self, token: str, expires_hours: int = 24) -> str:
        payload = self.validate_token(token)
        return self.generate_token(payload["sub"], payload["role"], payload["permissions"], expires_hours)
```

### 4.3 Database Transaction Helper

```python
class TransactionHelper:
    """Database transaction yardımcısı."""
    
    async def atomic(self, operations: List[Callable]) -> bool:
        """Birden fazla operasyonu tek transaction'da çalıştır."""
        async with get_pg_transaction() as tx:
            for op in operations:
                await op(tx)
        return True
    
    async def atomic_with_retry(self, operations: List[Callable], max_retries: int = 3) -> bool:
        """Retry ile atomic operasyon."""
        for attempt in range(max_retries):
            try:
                return await self.atomic(operations)
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
        return False
```

### 4.4 Config Hot-Reload

```python
class ConfigHotReload:
    """Config dosyası değişikliğini izle ve yeniden yükle."""
    
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.last_modified = 0
        self.callbacks = []
    
    def on_change(self, callback: Callable):
        self.callbacks.append(callback)
    
    async def watch(self):
        """Config dosyasını izle."""
        while True:
            try:
                current_modified = os.path.getmtime(self.config_path)
                if current_modified > self.last_modified:
                    old_settings = settings.copy()
                    new_settings = self._reload_config()
                    for callback in self.callbacks:
                        await callback(old_settings, new_settings)
                    self.last_modified = current_modified
            except Exception as e:
                logger.warning("Config watch error", error=str(e))
            await asyncio.sleep(5)
```

---

## 5. Uygulama Planı

### Faz 1: Kritik Eksikler (Hemen)
1. DLQ ekle (event_bus.py)
2. JWT token generation (security.py)
3. Transaction helper (database.py)
4. data_quality_v2.py sil

### Faz 2: Güçlendirmeler (1 hafta)
1. Circuit breaker metrics export
2. Config hot-reload
3. Audit log immutability (DB trigger)
4. Database health check improvements

### Faz 3: Observability (1 hafta)
1. OpenTelemetry entegrasyonu
2. Custom metrics (events, decisions, risk)
3. Distributed tracing correlation
4. Alert rules

### Faz 4: Resilience (1 hafta)
1. Graceful degradation states
2. Feature flags
3. Fallback responses
4. Chaos testing

---

## 6. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| Event Bus | ✅ | ✅ + DLQ |
| Database | ✅ | ✅ + Transaction helper |
| Config | ✅ | ✅ + Hot-reload |
| Security | ✅ | ✅ + JWT + RBAC |
| Circuit Breaker | ✅ | ✅ + Metrics export |
| Observability | ✅ | ✅ + Distributed Tracing |
| Audit Log | ✅ | ✅ + Immutable (hash chain) |
| Recovery | ✅ | ✅ + Graceful degradation |
| Resilience | ✅ | ✅ + System Governor |
| Data Quality | ✅ | ✅ v1 only (v2 deprecated) |

---

## 7. ÇÖZÜLDÜ — Düzeltme Kayıtları (2026-08-20)

### Düzeltme 5: Decision Engine → BUY/SELL Bias Düzeltmeleri (2026-08-21)
- **Dosya:** `decision_engine.py`
- **Sorunlar:**
  1. `max()` optimistic selection: `max(ml_score, spec_score*0.9)` systematic BUY bias yaratıyordu
  2. ML return bonus asimetrik: sadece pozitif return'ler için +5 veriyordu
  3. Yön eşikleri asimetrik: RSI >55/<45 (10 puan gap), ML >60/<40 (20 puan gap)
- **Çözümler:**
  1. `max()` → güven-ağırlıklı ortalama (`ml_confidence * ml_score + (1-ml_confidence) * spec_score*0.9`)
  2. ML return bonus simetrik: `>3 → +5`, `<-3 → -5` (ve 20d için de)
  3. Yön eşikleri simetrik: RSI >52/<48, ML >55/<45
- **Etki:** Systematic BUY bias kaldırıldı, LONG/SHORT kararları simetrik

### Düzeltme 6: Signal Fusion → Yön Belirleme Düzeltmesi (2026-08-21)
- **Dosya:** `signal_fusion.py`
- **Sorun:** `effective_weight = weight * (score/100)` yüksek skorlu sinyallerin yön kararını domine etmesine neden oluyordu
- **Çözüm:** Yön belirlemede sadece `weight` kullanılıyor, skor sadece `fused_score`'a yansıyor
- **Etki:** Daha dengeli yön kararları, tek bir yüksek skorlu sinyal diğerlerini baskılamıyor

### Düzeltme 1: Event Bus → DLQ Entegrasyonu
- **Dosya:** `event_bus.py`
- **Sorun:** Handler crash → event kayboluyordu
- **Çözüm:** `InternalEventBus.start_listening()` ve `EventConsumer._handle_event()`'te catch bloğuna DLQ push eklendi
- **Etki:** Başarısız event'ler artık `dead_letter_queue`'ya düşüyor, retry mekanizması ile kurtarılabiliyor

### Düzeltme 2: Security → JWT Manager Entegrasyonu
- **Dosya:** `security.py`
- **Sorun:** AuthenticationService kendi random token mekanizmasını kullanıyordu (JWT standardı yok)
- **Çözüm:** `authenticate()` → `jwt_manager.generate_token()`, `validate_token()` → `jwt_manager.validate_token()`
- **Etki:** Tüm authentication JWT standardına geçti, RBAC permission'ları token içinde taşıyor

### Düzeltme 3: Data Quality v2 Kaldırıldı
- **Dosya:** `data_quality_v2.py` → `data_quality_v2.py.deprecated`
- **Sorun:** v1 ve v2 birlikte duruyordu, kafa karışıklığı
- **Çözüm:** v2 `.deprecated` olarak yeniden adlandırıldı, import'lar v1'e yönlendirildi
- **Etki:** Tek veri kalitesi modülü (`data_quality.py`) kaldı

### Düzeltme 4: Entegrasyon Testleri
- **Dosya:** `tests/test_core_integration.py` (yeni)
- **İçerik:** 25 test, tüm core modüllerini kapsıyor
- **Durum:** 25/25 PASSED
