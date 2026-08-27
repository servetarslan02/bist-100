# 🏗️ ALPHA BIST — Composite Index Stratejisi

> **Oluşturulma:** 2026-08-28  
> **Kapsam:** PostgreSQL index stratejisi ve composite index önerileri  
> **Durum:** Aktif

---

## 📋 Mevcut Index Durumu

### Kritik Tablolar ve Sorgu Desenleri

| Tablo | Sıklıkla Sorgulanan Sütunlar | Mevcut Index | Composite Index İhtiyacı |
|---|---|---|---|
| `model_predictions` | instrument_id, prediction_date | ✅ Ayrı ayrı | 🔴 Gerekli |
| `signals` | instrument_id, strategy_id, status | ✅ Ayrı ayrı | 🔴 Gerekli |
| `positions` | portfolio_id, instrument_id, status | ✅ Ayrı ayrı | 🔴 Gerekli |
| `orders` | portfolio_id, status, created_at | ✅ Ayrı ayrı | 🔴 Gerekli |
| `alerts` | alert_type, severity, created_at | ✅ Ayrı ayrı | 🟠 Değerlendir |
| `scan_results` | scan_id, created_at | ✅ Ayrı ayrı | 🟠 Değerlendir |
| `audit_logs` | entity_type, entity_id, created_at | ✅ Ayrı ayrı | 🔴 Gerekli |
| `daily_performance` | date, strategy_id | ⚠️ Kontrol | 🔴 Gerekli |

---

## 🎯 Composite Index Önerileri

### 1. model_predictions (En kritik)

```sql
-- Mevcut: Ayrı index'ler
-- CREATE INDEX idx_model_predictions_instrument ON model_predictions(instrument_id);
-- CREATE INDEX idx_model_predictions_date ON model_predictions(prediction_date);

-- Önerilen: Composite index (sorgu desenine uygun)
CREATE INDEX idx_model_predictions_instrument_date 
    ON model_predictions(instrument_id, prediction_date DESC);

-- Puan bazlı sorgular için
CREATE INDEX idx_model_predictions_date_confidence 
    ON model_predictions(prediction_date DESC, confidence DESC);

-- Cleanup sorguları için
CREATE INDEX idx_model_predictions_created 
    ON model_predictions(created_at);
```

**Gerekçe:** 
- `WHERE instrument_id = ? AND prediction_date >= ?` → en yaygın sorgu
- `ORDER BY prediction_date DESC LIMIT ?` → son tahminleri getirme
- Ayrı index'ler bu sorgularda index merge yapar → composite daha verimli

### 2. signals

```sql
-- Mevcut: Ayrı index'ler
-- CREATE INDEX idx_signals_instrument ON signals(instrument_id);
-- CREATE INDEX idx_signals_strategy ON signals(strategy_id);
-- CREATE INDEX idx_signals_status ON signals(status);

-- Önerilen: Composite index'ler
CREATE INDEX idx_signals_instrument_status 
    ON signals(instrument_id, status);

CREATE INDEX idx_signals_strategy_status_created 
    ON signals(strategy_id, status, created_at DESC);

-- Aktif sinyal sorguları için
CREATE INDEX idx_signals_active 
    ON signals(status, created_at DESC) 
    WHERE status = 'active';
```

**Gerekçe:**
- `WHERE instrument_id = ? AND status = 'active'` → pozisyon kontrolü
- `WHERE strategy_id = ? AND status = ? ORDER BY created_at` → strateji performansı

### 3. positions

```sql
-- Mevcut: Ayrı index'ler
-- CREATE INDEX idx_positions_portfolio ON positions(portfolio_id);

-- Önerilen: Composite index
CREATE INDEX idx_positions_portfolio_status 
    ON positions(portfolio_id, status);

CREATE INDEX idx_positions_portfolio_instrument 
    ON positions(portfolio_id, instrument_id);

-- Aktif pozisyonlar için partial index
CREATE INDEX idx_positions_active 
    ON positions(portfolio_id, instrument_id) 
    WHERE status = 'open';
```

**Gerekçe:**
- `WHERE portfolio_id = ? AND status = 'open'` → aktif pozisyon listesi
- `WHERE portfolio_id = ? AND instrument_id = ?` → pozisyon detay sorgusu

### 4. orders

```sql
-- Mevcut: Ayrı index'ler
-- CREATE INDEX idx_orders_portfolio ON orders(portfolio_id);
-- CREATE INDEX idx_orders_status ON orders(status);

-- Önerilen: Composite index
CREATE INDEX idx_orders_portfolio_status_created 
    ON orders(portfolio_id, status, created_at DESC);

-- Emir geçmişi için
CREATE INDEX idx_orders_portfolio_created 
    ON orders(portfolio_id, created_at DESC);

-- Pending emirler için partial index
CREATE INDEX idx_orders_pending 
    ON orders(portfolio_id, created_at) 
    WHERE status = 'pending';
```

**Gerekçe:**
- `WHERE portfolio_id = ? AND status = ? ORDER BY created_at` → emir geçmişi
- `WHERE status = 'pending'` → bekleyen emirler (nadir ama kritik)

### 5. audit_logs

```sql
-- Mevcut: Ayrı index'ler
-- CREATE INDEX idx_audit_logs_entity ON audit_logs(entity_type, entity_id);

-- Önerilen: Composite index
CREATE INDEX idx_audit_logs_entity_time 
    ON audit_logs(entity_type, entity_id, created_at DESC);

-- Zaman bazlı sorgular için
CREATE INDEX idx_audit_logs_created 
    ON audit_logs(created_at DESC);

-- Belirli entity için partial index
CREATE INDEX idx_audit_logs_recent 
    ON audit_logs(entity_type, created_at DESC) 
    WHERE created_at > now() - interval '30 days';
```

**Gerekçe:**
- `WHERE entity_type = ? AND entity_id = ? ORDER BY created_at` → entity geçmişi
- `WHERE created_at > ?` → son aktivite sorguları

### 6. daily_performance

```sql
-- Önerilen: Composite index
CREATE INDEX idx_daily_performance_date_strategy 
    ON daily_performance(date DESC, strategy_id);

-- Strateji performansı için
CREATE INDEX idx_daily_performance_strategy_date 
    ON daily_performance(strategy_id, date DESC);
```

**Gerekçe:**
- `WHERE date >= ? AND strategy_id = ?` → performans hesaplama
- `ORDER BY date DESC` → son performans verileri

### 7. alerts

```sql
-- Mevcut: Ayrı index'ler
-- CREATE INDEX idx_alerts_type ON alerts(alert_type);
-- CREATE INDEX idx_alerts_severity ON alerts(severity);

-- Önerilen: Composite index
CREATE INDEX idx_alerts_type_severity_created 
    ON alerts(alert_type, severity, created_at DESC);

-- Kritik alarmlar için partial index
CREATE INDEX idx_alerts_critical_unresolved 
    ON alerts(created_at DESC) 
    WHERE severity = 'critical' AND resolved = false;
```

---

## 📊 Index Bakım Planı

### Haftalık Kontrol (Pazartesi 06:00)

```bash
# Index kullanım istatistikleri
python scripts/audit_query_performance.py --output reports/weekly_index_audit.md

# Kullanılmayan index'leri tespit et
psql -c "SELECT indexrelname, idx_scan FROM pg_stat_user_indexes WHERE idx_scan = 0 ORDER BY pg_relation_size(indexrelid) DESC;"
```

### Aylık Kontrol

```sql
-- Index şişmesi kontrolü
SELECT 
    indexname,
    pg_size_pretty(pg_relation_size(indexname::regclass)) as size
FROM pg_indexes 
WHERE schemaname = 'public'
ORDER BY pg_relation_size(indexname::regclass) DESC;

-- Dead row oranı yüksek tablolar
SELECT 
    relname,
    n_dead_tup,
    n_live_tup,
    round(n_dead_tup::numeric / NULLIF(n_live_tup, 0) * 100, 2) as dead_ratio
FROM pg_stat_user_tables
WHERE n_dead_tup > 10000
ORDER BY dead_ratio DESC;
```

### REINDEX Schedule

```sql
-- Yoğun yazma sonrası (haftalık)
REINDEX INDEX CONCURRENTLY idx_model_predictions_instrument_date;
REINDEX INDEX CONCURRENTLY idx_signals_instrument_status;
REINDEX INDEX CONCURRENTLY idx_orders_portfolio_status_created;
```

---

## ⚠️ Dikkat Edilecekler

1. **CONCURRENTLY kullan** — Production'da index oluştururken tablo kilitlemesini önler
2. **Önce test et** — `EXPLAIN ANALYZE` ile index'in gerçekten kullanıldığını doğrula
3. **Gereksiz index ekleme** — Her index yazma performansını düşürür
4. **Partial index** — Belirli koşullarda sorgulanan veriler için WHERE clause'lu index
5. **Covering index** — `INCLUDE` ile sadece index'ten döndürülebilen sütunlar

---

## 🔍 Doğrulama Komutları

```bash
# Index'in kullanıldığını doğrula
EXPLAIN ANALYZE SELECT * FROM model_predictions 
WHERE instrument_id = 1 AND prediction_date >= '2025-01-01';

# Index boyutlarını kontrol et
SELECT indexname, pg_size_pretty(pg_relation_size(indexname::regclass))
FROM pg_indexes WHERE tablename = 'model_predictions';

# Index kullanım istatistikleri
SELECT indexrelname, idx_scan, idx_tup_read 
FROM pg_stat_user_indexes 
WHERE relname = 'model_predictions';
```

---

*Bu strateji, ALPHA BIST'in sorgu desenlerine göre optimize edilmiştir.  
Periyodik olarak `scripts/audit_query_performance.py` ile gözden geçirilmelidir.*
