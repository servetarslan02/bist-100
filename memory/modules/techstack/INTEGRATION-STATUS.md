# Teknoloji Entegrasyon Durumu — Gerçek Durum

**Tarih:** 2026-08-21
**Prensip:** Requirements.txt'de yazmak ≠ entegre etmek

---

## 1. Entegrasyon Durumu

### ✅ Gerçekten Entegre (Kodda Kullanılıyor)

| Teknoloji | Dosya Sayısı | Durum |
|-----------|-------------|-------|
| PyTorch | 51 | ✅ Entegre |
| SQLAlchemy | 47 | ✅ Entegre |
| Polars | 23 | ✅ Entegre |
| SHAP | 25+ | ✅ Entegre |
| python-jose | 6 | ✅ Entegre |
| Lightweight Charts | 6 | ✅ Entegre |
| LightGBM | ml/ | ✅ Entegre |
| XGBoost | ml/ | ✅ Entegre |
| CatBoost | ml/ | ✅ Entegre |
| Optuna | ml/hyperparameter_tuner.py | ✅ Entegre |

### ❌ Entegre Değil (Sadece requirements.txt'de)

| Teknoloji | Durum | Aksiyon |
|-----------|-------|---------|
| **ORJSON** | ❌ 0 dosyada | API response'larında kullanılmalı |
| **PyArrow** | ⚠️ 3 dosyada (minimal) | Data pipeline'da kullanılmalı |
| **AG Grid** | ❌ 0 dosyada | Frontend'de data table olarak kullanılmalı |
| **Zustand** | ❌ 0 dosyada | Frontend'de state management olarak kullanılmalı |
| **OpenTelemetry** | ❌ 0 dosyada | Distributed tracing olarak kullanılmalı |
| **Ruff** | ❌ Config yok | pyproject.toml'a config eklenmeli |
| **cryptography** | ❌ 0 dosyada | Security modülünde kullanılmalı |
| **passlib** | ❌ 0 dosyada | Password hashing olarak kullanılmalı |
| **Alembic** | ❌ 0 dosyada | Mevcut migration runner var (manuel) |

### ⚠️ Mevcut Implementasyon Var (Değiştirilmemeli)

| Teknoloji | Mevcut | Neden Değiştirilmemeli |
|-----------|--------|----------------------|
| Migration Runner | `services/core/migrations/runner.py` | Zaten sağlam, distributed lock + checksum |
| JWT Manager | `services/core/jwt_manager.py` | Zaten HMAC-SHA256 tabanlı |
| Security | `services/core/security.py` | Zaten RBAC + session tabanlı |
| Event Bus | `services/core/event_bus.py` | Zaten Redis Pub/Sub tabanlı |

---

## 2. Aksiyon Planı

### Öncelik 1: Entegre Edilmeli (Gerekli)
1. ✅ ORJSON → API response'larında
2. ✅ Ruff → pyproject.toml config
3. ✅ PyArrow → Data pipeline'da

### Öncelik 2: Entegre Edilmeli (Frontend)
4. ✅ AG Grid → Data table olarak
5. ✅ Zustand → State management olarak

### Öncelik 3: Entegre Edilmeli (Monitoring)
6. ✅ OpenTelemetry → Distributed tracing olarak

### Öncelik 4: Mevcut Implementasyon Korunmalı
7. ⚠️ Alembic → Mevcut migration runner korunmalı
8. ⚠️ passlib → Mevcut security korunmalı
9. ⚠️ cryptography → Mevcut security korunmalı

---

## 3. Benchmark Planı

Her teknolojinin değerini kanıtlamak için benchmark'lar:

1. **Polars vs Pandas** — Gerçek BIST verisiyle hız karşılaştırması
2. **LightGBM vs CatBoost vs XGBoost** — OOS accuracy karşılaştırması
3. **Ensemble vs Single Model** — Stacking'in gerçekten değer katıp katmadığı
4. **ORJSON vs json** — API response hız karşılaştırması
