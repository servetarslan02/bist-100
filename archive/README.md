# Archive

Arşivlenen dosyalar — `documentation/16-YENIDEN-DUZENLEME-HARITASI.md` kapsamında.

## 2026-09-03

### `services/alternative/satellite.py` → `satellite.py.legacy`
- **Gerekçe:** `satellite_adapter.py`'deki `SatelliteAdapter` sınıfı ile aynı işi yapıyor (uydu verisi feature'ları). Legacy fonksiyon `satellite_adapter.py`'ye `compute_satellite_features()` olarak taşındı.
- **Kanıt:** `grep -rn "from services.alternative.satellite import" --include="*.py"` → sadece `tests/test_bolum25_32.py` (güncellendi) ve `__init__.py` (güncellendi).
- **Doğrulama:** `python3 -c "from services.alternative import compute_satellite_features"` → OK.

### `services/core/algo_notification.py` → `core/algo_notification.py`
- **Gerekçe:** Hiçbir dosya tarafından import edilmiyor (sadece `run_all_imports.py` referans veriyordu).
- **Kanıt:** `grep -rn "algo_notification" --include="*.py"` → sadece `run_all_imports.py` (güncellendi).

### `services/core/insider_detector.py` → `core/insider_detector.py`
- **Gerekçe:** Hiçbir dosya tarafından import edilmiyor.
- **Kanıt:** `grep -rn "insider_detector" --include="*.py"` → sadece `run_all_imports.py` (güncellendi).

### `services/core/manipulation_detector.py` → `core/manipulation_detector.py`
- **Gerekçe:** Hiçbir dosya tarafından import edilmiyor.
- **Kanıt:** `grep -rn "manipulation_detector" --include="*.py"` → sadece `run_all_imports.py` (güncellendi).

### `services/core/infrastructure.py` → `core/infrastructure.py`
- **Gerekçe:** Hiçbir dosya tarafından import edilmiyor. `infrastructure/mtls` referansları dizin yolu, bu modül değil.
- **Kanıt:** `grep -rn "from services.core.infrastructure" --include="*.py"` → 0 sonuç.

### `services/core/clickhouse_replication_health.py` → `core/clickhouse_replication_health.py`
- **Gerekçe:** 0 referans (hiçbir dosya, test veya script bile kullanmıyor).

### `services/core/data_schemas.py` → `core/data_schemas.py`
- **Gerekçe:** 0 referans.

### `services/core/health_reporter.py` → `core/health_reporter.py`
- **Gerekçe:** 0 referans.

### `services/core/pg_replication_health.py` → `core/pg_replication_health.py`
- **Gerekçe:** 0 referans.

### `services/core/duckdb_store.py` → `core/duckdb_store.py`
- **Gerekçe:** 0 referans. `duckdb_research.py` farklı dosya, aktif kullanımda.
