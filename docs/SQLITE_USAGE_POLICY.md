# 📋 ALPHA BIST — SQLite Kullanım Politikası

> **Oluşturulma:** 2026-08-28  
> **Amaç:** SQLite kullanım alanını kesin olarak sınırlandırmak  
> **Kural:** SQLite sadece belirli alanlarda kullanılabilir

---

## ✅ SQLite KULLANILABİLECEK ALANLAR

| Alan | Gerekçe | Örnek |
|---|---|---|
| **Unit testler** | Hızlı, bağımsız, DB gerektirmez | `test_db_lock.py`, `test_concurrency.py` |
| **Development** | Yerel geliştirme, Docker gerektirmez | Yerel test ortamı |
| **Standalone utility** | Bağımsız script'ler, tek dosya araçlar | `scripts/backup_alpha.sh` (artık DuckDB) |
| **Local cache** | Küçük, geçici, silinebilir veri | Feature cache, session data |

---

## ❌ SQLite KULLANILMAYACAK ALANLAR

| Alan | Gerekçe | Alternatif |
|---|---|---|
| **Production state** | Concurrency sorunları, crash recovery zayıf | PostgreSQL veya DuckDB |
| **Market data** | Büyük veri, sorgu performansı | ClickHouse veya QuestDB |
| **Kritik transaction** | ACID garantisi yetersiz | PostgreSQL |
| **Model metadata** | Versioning, audit trail gerekli | PostgreSQL |
| **Portföy verisi** | Multi-process erişim | PostgreSQL |

---

## 🔍 MEVCUT DURUM

### db_lock.py
- **Production:** `dialect="postgresql"` kullanılıyor (`services/portfolio/main.py:59`)
- **Test:** `dialect="sqlite"` kullanılıyor (test için uygun)
- **Karar:** ✅ Mevcut yapı doğru, SQLite testlerde kalabilir

### migrations/runner.py
- **Production:** `dialect="postgresql"` kullanılıyor
- **Development:** `dialect="sqlite"` fallback var
- **Karar:** ✅ Mevcut yapı doğru, development için SQLite kalabilir

### Testler
- `test_db_lock.py` → SQLite (test için uygun)
- `test_concurrency.py` → SQLite (test için uygun)
- `test_lock_resilience.py` → SQLite (test için uygun)
- **Karar:** ✅ Testlerde SQLite kalabilir

---

## 📊 DUCKDB'YE GEÇİŞ DURUMU

| Dosya | Mevcut | Hedef | Durum |
|---|---|---|---|
| `services/core/duckdb_store.py` | DuckDB | DuckDB | ✅ Zaten DuckDB |
| `services/core/state_store.py` | DuckDB | DuckDB | ✅ Zaten DuckDB |
| `scripts/backup_alpha.sh` | DuckDB | DuckDB | ✅ Güncellendi |
| `services/core/db_lock.py` | SQLite (test) | SQLite (test) | ✅ Test için uygun |
| `services/core/migrations/runner.py` | SQLite (dev) | SQLite (dev) | ✅ Dev için uygun |

---

## 📌 KURALLAR

1. **Yeni production kodu → SQLite KULLANMA**
   - Veri deposu için: PostgreSQL, DuckDB, ClickHouse veya QuestDB
   - Lock için: PostgreSQL advisory lock
   - Cache için: Redis

2. **Test kodu → SQLite KULLANABİLİR**
   - Hızlı, bağımsız, DB gerektirmez
   - Production DB'ye bağlı testler yavaş olur

3. **Mevcut SQLite kodu → KALABİLİR**
   - Production'da kullanılmıyorsa sorun yok
   - `dialect="postgresql"` ile çağrılıyorsa SQLite kodu çalışmaz

4. **Yeni migration → PostgreSQL ODAKLI**
   - `_pg_to_sqlite()` dönüşümü sadece development için
   - Production'da her zaman PostgreSQL

---

## 🔧 GELECEK İŞ

- [ ] `services/core/immutable_audit.py` → DuckDB'ye migrate et (eğer production'da kullanılıyorsa)
- [ ] `services/core/halt_monitor.py` → DuckDB'ye migrate et (eğer production'da kullanılıyorsa)
- [ ] Yeni feature'lar için DuckDB/PostgreSQL kullan

---

*Bu politika, ALPHA BIST'in veri depolama stratejisinin bir parçasıdır.  
SQLite sadece test ve development için, production için PostgreSQL/DuckDB/ClickHouse/QuestDB kullanın.*
