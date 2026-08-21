# ALPHA BIST — Teknoloji Yükseltme Önerileri

**Tarih:** 2026-08-22  
**Kapsam:** Mevcut stack'in üst seviye alternatiflerle karşılaştırması ve somut upgrade planı

---

## 📊 Mevcut Stack Özeti

| Katman | Mevcut Teknoloji | Versiyon |
|--------|-----------------|----------|
| API | FastAPI + Uvicorn | 0.141+ |
| Veri İşleme | Polars (primary) + Pandas (legacy) | 1.43+ |
| İlişkisel DB | PostgreSQL 17 | 17-alpine |
| Zaman Serisi DB | ClickHouse 24.3 | 24.3-alpine |
| Cache | Redis 8 | 8-alpine |
| Event Streaming | Redpanda (Kafka uyumlu) | - |
| ML | LightGBM + CatBoost + XGBoost | 4.7+ |
| ML Tracking | MLflow | 3.15+ |
| Monitoring | Prometheus + Grafana | 3.14 / 13.0 |
| Logging | structlog | 26.1+ |
| Tracing | OpenTelemetry | 1.44+ |
| Frontend | Next.js | - |
| Container | Docker Compose | - |

---

## 🔍 Tespit Edilen Sorunlar ve İyileştirme Önerileri

### 1. ZAMAN SERİSİ DB — ClickHouse ✅ Doğru Seçim

**Durum:** ClickHouse finansal zaman serisi için mükemmel bir seçim. Kolonar depolama, yüksek aggregation hızı ve PIT sorgular için ideal.

**İyileştirme Önerileri:**
- **Materialized View'lar**: Sık kullanılan aggregation'lar (günlük OHLCV, haftalık özetler) için otomatik materialized view'lar oluştur → sorgu hızı 10-100x artar
- **Partitioning stratejisi**: `PARTITION BY toYYYYMM(date)` ile aylık partitioning → eski veri yönetimi kolaylaşır
- **TTL politikası**: COLD katman verisi için otomatik TTL (ör. 2 yıl sonra S3'e taşı)
- **Buffer tables**: Yüksek frekanslı yazma işlemleri için buffer tables ekle

```sql
-- Örnek materialized view
CREATE MATERIALIZED VIEW daily_ohlcv_mv
ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (ticker, date)
AS SELECT
    ticker, date,
    argMinState(open, timestamp) as open,
    maxState(high) as high,
    minState(low) as low,
    argMaxState(close, timestamp) as close,
    sumState(volume) as volume
FROM trades
GROUP BY ticker, date;
```

### 2. İLİŞKİSEL DB — PostgreSQL ✅ Doğru Seçim, Eksik Konfigürasyon

**Durum:** PostgreSQL ACID garantisi için doğru seçim. Ancak production-ready konfigürasyon eksik.

**İyileştirme Önerileri:**
- **Connection pooling**: PgBouncer ekle (docker-compose'a ekle)
- **Read replica**: Analytics sorguları için read replica oluştur
- **WAL tuning**: `wal_level=replica`, `max_wal_size=2GB`
- **Backup otomasyonu**: pg_dump cron job veya WAL archiving
- **pg_stat_statements**: Slow query monitoring için aktif et

```yaml
# docker-compose.yml'a ekle
pgbouncer:
  image: edoburu/pgbouncer:1.23.1
  environment:
    DATABASE_URL: postgres://alpha:${POSTGRES_PASSWORD}@postgres:5432/alpha_bist
    POOL_MODE: transaction
    MAX_CLIENT_CONN: 200
    DEFAULT_POOL_SIZE: 20
  ports:
    - "6432:5432"
```

### 3. CACHE — Redis ✅ Doğru Seçim, Eksik Kullanım

**Durum:** Redis cache olarak doğru. Ancak mevcut kodda yeterince kullanılmıyor.

**İyileştirme Önerileri:**
- **Cache-aside pattern**: Feature hesaplama sonuçlarını cache'le (TTL: 5 dk)
- **Rate limiting**: API rate limiting için Redis sliding window
- **Session store**: API token'ları Redis'te tut (JWT blacklist)
- **Pub/Sub**: Real-time dashboard güncellemeleri için Redis Pub/Sub
- **Sorted sets**: Leaderboard/ranking sonuçları için

```python
# services/core/cache.py — Örnek cache wrapper
import redis.asyncio as redis
from functools import wraps

class FeatureCache:
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url)
    
    async def get_or_compute(self, key: str, compute_fn, ttl: int = 300):
        cached = await self.redis.get(key)
        if cached:
            return orjson.loads(cached)
        result = await compute_fn()
        await self.redis.setex(key, ttl, orjson.dumps(result))
        return result
```

### 4. EVENT STREAMING — Redpanda ⚠️ Fazla Karmaşık

**Durum:** Redpanda (Kafka uyumlu) mevcut projede aşırı karmaşık. Çoğu event bus zaten Redis-based.

**Öneri:** Redpanda'yı kaldır, Redis Streams ile değiştir:
- **Neden**: Mevcut event volume'ü Kafka/Redpanda gerektirmiyor
- **Redis Streams**: `XADD`/`XREAD` ile yeterli throughput
- **Avantaj**: Bir container azaltma, operasyonel karmaşıklık azaltma
- **Eğer ileride gerekirse**: NATS JetStream daha hafif alternatif

```python
# services/core/event_bus.py — Redis Streams tabanlı
class EventBus:
    async def publish(self, stream: str, event: dict):
        await self.redis.xadd(stream, event, maxlen=10000)
    
    async def subscribe(self, stream: str, group: str, consumer: str):
        return await self.redis.xreadgroup(group, consumer, {stream: ">"}, count=10)
```

### 5. ML PIPELINE — LightGBM ⚠️ Feature Store Eksik

**Durum:** LightGBM doğru seçim. Ancak feature management ve model registry eksik.

**İyileştirme Önerileri:**

#### 5a. Feature Store — Feast veya Hopsworks
Mevcut durumda feature'lar her seferinde hesaplanıyor. Feature store ile:
- Feature'ları bir kez hesapla, tekrar tekrar kullan
- Point-in-time join garantisi
- Feature versioning ve lineage

```python
# Alternatif: Basit feature store (Redis-based)
class FeatureStore:
    async def get_features(self, ticker: str, date: str, feature_names: list):
        """PIT-aware feature retrieval"""
        key = f"features:{ticker}:{date}"
        features = await self.redis.hgetall(key)
        return {k: float(v) for k, v in features.items() if k in feature_names}
    
    async def store_features(self, ticker: str, date: str, features: dict):
        key = f"features:{ticker}:{date}"
        await self.redis.hset(key, mapping={k: str(v) for k, v in features.items()})
        await self.redis.expire(key, 86400 * 7)  # 7 gün TTL
```

#### 5b. Model Registry — MLflow ✅ Mevcut, Daha İyi Kullan
MLflow zaten docker-compose'ta var ama yeterince entegre edilmemiş:
- Her model eğitimini MLflow'a logla
- Champion/Challenger tracking için MLflow Model Registry stages kullan
- A/B testing için MLflow'un model serving'ini değerlendir

#### 5c. Feature Importance Tracking
```python
# services/ml/feature_monitor.py
class FeatureDriftDetector:
    def __init__(self, reference_features: pd.DataFrame):
        self.reference = reference_features
        self.stats = self._compute_stats(reference_features)
    
    def detect_drift(self, current_features: pd.DataFrame) -> dict:
        """PSI (Population Stability Index) ile drift tespiti"""
        drift_scores = {}
        for col in self.reference.columns:
            psi = self._calculate_psi(self.reference[col], current_features[col])
            drift_scores[col] = {
                "psi": psi,
                "status": "CRITICAL" if psi > 0.25 else "WARNING" if psi > 0.1 else "OK"
            }
        return drift_scores
```

### 6. MONITORING — Prometheus + Grafana ⚠️ Eksik APM

**Durum:** Prometheus + Grafana iyi başlangıç ama APM (Application Performance Monitoring) eksik.

**İyileştirme Önerileri:**

#### 6a. Structured Logging → OpenTelemetry Logs
```python
# services/core/telemetry.py
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.metrics import MeterProvider

# Her karar için trace oluştur
tracer = trace.get_tracer("alpha.decision")

async def make_decision(features: dict) -> Decision:
    with tracer.start_as_current_span("decision.make") as span:
        span.set_attribute("ticker", features.get("ticker"))
        span.set_attribute("regime", features.get("regime"))
        
        # ... decision logic ...
        
        span.set_attribute("action", decision.action)
        span.set_attribute("confidence", decision.confidence)
        return decision
```

#### 6b. Custom Metrics
```python
# services/core/metrics.py
from prometheus_client import Counter, Histogram, Gauge

# Karar metrikleri
decisions_total = Counter('alpha_decisions_total', 'Total decisions', ['action', 'regime'])
decision_confidence = Histogram('alpha_decision_confidence', 'Decision confidence', ['action'])
feature_computation_time = Histogram('alpha_feature_computation_seconds', 'Feature computation time', ['motor'])
data_quality_score = Gauge('alpha_data_quality_score', 'Data quality score', ['ticker'])

# Model drift metrikleri
model_ic = Gauge('alpha_model_ic', 'Information Coefficient', ['model_version'])
model_drift = Gauge('alpha_model_drift', 'Model drift score', ['model_version'])
```

#### 6c. Alert Rules (Grafana)
```yaml
# infrastructure/grafana/alerts.yml
groups:
  - name: alpha_alerts
    rules:
      - alert: HighDecisionLatency
        expr: histogram_quantile(0.95, alpha_decision_latency_seconds) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Decision latency > 5s (p95)"
      
      - alert: DataQualityDrop
        expr: avg(alpha_data_quality_score) < 0.8
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Data quality dropped below 80%"
      
      - alert: ModelDriftDetected
        expr: alpha_model_drift > 0.25
        for: 15m
        labels:
          severity: critical
        annotations:
          summary: "Model drift detected - PSI > 0.25"
```

### 7. DATA QUALITY — Manuel Kontrol ⚠️ Framework Eksik

**Durum:** `data_quality.py` manuel kontroller yapıyor ama sistematik data quality framework'ü yok.

**Öneri: Pandera (lightweight) veya Great Expectations (heavy-duty)**

```python
# services/core/data_validation.py — Pandera tabanlı
import pandera as pa
from pandera import Column, DataFrameSchema, Check

ohlcv_schema = DataFrameSchema({
    "ticker": Column(str, Check.str_matches(r"^[A-Z]{3,6}$")),
    "date": Column(pa.DateTime, Check.less_than_or_equal_to("today")),
    "open": Column(float, Check.greater_than(0)),
    "high": Column(float, Check.greater_than(0)),
    "low": Column(float, Check.greater_than(0)),
    "close": Column(float, Check.greater_than(0)),
    "volume": Column(int, Check.greater_than_or_equal_to(0)),
}, checks=[
    Check(lambda df: df["high"] >= df["low"], error="High must be >= Low"),
    Check(lambda df: df["high"] >= df["open"], error="High must be >= Open"),
    Check(lambda df: df["high"] >= df["close"], error="High must be >= Close"),
    Check(lambda df: df["low"] <= df["open"], error="Low must be <= Open"),
    Check(lambda df: df["low"] <= df["close"], error="Low must be <= Close"),
])

def validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCV verisini doğrula, hatalı satırları maskele"""
    try:
        return ohlcv_schema.validate(df, lazy=True)
    except pa.errors.SchemaErrors as e:
        logger.warning("OHLCV validation errors", errors=e.failure_cases)
        # Hatalı satırları maskele (silme!)
        mask = _build_error_mask(df, e.failure_cases)
        return df[mask]
```

### 8. API GÜVENLİĞİ — Eksik Katmanlar

**Durum:** Auth mevcut ama production-ready değil.

**İyileştirmeler:**
- **Rate limiting**: `slowapi` veya Redis-based sliding window
- **CORS**: Daha restrictive CORS policy
- **Request validation**: Pydantic ile strict input validation
- **API versioning**: `/api/v1/` prefix
- **OpenTelemetry tracing**: Her request için trace

```python
# services/api/middleware.py
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, storage_uri="redis://redis:6379")

@router.get("/api/v1/decisions")
@limiter.limit("100/minute")
async def get_decisions(request: Request):
    ...
```

### 9. TEST INFRASTRUCTURE — Eksik Katmanlar

**İyileştirmeler:**
- **Property-based testing**: Hypothesis ile edge case keşfi
- **Mutation testing**: mutpy ile test kalitesi ölçümü
- **Contract testing**: API contract testing (schemathesis)
- **Load testing**: locust ile API load testleri

```python
# tests/test_properties.py — Hypothesis tabanlı
from hypothesis import given, strategies as st

@given(
    price=st.floats(min_value=0.01, max_value=10000),
    volume=st.integers(min_value=0, max_value=1_000_000_000),
    mask=st.integers(min_value=0, max_value=1),
)
def test_feature_computation_never_crashes(price, volume, mask):
    """Feature hesaplama hiçbir girdide crash olmamalı"""
    result = compute_features(price=price, volume=volume, mask=mask)
    assert result is not None
    assert not np.isnan(result.get("momentum", 0))
```

### 10. DEPLOYMENT — Eksik CI/CD

**İyileştirmeler:**
- **GitHub Actions**: Otomatik test + lint + build
- **Docker multi-stage build**: Image boyutunu küçült
- **Health check standardization**: Tüm servisler için统一 health endpoint
- **Graceful shutdown**: SIGTERM handling

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:17-alpine
        env:
          POSTGRES_PASSWORD: test
          POSTGRES_DB: alpha_bist_test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:8-alpine
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: ruff check .
      - run: mypy services/ --ignore-missing-imports
      - run: pytest tests/ -x --timeout=30 -q
```

---

## 📋 Öncelikli Upgrade Planı

### Faz 0 — Hemen (Bu Sprint)
| # | Upgrade | Etki | Zorluk |
|---|---------|------|--------|
| 1 | Redis cache entegrasyonu | 🔴 Yüksek | 🟢 Düşük |
| 2 | Rate limiting (slowapi) | 🔴 Yüksek | � Düşük |
| 3 | Pandera data validation | 🔴 Yüksek | 🟢 Düşük |
| 4 | pgBouncer connection pooling | � Orta | 🟢 Düşük |
| 5 | Custom Prometheus metrics | � Orta | � Düşük |

### Faz 1 — Kısa Vadeli (1-2 Hafta)
| # | Upgrade | Etki | Zorluk |
|---|---------|------|--------|
| 6 | OpenTelemetry tracing | 🔴 Yüksek | � Orta |
| 7 | Feature store (Redis-based) | 🔴 Yüksek | � Orta |
| 8 | CI/CD pipeline (GitHub Actions) | 🔴 Yüksek | � Orta |
| 9 | Grafana alert rules | � Orta | � Düşük |
| 10 | Redpanda → Redis Streams | � Orta | � Orta |

### Faz 2 — Orta Vadeli (1 Ay)
| # | Upgrade | Etki | Zorluk |
|---|---------|------|--------|
| 11 | ClickHouse materialized views | 🔴 Yüksek | � Orta |
| 12 | Feature drift detection (PSI) | 🔴 Yüksek | � Orta |
| 13 | PostgreSQL read replica | � Orta | � Orta |
| 14 | Mutation testing (mutpy) | � Orta | � Düşük |
| 15 | Load testing (locust) | � Orta | � Düşük |

### Faz 3 — Uzun Vadeli (2-3 Ay)
| # | Upgrade | Etki | Zorluk |
|---|---------|------|--------|
| 16 | SigNoz (unified observability) | � Orta | 🔴 Yüksek |
| 17 | Feast feature store (enterprise) | � Orta | 🔴 Yüksek |
| 18 | A/B testing framework | � Orta | � Orta |
| 19 | AutoML (Optuna integration) | � Düşük | � Orta |
| 20 | Multi-environment (staging/prod) | � Orta | 🔴 Yüksek |

---

## 🎯 Sonuç

Mevcut stack temel olarak doğru seçilmiş:
- ✅ **PostgreSQL** — ACID için doğru
- ✅ **ClickHouse** — Zaman serisi için doğru
- ✅ **Redis** — Cache için doğru
- ✅ **FastAPI** — API için doğru
- ✅ **LightGBM** — ML için doğru
- ⚠️ **Redpanda** — Fazla karmaşık, Redis Streams yeterli
- ⚠️ **MLflow** — Doğru seçim ama daha iyi kullanılmalı

Asıl sorun teknoloji seçimi değil, **entegrasyon kalitesi**:
- Feature'lar hesaplanıp cache'lenmiyor
- Data validation sistematik değil
- Monitoring sadece health check düzeyinde
- Test paketinde sahte assertion'lar var
- CI/CD pipeline eksik

**Önerilen strateji:** Yeni teknoloji ekleme → mevcut olanları doğru kullan.
