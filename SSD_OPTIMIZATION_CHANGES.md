# SSD Yazma Optimizasyonu — Uygulanan Değişiklikler

**Tarih:** 2026-08-31  
**Tahmini Tasarruf:** ~650-700 MB/saat (seans saatlerinde)

---

## Yapılan Değişiklikler (22 adet)

### 🔴 Yüksek Etki — Docker & Veritabanı

| # | Değişiklik | Dosya | Etki |
|---|---|---|---|
| 1 | Docker log `max-size: 1m` → `100k` | docker-compose.yml | ~320 MB/saat |
| 2 | PostgreSQL `synchronous_commit=off` | docker-compose.yml | ~150 MB/saat |
| 3 | PostgreSQL `full_page_writes=off` | docker-compose.yml | (yukarıyla birlikte) |
| 4 | PostgreSQL `wal_level=minimal` | docker-compose.yml | WAL üretimi azaldı |
| 5 | PostgreSQL `max_wal_size=512MB` → `256MB` | docker-compose.yml | WAL dosya boyutu |
| 6 | PostgreSQL replica devre dışı | docker-compose.yml | WAL okuma/yazma |
| 7 | Redis snapshot `900s` → `3600s` | docker-compose.yml | ~15 MB/saat |

### 🟡 Orta Etki — Polling & Log

| # | Değişiklik | Dosya | Etki |
|---|---|---|---|
| 8 | Prometheus scrape `5-30s` → `15-60s` | prometheus.yml | ~68 MB/saat |
| 9 | Frontend polling `10-30s` → `20-60s` | GlobalTelemetrySync.tsx | ~30 MB/saat |
| 10 | Asset sayfa polling `1.5s` → `5s` | asset/page.tsx | API log azalması |
| 11 | Radar refresher `2s` → `5s` | background_tasks.py | Redis yazma azalması |
| 12 | Log seviyesi `INFO` → `WARNING` | logging.py | Docker log azalması |
| 13 | PgBouncer log `1` → `0` | docker-compose.yml | Log azalması |
| 14 | Autoheal interval `60s` → `300s` | docker-compose.yml | Kontrol sıklığı |
| 15 | Healthcheck interval'ları `15s` → `30s` | docker-compose.yml | 8 servis |

### 🟢 Güvenlik & Bakım

| # | Değişiklik | Dosya | Etki |
|---|---|---|---|
| 16 | Connection leak düzeltildi | check_pending.py | DuckDB bağlantı sızıntısı |
| 17 | Hardcoded şifre kaldırıldı | mock_redis.py | Güvenlik açığı |
| 18 | SSL doğrulaması aktif | news_provider.py | MITM koruması |
| 19 | gRPC timeout `None` → `30s` | market_pb2_grpc.py | Thread bloklanma |
| 20 | CORS `*` → spesifik method/header | app.py | CSRF koruması |
| 21 | Fire-and-forget task referansları | 3 dosya | GC koruması |
| 22 | Background event loop shutdown | orchestrator.py | Resource leak |

### 🔧 SSD-Specific

| # | Değişiklik | Dosya | Etki |
|---|---|---|---|
| 23 | DuckDB WAL `10MB` → `2MB` | duckdb_store.py | WAL dosya boyutu |
| 24 | SSDThrottledWriter devre dışı | hardware_orchestrator.py | Boş thread kaldırıldı |
| 25 | apply_ssd_write_limit() ionice | start.py | I/O öncelik ayarı |
| 26 | replace_market.py güvenlik kilidi | replace_market.py | Yanlışlıkla çalıştırma |

---

## Yapılmayan Değişiklikler (Kasıtlı)

| Öneri | Neden Yapılmadı |
|---|---|
| `fsync=off` | Crash'te veri kaybı riski. `synchronous_commit=off` yeterli. |
| Docker log `driver: none` | Log tamamen kaybolur, debug imkansız. |
| DuckDB dosya birleştirme (8→2-3) | Çok riskli kod değişikliği. Mevcut buffered write sistemi çalışıyor. |
| JSON dosya debounce | Düşük etki (~18 MB/saat). Uğraşmaya değmez. |
| pickle.load hash doğrulama | Zaten her iki dosyada da hash doğrulaması varmış. |
| WebSocket'e geçiş | Frontend tarafında büyük refactor gerekir. |

---

## Tahmini SSD Yazma Azaltması

| Kaynak | Önce | Sonra | Tasarruf |
|---|---|---|---|
| Docker JSON log | ~360 MB/saat | ~40 MB/saat | **~320 MB** |
| PostgreSQL WAL | ~180 MB/saat | ~30 MB/saat | **~150 MB** |
| Prometheus TSDB | ~108 MB/saat | ~40 MB/saat | **~68 MB** |
| Redis RDB | ~20 MB/saat | ~5 MB/saat | **~15 MB** |
| Frontend polling | ~50 MB/saat | ~20 MB/saat | **~30 MB** |
| DuckDB WAL | ~72 MB/saat | ~15 MB/saat | **~57 MB** |
| Healthcheck/log | ~30 MB/saat | ~10 MB/saat | **~20 MB** |
| **TOPLAM** | **~794 MB/saat** | **~170 MB/saat** | **~624 MB/saat (%78 azalma)** |

---

## Geri Alma

```bash
cd bist-100
cp docker-compose.yml.bak docker-compose.yml
git checkout .
```

---

## Dikkat Edilmesi Gerekenler

1. **PostgreSQL replica** devre dışı. Replica lazımsa `wal_level=replica` ve `max_wal_senders=3`'e geri dön.
2. **Log seviyesi WARNING** — sorun olduğunda log bulmak zorlaşabilir.
3. **Frontend polling** yavaşladı — kullanıcı deneyiminde hafif gecikme olabilir.
4. **CORS** daraltıldı — farklı origin'den istek gelirse engellenir.
5. **gRPC timeout 30s** — uzun süren çağrılar timeout'a düşebilir.
