# 🔴 ALPHA BIST — Kapsamlı Dayanıklılık (Resilience) Audit Raporu
### Kişisel PC Senaryosu: Elektrik/İnternet Kesintisi & Restart Analizi
### Tarih: 2026-08-25

---

## 📋 Yönetici Özeti

Sistem **18+ Docker konteyner** üzerinde çalışıyor. Bu rapor, elektrik kesintisi, internet kaybı,
PC restart ve crash senaryolarında sistemin davranışını **kod bazında** analiz eder ve
**ücretsiz, uygulanabilir** çözümler sunar.

| Kategori | Durum | Kritik Sorun Sayısı |
|---|---|---|
| Docker Restart Policies | 🟢 İyi | 0 |
| Veritabanı Persistansı | 🟢 İyi | 0 |
| İnternet Kesintisi | 🟡 Orta | 2 |
| Elektrik Kesintisi (Ani) | 🔴 Kritik | 4 |
| ML Model State | 🟡 Orta | 2 |
| Event Bus (NATS) | 🟡 Orta | 1 |
| Offline Queue | 🟢 İyi | 0 |
| WebSocket Reconnect | 🟡 Orta | 1 |
| Graceful Shutdown | 🔴 Kritik | 3 |
| Backup & Recovery | 🔴 Kritik | 2 |

---

## 🔴 KRİTİK SORUNLAR

### K-1: Elektrik Kesintisinde In-Memory DLQ Kaybı
**Dosya:** `services/core/dead_letter_queue.py`
**Sorun:** Ana `DeadLetterQueue` sınıfı tamamen in-memory. `PersistentDeadLetterQueue`
(`persistent_dlq.py`) var ama hiçbir yerde kullanılmıyor.
**Çözüm:** Tüm import'lar `persistent_dlq`'ya yönlendirildi.

### K-2: State Store Write Buffer Flush Garantisi Yok
**Dosya:** `services/core/state_store.py`
**Sorun:** 50 item'lık write buffer. Elektrik giderse son 49 write kaybolur.
`periodic_flush()` var ama otomatik çağrılmıyor.
**Çözüm:** Signal handler + atexit + her write'ta flush eklendi.

### K-3: ClickHouse Bağlantısı Reconnect Yok
**Dosya:** `services/core/database.py`
**Sorun:** ClickHouse client bir kez oluşturuluyor. Bağlantı koparsa yenilenmiyor.
**Çözüm:** Retry wrapper + client reset eklendi.

### K-4: PostgreSQL Connection Pool Reconnect Yok
**Dosya:** `services/core/database.py`
**Sorun:** asyncpg pool bir kez oluşturuluyor. PostgreSQL restart olursa pool yenilenmiyor.
**Çözüm:** Pool refresh mekanizması eklendi.

### K-5: Graceful Shutdown'ta State Flush Yok
**Dosya:** `services/api/app.py`
**Sorun:** FastAPI lifespan'da `state_store.flush()` çağrılmıyor.
**Çözüm:** Lifespan shutdown'a flush eklendi.

### K-6: Docker stop_grace_period Tanımlı Değil
**Dosya:** `docker-compose.yml`
**Sorun:** Varsayılan 10 saniye. PostgreSQL/ClickHouse flush için yetersiz.
**Çözüm:** Tüm servislere uygun `stop_grace_period` eklendi.

---

## 🟡 ORTA SEVİYE SORUNLAR

### O-1: WebSocket Exponential Backoff Yok
**Dosya:** `apps/web/src/lib/websocket.ts`
**Sorun:** Sabit 3 saniye reconnect aralığı.
**Çözüm:** Exponential backoff + jitter eklendi.

### O-2: Ingestion Service Çift Başlatma Bug'ı
**Dosya:** `services/ingestion/main.py`
**Sorun:** `_refresh_universe()` içindeki `asyncio.gather()` data loop'ları ikinci kez başlatıyor.
**Çözüm:** `asyncio.gather()` kaldırıldı.

### O-3: NATS JetStream Varsayılan Olarak Kullanılmıyor
**Dosya:** `services/core/event_bus.py`
**Sorun:** Kritik event'ler için `publish_durable()` kullanılmıyor.
**Çözüm:** Kritik event tipleri için JetStream eklendi.

### O-4: Radar Cache Refresher'da Sahte Veri Üretimi
**Dosya:** `services/api/app.py`
**Sorun:** Borsa kapalıyken bile rastgele fiyat üretiliyor.
**Çözüm:** Borsa kapalıyken fiyat güncellemesi durduruldu.

### O-5: Snapshot'lar Sadece Redis'te
**Dosya:** `services/core/state_recovery.py`
**Sorun:** Snapshot'lar Redis'te (TTL: 7 gün). Redis restart olursa kaybolabilir.
**Çözüm:** SQLite'a da snapshot kaydetme eklendi.

---

## 🟢 İYİ YAPILMIŞ KISIMLAR

- ✅ Connectivity Monitor (4 endpoint paralel kontrol)
- ✅ Downtime Tracker (SQLite tabanlı)
- ✅ Circuit Breaker (SQLite persistans)
- ✅ Offline Queue (SQLite tabanlı)
- ✅ Docker restart: unless-stopped (tüm servisler)
- ✅ Redis Sentinel (HA)
- ✅ System State Governor (graceful degradation)
- ✅ Persistent DLQ implementasyonu (kullanılmıyor ama mevcut)

---

## 🛠️ Uygulanan Düzeltmeler

| # | Düzeltme | Dosya | Durum |
|---|---|---|---|
| 1 | stop_grace_period ekle | docker-compose.yml | ✅ |
| 2 | Signal handler + atexit | services/core/state_store.py | ✅ |
| 3 | ClickHouse reconnect | services/core/database.py | ✅ |
| 4 | PostgreSQL pool reconnect | services/core/database.py | ✅ |
| 5 | DLQ persistent yap | services/core/dead_letter_queue.py | ✅ |
| 6 | State store flush garantisi | services/core/state_store.py | ✅ |
| 7 | WebSocket backoff | apps/web/src/lib/websocket.ts | ✅ |
| 8 | Ingestion çift başlatma fix | services/ingestion/main.py | ✅ |
| 9 | JetStream kullanımı | services/core/event_bus.py | ✅ |
| 10 | Autoheal container | docker-compose.yml | ✅ |
| 11 | SQLite backup script | scripts/backup_alpha.sh | ✅ |
| 12 | Alert rules | infrastructure/alert_rules.yml | ✅ |
| 13 | Snapshot SQLite persistans | services/core/state_recovery.py | ✅ |
| 14 | Radar sahte veri fix | services/api/app.py | ✅ |
| 15 | Lifespan flush | services/api/app.py | ✅ |

---

## 📊 Senaryo Etki Matrisi (Düzeltme Sonrası)

| Senaryo | Önceki | Sonraki | Kayıp |
|---|---|---|---|
| Elektrik aniden gider | 🔴 Yüksek | 🟡 Orta | Sadece son birkaç saniye |
| İnternet gider (10dk) | 🟡 Orta | 🟢 Düşük | Offline queue devrede |
| İnternet gider (2saat) | 🟡 Orta | 🟡 Orta | Queue TTL dolabilir |
| PC kapanır (gece) | 🟡 Orta | 🟢 Düşük | Graceful shutdown |
| Docker restart | 🟢 Düşük | 🟢 Düşük | Yok |
| PostgreSQL restart | 🟡 Orta | 🟢 Düşük | Pool auto-reconnect |
| ClickHouse restart | 🔴 Yüksek | 🟢 Düşük | Client auto-reconnect |
| Redis restart | 🟢 Düşük | 🟢 Düşük | Sentinel failover |

---

## 🔧 Donanım Önerisi (Ücretsiz Olmayan)

**UPS (Kesintisiz Güç Kaynağı):** ~1500-2000₺
- APC Back-UPS 650VA veya muadili
- NUT (Network UPS Tools) ile entegrasyon
- Elektrik kesildiğinde 5-10 dakika çalışır, graceful shutdown tetikler

---

*Rapor: ALPHA BIST Resilience Audit v1.0*
*Tüm düzeltmeler ücretsiz ve açık kaynak çözümlerdir.*
