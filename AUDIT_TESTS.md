# 🔍 ALPHA BIST — Test, Config, Docker & Script Derinlemesine Analiz Raporu

> **Tarih:** 2026-08-22  
> **Kapsam:** tests/, config/, database/, scripts/, docker-compose.yml, .env.example, requirements.txt, entry points, pyproject.toml, pytest.ini, monitoring/, infrastructure/  
> **Toplam Test Dosyası:** 97 | **Toplam Test Fonksiyonu:** ~2,247 | **Toplam Test Satırı:** ~52,699

---

## 📊 Yönetici Özeti

| Kategori | P0 (Kritik) | P1 (Yüksek) | P2 (Orta) | Toplam |
|----------|:-----------:|:------------:|:---------:|:------:|
| Sahte Test Assertion'ları | 1 | 3 | 2 | 6 |
| Eski/Uyumsuz Testler | 0 | 2 | 1 | 3 |
| Hard-coded Secret'lar | 1 | 1 | 0 | 2 |
| Çakışan Entry Point'ler | 1 | 2 | 1 | 4 |
| Eksik/Fazla Bağımlılıklar | 0 | 2 | 3 | 5 |
| Dead Code / Kullanılmayan Script'ler | 0 | 1 | 4 | 5 |
| Konfigürasyon Tutarsızlıkları | 1 | 2 | 1 | 4 |
| Docker/Altyapı Sorunları | 1 | 2 | 2 | 5 |
| Test Kapsamı Boşlukları | 0 | 3 | 2 | 5 |
| CI/CD Eksiklikleri | 1 | 1 | 1 | 3 |
| **TOPLAM** | **6** | **19** | **17** | **42** |

---

## 1. SAHTE TEST ASSERTION'LARI

### F-01 | `assert True` — Her Zaman Geçen Assertion
- **Öncelik:** 🔴 P0
- **Dosya:** `tests/test_async_providers.py`, satır 66
- **Kod:**
  ```python
  assert True, "Client Timeout: manual verification required"
  ```
- **Sorun:** Test hiçbir şeyi doğrulamıyor. Timeout davranışı test edilmemiş oluyor. Bu bir "sahte geçiş" — CI'da yeşil görünür ama hiçbir garantisi yok.
- **Düzeltme:** Gerçek timeout davranışı test edilmeli:
  ```python
  with pytest.raises(asyncio.TimeoutError):
      await client.get_text("http://httpbin.org/delay/5", timeout=0.01)
  ```

### F-02 | `except Exception: pass` — Silent Failure Pattern (14 test dosyası)
- **Öncelik:** 🔴 P0 (kümülatif)
- **Etkilenen Dosyalar:**
  - `tests/test_concurrency.py`: satır 160, 203, 247
  - `tests/test_db_lock.py`: satır 217, 261
  - `tests/test_financial_integrity.py`: satır 34
  - `tests/test_lock_resilience.py`: satır 228, 279
  - `tests/test_monitoring.py`: satır 37
  - `tests/test_multi_instance.py`: satır 24
  - `tests/test_portfolio_restart.py`: satır 27
  - `tests/test_portfolio_service_v2.py`: satır 21
  - `tests/test_production_validation.py`: satır 464
  - `tests/test_realistic_integration.py`: satır 744
  - `tests/integration_test.py`: satır 167
- **Sorun:** `except Exception: pass` blokları hataları yutuyor. Test "geçiyor" görünüyor ama aslında beklenen kod hiç çalışmamış olabilir. Bu, **sahte geçişlerin en yaygın kaynağıdır**.
- **Düzeltme:** Her `except` bloğunda ya `pytest.fail()` çağrılmalı ya da exception assertion ile beklenmeli:
  ```python
  with pytest.raises(SomeError):
      risky_operation()
  ```

### F-03 | `except Exception: pass` + Sonrası Assertion Yok
- **Öncelik:** 🟡 P1
- **Etkilenen Dosyalar:** `tests/test_concurrency.py` (4 yer), `tests/test_db_lock.py` (2 yer)
- **Sorun:** Exception yutulduktan sonra test hiçbir assertion yapmadan sona eriyor. "Geçti" ama hiçbir şey kanıtlamadı.
- **Düzeltme:** Exception'ı yakalayıp assertion ile doğrula:
  ```python
  try:
      result = risky_op()
  except ExpectedError:
      result = None  # expected
  assert result is not None or expected_condition
  ```

### F-04 | `pytest.ini` vs `pyproject.toml` — Çelişki: `asyncio_mode`
- **Öncelik:** 🟡 P1
- **Dosyalar:** `pytest.ini` satır 8, `pyproject.toml` satır 34
- **Sorun:**
  - `pytest.ini`: `asyncio_mode = auto`
  - `pyproject.toml`: `asyncio_mode = "strict"`
  
  Bu iki dosya çelişiyor. pytest hangisini kullanacağına dosya önceliğine göre karar verir (pytest.ini > pyproject.toml). Bu, **farklı ortamlarda farklı test davranışlarına** neden olabilir.
- **Düzeltme:** Tek bir kaynak belirle. `auto` modu `async def test_*` fonksiyonlarını otomatik async olarak çalıştırır; `strict` modu `@pytest.mark.asyncio` gerektirir. Tutarlılık için birini seçin.

### F-05 | Skip Edilen Test Dosyası — Eski API Uyumsuzluğu
- **Öncelik:** 🟡 P1
- **Dosya:** `tests/test_faz3_ranking.py`, satır 18
- **Kod:**
  ```python
  pytestmark = pytest.mark.skip(
      reason="Eski RankingModel API'sini test ediyor..."
  )
  ```
- **Sorun:** Dosya tamamen skip ediliyor. 5 test fonksiyonu hiç çalışmıyor. `tests/test_suite.py::TestRankingModel` ile eşdeğer testlerin olduğu belirtilmiş ama bu doğrulanmamış.
- **Düzeltme:** Ya eski test dosyasını silin ya da güncel API'ye göre yeniden yazın. Skip kalıcı çözüm değildir.

### F-06 | E2E Test Framework — pytest Dışı
- **Öncelik:** 🟢 P2
- **Dosya:** `tests/e2e_full_test.py`
- **Sorun:** Kendi `E2ETest` sınıfını kullanıyor, pytest fixture'ları ile uyumsuz. `pytest.ini`'de `addopts = --ignore=tests/e2e_full_test.py` ile hariç tutulmuş ama bu test hiçbir CI'da çalışmaz.
- **Düzeltme:** pytest framework'üne geçirin veya CI'da ayrı bir step olarak çalıştırın.

---

## 2. ESKİ API SÖZLEŞMELERİNİ TEST EDEN GÜNCEL OLMAYAN TESTLER

### F-07 | `test_faz3_ranking.py` — Tamamen Eski API
- **Öncelik:** 🟡 P1
- **Dosya:** `tests/test_faz3_ranking.py`
- **Sorun:** `RuleBasedRanker`, `LightGBMRanker`, `FeatureImportanceTracker`, `AdjustedMSELoss` sınıfları artık mevcut değil. Kod `services/ml/ranking_model.py`'de refactor edilmiş ama testler güncellenmemiş.
- **Düzeltme:** Dosyayı silin ve `tests/test_suite.py::TestRankingModel` kapsamını artırın.

### F-08 | `run_all_imports.py` — Olmayan Modülü Referans Ediyor
- **Öncelik:** 🟡 P1
- **Dosya:** `run_all_imports.py`, satır 63
- **Sorun:** `"services.scheduler.main"` modülü referans ediliyor ama `services/scheduler/main.py` dosyası **mevcut değil**. `__init__.py`'de de böyle bir modül yok.
- **Düzeltme:** `"services.scheduler.main"` yerine `"services.scheduler.unified_scheduler"` kullanın.

### F-09 | Root-Level Test Dosyaları — pytest Koleksiyonu Dışında
- **Öncelik:** 🟢 P2
- **Dosyalar:** `test_core_comprehensive.py`, `test_core_regressions.py`, `test_phase5_end_to_end.py`, `test_providers_live.py`
- **Sorun:** Bu dosyalar `tests/` dizini dışında, pytest `testpaths` ayarına göre toplanmazlar. `test_core_comprehensive.py` tamamen boş (0 byte). Diğerleri `print` ile sonuç yazıyor, pytest assertion kullanmıyor.
- **Düzeltme:** `tests/` dizinine taşıyın ve pytest assertion'larına çevirin veya `test_core_comprehensive.py`'yi silin.

---

## 3. HARD-CODED SECRET'LAR

### F-10 | ClickHouse Healthcheck'te Hard-coded Password
- **Öncelik:** 🔴 P0
- **Dosya:** `docker-compose.yml`, satır 57
- **Kod:**
  ```yaml
  test: ["CMD", "clickhouse-client", "--user", "alpha", "--password", "alpha", "--query", "SELECT 1"]
  ```
- **Sorun:** ClickHouse healthcheck'te kullanıcı adı ve şifre hard-coded olarak `"alpha"` / `"alpha"` yazılmış. Environment variable (`${CLICKHOUSE_USER}`, `${CLICKHOUSE_PASSWORD}`) kullanılmamış. Bu, production'da credential leak riski taşır.
- **Düzeltme:**
  ```yaml
  test: ["CMD", "clickhouse-client", "--user", "${CLICKHOUSE_USER}", "--password", "${CLICKHOUSE_PASSWORD}", "--query", "SELECT 1"]
  ```
  Not: Docker Compose healthcheck'te env değişkenleri doğrudan kullanılamaz. Alternatif: bir healthcheck script dosyası oluşturun veya `CLICKHOUSE_USER`/`CLICKHOUSE_PASSWORD`'ı container environment'ından okuyun.

### F-11 | Grafana Admin Password — Environment Variable Ama Boş Default
- **Öncelik:** 🟡 P1
- **Dosya:** `docker-compose.yml`, satır 213; `.env.example`, satır 76
- **Sorun:** `GRAFANA_PASSWORD=${GRAFANA_PASSWORD}` kullanılmış ama `.env.example`'da default boş. Production'da boş şifre ile Grafana açılabilir. `config.py`'de `_MIN_SECRET_LENGTH = 16` tanımı var ama Grafana için uygulanmıyor.
- **Düzeltme:** `.env.example`'da `GRAFANA_PASSWORD=change-this-min-16-chars` gibi bir placeholder ekleyin ve startup validation'da kontrol edin.

---

## 4. ÇAKIŞAN ENTRY POINT'LER

### F-12 | 4 Farklı Entry Point — Hangisi Canonical?
- **Öncelik:** 🔴 P0
- **Dosyalar:**
  1. `main.py` — 500+ satır, `--mode daily|backtest|paper|learning|health|full|live`
  2. `start.py` — 33 satır, `main.py`'ye delegate ediyor
  3. `run_system.py` — 49 satır, `main.py`'ye delegate ediyor
  4. `apps/api/main.py` → `services/api/app.py` (canonical production API)
  5. `services/api/main.py` → DEPRECATED, `services/api/app.py`'ye redirect
  6. `services/api/server.py` → DEV/LEGACY (SQLite tabanlı)
- **Sorun:** 6 farklı "entry point" var. `start.py` ve `run_system.py` neredeyse aynı işi yapıyor (ikisi de `main.py`'ye delegate). `services/api/main.py` deprecated ama hala import edilebilir. `services/api/server.py` SQLite tabanlı dev sunucu ama production'dan ayırt etmek zor. Dockerfile `services/api/app.py`'yi kullanıyor ama `docker-compose.yml`'de `api` service'inin `command`'ı yok (Dockerfile CMD'si çalışıyor).
- **Düzeltme:**
  - `main.py` → CLI entry point olarak tutun (daily/backtest/paper/learning/health/full/live)
  - `start.py` → Silin (gereksiz wrapper)
  - `run_system.py` → Silin (gereksiz wrapper)
  - `services/api/main.py` → Silin (deprecated)
  - `services/api/server.py` → `services/api/dev_server.py` olarak yeniden adlandırın

### F-13 | `alpha` Shell Script — `start.py`'ye Bağlı
- **Öncelik:** 🟡 P1
- **Dosya:** `alpha`, satır 5
- **Sorun:** `start.py`'yi çağırıyor ama `start.py` gereksiz bir wrapper. `main.py`'ye doğrudan bağlanmalı.
- **Düzeltme:** `alpha` script'inde `python3 start.py` yerine `python3 main.py --mode daily` kullanın.

### F-14 | Docker Compose API Service — Command Yok
- **Öncelik:** 🟡 P1
- **Dosya:** `docker-compose.yml`, `api` service
- **Sorun:** `api` service'inin `command`'ı yok. Dockerfile'daki `CMD` çalışıyor (`uvicorn services.api.app:app`). Ama `ingestion`, `feature-engine` vb. servislerin `command`'ları var. Bu tutarsız.
- **Düzeltme:** `api` service'ine explicit `command` ekleyin:
  ```yaml
  command: python -m uvicorn services.api.app:app --host 0.0.0.0 --port 8000
  ```

---

## 5. EKSİK/FAZLA BAĞIMLILIKLAR

### F-15 | `requirements.txt` — `aiosqlite` Listed Ama Kullanılmıyor
- **Öncelik:** 🟡 P1
- **Dosya:** `requirements.txt`, satır 23
- **Sorun:** `aiosqlite>=0.22.0` listelenmiş ama hiçbir `services/` dosyasında `import aiosqlite` yok. Sadece `services/api/server.py` (dev/legacy) SQLite kullanıyor olabilir ama o da `database_dev.py` üzerinden.
- **Düzeltme:** Gerekliyse tutun, değilse kaldırın.

### F-16 | `requirements.txt` — `passlib` Listed Ama Kullanılmıyor
- **Öncelik:** 🟢 P2
- **Dosya:** `requirements.txt`, satır 52
- **Sorun:** `passlib[bcrypt]>=1.7.4` listelenmiş ama hiçbir dosyada `import passlib` yok.
- **Düzeltme:** Kullanılmıyorsa kaldırın.

### F-17 | `requirements.txt` — `nest_asyncio` Listed Ama Kullanılmıyor
- **Öncelik:** 🟢 P2
- **Dosya:** `requirements.txt`, satır 67
- **Sorun:** `nest_asyncio>=1.6.0` listelenmiş ama hiçbir dosyada `import nest_asyncio` yok.
- **Düzeltme:** Kullanılmıyorsa kaldırın.

### F-18 | `requirements.txt` — `alembic` Listed Ama Custom Migration Runner Var
- **Öncelik:** 🟢 P2
- **Dosya:** `requirements.txt`, satır 55
- **Sorun:** `alembic>=1.19.0` listelenmiş ama hiçbir dosyada `import alembic` yok. Proje kendi migration runner'ını kullanıyor (`services/core/migrations/runner.py`).
- **Düzeltme:** Alembic kullanılmıyorsa kaldırın. Yoksa runner'ı Alembic'e geçirin.

### F-19 | `requirements.txt` — `uv.lock` Conflict Risk
- **Öncelik:** 🟡 P1
- **Dosya:** `uv.lock`
- **Sorun:** Hem `requirements.txt` hem `uv.lock` var. `uv.lock` farklı dependency resolver kullanıyor. Bu,版本 çakışmalarına neden olabilir.
- **Düzeltme:** Tek bir dependency yönetim aracı seçin (pip + requirements.txt VEYA uv + pyproject.toml).

---

## 6. DEAD CODE / KULLANILMAYAN SCRIPT'LER

### F-20 | `data/` Dizininde Script'ler — Yanlış Yerde
- **Öncelik:** 🟡 P1
- **Dosyalar:**
  - `data/verify_engines.py` — Motor doğrulama script'i
  - `data/run_large_scale_training_simulation.py` — Eğitim simülasyonu
  - `data/seed_learning_history.py` — Learning history seed
- **Sorun:** Bu script'ler `data/` dizininde ama veri değil, çalışan Python kodu. `data/` dizini `.gitignore`'da `data/*.json` ile filtrelenmiş ama `.py` dosyaları git'e dahil.
- **Düzeltme:** `scripts/` dizinine taşıyın.

### F-21 | `test_core_comprehensive.py` — Boş Dosya
- **Öncelik:** 🟢 P2
- **Dosya:** `test_core_comprehensive.py` (root)
- **Sorun:** Dosya tamamen boş (0 byte test fonksiyonu). Gereksiz dosya.
- **Düzeltme:** Silin.

### F-22 | `full_system_audit.py` — Root'da Teknik Debt
- **Öncelik:** 🟢 P2
- **Dosya:** `full_system_audit.py` (root)
- **Sorun:** 700+ satırlık audit script'i root dizininde. pytest ile çalıştırılmıyor, bağımsız script.
- **Düzeltme:** `scripts/` dizinine taşıyın.

### F-23 | `verify_singleton_safety.py` — Root'da Teknik Debt
- **Öncelik:** 🟢 P2
- **Dosya:** `verify_singleton_safety.py` (root)
- **Sorun:** Singleton analiz script'i root dizininde.
- **Düzeltme:** `scripts/` dizinine taşıyın.

### F-24 | `services/core/data_quality_v2.py.deprecated` — Dead Code
- **Öncelik:** 🟢 P2
- **Dosya:** `services/core/data_quality_v2.py.deprecated`
- **Sorun:** Deprecated dosya hala repository'de. Git history'de durabilir.
- **Düzeltme:** Silin.

---

## 7. KONFİGÜRASYON TUTARSIZLIKLARI

### F-25 | `pytest.ini` vs `pyproject.toml` — Çelişkili pytest Ayarları
- **Öncelik:** 🔴 P0
- **Dosyalar:** `pytest.ini`, `pyproject.toml`
- **Sorun:**
  | Ayar | `pytest.ini` | `pyproject.toml` |
  |------|-------------|-----------------|
  | `asyncio_mode` | `auto` | `strict` |
  | `addopts` | `--ignore=tests/e2e_full_test.py` | `--tb=short -q` |
  | `testpaths` | (yok) | `["tests"]` |

  pytest önceliği: `pytest.ini` > `pyproject.toml` > `conftest.py`. İki dosya arasındaki çelişki, farklı geliştirici makinelerinde farklı sonuçlara neden olabilir.
- **Düzeltme:** `pyproject.toml`'deki `[tool.pytest.ini_options]`'ı kaldırın VEYA `pytest.ini`'yi silin ve her şeyi `pyproject.toml`'ye taşıyın.

### F-26 | `config/` Dizininde 4 Farklı Config — Hangisi Kullanılıyor?
- **Öncelik:** 🟡 P1
- **Dosyalar:** `config/alpha_config.json`, `config/alpha_production.json`, `config/alpha_test.json`, `config/alpha_development.json`
- **Sorun:** 4 config dosyası var ama `config_loader.py` sadece `alpha_config.json`'ı yüklüyor. Diğer üçü (`alpha_production.json`, `alpha_test.json`, `alpha_development.json`) hiçbir yerde referans edilmiyor.
- **Düzeltme:** Ya environment-based loading ekleyin ya da gereksiz config dosyalarını silin.

### F-27 | Config Dosyaları Arasında Değer Farklılıkları — Uyum Yok
- **Öncelik:** 🟡 P1
- **Örnek:**
  | Key | `alpha_config.json` | `alpha_production.json` | `alpha_test.json` |
  |-----|--------------------|-----------------------|------------------|
  | `initial_capital` | 100,000 | 1,000,000 | 50,000 |
  | `max_drawdown_pct` | 15.0 | 8.0 | 10.0 |
  | `daily_loss_limit_pct` | 5.0 | 2.0 | 3.0 |
  | `port` | 8000 | 80 | 8001 |

  Production config'de `port: 80` var ama `docker-compose.yml`'de API `8000` portunda çalışıyor.
- **Düzeltme:** Config dosyalarını environment-aware hale getirin ve tutarlılığı sağlayın.

### F-28 | `holidays.json` — Sadece 2026 Yılı
- **Öncelik:** 🟢 P2
- **Dosya:** `config/holidays.json`
- **Sorun:** Sadece 2026 tatillerini içeriyor. Backtest 2020-2025 yıllarını kapsıyorsa tatiller eksik kalır.
- **Düzeltme:** Dinamik tatil kaynağı ekleyin veya birden fazla yılı kapsayın.

---

## 8. DOCKER/ALTYAPI SORUNLARI

### F-29 | ClickHouse Healthcheck — Hard-coded Credential
- **Öncelik:** 🔴 P0
- **Dosya:** `docker-compose.yml`, satır 57
- **Sorun:** `--user alpha --password alpha` hard-coded. (Bkz. F-10)

### F-30 | Prometheus — Exporter Olmayan Servisleri Scrape Ediyor
- **Öncelik:** 🟡 P1
- **Dosya:** `infrastructure/prometheus.yml`, satır 15-24
- **Sorun:** `ingestion`, `feature-engine`, `market-state` vb. servisler Prometheus'un scrape edeceği `/metrics` endpoint'ini sunmuyor olabilir. Bu servisler FastAPI değil, `python -m services.xxx.main` ile çalışıyor. Prometheus exporteri eklenmeden scrape edilemez.
- **Düzeltme:** Her servise `/metrics` endpoint'i ekleyin VEYA sadece API servisini scrape edin.

### F-31 | Docker Compose — `.env` Dosyası Zorunlu Ama Oluşturulmamış
- **Öncelik:** 🟡 P1
- **Dosya:** `docker-compose.yml`, `env_file: .env`
- **Sorun:** Tüm servisler `.env` dosyasını okuyor ama `.env.example`'dan `.env` oluşturmak manuel. Docker compose başladığında `.env` yoksa hata verir.
- **Düzeltme:** `docker-compose.yml`'de `env_file` yerine `environment` section'ı kullanın VEYA startup script'inde `.env` kontrolü ekleyin.

### F-32 | Dockerfile.api — `COPY . .` Her Şeyi Kopyalıyor
- **Öncelik:** 🟢 P2
- **Dosya:** `infrastructure/Dockerfile.api`, satır 11
- **Sorun:** `COPY . .` tüm repository'yi kopyalar (test dosyaları, documentation, `.git`, vs.). `.dockerignore` var ama `tests/` ve `docs/` hariç tutulmuş, `documentation/`, `memory/` hariç tutulmamış.
- **Düzeltme:** `.dockerignore`'ı genişletin:
  ```
  documentation/
  memory/
  reports/
  *.md
  test_*.py
  ```

### F-33 | ClickHouse Image — Versiyon Pin Uyumsuzluğu
- **Öncelik:** 🟢 P2
- **Dosya:** `docker-compose.yml`, satır 36
- **Sorun:** `clickhouse/clickhouse-server:24.3-alpine` kullanılıyor. `clickhouse-connect>=0.8.0` client ile uyumlu olmalı ama versiyon uyumluluğu doğrulanmamış.
- **Düzeltme:** ClickHouse server ve client versiyon uyumluluğunu test edin.

---

## 9. TEST KAPSAMI BOŞLUKLARI

### F-34 | Services Dizininde 300+ Modül, Sadece ~97 Test Dosyası
- **Öncelik:** 🟡 P1
- **Sorun:** `services/` altında 300+ Python modülü var ama `tests/`'de sadece ~97 test dosyası. Birçok kritik modül test edilmemiş:
  - `services/core/compliance.py` — SPK uyum testi yok
  - `services/core/manipulation_detector.py` — Test yok
  - `services/core/insider_detector.py` — Test yok
  - `services/core/tax.py` — Vergi hesaplama testi yok
  - `services/core/distributed_tracing.py` — Test yok
  - `services/core/otel.py` — Test yok
  - `services/core/config_hot_reload.py` — Test yok
  - `services/viop/*.py` (6 modül) — `test_viop_modules.py` var ama kapsamı dar
- **Düzeltme:** Kritik modüller için test yazın. Özellikle compliance, manipulation detection, tax hesaplama.

### F-35 | Database Migration Testleri — Eksik
- **Öncelik:** 🟡 P1
- **Dosya:** `tests/test_migration.py` var ama sadece runner'ı test ediyor
- **Sorun:** 7 migration dosyası (`v001`-`v007`) var ama migration'lar arası uyumluluk, rollback, ve veri kaybı testleri eksik.
- **Düzeltme:** Her migration için up/down testleri yazın.

### F-36 | API Endpoint Testleri — Sadece Temel Sağlık Kontrolü
- **Öncelik:** 🟡 P1
- **Dosya:** `tests/test_api.py`
- **Sorun:** 92 REST endpoint var ama test dosyası sadece temel endpoint'leri test ediyor. Hata durumları, rate limiting, authentication testleri eksik.
- **Düzeltme:** Her v1 endpoint'i için en az 3 test yazın (happy path, error, auth).

### F-37 | Async Test'ler — `asyncio_mode` Belirsizliği
- **Öncelik:** 🟢 P2
- **Sorun:** `pytest.ini` `auto` modunda, `pyproject.toml` `strict` modunda. `auto` modunda `async def test_*` otomatik çalışır, `strict` modunda `@pytest.mark.asyncio` gerekir. Bu belirsizlik, bazı async test'lerin sessizce atlanmasına neden olabilir.
- **Düzeltme:** Tek mod seçin ve tüm async test'leri buna göre güncelleyin.

### F-38 | Root-Level Test Dosyaları — CI Dışında
- **Öncelik:** 🟢 P2
- **Dosyalar:** `test_core_comprehensive.py`, `test_core_regressions.py`, `test_phase5_end_to_end.py`, `test_providers_live.py`
- **Sorun:** `tests/` dizini dışında oldukları için pytest `testpaths` ayarına göre toplanmazlar. CI'da çalışmazlar.
- **Düzeltme:** `tests/` dizinine taşıyın.

---

## 10. CI/CD EKSİKLİKLERİ

### F-39 | CI/CD Pipeline — Hiçbir Yapılandırma Yok
- **Öncelik:** 🔴 P0
- **Sorun:** `.github/`, `.gitlab-ci.yml`, `Makefile`, `Jenkinsfile` — hiçbir CI/CD yapılandırması yok. Testler sadece manuel olarak çalıştırılabilir.
- **Düzeltme:** Minimum CI/CD:
  ```yaml
  # .github/workflows/test.yml
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
        - run: pytest tests/ --tb=short -q
  ```

### F-40 | Linter/Formatter — Config Var Ama CI'da Çalışmıyor
- **Öncelik:** 🟡 P1
- **Dosya:** `pyproject.toml` (ruff, mypy config)
- **Sorun:** `ruff` ve `mypy` config'i var ama CI pipeline'ı yok. Manuel çalıştırılmıyor olabilir.
- **Düzeltme:** CI'da `ruff check .` ve `mypy services/` ekleyin.

### F-41 | Docker Build — CI'da Test Edilmiyor
- **Öncelik:** 🟢 P2
- **Sorun:** `Dockerfile.api` ve `apps/web/Dockerfile` var ama CI'da build edilip edilmediği bilinmiyor.
- **Düzeltme:** CI'da `docker build` step'i ekleyin.

---

## 📋 Öncelikli Aksiyon Planı

### 🔴 P0 — Hemen Düzelt (Güvenlik & Güvenilirlik)
1. **F-10/F-29:** ClickHouse healthcheck'teki hard-coded credential'ı kaldırın
2. **F-01:** `assert True` sahte assertion'ını gerçek test ile değiştirin
3. **F-02:** 14 test dosyasındaki `except Exception: pass` bloklarını düzeltin
4. **F-12:** Entry point'leri temizleyin (start.py, run_system.py silin)
5. **F-25:** pytest konfigürasyon çelişkisini çözün
6. **F-39:** CI/CD pipeline oluşturun

### 🟡 P1 — Kısa Vadeli Düzeltme
7. **F-04/F-37:** `asyncio_mode` tutarlılığı sağlayın
8. **F-05/F-07:** Skip edilen/eski test dosyalarını temizleyin
9. **F-08:** `run_all_imports.py`'deki olmayan modül referansını düzeltin
10. **F-11:** Grafana şifre varsayılanını güvenli hale getirin
11. **F-15/F-19:** Gereksiz bağımlılıkları kaldırın
12. **F-26/F-27:** Config dosyalarını temizleyin ve tutarlılığı sağlayın
13. **F-30:** Prometheus scrape hedeflerini düzeltin
14. **F-34-F-36:** Kritik modüller için test yazın

### 🟢 P2 — Orta Vadeli İyileştirme
15. **F-06/F-09/F-21-F-24:** Dead code ve yanlış yerdeki dosyaları temizleyin
16. **F-16/F-17/F-18:** Kullanılmayan bağımlılıkları kaldırın
17. **F-20:** `data/` dizinindeki script'leri `scripts/`'e taşıyın
18. **F-28:** Tatil config'ini genişletin
19. **F-32/F-33:** Docker optimizasyonları yapın
20. **F-40/F-41:** Linter ve Docker build CI'ya ekleyin

---

## 📈 İstatistikler

| Metrik | Değer |
|--------|-------|
| Toplam test dosyası | 97 |
| Toplam test fonksiyonu | ~2,247 |
| Toplam test satırı | ~52,699 |
| Sahte assertion (`assert True`) | 1 |
| Silent failure (`except: pass`) | 22 yer, 14 dosya |
| Skip edilen test dosyası | 1 (tamamen) |
| Hard-coded credential | 1 (ClickHouse) |
| Entry point sayısı | 6 |
| Config dosyası sayısı | 4 (3'ü kullanılmıyor) |
| Dead code dosyası | 5+ |
| CI/CD yapılandırması | 0 |
| Eksik test kapsamı | ~200+ modül |

---

*Bu rapor otomatik analiz ile oluşturulmuştur. Manuel doğrulama önerilir.*
