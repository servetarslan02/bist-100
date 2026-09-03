# Archive

Arşivlenen dosyalar — `documentation/16-YENIDEN-DUZENLEME-HARITASI.md` kapsamında.

## 2026-09-03

### `services/alternative/satellite.py` → `satellite.py.legacy`
- **Gerekçe:** `satellite_adapter.py`'deki `SatelliteAdapter` sınıfı ile aynı işi yapıyor (uydu verisi feature'ları). Legacy fonksiyon `satellite_adapter.py`'ye `compute_satellite_features()` olarak taşındı.
- **Kanıt:** `grep -rn "from services.alternative.satellite import" --include="*.py"` → sadece `tests/test_bolum25_32.py` (güncellendi) ve `__init__.py` (güncellendi).
- **Doğrulama:** `python3 -c "from services.alternative import compute_satellite_features"` → OK.
