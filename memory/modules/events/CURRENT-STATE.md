# Events Modülü — Güncel Durum Raporu

**Tarih:** 2026-08-21
**Analiz:** Kod tabanı envanteri

---

## Genel Durum

| Metrik | Değer |
|--------|-------|
| Modül sayısı | 3 (core içinde) |
| Toplam satır | ~1,000 |
| Test sayısı | 8 |
| Event tipi sayısı | 40+ |

---

## Modül Olgunluk Durumu

| Modül | Durum | Not |
|-------|-------|-----|
| event_schema.py | ✅ TAM | 40+ EventType, typed data schemas |
| event_bus.py | ✅ TAM | Redis Pub/Sub + Stream + Kafka opsiyonel |
| dead_letter_queue.py | ✅ TAM | Exponential backoff retry |

---

## Çözülen Sorunlar (2026-08-20)

1. **Event Bus → DLQ entegrasyonu** — Handler crash → DLQ push mekanizması eklendi
2. **Sessiz hata yönetimi** — `except: pass` blokları logger'larla değiştirildi

---

## Bilinen Sınırlamalar

| Sınırlama | Öncelik | Açıklama |
|-----------|---------|----------|
| In-memory DLQ | P1 | Restart sonrası DLQ kayıtları kaybolur |
| In-memory idempotency set | P1 | 50.000'e kadar büyür, sonra temizlenir |
| Redis Stream maxlen | P2 | 10.000 event ile sınırlı |
| Kafka opsiyonel | P2 | `REDPANDA_BROKERS` tanımlı değilse kullanılmaz |
| `services/events/` boş | P2 | Event-specific servisler henüz taşınmadı |
| PostgreSQL fallback | P2 | `event_ledger` tablosu varsayılıyor |
