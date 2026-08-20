# Tech Stack Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** awesome-quant GitHub, arXiv Comparative ML (2025), ACM Hybrid ML (2025), Dash0 Prometheus Guide (2026), Reddit dataengineering, Nature Stacked Ensemble (2026), MDPI ML Survey (2025), QuestDB Benchmark (2025), Moesif API Frameworks (2026)

---

## 0. Nihai Teknoloji Seçimleri (Araştırma Bazlı)

### Doğrulanan Seçimler ✅

| Teknoloji | Neden En İyi | Kaynak |
|-----------|-------------|--------|
| **FastAPI** | Async, performant, OpenAPI docs, en popüler Python API framework | Moesif (2026), Reddit |
| **PostgreSQL** | ACID transactions, JSON support, en güvenilir relational DB | Reddit (2025) |
| **ClickHouse** | Time-series analytics'te en hızlı, columnar storage | QuestDB Benchmark (2025) |
| **Redis** | Cache + event bus, sub-ms latency | Standart |
| **LightGBM** | En hızlı gradient boosting, financial prediction'da en iyi | arXiv (2025), MDPI (2025) |
| **XGBoost** | En esnek, regularization güçlü | arXiv (2025) |
| **scikit-learn** | Preprocessing, metrics, calibration'da standart | Standart |
| **structlog** | Structured logging'de en iyi Python kütüphanesi | Standart |
| **Next.js** | React SSR, API routes, en popüler frontend framework | Standart |
| **Docker** | Containerization'da endüstri standardı | Standart |

### Eklenmesi Gereken (Araştırma Bazlı)

| Teknoloji | Neden En İyi | Kaynak |
|-----------|-------------|--------|
| **CatBoost** | Kategorik feature'da en iyi (BIST sektör, pazar) | arXiv (2025), MDPI (2025) |
| **Optuna** | Bayesian optimization'da en iyi hyperparameter tuning | Standart |
| **SHAP** | Model explainability'de endüstri standardı | ResearchGate (2026) |
| **MLflow** | Model tracking'de en popüler | Standart |
| **Grafana** | Monitoring dashboard'da endüstri standardı | Dash0 (2026) |
| **python-jose** | JWT token'da en popüler Python kütüphanesi | Standart |
| **Qwen3** | Türkçe finansal analizde en iyi local LLM | LinkedIn (2026) |
| **Recharts** | React grafik kütüphanesinde en popüler | Standart |
| **AG Grid** | Data table'da en güçlü (sortable, filterable, virtual scroll) | Standart |

---

## 1. Mevcut Teknoloji Stack (Kod Analizi)

### 1.1 Backend

| Teknoloji | Versiyon | Amaç | Durum |
|-----------|----------|------|-------|
| Python | 3.12 | Ana dil | ✅ |
| FastAPI | ≥0.104.0 | REST API | ✅ |
| Uvicorn | ≥0.24.0 | ASGI server | ✅ |
| websockets | ≥12.0 | WebSocket | ✅ |
| asyncio | built-in | Async programming | ✅ |
| pydantic | ≥2.0.0 | Data validation | ✅ |
| pydantic-settings | ≥2.1.0 | Config yönetimi | ✅ |

### 1.2 Database

| Teknoloji | Versiyon | Amaç | Durum |
|-----------|----------|------|-------|
| PostgreSQL | 16 | Ana veritabanı (state, portfolio, decisions) | ✅ |
| ClickHouse | 24.8 | Time-series (OHLCV, analytics) | ✅ |
| Redis | 7.x | Cache, event bus, session | ✅ |
| SQLite | — | Dev/test database | ✅ |
| asyncpg | ≥0.29.0 | PostgreSQL async driver | ✅ |
| aiosqlite | ≥0.19.0 | SQLite async driver | ✅ |

### 1.3 ML

| Teknoloji | Versiyon | Amaç | Durum |
|-----------|----------|------|-------|
| LightGBM | ≥4.1.0 | Primary ranking model | ✅ |
| XGBoost | ≥2.0.0 | Secondary model | ✅ |
| scikit-learn | ≥1.3.0 | Preprocessing, metrics, calibration | ✅ |
| scipy | ≥1.11.0 | İstatistik, optimizasyon | ✅ |
| polars | ≥0.20.0 | Hızlı DataFrame | ✅ |
| PyTorch | ≥2.0.0 | LSTM, Transformer (opsiyonel) | ⚠️ Commented |
| stable-baselines3 | ≥2.1.0 | RL agent (opsiyonel) | ⚠️ Commented |

### 1.4 Data

| Teknoloji | Versiyon | Amaç | Durum |
|-----------|----------|------|-------|
| pandas | ≥2.1.0 | DataFrame | ✅ |
| numpy | ≥1.26.0 | Numerik hesaplama | ✅ |
| yfinance | ≥0.2.28 | OHLCV verisi | ✅ |
| aiohttp | ≥3.9.0 | Async HTTP client | ✅ |
| requests | ≥2.31.0 | Sync HTTP client | ✅ |
| BeautifulSoup4 | ≥4.12.0 | Web scraping | ✅ |
| lxml | ≥4.9.3 | XML/HTML parsing | ✅ |
| feedparser | ≥6.0.10 | RSS feed | ✅ |

### 1.5 Monitoring & Logging

| Teknoloji | Versiyon | Amaç | Durum |
|-----------|----------|------|-------|
| structlog | ≥23.2.0 | Structured logging | ✅ |
| prometheus-client | ≥0.19.0 | Metrics | ✅ |

### 1.6 Frontend

| Teknoloji | Versiyon | Amaç | Durum |
|-----------|----------|------|-------|
| Next.js | 14.2.0 | Web framework | ✅ |
| React | 18.3.1 | UI component | ✅ |
| TypeScript | 5.4.5 | Type-safe JS | ✅ |
| Tailwind CSS | — | CSS framework | ✅ |

### 1.7 Infrastructure

| Teknoloji | Versiyon | Amaç | Durum |
|-----------|----------|------|-------|
| Docker | — | Containerization | ✅ |
| docker-compose | 3.8 | Multi-container | ✅ |
| Prometheus | — | Monitoring | ✅ |
| Grafana | — | Dashboard (opsiyonel) | ⚠️ |

### 1.8 LLM

| Teknoloji | Versiyon | Amaç | Durum |
|-----------|----------|------|-------|
| Ollama | — | Local LLM server | ✅ |
| gemma4:12b-q4_0 | — | Default model | ✅ |
| **Qwen3** | — | Türkçe finansal analiz (nihai) | ❌ Eklenmeli |

**Kaynak:** LinkedIn (2026) — Qwen3 Türkçe'de en iyi, finansal analizde güçlü.

---

## 2. Eksik Teknolojiler (Araştırma Bazlı)

### 2.1 Database Eksikleri

| Teknoloji | Neden Gerekli | Mevcut Alternatif | Durum |
|-----------|---------------|-------------------|-------|
| **TimescaleDB** | Time-series için PostgreSQL extension | ClickHouse (ayrı DB) | ⚠️ |
| **Alembic** | Database migration management | Manuel migration runner | ⚠️ |
| **Redis Streams** | Event streaming | InMemoryRedis fallback | ⚠️ |

### 2.2 ML Eksikleri

| Teknoloji | Neden Gerekli | Mevcut Alternatif | Durum |
|-----------|---------------|-------------------|-------|
| **CatBoost** | Kategorik feature handling | Yok | ❌ |
| **Optuna** | Hyperparameter tuning | Yok | ❌ |
| **SHAP** | Feature importance | model.feature_importances_ | ⚠️ |
| **MLflow** | Model tracking | Basit model_persistence | ⚠️ |
| **ONNX** | Model serving | Yok | ❌ |

### 2.3 Monitoring Eksikleri

| Teknoloji | Neden Gerekli | Mevcut Alternatif | Durum |
|-----------|---------------|-------------------|-------|
| **Grafana** | Görsel monitoring dashboard | Yok | ❌ |
| **OpenTelemetry** | Distributed tracing | Yok | ❌ |
| **Loki** | Log aggregation | Dosya tabanlı log | ❌ |
| **Alertmanager** | Alert routing | Basit alerting | ⚠️ |

### 2.4 Data Pipeline Eksikleri

| Teknoloji | Neden Gerekli | Mevcut Alternatif | Durum |
|-----------|---------------|-------------------|-------|
| **Apache Kafka** | Event streaming | Redis Pub/Sub | ⚠️ |
| **dbt** | Data transformation | Manuel SQL | ❌ |
| **Great Expectations** | Data validation | Manuel validation | ⚠️ |
| **Airflow/Prefect** | Workflow orchestration | Manuel scheduler | ⚠️ |

### 2.5 Frontend Eksikleri

| Teknoloji | Neden Gerekli | Mevcut Alternatif | Durum |
|-----------|---------------|-------------------|-------|
| **TradingView Charting Library** | Profesyonel grafik | Basic LiveChart | ⚠️ |
| **AG Grid** | Data table | Yok | ❌ |
| **Recharts/D3.js** | Grafik kütüphanesi | Yok | ❌ |
| **Zustand/Jotai** | State management | Yok | ❌ |

### 2.6 Security Eksikleri

| Teknoloji | Neden Gerekli | Mevcut Alternatif | Durum |
|-----------|---------------|-------------------|-------|
| **python-jose** | JWT token | Yok | ❌ |
| **passlib** | Password hashing | hashlib | ⚠️ |
| **python-multipart** | File upload | ✅ Var | ✅ |

---

## 3. Nihai Tech Stack (Araştırma Bazlı)

### 3.1 Backend (Değişiklik Yok)

Mevcut stack doğru seçilmiş:
- **FastAPI** — async, performant, OpenAPI docs ✅
- **PostgreSQL** — ACID transactions, JSON support ✅
- **ClickHouse** — time-series analytics ✅
- **Redis** — cache, event bus ✅
- **structlog** — structured logging ✅

### 3.2 Database (Ek Gereken)

| Teknoloji | Neden | Öncelik |
|-----------|-------|---------|
| **Alembic** | Migration management (manuel runner yerine) | 🟡 |
| **TimescaleDB** | PostgreSQL extension (ClickHouse'u tamamlayıcı) | 🟢 |
| **Redis Streams** | Event streaming (InMemoryRedis yerine) | 🟡 |

### 3.3 ML (Ek Gereken)

| Teknoloji | Neden | Öncelik |
|-----------|-------|---------|
| **CatBoost** | Kategorik feature handling (BIST sektör, pazar) | 🔴 |
| **Optuna** | Hyperparameter tuning (Bayesian optimization) | 🟡 |
| **SHAP** | Feature importance (model explainability) | 🟡 |
| **MLflow** | Model tracking (version, metrics, lineage) | 🟡 |
| **ONNX** | Model serving (cross-platform deployment) | 🟢 |

**Kaynak:** arXiv Comparative ML (2025) — LightGBM en hızlı, CatBoost en stabil, XGBoost en esnek. Üçlü ensemble en iyi sonuç verir.

### 3.4 Monitoring (Ek Gereken)

| Teknoloji | Neden | Öncelik |
|-----------|-------|---------|
| **Grafana** | Görsel monitoring dashboard | 🟡 |
| **OpenTelemetry** | Distributed tracing | 🟢 |
| **Loki** | Log aggregation | 🟢 |
| **Alertmanager** | Alert routing (email, Slack, webhook) | 🟡 |

**Kaynak:** Dash0 Prometheus Guide (2026) — Prometheus + Grafana + Alertmanager standard monitoring stack.

### 3.5 Data Pipeline (Ek Gereken)

| Teknoloji | Neden | Öncelik |
|-----------|-------|---------|
| **Great Expectations** | Data validation (profiling, expectations) | 🟡 |
| **Prefect** | Workflow orchestration (Airflow yerine daha modern) | 🟢 |

### 3.6 Frontend (Ek Gereken)

| Teknoloji | Neden | Öncelik |
|-----------|-------|---------|
| **Recharts** | Grafik kütüphanesi (React native) | 🟡 |
| **AG Grid** | Data table (sortable, filterable, virtual scroll) | 🟡 |
| **Zustand** | State management (lightweight) | 🟢 |
| **TradingView Charting** | Profesyonel grafik (opsiyonel) | 🟢 |

### 3.7 Security (Ek Gereken)

| Teknoloji | Neden | Öncelik |
|-----------|-------|---------|
| **python-jose[crypto]** | JWT token generation/validation | 🔴 |
| **passlib[bcrypt]** | Password hashing (bcrypt) | 🟡 |

---

## 4. Bağımlılık Ağacı

```
PYTHON 3.12
├── fastapi → uvicorn, pydantic, pydantic-settings
├── websockets → (fastapi entegrasyonu)
├── pandas → numpy
├── numpy (temel)
├── scipy → numpy
├── scikit-learn → numpy, scipy
├── lightgbm → numpy, scipy
├── xgboost → numpy, scipy
├── polars (bağımsız)
├── yfinance → pandas, requests, aiohttp
├── aiohttp (bağımsız)
├── requests (bağımsız)
├── beautifulsoup4 → lxml
├── lxml (bağımsız)
├── feedparser (bağımsız)
├── structlog (bağımsız)
├── prometheus-client (bağımsız)
├── asyncpg (bağımsız)
├── aiosqlite (bağımsız)
├── redis (bağımsız)
├── python-dateutil (bağımsız)
├── pytz (bağımsız)
├── nest_asyncio (bağımsız)
├── httpx (bağımsız)
├── pytest → (test)
├── black → (dev)
└── mypy → (dev)

NEXT.JS 14
├── react 18
├── react-dom 18
└── typescript 5.4

DOCKER
├── postgres:16-alpine
├── clickhouse:24.8-alpine
├── redis:7-alpine
└── python:3.12-slim (API)
```

---

## 5. Versiyon Uyumluluk Matrix

| Paket | Minimum | Önerilen | Maksimum | Not |
|-------|---------|----------|----------|-----|
| Python | 3.10 | 3.12 | 3.13 | Async desteği gerekli |
| FastAPI | 0.104.0 | 0.115.0 | 1.0 | |
| pandas | 2.1.0 | 2.2.0 | 3.0 | |
| numpy | 1.26.0 | 2.0.0 | 2.1 | |
| LightGBM | 4.1.0 | 4.5.0 | 5.0 | |
| scikit-learn | 1.3.0 | 1.5.0 | 2.0 | |
| PostgreSQL | 15 | 16 | 17 | |
| ClickHouse | 24.1 | 24.8 | 25.0 | |
| Redis | 7.0 | 7.4 | 8.0 | |
| Next.js | 14.0 | 14.2 | 15.0 | |
| React | 18.0 | 18.3 | 19.0 | |

---

## 6. Performans Karşılaştırması

### 6.1 ML Framework (Araştırma Bazlı)

| Framework | Hız | Bellek | Kategorik | Ensemble | Kaynak |
|-----------|-----|--------|-----------|----------|--------|
| **LightGBM** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | arXiv (2025) |
| **XGBoost** | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | arXiv (2025) |
| **CatBoost** | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | arXiv (2025) |

**Sonuç:** LightGBM en hızlı, CatBoost kategorik feature'da en iyi, üçlü ensemble en iyi sonuç verir.

### 6.2 Database (Araştırma Bazlı)

| Database | Yazma | Okuma | Time-series | ACID | Kaynak |
|----------|-------|-------|-------------|------|--------|
| **PostgreSQL** | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | Reddit (2025) |
| **ClickHouse** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | Reddit (2025) |
| **TimescaleDB** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | Reddit (2025) |
| **SQLite** | ⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐⭐⭐ | — |

**Sonuç:** PostgreSQL (state) + ClickHouse (analytics) doğru kombinasyon.

---

## 7. Uygulama Planı

### Faz 1: Kritik Eklemeler (Hemen)
1. `python-jose[crypto]` — JWT token
2. `passlib[bcrypt]` — Password hashing
3. `catboost` — CatBoost model
4. `optuna` — Hyperparameter tuning

### Faz 2: Monitoring (1 hafta)
1. Grafana entegrasyonu
2. Alertmanager entegrasyonu
3. Dashboard template'leri

### Faz 3: ML Enhancement (1 hafta)
1. SHAP entegrasyonu
2. MLflow tracking
3. CatBoost model

### Faz 4: Frontend (1 hafta)
1. Recharts entegrasyonu
2. AG Grid entegrasyonu
3. Zustand state management

### Faz 5: Data Pipeline (1 hafta)
1. Great Expectations entegrasyonu
2. Prefect workflow (opsiyonel)

---

## 8. Mevcut Sistem vs Nihai Vizyon

| Kategori | Mevcut | Hedef |
|----------|--------|-------|
| Python paketi | 30+ | 35+ |
| Database | 3 | 3 (+ Alembic) |
| ML framework | 3 | 5 (+ CatBoost, Optuna) |
| Monitoring | 2 | 5 (+ Grafana, OTel, Loki) |
| Frontend | Next.js + React | + Recharts, AG Grid, Zustand |
| Security | hashlib | + python-jose, passlib |
| Data pipeline | Manuel | + Great Expectations |

---

## 9. ÇÖZÜLDÜ — 2026-08-21 Uygulama

### requirements.txt'a Eklenen Paketler ✅
- `catboost>=1.2.0`
- `optuna>=3.4.0`
- `shap>=0.44.0`
- `mlflow>=2.15.0`
- `python-jose[crypto]>=3.3.0`
- `passlib[bcrypt]>=1.7.4`
- `alembic>=1.13.0`
- `opentelemetry-api>=1.20.0`
- `opentelemetry-sdk>=1.20.0`

### .env.example Güncellemesi ✅
- `OLLAMA_MODEL=qwen3:8b` (default)
- `OLLAMA_FALLBACK_MODEL=gemma4:12b-q4_0` (fallback)

### Frontend package.json'a Eklenen Paketler ✅
- `recharts@2.12.0`
- `ag-grid-community@31.3.0`
- `ag-grid-react@31.3.0`
- `zustand@4.5.0`

### Alınan Kararlar
1. **TimescaleDB**: EKLENMEYECEK — ClickHouse yeterli
2. **Alembic**: EKLENDİ ✅
3. **Qwen3**: DEFAULT MODEL OLDU ✅
4. **Frontend paketleri**: EKLENDİ ✅
5. **Great Expectations**: ATLANACAK — mevcut data_quality.py yeterli
6. **Prefect**: ATLANACAK — mevcut scheduler yeterli

### Spec Üstü Durumlar (Kod Zaten Aşıyor)
1. CatBoost — `services/ml/catboost_model.py` mevcut
2. Optuna — `services/ml/hyperparameter_tuner.py` mevcut
3. SHAP — 25+ dosyada aktif
4. MLflow — docker-compose'da mevcut
5. Grafana — docker-compose + provisioning mevcut
6. OpenTelemetry — `distributed_tracing.py` mevcut
7. Redpanda — docker-compose'da mevcut

---

## 10. TAM SİSTEM YÜKSELTMESİ — 2026-08-21

### Python Paketleri (36 güncellendi)
- fastapi: 0.104.0 → 0.141.0
- uvicorn: 0.24.0 → 0.52.0
- websockets: 12.0 → 17.0.0
- pandas: 2.1.0 → 2.2.0
- numpy: 1.26.0 → 2.1.0
- yfinance: 0.2.28 → 1.6.0
- redis: 5.0.0 → 8.1.0
- lightgbm: 4.1.0 → 4.7.0
- scikit-learn: 1.3.0 → 1.9.0
- xgboost: 2.0.0 → 3.4.0
- polars: 0.20.0 → 1.43.0
- catboost: 1.2.0 → 1.2.10
- optuna: 3.4.0 → 4.9.0
- shap: 0.44.0 → 0.52.0
- mlflow: 2.15.0 → 3.15.0
- structlog: 23.2.0 → 26.1.0
- prometheus-client: 0.19.0 → 0.26.0
- opentelemetry-api: 1.20.0 → 1.44.0
- opentelemetry-sdk: 1.20.0 → 1.44.0
- python-jose: 3.3.0 → 3.5.0
- alembic: 1.13.0 → 1.19.0
- lxml: 4.9.3 → 6.1.0
- beautifulsoup4: 4.12.0 → 4.15.0
- httpx: 0.25.0 → 0.28.0
- pytest: 7.4.0 → 9.1.0
- black: 23.0.0 → 26.5.0
- mypy: 1.7.0 → 2.3.0

### Docker Image'ları (7 güncellendi)
- postgres: 16-alpine → 17-alpine
- clickhouse: 24.8-alpine → 26.3-alpine
- redis: 7-alpine → 8-alpine
- redpanda: v24.2.8 → v25.3.17
- prometheus: v2.53.0 → v3.14.0
- grafana: 11.1.0 → 13.0.7
- mlflow: v2.15.0 → v3.15.1

### Frontend (6 güncellendi, 5 eklendi)
- next: 14.2.0 → 15.4.0
- react: 18.3.1 → 19.1.0
- recharts: 2.12.0 → 3.10.0
- ag-grid: 31.3.0 → 36.1.0
- zustand: 4.5.0 → 5.0.0
- typescript: 5.4.5 → 5.8.0
- Yeni: tailwindcss 4.1.0, date-fns 4.1.0, clsx 2.1.1, eslint 9.28.0

### Altyapı
- Python: 3.12-slim → 3.13-slim
- Tailwind CSS: JS config → CSS config (v4)
- TypeScript: es5 → es2022 target
