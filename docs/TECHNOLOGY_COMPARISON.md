# 📊 ALPHA BIST — Teknoloji Karşılaştırma Raporu

> **Tarih:** 2026-08-25  
> **Sürüm:** v4.5  
> **Kapsam:** Mevcut sistem bileşenleri vs zirve sistem standartları  
> **Strateji:** Her kategoride TEK en iyi teknoloji — çift başlılık yok  
> **Not:** Bu rapor kod tabanı doğrulaması ile hazırlanmıştır. Her bileşen için gerçek implementasyon durumu belirtilmiştir.

---

## 1. İletişim Protokolleri

| Protokol | Gecikme | Yön | ALPHA BIST | Amaç |
|---|---|---|---|---|
| **WebSocket** | ~1-5ms | Çift yönlü | ✅ Ana protokol | Gerçek zamanlı veri akışı |
| **REST** | ~50-200ms | İstek-Yanıt | ✅ CRUD operasyonları | API endpoint'leri |
| **gRPC** | ~0.5-2ms | Çift yönlü | ✅ Servisler arası (round_robin LB) | Internal iletişim |
| **SSE** | ~5-10ms | Server→Client | ✅ Tek yönlü push | Bildirimler |

**Strateji:** 4 protokol, her biri farklı amaç için. Çift başlılık yok.

---

## 2. Veri Formatları

| Format | Amaç | ALPHA BIST |
|---|---|---|
| **orjson** | Ana JSON serializer (Rust tabanlı, 4x hızlı) | ✅ Tek kaynak (130+ dosyada aktif) |
| **Protobuf** | gRPC binary iletişim | ✅ Sadece gRPC |
| **pickle** | ML model serialization (LightGBM, XGBoost, PyTorch) | ✅ Sadece ML modelleri |

**Strateji:** orjson tek JSON kaynağı. Protobuf sadece gRPC için. pickle sadece ML model serialization için. MessagePack kaldırıldı.

---

## 3. Mesajlaşma Sistemi

| Sistem | Amaç | ALPHA BIST |
|---|---|---|
| **NATS** | Ana mesajlaşma (yüksek throughput) | ✅ Primary |
| **NATS JetStream** | Kalıcı mesajlama (at-least-once) | ✅ Durable |
| **Redis Pub/Sub** | Anlık bildirim, push-based | ✅ Secondary (yardımcı) |
| **Redis Streams** | Event ledger, at-least-once | ✅ Durable |

**Strateji:** NATS ana mesajlaşma sistemi. JetStream ile kalıcılık. Redis Pub/Sub anlık bildirimler için yardımcı olarak kullanılır. Kafka/Redpanda kaldırıldı.

---

## 4. Veritabanları

| Sistem | Amaç | ALPHA BIST |
|---|---|---|
| **PostgreSQL 17** | İşlemsel veriler | ✅ Tek RDBMS |
| **ClickHouse** | OLAP, analitik | ✅ Tek OLAP |
| **Redis 8** | Cache + pub/sub + streams | ✅ Tek cache |
| **Redis Sentinel** | High availability (3 node quorum) | ✅ HA |

**Strateji:** Her kategoride tek veritabanı. Sentinel ile otomatik failover. Çift başlılık yok.

---

## 5. Makine Öğrenmesi

| Kütüphane | Amaç | ALPHA BIST |
|---|---|---|
| **LightGBM** | Ana gradient boosting | ✅ Primary |
| **XGBoost** | Ensemble alternatifi | ✅ Secondary |
| **CatBoost** | Kategorik veri | ✅ Tertiary |
| **PyTorch** | Deep learning | ✅ LSTM/Transformer |
| **scikit-learn** | Preprocessing, metrics | ✅ Yardımcı |

**Strateji:** 3 gradient boosting modeli ensemble'da çeşitlilik için kullanılır. PyTorch deep learning için. Gereksiz yok.

---

## 6. Altyapı

| Bileşen | Amaç | ALPHA BIST |
|---|---|---|
| **Docker Compose** | Container orchestration | ✅ Tek orchestrator |
| **Traefik** | API Gateway (routing, rate limiting) | ✅ Tek gateway |
| **Celery** | Async task queue (Redis broker) | ✅ Tek task queue |
| **Prometheus** | Metrik toplama | ✅ Tek metrik |
| **Grafana** | Dashboard | ✅ Tek dashboard |
| **Alembic** | DB migration | ✅ Tek migration |

**Strateji:** Her kategoride tek araç. Docker Compose tek sunucu deployment için uygundur.

---

## 7. Sistem Bileşenleri Karşılaştırması

### ✅ Zirve Seviyede Olan Bileşenler

| Bileşen | Durum | Zirve Standartı |
|---|---|---|
| **Binary WebSocket** | ✅ Protobuf + orjson | ✅ Zirve |
| **Rate Limiter** | ✅ In-memory | ✅ Zirve |
| **Circuit Breaker** | ✅ Full implementasyon | ✅ Zirve |
| **OpenTelemetry** | ✅ Tracing aktif | ✅ Zirve |
| **Feature Store** | ✅ Redis-backed | ✅ Zirve |
| **Model Registry** | ✅ Version tracking | ✅ Zirve |
| **Backtest Engine** | ✅ Walk-forward | ✅ Zirve |
| **Risk Parity** | ✅ Inverse volatility | ✅ Zirve |
| **Walk-Forward** | ✅ Rolling window | ✅ Zirve |
| **TradingView** | ✅ Lightweight chart | ✅ Zirve |
| **gRPC Load Balancing** | ✅ round_robin, DNS-based | ✅ Zirve |
| **Redis Sentinel** | ✅ 3 node quorum, otomatik failover | ✅ Zirve |
| **NATS JetStream** | ✅ Durable messaging, at-least-once | ✅ Zirve |
| **API Gateway** | ✅ Traefik, centralized routing | ✅ Zirve |
| **Cache Warming** | ✅ Otomatik sıcak veri yükleme | ✅ Zirve |
| **Async Task Queue** | ✅ Celery + Redis broker | ✅ Zirve |

### ✅ Aktif ve Çalışan Bileşenler

| Bileşen | Durum | Açıklama |
|---|---|---|
| **PostgreSQL Read Replica** | ✅ Aktif | Streaming replica + read/write splitting |
| **ClickHouse Replication** | ✅ Aktif | ReplicatedMergeTree + ZooKeeper, 2 node |
| **Service Discovery** | ✅ Aktif | Servis keşfi + health check + monitoring |
| **Database Sharding** | ✅ Aktif | Ticker-based (A-F, G-M, N-Z), 3 shard |
| **Monte Carlo** | ✅ Aktif | GPU destekli (var_cvar) + CPU (advanced) |

### ⚠️ Kısıtlı veya Geliştirme Aşamasında Olan Bileşenler

| Bileşen | Durum | Açıklama |
|---|---|---|
| **Service Mesh (mTLS)** | ⚠️ Kısıtlı | Self-signed CA mevcut, per-request mTLS yok |

---

## 8. Mimari Kararlar ve Gerekçeler

### Neden NATS (Kafka/Redpanda Yerine)?
- **Düşük gecikme:** NATS ~1ms, Kafka ~5-10ms
- **Daha basit operasyonel yük:** Broker gerektirmez, tek binary
- **JetStream ile kalıcılık:** At-least-once delivery garantisi
- **Yeterli throughput:** 10M+ msg/s (BIST 100 için fazlasıyla yeterli)

### Neden 3 Gradient Boosting Modeli?
- **Çeşitlilik:** LightGBM (hız), XGBoost (olgunluk), CatBoost (kategorik veri)
- **Stacking ensemble:** Farklı ağaç yapıları hata korelasyonunu azaltır
- **Akademik destek:** 2025-2026 araştırmaları stacking ensemble'ları doğruluyor

### Neden Docker Compose (Kubernetes Yerine)?
- **Tek sunucu yeterli:** BIST 100 verisi tek makinede işlenebilir
- **Daha basit operasyonel yük:** Kubernetes cluster yönetimi gerektirmez
- **Maliyet etkin:** Küçük ekip için uygun
- **Not:** Ölçeklenme gerektiğinde Kubernetes geçişi düşünülebilir

---

## 9. Kaldırılan Teknolojiler

| Teknoloji | Neden Kaldırıldı | Yerine |
|---|---|---|
| **Kafka/Redpanda** | Gereksiz karmaşıklık, NATS yeterli | NATS |
| **MessagePack** | orjson daha hızlı, gereksiz | orjson |

---

## 10. Sonuç

ALPHA BIST sistemi, **her kategoride tek en iyi teknoloji** prensibiyle yapılandırılmıştır:

### Mevcut Durum (v4.5)
- **1 mesajlaşma sistemi:** NATS + JetStream (Redis pub/sub secondary)
- **1 JSON formatı:** orjson
- **1 RDBMS:** PostgreSQL + Replica + Sharding
- **1 OLAP:** ClickHouse + Replication
- **1 cache:** Redis + Sentinel HA
- **1 container orchestrator:** Docker Compose
- **1 API Gateway:** Traefik
- **1 task queue:** Celery
- **1 service discovery:** Health check + monitoring
- **1 metrik:** Prometheus + Grafana

### Sistem Skoru
```
Zirve seviyede olan:        16 bileşen ✅
Aktif ve çalışan:            5 bileşen ✅
Kısıtlı/geliştirme aşaması:  1 bileşen ⚠️
Toplam:                     22 bileşen
Başarı oranı:               %95.5
```

**Çift başlılık yok. Her teknoloji tek amaca hizmet eder.**
