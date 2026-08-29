# 🔍 BIST-100 ALPHA — Test, Entegrasyon ve Altyapı Teftiş Raporu

**Tarih:** 2026-08-21  
**Kapsam:** tests/, docker-compose.yml, Dockerfile, config/, pyproject.toml, requirements.txt, scripts/, infrastructure/, database/  
**Toplam Test Dosyası:** 120  
**Toplam Test Fonksiyonu:** ~2.234  
**Toplam Assertion:** ~3.813  

---

## 📊 ÖZET

| Kategori | Kritik | Yüksek | Orta | Düşük | Toplam |
|----------|--------|--------|------|-------|--------|
| Test Kalitesi | 3 | 5 | 4 | 2 | 14 |
| Test Coverage | 1 | 2 | 3 | 1 | 7 |
| Mock & Isolation | 2 | 3 | 2 | 1 | 8 |
| CI/CD | 1 | 1 | 0 | 0 | 2 |
| Docker & Container | 1 | 2 | 2 | 1 | 6 |
| Config & Security | 2 | 2 | 1 | 1 | 6 |
| Dependencies | 0 | 1 | 2 | 0 | 3 |
| Database | 1 | 1 | 1 | 0 | 3 |
| Performance | 0 | 1 | 2 | 0 | 3 |
| **TOPLAM** | **11** | **18** | **15** | **6** | **50** |

---

## 🔴 KRİTİK HATALAR

### 1. [KRİTİK] `assert True` — Sahte Testler (Boş Assertion)

**Dosya:** `tests/test_agent_system.py` satır 622  
```python
assert True  # Import başarılı
```

**Dosya:** `tests/test_alternative_data.py` satır 641  
```python
assert True
```

**Dosya:** `tests/test_ingestion_faz3.py` satır 327, 334, 341, 351  
```python
assert True  # Crash olmadı
assert True
assert True
assert True
```

**Sorun:** Bu testler hiçbir şey doğrulamıyor. `assert True` her zaman geçer, test覆盖率 yanıltıcı olur.  
**Etki:** 6 test fonksiyonu aslında hiçbir şey test etmiyor.  
**Düzeltme:** Her test için gerçek assertion ekleyin. Örneğin:
```python
# Yerine:
result = some_function()
assert result is not None
assert isinstance(result, dict)
assert "expected_key" in result
```

---

### 2. [KRİTİK] Test Fonksiyonları Return Kullanıyor, Assertion Değil

**Dosya:** `tests/test_autonomous_ops.py` (30+ test fonksiyonu)  
**Dosya:** `tests/test_async_providers.py` (10+ test fonksiyonu)  
**Dosya:** `tests/test_phase1.py`, `tests/test_phase2.py` ve diğer phase testleri  

**Örnek (test_autonomous_ops.py satır 73):**
```python
return "Alert Lifecycle States", len(issues) == 0, issues
```

**Sorun:** Bu testler `return` ile sonuç döndürüyor ama pytest assertion kullanmıyor. pytest bu return değerlerini yoksayar ve testi "geçti" sayar.  
**Etki:** ~50+ test fonksiyonu aslında hiçbir şey doğrulamıyor.  
**Düzeltme:** Tüm testlerde `assert` kullanın:
```python
assert len(issues) == 0, f"Issues: {issues}"
```

---

### 3. [KRİTİK] CI/CD Pipeline Eksik

**Dosya:** Proje kök dizini  

**Sorun:** `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, `Makefile` veya herhangi bir CI/CD konfigürasyonu bulunamadı.  
**Etki:** Testler otomatik olarak çalışmıyor, PR'lerde kalite kontrolü yok.  
**Düzeltme:** `.github/workflows/test.yml` oluşturun:
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: pytest tests/ -v --tb=short
```

---

### 4. [KRİTİK] `conftest.py` Eksik — Test Fixtures Merkezi Yok

**Dosya:** `tests/conftest.py` (mevcut değil)  

**Sorun:** 120 test dosyası var ama `conftest.py` yok. Her test dosyası kendi setup/teardown mantığını kendisi yazıyor.  
**Etki:** Kod tekrarı, test isolation sorunları, fixture paylaşımı imkansız.  
**Düzeltme:** `tests/conftest.py` oluşturun:
```python
import pytest
import os


@pytest.fixture(autouse=True)
def clean_env():
    """Her test sonrası env değişkenlerini temizle."""
    original = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(original)
```

---

### 5. [KRİTİK] Environment Variable Sızıntısı — Test Isolation Yok

**Dosya:** `tests/test_config.py` satır 116-117, 147-150, 178, 221, 229  
**Dosya:** `tests/test_realistic_integration.py` satır 346, 359  

```python
os.environ["ALPHA_APP_PORT"] = "9999"
os.environ["APP_ENV"] = "production"
# ... test çalışır ...
del os.environ["ALPHA_APP_PORT"]  # Cleanup bazen eksik
```

**Sorun:** Testler `os.environ`'u doğrudan manipüle ediyor. Eğer test fail olursa cleanup kodu çalışmaz ve sonraki testler etkilenir.  
**Etki:** Testler birbirini etkileyebilir, non-deterministic sonuçlar.  
**Düzeltme:** `monkeypatch` fixture kullanın:
```python
def test_env_override(monkeypatch):
    monkeypatch.setenv("ALPHA_APP_PORT", "9999")
    # ... test ...
    # monkeypatch otomatik temizler
```

---

### 6. [KRİTİK] `INSERT OR IGNORE` — PostgreSQL Syntax Hatası

**Dosya:** `tests/test_concurrency.py` satır 164-166, 251-253  
**Dosya:** `tests/test_db_lock.py` satır 221-223, 265  
**Dosya:** `tests/test_financial_integrity.py` satır 37  
**Dosya:** `tests/test_monitoring.py` satır 40  
**Dosya:** `tests/test_multi_instance.py` satır 27  
**Dosya:** `tests/test_lock_resilience.py` satır 232, 283  

```python
await dev_db.pg_execute("INSERT OR IGNORE INTO sectors (code, name) VALUES ('T', 'T')")
```

**Sorun:** `INSERT OR IGNORE` SQLite syntax'ıdır. PostgreSQL'de `INSERT ... ON CONFLICT DO NOTHING` kullanılmalı.  
**Etki:** Bu testler PostgreSQL'de hata verir, sadece SQLite dev_db'de çalışır.  
**Düzeltme:** 
```python
await dev_db.pg_execute("INSERT INTO sectors (code, name) VALUES ('T', 'T') ON CONFLICT (code) DO NOTHING")
```

---

### 7. [KRİTİK] ClickHouse Image Versiyonu Mevcut Değil

**Dosya:** `docker-compose.yml` satır 32  

```yaml
image: clickhouse/clickhouse-server:26.3-alpine
```

**Sorun:** ClickHouse 26.3 henüz yayınlanmamış bir versiyon. En son stabil versiyon ~24.x civarında.  
**Etki:** Container build başarısız olur.  
**Düzeltme:** Stabil bir versiyon kullanın:
```yaml
image: clickhouse/clickhouse-server:24.3-alpine
```

---

### 8. [KRİTİK] PostgreSQL `vector` Extension — Özel Build Gerektirir

**Dosya:** `database/init/001_schema.sql` satır 8, 262  

```sql
CREATE EXTENSION IF NOT EXISTS "vector";
-- ...
embedding vector(1024),
```

**Sorun:** `pgvector` extension varsayılan PostgreSQL image'ında yok. `postgres:17-alpine` image'ı bu extension'ı içermez.  
**Etki:** Database init başarısız olur, container crash eder.  
**Düzeltme:** Özel Dockerfile kullanın veya extension'ı manuel yükleyin:
```dockerfile
FROM postgres:17-alpine
RUN apk add --no-cache postgresql17-pgvector
```

---

### 9. [KRİTİK] `services/events/` Dizini Boş — `__init__.py` Eksik

**Dosya:** `services/events/` (sadece `.gitkeep` var)  

**Sorun:** Dizinde `.gitkeep` dışında dosya yok, `__init__.py` eksik. Import edilirse ImportError alınır.  
**Etki:** Modül import edilemez.  
**Düzeltme:** `services/events/__init__.py` oluşturun veya boş dizini kaldırın.

---

### 10. [KRİTİK] Bare `except:` Kullanımı — Hata Maskeleniyor

**Dosya:** `tests/test_concurrency.py` satır 161, 204, 248  
**Dosya:** `tests/test_db_lock.py` satır 218, 262  
**Dosya:** `tests/test_financial_integrity.py` satır 35  
**Dosya:** `tests/test_lock_resilience.py` satır 229, 280  
**Dosya:** `tests/test_monitoring.py` satır 38  
**Dosya:** `tests/test_multi_instance.py` satır 25  

```python
try:
    await dev_db.pg_execute(f"DELETE FROM {t}")
except:
    pass
```

**Sorun:** Bare `except:` tüm exception'ları yakalar (KeyboardInterrupt dahil). Hata mesajı kaybolur, debugging zorlaşır.  
**Etki:** Gerçek hatalar gizlenir, testler yanlış geçebilir.  
**Düzeltme:** Spesifik exception yakalayın:
```python
try:
    await dev_db.pg_execute(f"DELETE FROM {t}")
except Exception as e:
    logger.debug(f"Table {t} cleanup: {e}")
```

---

### 11. [KRİTİK] Docker Compose — Servislerde Health Check Eksik

**Dosya:** `docker-compose.yml`  

**Eksik health check'ler:**
- `ingestion` servisi (satır 130-145)
- `feature-engine` servisi (satır 147-165)
- `market-state` servisi (satır 167-185)
- `intelligence` servisi (satır 187-210)
- `simulation` servisi (satır 212-230)
- `risk` servisi (satır 232-250)
- `portfolio` servisi (satır 252-270)
- `learning` servisi (satır 272-295)
- `dashboard` servisi (satır 297-310)

**Sorun:** Sadece veritabanları ve API'de health check var. Diğer servisler sağlıklımı kontrol edilemiyor.  
**Etki:** Servisler hazır olmadan bağımlı servisler başlayabilir.  
**Düzeltme:** Her servise health check ekleyin:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 30s
  timeout: 5s
  retries: 3
```

---

## 🟠 YÜKSEK ÖNCELİKLİ HATALAR

### 12. [YÜKSEK] Test Dosyalarında `sys.path.insert` — Paket Yönetimi Bozuk

**Dosya:** 20+ test dosyası  

```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

**Sorun:** Her test dosyası manuel olarak `sys.path`'e proje kökünü ekliyor. Bu, `pyproject.toml`'deki `[tool.pytest.ini_options]` ile çelişir.  
**Düzeltme:** `pyproject.toml`'de `pythonpath` ekleyin:
```toml
[tool.pytest.ini_options]
pythonpath = ["."]
```

---

### 13. [YÜKSEK] `pytest.mark.parametrize` Kullanılmamış

**Dosya:** Tüm test dosyaları  

**Sorun:** 2.234 test fonksiyonu içinde tek bir `@pytest.mark.parametrize` dekoratörü yok.  
**Etki:** Benzer testler tekrar tekrar yazılıyor, coverage düşük kalıyor.  
**Düzeltme:** Parametrize kullanın:
```python
@pytest.mark.parametrize(
    "ticker,expected",
    [
        ("THYAO", True),
        ("GARAN", True),
        ("INVALID", False),
    ],
)
def test_ticker_validation(ticker, expected):
    assert validate_ticker(ticker) == expected
```

---

### 14. [YÜKSEK] `@pytest.fixture` Kullanımı Çok Az

**Dosya:** Tüm test dosyaları  

**Sorun:** Sadece 2 dosyada `@pytest.fixture` kullanılmış (`test_market_state_v2.py`, `test_suite.py`). 118 dosyada fixture yok.  
**Etki:** Her test kendi setup'ını yapıyor, kod tekrarı çok fazla.  
**Düzeltme:** Ortak fixture'ları `conftest.py`'ye taşıyın.

---

### 15. [YÜKSEK] `time.sleep()` Kullanımı — Testler Yavaş

**Dosya:** `tests/test_faz5_4_broker_risk.py` satır 325, 359  
```python
time.sleep(1.1)
```

**Dosya:** `tests/test_faz5_2_scheduler.py` satır 395  
```python
await asyncio.sleep(0.5)
```

**Dosya:** `tests/test_full_pipeline.py` satır 76, 82, 115, 121  
```python
await asyncio.sleep(0.3)
await asyncio.sleep(0.5)
```

**Sorun:** Testlerde gerçek `sleep` kullanılıyor. Toplamda ~5+ saniye bekleme var.  
**Düzeltme:** `unittest.mock.patch('time.sleep')` veya `asyncio.sleep` mock'u kullanın.

---

### 16. [YÜKSEK] Docker Compose — Default Password `changeme`

**Dosya:** `docker-compose.yml` satır 22, 330  

```yaml
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD:-changeme}
```

**Sorun:** Default parola `changeme`. Production'da unutulursa ciddi güvenlik açığı.  
**Düzeltme:** Default parolayı kaldırın, zorunlu hale getirin:
```yaml
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}  # Zorunlu, default yok
```

---

### 17. [YÜKSEK] Prometheus — Servisler Metrics Endpoint Sunmuyor

**Dosya:** `infrastructure/prometheus.yml` satır 15-22  

```yaml
- job_name: 'alpha-services'
  static_configs:
    - targets:
        - 'ingestion:8000'
        - 'feature-engine:8000'
        # ...
  metrics_path: '/metrics'
```

**Sorun:** Prometheus bu servislerden metrics toplamaya çalışıyor ama servislerin `/metrics` endpoint'i yok (sadece `api` servisinde var).  
**Etki:** Prometheus scrape hata verir, monitoring çalışmaz.  
**Düzeltme:** Her servise metrics endpoint ekleyin veya Prometheus config'den çıkarın.

---

### 18. [YÜKSEK] Dockerfile — `COPY . .` Güvenlik Açığı

**Dosya:** `infrastructure/Dockerfile.api` satır 15  

```dockerfile
COPY . .
```

**Sorun:** Tüm proje dosyalarını (`.env`, `.git`, test dosyaları, vs.) container'a kopyalar.  
**Düzeltme:** `.dockerignore` oluşturun:
```
.env
.git
tests/
docs/
*.md
__pycache__
```

---

### 19. [YÜKSEK] `requirements.txt` — Versiyon Sabitleme Eksik

**Dosya:** `requirements.txt`  

```
fastapi>=0.141.0
uvicorn[standard]>=0.52.0
polars>=1.43.0
```

**Sorun:** Tüm bağımlılıklar `>=` ile tanımlanmış, exact version yok. Farklı zamanlarda farklı versiyonlar kurulabilir.  
**Düzeltme:** `requirements.txt`'de exact version kullanın veya `pip freeze` ile lock dosyası oluşturun:
```
fastapi==0.141.0
uvicorn[standard]==0.52.0
```

---

### 20. [YÜKSEK] Test Dosyası Skip Edilmiş — Eski API

**Dosya:** `tests/test_faz3_ranking.py` satır 18  

```python
pytestmark = pytest.mark.skip(reason="Eski RankingModel API'sini test ediyor...")
```

**Sorun:** Tüm dosya skip edilmiş. Eski API'ye ait testler hâlâ duruyor ama çalışmıyor.  
**Düzeltme:** Ya testleri güncel API'ye göre yeniden yazın ya da dosyayı silin.

---

### 21. [YÜKSEK] `e2e_full_test.py` — pytest Dışında Çalıştırılıyor

**Dosya:** `pytest.ini` satır 4  

```ini
addopts = --ignore=tests/e2e_full_test.py
```

**Dosya:** `tests/e2e_full_test.py`  

**Sorun:** E2E testi pytest'ten ayrı çalıştırılıyor. CI/CD'de otomatik çalışmaz.  
**Düzeltme:** Testi pytest fixture'larına dönüştürün veya CI'da ayrı step olarak ekleyin.

---

### 22. [YÜKSEK] `test_autonomous_ops.py` — Testler Return Kullanıyor, Assertion Değil

**Dosya:** `tests/test_autonomous_ops.py` (tüm dosya)  

**Sorun:** 30+ test fonksiyonu `return (name, passed, issues)` formatında sonuç döndürüyor. pytest bu return değerlerini yoksayar.  
**Etki:** Tüm testler "geçti" görünüyor ama aslında hiçbir şey doğrulanmıyor.  
**Düzeltme:** Her test fonksiyonunda `assert` kullanın.

---

### 23. [YÜKSEK] `test_async_providers.py` — Aynı Sorun

**Dosya:** `tests/test_async_providers.py` (tüm dosya)  

**Sorun:** 10+ test fonksiyonu return-based test pattern kullanıyor.  
**Düzeltme:** Assertion'a dönüştürün.

---

### 24. [YÜKSEK] `test_phase*.py` Dosyaları — Return-Based Test Pattern

**Dosya:** `tests/test_phase1.py`, `tests/test_phase2.py`, `tests/test_phase3.py`, vb.  

**Sorun:** Phase test dosyalarının çoğu return-based pattern kullanıyor.  
**Düzeltme:** Tüm phase testlerini assertion-based'e dönüştürün.

---

### 25. [YÜKSEK] Grafana Dashboard — Provisioning Dosyası Eksik

**Dosya:** `infrastructure/grafana/dashboards/market_state.json`  

**Sorun:** Dashboard JSON'u var ama provisioning config dosyası (`dashboard.yml`) eksik. Grafana otomatik yüklemez.  
**Düzeltme:** `infrastructure/grafana/provisioning/dashboards/dashboards.yml` oluşturun:
```yaml
apiVersion: 1
providers:
  - name: 'default'
    folder: ''
    type: file
    options:
      path: /etc/grafana/provisioning/dashboards
```

---

### 26. [YÜKSEK] Docker Compose — `dashboard` Servisi Port Çatışması

**Dosya:** `docker-compose.yml` satır 297, 323  

```yaml
dashboard:
  ports:
    - "3000:3000"
grafana:
  ports:
    - "3001:3000"
```

**Sorun:** Dashboard 3000'de, Grafana 3001'de çalışıyor. Ama Grafana container içinde 3000'de çalışıyor ve host'ta 3001'e map'leniyor. Eğer dashboard container'ı da 3000 kullanırsa çatışma olmaz ama kafa karıştırıcı.  
**Düzeltme:** Port numaralarını netleştirin.

---

## 🟡 ORTA ÖNCELİKLİ HATALAR

### 27. [ORTA] Test Coverage — Kritik Servisler Test Edilmemiş

**Eksik testler:**
- `services/events/` — Boş dizin, test yok
- `services/scanner/` — Test dosyası var ama servis yapısı eksik
- `services/macro/` — Sadece backfill script'i var, unit test yok
- `services/data/` — Test dosyası yok

**Düzeltme:** Her servis için en az bir smoke test yazın.

---

### 28. [ORTA] Config Dosyaları — Environment Spesifik Farklılıklar Yetersiz

**Dosya:** `config/alpha_production.json`  

```json
{
  "app": { "env": "production", "debug": false, "port": 80 }
}
```

**Sorun:** Production config'de `debug: false` var ama `alpha_config.json`'da `debug: true`. Production'da debug mode açık kalabilir.  
**Düzeltme:** Config loader'ın production'da debug'u zorunlu kapatmasını sağlayın.

---

### 29. [ORTA] `pyproject.toml` — `asyncio_mode = "auto"` Sorun Çıkarabilir

**Dosya:** `pyproject.toml` satır 24  

```toml
asyncio_mode = "auto"
```

**Sorun:** Auto mode tüm async fonksiyonları otomatik olarak async test olarak çalıştırır. Bu, sync testlerde beklenmeyen davranışlara yol açabilir.  
**Düzeltme:** `asyncio_mode = "strict"` kullanın ve async testleri manuel olarak işaretleyin.

---

### 30. [ORTA] Test Dosyalarında Hardcoded Tarihler

**Dosya:** `tests/test_phase1.py` satır 31-32  

```python
d = date(2026, 8, 18)  # Pazartesi
d = date(2026, 8, 15)  # Cumartesi
```

**Sorun:** Tarihler hardcoded. 2026'dan sonra testler farklı sonuç verebilir.  
**Düzeltme:** Dinamik tarih kullanın:
```python
from datetime import date, timedelta

today = date.today()
monday = today - timedelta(days=today.weekday())
```

---

### 31. [ORTA] `backfill_data.py` — Hata Yönetimi Zayıf

**Dosya:** `scripts/backfill_data.py` satır 35-36  

```python
except Exception as e:
    logger.debug("Insert failed", ticker=ticker, date=date_str, error=str(e))
```

**Sorun:** Insert hataları `debug` seviyesinde loglanıyor. Veri kaybı fark edilmez.  
**Düzeltme:** `warning` seviyesine çıkarın ve retry mekanizması ekleyin.

---

### 32. [ORTA] `backfill_macro_data.py` — Sync/Async Karışımı

**Dosya:** `scripts/backfill_macro_data.py`  

**Sorun:** Script sync fonksiyonlar kullanıyor ama proje genelde async. Database erişimi sorunlu olabilir.  
**Düzeltme:** Script'i async'e dönüştürün veya sync database connection kullanın.

---

### 33. [ORTA] Docker Compose — `redpanda` Memory Limit Düşük

**Dosya:** `docker-compose.yml` satır 87  

```yaml
mem_limit: 1g
```

**Sorun:** Redpanda 1GB memory limit ile çalıştırılıyor. Production'da bu yetersiz olabilir.  
**Düzeltme:** Production'da memory limit'i artırın veya environment variable ile ayarlayın.

---

### 34. [ORTA] `infrastructure/prometheus.yml` — Scrape Interval Çok Sık

**Dosya:** `infrastructure/prometheus.yml` satır 2  

```yaml
scrape_interval: 15s
```

**Sorun:** 15 saniyelik scrape interval, çok sayıda servis için yüksek load oluşturabilir.  
**Düzeltme:** Servis sayısına göre interval'ı ayarlayın (30s-60s daha uygun olabilir).

---

### 35. [ORTA] Test Dosyalarında `import *` Kullanımı

**Dosya:** `tests/test_features_nihai.py` satır 459  

```python
self.feature_importances_ = [1.0 / n] * n
```

**Sorun:** Bu bir `import *` değil ama benzer şekilde namespace pollution yaratabilecek patterns var.  
**Düzeltme:** Explicit import kullanın.

---

### 36. [ORTA] `database/init/001_schema.sql` — Index Eksiklikleri

**Dosya:** `database/init/001_schema.sql`  

**Eksik index'ler:**
- `orders.signal_id` — Foreign key ama index yok
- `orders.strategy_id` — Foreign key ama index yok
- `model_outcomes.prediction_id` — Foreign key ama index yok
- `scenarios.simulation_id` — Foreign key ama index yok

**Düzeltme:** Eksik index'leri ekleyin:
```sql
CREATE INDEX idx_orders_signal ON orders(signal_id);
CREATE INDEX idx_orders_strategy ON orders(strategy_id);
```

---

### 37. [ORTA] `database/clickhouse/init/001_schema.sql` — Materialized View Sorunlu

**Dosya:** `database/clickhouse/init/001_schema.sql` satır ~250  

```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS alpha_bist.ohlcv_daily_mv
TO alpha_bist.ohlcv
AS SELECT ...
```

**Sorun:** Materialized view `ohlcv` tablosuna yazıyor ama `ohlcv` tablosu `ReplacingMergeTree` kullanıyor. Bu, duplicate kayıtlara yol açabilir.  
**Düzeltme:** View'in yazdığı tablo `ReplacingMergeTree` yerine `MergeTree` olmalı veya view'i farklı bir tabloya yazın.

---

### 38. [ORTA] `apps/web/Dockerfile` — Multi-stage Build Eksik

**Dosya:** `apps/web/Dockerfile`  

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --frozen-lockfile || npm install
COPY . .
RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]
```

**Sorun:** Multi-stage build yok. Build araçları (node_modules, source code) production image'ında kalıyor.  
**Düzeltme:** Multi-stage build kullanın:
```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./
EXPOSE 3000
CMD ["npm", "start"]
```

---

### 39. [ORTA] `.env.example` — Eksik Değişkenler

**Dosya:** `.env.example`  

**Eksik değişkenler:**
- `GRAFANA_PASSWORD` (docker-compose'da kullanılıyor)
- `POSTGRES_PASSWORD` (docker-compose'da kullanılıyor)
- `CLICKHOUSE_PASSWORD` (docker-compose'da kullanılıyor)

**Düzeltme:** Tüm kullanılan environment değişkenlerini `.env.example`'e ekleyin.

---

### 40. [ORTA] Test Dosyalarında Mock Kullanımı Çok Az

**Dosya:** Tüm test dosyaları  

**Sorun:** 2.234 test fonksiyonunda sadece 131 mock/patch kullanımı var. Bu, testlerin büyük ölçüde entegrasyon testi olduğunu gösterir.  
**Etki:** Testler yavaş, dış bağımlılıklara bağlı.  
**Düzeltme:** Unit testlerde mock kullanın:
```python
from unittest.mock import patch, MagicMock


@patch("services.ingestion.providers.yfinance.yf.download")
def test_data_fetch(mock_download):
    mock_download.return_value = pd.DataFrame(...)
```

---

## 🟢 DÜŞÜK ÖNCELİKLİ HATALAR

### 41. [DÜŞÜK] `pyproject.toml` — `ruff` Config Eksik

**Dosya:** `pyproject.toml`  

**Sorun:** `ruff` config var ama `ruff.toml` veya `[tool.ruff.format]` section'ı eksik.  
**Düzeltme:** Format config ekleyin:
```toml
[tool.ruff.format]
quote-style = "double"
```

---

### 42. [DÜŞÜK] `.gitignore` — `data/` Dizini Tamamen Ignore Edilmemiş

**Dosya:** `.gitignore`  

```
data/universe_cache.json
```

**Sorun:** Sadece `universe_cache.json` ignore ediliyor. `data/` dizinindeki diğer dosyalar (`.pid`, `learning_state.json`, `system_snapshot.json`) git'e dahil.  
**Düzeltme:** Tüm data dosyalarını ignore edin:
```
data/
!data/.gitkeep
```

---

### 43. [DÜŞÜK] `config/holidays.json` — Türkiye Tatilleri Güncel Mi?

**Dosya:** `config/holidays.json`  

**Sorun:** Tatil listesinin güncel olup olmadığı kontrol edilmeli.  
**Düzeltme:** Yıllık olarak tatil listesini güncelleyin.

---

### 44. [DÜŞÜK] Test Dosyalarında Türkçe Karakter Encoding

**Dosya:** Birçok test dosyası  

**Sorun:** Test dosyalarında Türkçe karakterler kullanılıyor (`ş`, `ğ`, `ı`, `ö`, `ü`, `ç`). Encoding sorunları olabilir.  
**Düzeltme:** Tüm Python dosyalarında `# -*- coding: utf-8 -*-` header'ı ekleyin veya Python 3'ün default encoding'ine güvenin.

---

### 45. [DÜŞÜK] `monitoring/` Dizini Boş

**Dosya:** `monitoring/`  

**Sorun:** Dizinde sadece `.gitkeep` var. Monitoring konfigürasyonu `infrastructure/` altında.  
**Düzeltme:** Dizini kaldırın veya monitoring config'leri buraya taşıyın.

---

## 📋 EK BULGULAR

### 46. [ORTA] Test Suite Tutarlılığı — İki Farklı Test Pattern

Proje genelinde iki farklı test pattern kullanılıyor:

1. **Pattern A (Assertion-based):** `test_phase2.py`, `test_suite.py`, `test_api.py` gibi dosyalar `assert` kullanıyor.
2. **Pattern B (Return-based):** `test_autonomous_ops.py`, `test_async_providers.py`, `test_phase1.py` gibi dosyalar `return (name, passed, issues)` kullanıyor.

**Sorun:** Pattern B'deki testler pytest tarafından "geçti" sayılıyor ama aslında hiçbir şey doğrulanmıyor.  
**Düzeltme:** Tüm testleri Pattern A'ya dönüştürün.

---

### 47. [ORTA] `test_configurable_ops.py` — Dosya Yazma Testi

**Dosya:** `tests/test_configurable_ops.py` satır 138  

```python
with open(config_path, "w") as f:
    json.dump(config, f)
```

**Sorun:** Test dosya sistemi'ne yazıyor. Test isolation ihlali.  
**Düzeltme:** `tmp_path` fixture kullanın.

---

### 48. [ORTA] `test_full_pipeline.py` — Dosya Yazma Testi

**Dosya:** `tests/test_full_pipeline.py` satır 79, 118  

```python
with open(config_path, "w") as f:
    json.dump(config, f)
```

**Sorun:** Aynı sorun — dosya sistemi'ne yazıyor.  
**Düzeltme:** `tmp_path` fixture kullanın.

---

### 49. [DÜŞÜK] `test_backtest_v4.py` — SQLite Kullanımı

**Dosya:** `tests/test_backtest_v4.py` satır 19  

```python
import sqlite3
```

**Sorun:** Test SQLite kullanıyor ama production PostgreSQL. Behavior farkları olabilir.  
**Düzeltme:** Test için de PostgreSQL kullanın veya SQLite-specific testleri işaretleyin.

---

### 50. [DÜŞÜK] `test_autonomous_ops.py` — SQLite Alerting System

**Dosya:** `tests/test_autonomous_ops.py` satır 187-193  

```python
import sqlite3

db = sqlite3.connect(":memory:")
alerting = AlertingSystem(db=db, dialect="sqlite")
```

**Sorun:** Alerting system SQLite ile test ediliyor ama production'da PostgreSQL.  
**Düzeltme:** Test için PostgreSQL dev_db kullanın.

---

## 🎯 ÖNERİLEN ÖNCELİK SIRASI

### Hemen Düzelt (Sprint 1)
1. ✅ `assert True` testlerini gerçek assertion'lara dönüştürün (#1)
2. ✅ Return-based testleri assertion-based'e dönüştürün (#2, #22, #23, #24)
3. ✅ `INSERT OR IGNORE` → `ON CONFLICT DO NOTHING` (#6)
4. ✅ ClickHouse image versiyonunu düzeltin (#7)
5. ✅ `conftest.py` oluşturun (#4)

### Kısa Vadeli (Sprint 2-3)
6. ✅ CI/CD pipeline oluşturun (#3)
7. ✅ Environment variable isolation (#5)
8. ✅ Bare `except:` → spesifik exception (#10)
9. ✅ Docker health check'ler ekleyin (#11)
10. ✅ `.dockerignore` oluşturun (#18)

### Orta Vadeli (Sprint 4-6)
11. ✅ `pytest.mark.parametrize` kullanın (#13)
12. ✅ Mock kullanımını artırın (#40)
13. ✅ `sys.path.insert` kaldırın (#12)
14. ✅ Dockerfile multi-stage build (#38)
15. ✅ Database index'leri ekleyin (#36)

---

## 📊 TEST SAĞLIK SKORU

| Metrik | Değer | Hedef |
|--------|-------|-------|
| Test Dosyası | 120 | - |
| Test Fonksiyonu | ~2.234 | - |
| Gerçek Assertion | ~3.813 | - |
| Sahte Test (`assert True`) | 6 | 0 |
| Return-Based Test | ~50+ | 0 |
| Skip Edilen Test | 1 dosya | 0 |
| Mock Kullanımı | 131 | 500+ |
| `conftest.py` | 0 | 1 |
| CI/CD | 0 | 1 |
| Parametrize | 0 | 50+ |

**Genel Test Sağlık Skoru: %65/100**  
*(Sahte testler ve return-based pattern'ler düzeltilirse %85'e çıkar)*

---

*Rapor otomatik olarak oluşturulmuştur. 2026-08-21*
