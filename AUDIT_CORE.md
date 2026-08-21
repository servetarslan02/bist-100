# ALPHA BIST — Core Service Deep Audit Report

**Tarih:** 2026-08-22  
**Kapsam:** `services/core/`, `services/ingestion/`, `services/api/`  
**Analiz:** Satır satır statik analiz + mimari inceleme  

---

## Özet

| Öncelik | Sayı | Tanım |
|---------|------|-------|
| **P0** | 4 | Kritik — çalışırken yanlış sonuç üretir veya güvenlik açığı |
| **P1** | 12 | Yapısal — bakım zorluğu, mimari ihlal, veri bütünlüğü riski |
| **P2** | 8 | Olgunluk — kod kalitesi, best practice, performans |

---

## P0 — KRİTİK BULGULAR

### P0-1: TCMB Provider — Hard-coded "Canonical Baseline" Değerler Canlı Veri Gibi Sunuluyor

**Dosya:** `services/ingestion/providers/tcmb_provider.py`  
**Satır:** 83–95  

**Sorun:** API key olmadığında `baseline_values` dict'indeki sabit değerler (ör. `usd_try: 36.5`, `policy_rate: 50.0`) `is_live: False` etiketiyle döndürülüyor. Ancak bu değerler **tüketici servisler tarafından canlı veri olarak kullanılabilir** — `is_live` flag'i kontrol edilmezse decision engine bu eski değerlerle karar üretir.

```python
baseline_values = {
    "policy_rate": 50.0,      # ← Ne zaman güncellendi?
    "usd_try": 36.5,          # ← Bugünün kuru bu mu?
    "bist_100": 9850.0,       # ← Endeks bu seviyede mi?
}
```

**Etki:** Makro rejim tespiti, risk skoru ve karar motoru yanlış veriyle çalışır.  
**Düzeltme:**  
1. Baseline değerleri config dosyasından yükle (hard-code değil)
2. `is_live: False` durumunda tüketici servislerde `WARNING` log + fallback davranışı tanımla
3. Baseline'a `last_updated` timestamp ekle, 30 günden eski ise `CRITICAL` alert

---

### P0-2: Auth Bypass — AUTH_STRICT=false iken Anonim Kullanıcıya ADMIN Rolü

**Dosya:** `services/api/dependencies.py`  
**Satır:** 97–107  

**Sorun:** `AUTH_STRICT` environment variable'ı `false` (varsayılan) olduğunda, token göndermeyen her istemciye **ADMIN rolü ve tam yetki** veriliyor:

```python
return TokenPayload(
    sub="anonymous",
    username="dashboard_viewer",
    role=Role.ADMIN.value if not auth_strict else Role.VIEWER.value,
    permissions=["GET", "POST", "PUT", "DELETE"] if not auth_strict else ["GET"],
)
```

**Etki:** Development ortamında yanlışlıkla production'a deploy edilirse tüm API açık halde kalır.  
**Düzeltme:**  
1. Varsayılan rol `VIEWER` olmalı (ADMIN asla default olmamalı)
2. `AUTH_STRICT` default `true` olmalı
3. Production'da `AUTH_STRICT=false` ise startup'ta FAIL

---

### P0-3: Decision Engine — `macro_impact * 100` Aşırı Skor Bozulması

**Dosya:** `services/core/decision_engine.py`  
**Satır:** 285–286  

**Sorun:** `_macro_score` metodunda `macro_impact` değeri -1.0 ile +1.0 arasında geliyor ve **100 ile çarpılıyor**. Bu, toplam composite skoru (0–100 arası) tek başına çökertebilir:

```python
if inp.macro_impact != 0:
    score += inp.macro_impact * 100  # -100 ile +100 arası!
```

**Senaryo:** `macro_impact = 0.8` → `score += 80` → Diğer tüm sinyaller anlamsız hale gelir.  
**Düzeltme:** `macro_impact` için makul bir aralık tanımla (ör. `* 15` max ±15 puan) veya `_macro_score` sonucunu `min(100, max(0, ...))` ile sınırla (ki zaten yapıyor ama alt skor 100'ü aşabilir → `total`'a eklendiğinde composite 100'ü aşar).

---

### P0-4: BIST Provider — Redundant `or` Operatörleri (Sessiz Null Masking)

**Dosya:** `services/ingestion/providers/bist_provider.py`  
**Satır:** 67–78  

**Sorun:** `fetch_stock_price` metodunda her alan `data.get("X") or data.get("X", 0)` şeklinde — bu **mantıksal olarak anlamsız** ve `None` veya `0` değerlerini gizler:

```python
"price": data.get("lastPrice") or data.get("lastPrice", 0),  # ← Aynı key!
"change_pct": data.get("changePercent") or data.get("changePercent", 0),
```

**Etki:** Gerçek fiyat `0` ise (kıymet bölünmesi sonrası), `or` operatörü `0`'ı falsy kabul eder ve `data.get("lastPrice", 0)` yine `0` döner — bu durumda sorun yok. Ama `None` gelirse `0` ile değiştirilir ve **hatalı fiyat** olarak kaydedilir.  
**Düzeltme:** Redundant `or` kaldırılmalı, sadece `data.get("lastPrice", 0)` kullanılmalı.

---

## P1 — YAPISAL BULGULAR

### P1-1: Learning Router Çift Kayıt (Endpoint Çakışması)

**Dosya:** `services/api/app.py` satır 214–215 + `services/api/v1/__init__.py` satır 34  

**Sorun:** Learning router iki kez kayıtlı:
1. `v1_router` → `/api/v1/learning` (canonical)
2. `app.py` doğrudan → `/api/learning` (legacy)

```python
# app.py:214
app.include_router(learning_router, prefix="/api/learning", tags=["Learning Legacy"])
```

**Etki:** Aynı endpoint iki farklı prefix'te çalışır. Test sonuçları hangisine göre?  
**Düzeltme:** Legacy alias kaldırılmalı, sadece `/api/v1/learning` kalmalı.

---

### P1-2: Event Bus — Sessiz Hata Yutma (3 Katman)

**Dosya:** `services/core/event_bus.py`  
**Satır:** 267–295 (`_check_and_mark_published`), 305–340 (`_publish_to_stream`)

**Sorun:** Her hata yakalama bloğunda `logger.debug("Handled exception", ...)` kullanılıyor — hatalar **debug seviyesinde** loglanıyor ve sessizce yutuluyor:

```python
except Exception as e:
    logger.debug("Handled exception", error=str(e), context="event_bus.py:271")
# ↑ Redis hatası → debug seviyesinde, production'da görünmez
```

**Etki:** Redis bağlantı sorunları, PostgreSQL hataları production'da fark edilmez. Event kaybı olabilir.  
**Düzeltme:**  
1. `logger.warning` seviyesine çıkarılmalı
2. Metrics counter eklenmeli (event_publish_failures)
3. Fail-open davranışı açıkça documented olmalı

---

### P1-3: Event Bus — `_publish_to_stream` Her Seferinde Yeni Redis Bağlantısı Açıyor

**Dosya:** `services/core/event_bus.py`  
**Satır:** 322–330  

**Sorun:** `_publish_to_stream` fonksiyonu her çağrıda yeni bir `aioredis.from_url()` bağlantısı açıyor ve `await r.close()` ile kapatıyor. Module-level `_redis_conn` var ama bu fonksiyonda kullanılmıyor:

```python
async def _publish_to_stream(event: CanonicalEvent):
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, decode_responses=True)  # ← Yeni bağlantı!
        ...
        await r.close()
```

**Etki:** Her event publish'de TCP bağlantı aç/kapa → performans kaybı, connection pool exhaustion.  
**Düzeltme:** `_get_redis()` fonksiyonunu kullan (zaten var, satır 254).

---

### P1-4: Decision Engine — `_calculate_expected_return` Dead Code (Canonical Path)

**Dosya:** `services/core/decision_engine.py`  
**Satır:** 322–332  

**Sorun:** `_calculate_expected_return` sadece `decide()` methodunda çağrılmıyor, `decide_from_canonical()` methodunda hiç çağrılmıyor. CanonicalScore yolunda `expected_return` hep `0.0` kalıyor.

**Etki:** Canonical karar yolunda beklenen getiri hesaplanmaz — risk/ödül analizi eksik kalır.  
**Düzeltme:** `decide_from_canonical` methodunda da `expected_return` hesaplanmalı.

---

### P1-5: Data Quality — `apply_mask` In-Place Mutasyon

**Dosya:** `services/core/data_quality.py`  
**Satır:** 112–122  

**Sorun:** `apply_mask` metodu gelen `raw_data` dict'ini **in-place** modifiye ediyor (fiyatları `None` yapıyor). Çağrıran taraf bu değişikliği beklemiyorsa veri kaybı olur:

```python
def apply_mask(self, raw_data: Dict[str, Any], mask: TradabilityMask) -> Dict[str, Any]:
    if mask.price_mask == 0.0:
        for col in price_cols:
            if col in raw_data:
                raw_data[col] = None  # ← Orijinal dict mutate ediliyor
```

**Düzeltme:** Ya deepcopy ile kopya üzerinde çalış, ya da docstring'te in-place olduğunu belirt.

---

### P1-6: WebSocket Auth — Sessiz Exception Handling

**Dosya:** `services/api/server.py`  
**Satır:** 239–249  

**Sorun:** WebSocket token doğrulamasında iki ayrı `try/except Exception: pass` bloğu var:

```python
try:
    if monitoring_auth.verify_admin_token(token) or ...:
        authenticated = True
except Exception:
    pass  # ← Tüm exception'lar yutuluyor

try:
    from services.api.auth import jwt_handler
    payload = jwt_handler.verify_token(token)
    if payload:
        authenticated = True
except Exception:
    pass  # ← Tüm exception'lar yutuluyor
```

**Etki:** JWT kütüphanesi hatası, import hatası, bağlantı hatası — hepsi sessizce yutulur.  
**Düzeltme:** `except Exception as e: logger.debug("WS auth check failed", error=str(e))`

---

### P1-7: Regime Detector — Hard-Coded Geçiş Matrisi

**Dosya:** `services/core/regime_detector.py`  
**Satır:** 194–202  

**Sorun:** Markov geçiş olasılıkları hard-coded ve asla güncellenmiyor:

```python
transition_matrix = {
    "BULL": {"BULL": 0.65, "BEAR": 0.15, ...},
    "BEAR": {"BULL": 0.10, "BEAR": 0.55, ...},
}
```

**Etki:** Piyasa yapısı değiştiğinde (ör. 2020 COVID, 2022 savaş) geçiş olasılıkları eski kalır.  
**Düzeltme:** Config dosyasından yükle veya tarihsel veriden hesapla.

---

### P1-8: TCMB Series — `bist_100` Yanlış Seri Kodu

**Dosya:** `services/ingestion/providers/tcmb_provider.py`  
**Satır:** 22  

**Sorun:** `bist_100` seri kodu olarak `TP.TUFE1YI1` (TÜFE) atanmış — bu BIST-100 endeksi değil, Tüketici Fiyat Endeksi:

```python
"bist_100": "TP.TUFE1YI1",  # ← Bu TÜFE, BIST-100 değil!
```

**Etki:** BIST-100 endeksi olarak TÜFE verisi sunulur.  
**Düzeltme:** Doğru seri kodu atanmalı veya bu alan kaldırılmalı (BIST-100 TCMB'de yok).

---

### P1-9: Decision Engine — `_determine_direction` HOLD Gap

**Dosya:** `services/core/decision_engine.py`  
**Satır:** 297–321  

**Sorun:** 4 sinyalden 3'ü gerekli (`bullish_signals >= 3`). Sadece 2 bullish + 2 bearish sinyal varsa "HOLD" döner ama bu durumda piyasanın gerçekten nötr mü yoksa sinyallerin çelişkili mi olduğu belirsiz.

**Etki:** Çelişkili sinyallerde HOLD üretmek doğru olabilir ama confidence düşürülmeli.  
**Düzeltme:** HOLD durumunda confidence'ı düşür (şu an input'tan geliyor, HOLD olsa bile yüksek kalabilir).

---

### P1-10: Event Bus — `publish_event` Sync Context'ten Async Çağrı

**Dosya:** `services/core/event_bus.py`  
**Satır:** 221  

**Sorun:** `publish_event` fonksiyonu sync (def) ve içinde `asyncio.create_task(_publish_with_idempotency(event))` çağrısı yapıyor. Eğer event loop yoksa bu hata verir:

```python
def publish_event(event: CanonicalEvent, key: Optional[str] = None):
    ...
    asyncio.create_task(_publish_with_idempotency(event))  # ← Sync context'te
```

**Etki:** Test ortamında veya sync worker'da `RuntimeError: no running event loop`.  
**Düzeltme:** Try/except ile wrap veya `asyncio.get_event_loop().create_task()` kullan.

---

### P1-11: RealTime Engine — MD5 Content Hash

**Dosya:** `services/ingestion/providers/realtime_provider.py`  
**Satır:** 31  

**Sorun:** Duplicate detection için MD5 kullanılıyor. MD5 collision riski düşük ama best practice değil:

```python
self.content_hash = hashlib.md5(raw.encode()).hexdigest()
```

**Düzeltme:** `hashlib.sha256` kullan.

---

### P1-12: Server.py — 5 Kullanılmayan Import

**Dosya:** `services/api/server.py`  
**Satır:** 19–52  

**Sorun:** Aşağıdaki import'lar dosyada hiç kullanılmıyor:
- `uuid` (satır 31)
- `Optional`, `Any` (typing)
- `BISTUniverse` (satır 52)
- `regime_engine` (satır 42)
- `position_sizer` (satır 47)

**Etki:** Gereksiz bellek kullanımı, import zamanı yavaşlaması, kafa karışıklığı.  
**Düzeltme:** Kullanılmayan import'lar kaldırılmalı.

---

## P2 — OLGUNLUK BULGULARI

### P2-1: Auth Handler — Import Inside Method

**Dosya:** `services/api/auth.py`  
**Satır:** 86, 101, 122, 150  

**Sorun:** `json` ve `base64` modülleri method içinde import ediliyor (her token doğrulamada):

```python
def create_token(self, ...):
    import json      # ← Her çağrıda
    import base64    # ← Her çağrıda
```

**Düzeltme:** Dosya seviyesinde import et.

---

### P2-2: Regime Detector — `Tuple` Import'u Kullanılmıyor

**Dosya:** `services/core/regime_detector.py`  
**Satır:** 14  

**Sorun:** `Tuple` import edilmiş ama hiçbir type hint'te kullanılmıyor.  
**Düzeltme:** Import satırından kaldır.

---

### P2-3: Event Bus — `EventType` Import'u Kullanılmıyor

**Dosya:** `services/core/event_bus.py`  
**Satır:** 24  

**Sorun:** `EventType` import edilmiş ama dosyada hiç kullanılmıyor.  
**Düzeltme:** Import satırından kaldır.

---

### P2-4: News Provider — Empty `pass` After Exception

**Dosya:** `services/ingestion/providers/news_provider.py`  
**Satır:** 188  

**Sorun:** `_load_rss_feeds` metodunda exception sonrası `pass` var (gereksiz):

```python
except Exception as e:
    logger.debug("Handled exception", error=str(e), context="news_provider.py:187")
    pass  # ← Gereksiz
```

**Düzeltme:** `pass` kaldır.

---

### P2-5: Decision Engine — Hard-Coded Stop Fallback (%6.5)

**Dosya:** `services/core/decision_engine.py`  
**Satır:** 365  

**Sorun:** ATR olmadığında stop mesafesi hard-coded `%6.5`:

```python
stop_pct = 6.5  # Canonical Hard Stop Fallback
```

**Düzeltme:** Config'den okunmalı (farklı piyasa rejimleri farklı stop gerektirebilir).

---

### P2-6: Universe Provider — Hard-Coded Cache Path

**Dosya:** `services/ingestion/providers/universe_provider.py`  
**Satır:** 274  

**Sorun:** Cache dosya yolu hard-coded:

```python
CACHE_FILE = Path("/mnt/agents/output/bist-100/data/universe_cache.json")
```

**Düzeltme:** Config'den veya environment variable'dan okunmalı.

---

### P2-7: Data Quality Checker — Missing `timestamp` Column Check

**Dosya:** `services/core/data_quality.py`  
**Satır:** 168–197 (`DataQualityChecker.full_quality_check`)  

**Sorun:** `timestamp`/`date` sütunu kontrolü yok. Duplicate tarih, gelecek tarih, gap detection eksik.

**Düzeltme:** Tarih sütunu için duplicate, future date, gap check eklenmeli.

---

### P2-8: InMemoryRateLimiter — Memory Leak Riski

**Dosya:** `services/api/rate_limiter.py`  
**Satır:** 56  

**Sorun:** `_buckets` dict'i asla temizlenmiyor. Her farklı `client_id:key` kombinasyonu için yeni entry oluşur:

```python
self._buckets: Dict[str, Dict[str, any]] = defaultdict(lambda: {
    "tokens": 100,
    "last_refill": time.monotonic(),
})
```

**Etki:** Uzun süreli çalışmalarda bellek şişmesi.  
**Düzeltme:** Periyodik cleanup (son refill'ı 1 saatten eski olan bucket'ları sil).

---

## Mimari Özet

```
┌─────────────────────────────────────────────────────────────────┐
│                    API KATMANI SORUNLARI                        │
├─────────────────────────────────────────────────────────────────┤
│ app.py (CANONICAL) ←── main.py (DEPRECATED, re-export)         │
│    │                                                            │
│    ├── v1_router (/api/v1/*) ← 16 alt router                   │
│    └── learning_router (/api/learning) ← ÇIFT KAYIT (P1-1)     │
│                                                                 │
│ server.py (DEV/LEGACY) ← Tamamen ayrı bir FastAPI app          │
│    └── SQLite dev_db kullanır, production'da KULLANILMAMALI     │
├─────────────────────────────────────────────────────────────────┤
│                   VERİ KATMANI SORUNLARI                       │
├─────────────────────────────────────────────────────────────────┤
│ tcmb_provider.py: baseline_values hard-coded (P0-1)            │
│ bist_provider.py: redundant or operatörleri (P0-4)             │
│ event_bus.py: sessiz hata yutma (P1-2) + connection leak (P1-3)│
│ regime_detector.py: hard-coded geçiş matrisi (P1-7)            │
├─────────────────────────────────────────────────────────────────┤
│                  GÜVENLİK SORUNLARI                            │
├─────────────────────────────────────────────────────────────────┤
│ dependencies.py: AUTH_STRICT=false → ADMIN rolü (P0-2)         │
│ server.py: WebSocket auth exception pass (P1-6)                │
│ realtime_provider.py: MD5 hash (P1-11)                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Önerilen Öncelikli Aksiyonlar

1. **P0-2 → Hemen:** `AUTH_STRICT` default `true` yap, anonim rol `VIEWER`'a düşür
2. **P0-1 → 1 gün:** TCMB baseline_values'ı config'den yükle, `is_live` tüketimini zorunlu kıl
3. **P0-3 → 1 gün:** `macro_impact` çarpanını sınırla (max ±15 puan)
4. **P1-1 → 1 hafta:** Legacy learning router alias'ı kaldır
5. **P1-2 → 1 hafta:** Event bus log seviyelerini `warning`'a çıkar
6. **P1-3 → 1 hafta:** `_publish_to_stream`'de connection reuse
