# ALPHA BIST — Derin Sistem Bütünlük Denetim Raporu (v4.0 — 36 Boyut)

> **Tarih:** 2026-08-29 14:50  
> **Motor:** Deep System Integrity Auditor v4.0 (36 Boyut, 0 Token, 6.03 saniye)  
> **Kapsam:** Kod Kalitesi + Motor Mantığı + Sinyal Zinciri + Altyapı + ML + Mesajlaşma  
> **Taranan:** 850 dosya, 247,906 satır  
> **Sistem Sağlık Puanı:** **30 / 100**

---

## Genel Özet

| Seviye | Adet | Etki |
|---|---|---|
| **KRİTİK** | **104** | Sistem çökebilir, veri kaybolur, güvenlik açığı |
| **YÜKSEK** | **987** | Motor zinciri kırık, hata maskeleme, altyapı hatası |
| **ORTA** | **1950** | Kod kalitesi, standart ihlali, şema uyumsuzluğu |
| **DÜŞÜK** | **2473** | Dokümantasyon, tip eksikliği, biçim |
| **TOPLAM** | **5514** | |

---

## 36 Boyut Bazlı Sonuç Tablosu

| # | Boyut | Alan | Bulgu | Durum |
|---|---|---|---|---|
| **B01** | Sözdizimi & Dosya Bütünlüğü | Syntax hataları | 1 | 🔴 KRİTİK |
| **B02** | Boş/Yarım Bırakılan Kod | stub, `...`, pass, NotImplementedError | ÇOK | 🔴 KRİTİK |
| **B03** | Fail-Closed & Hata Yönetimi | bare except, pass in except | ÇOK | 🟠 YÜKSEK |
| **B04** | Async Bütünlüğü | await eksik, sync+async karışımı | VAR | 🟠 YÜKSEK |
| **B05** | Teknoloji Yığını Uyumu | kütüphane versiyon uyumu | VAR | 🟡 ORTA |
| **B06** | Güvenlik & Sır Tespiti | hardcoded secret, SQL injection riski | VAR | 🔴 KRİTİK |
| **B07** | Kod Kalitesi & Standartlar | magic number, karmaşık fonksiyon | ÇOK | 🟡 ORTA |
| **B08** | Tip Güvenliği | Any, eksik annotation | ÇOK | 🟡 ORTA |
| **B09** | PnL & Quant Doğruluğu | float karşılaştırma, sıfıra bölme riski | VAR | 🟠 YÜKSEK |
| **B10** | Mimari & Katman Uyumu | döngüsel import, katman ihlali | VAR | 🟠 YÜKSEK |
| **B11** | Servis Init Bütünlüğü | `__init__.py` eksiklikleri | VAR | 🟡 ORTA |
| **B12** | Docker & .env Uyumu | env var eşleşmesi | VAR | 🟡 ORTA |
| **B13** | Loglama Standartı | print(), raw logging | ÇOK | 🟡 ORTA |
| **B14** | Kaynak Sızıntısı | kapatılmayan bağlantı/dosya | VAR | 🟠 YÜKSEK |
| **B15** | Test Kapsamı | test dosyası eksik servisler | ÇOK | 🟠 YÜKSEK |
| **B16** | Dokümantasyon Bütünlüğü | docstring eksik | ÇOK | 🟡 DÜŞÜK |
| **B17** | Orchestrator Servis Kaydı | kayıtlı olmayan servisler | VAR | 🟠 YÜKSEK |
| **B18** | Servis Arayüz Uyumu | eksik metodlar | 4 | 🔴 KRİTİK |
| **B19** | Sinyal Fuzyon Ağırlık | toplam ≠ 1.0 | VAR | 🟡 ORTA |
| **B20** | DecisionInput Kapsamı | `news_sentiment` set edilmiyor | 1 | 🟠 YÜKSEK |
| **B21** | RiskGate Parametre Uyumu | eksik `price`, `portfolio_value` | 3 | 🔴 KRİTİK |
| **B22** | ML Pipeline Zinciri | trainer→inference zinciri | VAR | 🟠 YÜKSEK |
| **B23** | Feature Contract | 3 kayıtlı feature hesaplanmıyor | 1 | 🔴 KRİTİK |
| **B24** | Event Schema | event class/field uyumsuzluğu | VAR | 🟡 ORTA |
| **B25** | Portfolio Manager | `execute_decision` zinciri kırık | 2 | 🔴 KRİTİK |
| **B26** | Ölü Kod | tanımlı ama referanssız | ÇOK | 🟡 DÜŞÜK |
| **B27** | Çoklu Tanım Çakışması | aynı isim birden fazla modülde | VAR | 🟡 ORTA |
| **B28** | Şüpheli Dosya | `.pem`/`.key` repoda | 0 | ✅ TEMİZ |
| **B29** | Docker Compose Derin | healthcheck, volume, depends_on | 0 | ✅ TEMİZ |
| **B30** | pyproject Bağımlılık | undeclared imports | **328** | 🟠 YÜKSEK |
| **B31** | ML Model Dosya Varlığı | `models/` dizini yok | **2** | 🔴 KRİTİK |
| **B32** | NATS/Redis Şeması | prefix'siz 228 dosyada Redis key | **1** | 🟡 ORTA |
| **B33** | Çok Adımlı Döngü | A→B→C→A import döngüsü | 0 | ✅ TEMİZ |
| **B34** | Config↔Docker Cross-Ref | .env'de eksik 16 docker env var | **16** | 🟠 YÜKSEK |
| **B35** | DB Şema ↔ SQL | schema'da olmayan tablolar | **104** | 🟡 ORTA |
| **B36** | Async Güvenlik | fire-and-forget task (7 yer) | **7** | 🟠 YÜKSEK |

---

## Kritik Motor Zinciri Kırıkları (Derhal Düzeltilmeli)

### 🔴 B18 — Servis Arayüz Uyumsuzluğu (4 KRITIK)
| Servis | Eksik Metod | Etki |
|---|---|---|
| `decision_engine` | `make_decision` | Karar üretilemiyor |
| `portfolio_manager` | `execute_decision` | Trade çalıştırılamıyor |
| `portfolio_manager` | `get_portfolio_summary` | Dashboard boş |
| `position_sizing` | `calculate_position_size` | Pozisyon 0 kalıyor |

### 🔴 B21 — RiskGate Parametre Eksikliği (3 yer)
```
risk_gate.check_order() çağrısında 'price' ve 'portfolio_value' eksik
→ risk kontrolü yapılmadan order geçiyor olabilir
```

### 🔴 B25 — Portfolio Zinciri Kırık
```
Orchestrator: risk_gate.check_order() ÇAĞIRIYOR
Orchestrator: portfolio_manager.execute_decision() ÇAĞIRMIYOR  ← KRİTİK GAP
```

### 🔴 B02 — Tamamlanmamış Implementasyonlar
| Dosya | Stub Sayısı | Kritik Metodlar |
|---|---|---|
| `services/backtest/walk_forward_engine.py` | 5 | `fit`, `predict`, `get_feature_importance` |
| `services/core/broker.py` | 5 | `submit_order`, `cancel_order`, `get_positions` |
| `services/core/alerting.py` | 5 | `send`, `close` |
| `services/core/state_store.py` | 2 | `commit`, `close` |

---

## Yeni Bulgular (B29-B36)

### 🟠 B30 — Bildirilmemiş 328 Bağımlılık
> pyproject.toml'da tanımlanmamış paketler import ediliyor.

**En kritik eksikler:**
- `shap` (7 dosyada — ML açıklanabilirliği için)
- `agent_system` (8 dosyada — AI agent altyapısı)  
- `agent_pipeline`, `communication_bus`, `synthesis_engine` (iç modüller mi? dış paket mi? belirsiz)
- `conflict_detector`, `risk_assessor`, `self_evaluator`, `parallel_runner`

> [!WARNING]
> `agent_system`, `agent_pipeline` gibi 8+ dosyada kullanılan modüller bir iç paketse `pyproject.toml`'da `[tool.setuptools.packages]` altında listelenmeli. Eğer dış paketse mutlaka `dependencies`'e eklenmeli.

### 🔴 B31 — ML Model Dizini Yok (KRİTİK)
```
models/ dizini YOK!
→ Tüm inference servisleri model yükleyemiyor
→ MLflow tracking aktif ama tracking server bağlantısı doğrulanmamış
```

### 🟡 B32 — Redis Key Prefix Eksikliği
```
228 dosyada prefix'siz Redis key kullanılıyor
Örn: redis.set("data", ...) yerine redis.set("alpha:ticker:data", ...)
→ Farklı servisler arasında key çakışması riski
```

### 🟠 B34 — Docker Compose ↔ .env Uyumsuzluğu (16 Değişken)
> docker-compose.yml'de `${VAR}` ile referans edilen ama `.env` dosyasında bulunmayan değişkenler:

| Eksik .env Değişkeni | Etki |
|---|---|
| `API_URL` | Servisler birbirini bulamıyor |
| `GRPC_PORT`, `GRPC_HOSTS` | gRPC bağlantısı başlamıyor |
| `MTLS_CA_CERT`, `MTLS_SERVER_CERT`, `MTLS_SERVER_KEY` | mTLS açılmıyor |
| `MTLS_CLIENT_CERT`, `MTLS_CLIENT_KEY` | Client auth çalışmıyor |
| `AUTOHEAL_CONTAINER_LABEL`, `AUTOHEAL_INTERVAL`, `AUTOHEAL_START_PERIOD` | autoheal çalışmıyor |

### 🟡 B35 — Schema'da Olmayan SQL Tabloları (104 bulgu)
> Kod içinde kullanılan ama `database/init/*.sql` migration'larında tanımlanmamış tablolar:

| Tablo | Dosya Sayısı | Önem |
|---|---|---|
| `paper_trade_portfolio` | 4 | Yüksek — paper trading çalışmıyor |
| `backtests` / `backtest_results` | 3 | Yüksek — backtest kaydedilemiyor |
| `decisions` | 2 | Yüksek — karar logu yok |
| `typing`, `datetime` | 45+43 | Düşük — false positive (regex sınırlı) |

### 🟠 B36 — Fire-and-Forget Async Task (7 yer)
```python
# YANLIŞ:
asyncio.create_task(some_critical_task())   ← task referans yok

# DOĞRU:
_task = asyncio.create_task(some_critical_task())
_bg_tasks.add(_task)
_task.add_done_callback(_bg_tasks.discard)
```
> Exception sessizce yutulur, task iptal edildiğinde fark edilmez.

---

## Öncelik Sırası (Düzeltme Yol Haritası)

```
HAFTA 1 — Kritik Motor Zinciri (Sistem Çalışmıyor)
├── B18: decision_engine.make_decision(), portfolio_manager.execute_decision() → IMPLEMENT
├── B21: risk_gate.check_order(price=, portfolio_value=) → parametreleri ekle
├── B25: orchestrator → portfolio_manager.execute_decision() çağrısı ekle
├── B02: broker.submit_order/cancel_order → implement or raise NotImplementedError with logging
└── B31: models/ dizini oluştur veya MLflow model registry bağla

HAFTA 2 — Altyapı Stabilitesi
├── B34: .env dosyasına GRPC_PORT, GRPC_HOSTS, MTLS_* değişkenleri ekle
├── B34: API_URL, AUTOHEAL_* değişkenleri ekle
├── B36: create_task() fire-and-forget → task set pattern ile koru
└── B23: feature engine'de eksik 3 feature'ı hesapla (breadth_advance_ratio, cs_rank_rsi_...)

HAFTA 3 — Veri Bütünlüğü
├── B35: backtests, decisions, paper_trade_portfolio tablolarını migration'a ekle
├── B32: Redis key'lerine "alpha:servis:key" prefix standardı uygula
└── B30: pyproject.toml'a shap ve belirsiz iç modülleri ekle/belgele
```

---

*Deep System Integrity Auditor v4.0 (36 Boyut) — JSON: `audit/full_spectrum_audit_20260829_145022.json`*


---

## Canlı API Test Sonuçları (Runtime Analizi)

### 🔴 Hatalı Uç Noktalar (Çöken & Timeout Veren)
- GET /api/v1/portfolio/position-history → **500** (Yıkıcı Hata / Timeout)
- GET /api/v1/portfolio/equity-snapshots → **500** (Yıkıcı Hata / Timeout)
- GET /api/v1/portfolio/tax → **500** (Yıkıcı Hata / Timeout)
- GET /api/v1/portfolio/tca → **500** (Yıkıcı Hata / Timeout)
- GET /api/v1/risk/portfolio → **ERROR** (Yıkıcı Hata / Timeout)
- GET /api/v1/risk/liquidity → **ERROR** (Yıkıcı Hata / Timeout)
- GET /api/v1/macro/indicators → **ERROR** (Yıkıcı Hata / Timeout)
- GET /api/v1/strategy/position-history → **500** (Yıkıcı Hata / Timeout)
- GET /api/v1/strategy/equity-snapshots → **500** (Yıkıcı Hata / Timeout)
- GET /api/v1/strategy/tax → **500** (Yıkıcı Hata / Timeout)
- GET /api/v1/strategy/tca → **500** (Yıkıcı Hata / Timeout)

### 🟠 Yüksek Gecikmeli Uç Noktalar (> 300 ms)
- GET /api/v1/market/events → **387.0 ms** (Optimizasyon Gerekli)
- GET /api/v1/market/radar → **783.8 ms** (Optimizasyon Gerekli)
- GET /api/v1/portfolio/trades → **396.3 ms** (Optimizasyon Gerekli)
- GET /api/v1/risk/limits → **3465.4 ms** (Optimizasyon Gerekli)
- GET /api/v1/risk/stress-test → **3754.8 ms** (Optimizasyon Gerekli)
- GET /api/v1/scanner/dashboard → **601.3 ms** (Optimizasyon Gerekli)
- GET /api/v1/alternative/news → **1547.9 ms** (Optimizasyon Gerekli)
- GET /api/v1/alternative/macro → **3001.9 ms** (Optimizasyon Gerekli)
- GET /api/v1/event-study/calendar → **1041.9 ms** (Optimizasyon Gerekli)
- GET /api/v1/dashboard → **453.1 ms** (Optimizasyon Gerekli)
