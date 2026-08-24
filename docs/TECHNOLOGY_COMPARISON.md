# 📊 ALPHA BIST — Teknoloji Karşılaştırma Raporu

> **Tarih:** 2026-08-25  
> **Sürüm:** v4.2  
> **Kapsam:** Mevcut sistem bileşenleri vs endüstri standartları  
> **Strateji:** Her kategoride TEK en iyi teknoloji — çift başlılık yok

---

## 1. İletişim Protokolleri

| Protokol | Gecikme | Yön | ALPHA BIST | Amaç |
|---|---|---|---|---|
| **WebSocket** | ~1-5ms | Çift yönlü | ✅ Ana protokol | Gerçek zamanlı veri akışı |
| **REST** | ~50-200ms | İstek-Yanıt | ✅ CRUD operasyonları | API endpoint'leri |
| **gRPC** | ~0.5-2ms | Çift yönlü | ✅ Servisler arası | Internal iletişim |
| **SSE** | ~5-10ms | Server→Client | ✅ Tek yönlü push | Bildirimler |

**Strateji:** 4 protokol, her biri farklı amaç için. Çift başlılık yok.

---

## 2. Veri Formatları

| Format | Amaç | ALPHA BIST |
|---|---|---|
| **orjson** | Ana JSON serializer (10x hızlı) | ✅ Tek kaynak |
| **Protobuf** | gRPC binary iletişim | ✅ Sadece gRPC |

**Strateji:** orjson tek JSON kaynağı. Protobuf sadece gRPC için. MessagePack kaldırıldı.

---

## 3. Mesajlaşma Sistemi

| Sistem | Amaç | ALPHA BIST |
|---|---|---|
| **NATS** | Ana mesajlaşma (yüksek throughput) | ✅ Primary |
| **Redis Pub/Sub** | Anlık bildirim, push-based | ✅ Secondary |
| **Redis Streams** | Event ledger, at-least-once | ✅ Durable |

**Strateji:** NATS tek kaynak mesajlaşma. Redis sadece cache + pub/sub. Kafka/Redpanda kaldırıldı (gereksiz karmaşıklık).

---

## 4. Veritabanları

| Sistem | Amaç | ALPHA BIST |
|---|---|---|
| **PostgreSQL 17** | İşlemsel veriler | ✅ Tek RDBMS |
| **ClickHouse** | OLAP, analitik | ✅ Tek OLAP |
| **Redis 8** | Cache + pub/sub + streams | ✅ Tek cache |

**Strateji:** Her kategoride tek veritabanı. Çift başlılık yok.

---

## 5. Makine Öğrenmesi

| Kütüphane | Amaç | ALPHA BIST |
|---|---|---|
| **LightGBM** | Ana gradient boosting | ✅ Primary |
| **XGBoost** | Ensemble alternatifi | ✅ Secondary |
| **CatBoost** | Kategorik veri | ✅ Tertiary |
| **PyTorch** | Deep learning | ✅ LSTM/Transformer |
| **scikit-learn** | Preprocessing, metrics | ✅ Yardımcı |

**Strateji:** 3 gradient boosting (ensemble için gerekli). PyTorch deep learning için. Gereksiz yok.

---

## 6. Altyapı

| Bileşen | Amaç | ALPHA BIST |
|---|---|---|
| **Docker Compose** | Container orchestration | ✅ Tek orchestrator |
| **Prometheus** | Metrik toplama | ✅ Tek metrik |
| **Grafana** | Dashboard | ✅ Tek dashboard |
| **Alembic** | DB migration | ✅ Tek migration |

**Strateji:** Her kategoride tek araç.

---

## 7. Kaldırılan Teknolojiler

| Teknoloji | Neden Kaldırıldı | Yerine |
|---|---|---|
| **Kafka/Redpanda** | Gereksiz karmaşıklık, NATS yeterli | NATS |
| **MessagePack** | orjson daha hızlı, gereksiz | orjson |

---

## 8. Sonuç

ALPHA BIST sistemi, **her kategoride tek en iyi teknoloji** prensibiyle yapılandırılmıştır:

- **1 mesajlaşma sistemi:** NATS (Redis pub/sub secondary)
- **1 JSON formatı:** orjson
- **1 RDBMS:** PostgreSQL
- **1 OLAP:** ClickHouse
- **1 cache:** Redis
- **1 container orchestrator:** Docker Compose
- **1 metrik:** Prometheus
- **1 dashboard:** Grafana

**Çift başlılık yok. Her teknoloji tek amaca hizmet eder.**
