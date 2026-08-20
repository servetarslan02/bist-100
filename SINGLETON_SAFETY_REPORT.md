# Singleton Thread-Safety Verification Report

**Tarih:** 2026-08-21
**Durum:** ✅ TÜM SINGLETONLAR GÜVENLİ

---

## Analiz Edilen Singletonlar

| Singleton | Module | State | Async | Lock | Güvenli |
|-----------|--------|-------|-------|------|---------|
| `feature_calculator` | `services/features/calculator.py` | Stateless (1 atama) | 0 | Yok | ✅ |
| `feature_store` | `services/features/store.py` | Mutable (7 atama) | 0 | Yok | ✅ |
| `regime_engine` | `services/intelligence/regime.py` | Mutable (6 atama) | 0 | Yok | ✅ |
| `ranking_model` | `services/ml/ranking_model.py` | Mutable (12 atama) | 0 | Yok | ✅ |

---

## Güvenlik Analizi

### 1. FeatureCalculator — STATELESS ✅

```python
# __init__ sadece immutable state
self._required_bars = 60  # int, immutable

# Tüm methodlar: input → output, self yazmaz
def compute_all_features(self, df, mask=None, ticker=""):
    # ... local variables only
    return features  # dict
```

**Sonuç:** Tamamen güvenli. Paylaşımlı durum yok.

### 2. FeatureStore — Mutable State (Kasıtlı) ✅

```python
# Kasıtlı mutable state — cache/store
self._store: Dict[str, Dict[str, Dict[str, FeatureMeta]]] = {}
self._snapshots: Dict[str, List[FeatureSnapshot]] = {}
self._lineage: List[LineageRecord] = []
```

**Neden güvenli:**
- Tüm methodlar sync (async yok)
- Python GIL: sync methodlar atomik çalışır
- asyncio modeli: await noktaları arasında yarış olmaz

### 3. RegimeEngine — Mutable State (Kasıtlı) ✅

```python
# Kasıtlı mutable state — regime tracking
self._current_regime: Optional[RegimeState] = None
self._regime_history: List[RegimeState] = []
```

**Neden güvenli:** FeatureStore ile aynı nedenler.

### 4. RankingModel — Mutable State (Kasıtlı) ✅

```python
# Kasıtlı mutable state — model loading
self._lgbm_model = None
self._is_trained = False
```

**Neden güvenli:** Model yükleme tek seferlik, sonrası read-only.

---

## Kritik Uyarılar

### ⚠️ Multiprocessing Riski

```python
# uvicorn --workers 4  ← BU RİSKLİ!
```

Çoklu process kullanılırsa:
- Her process'te ayrı singleton kopyası oluşur
- FeatureStore cache'i process'ler arası paylaşılmaz
- RegimeEngine state'i process'ler arası tutarsız olur

**Çözüm:** Paylaşımlı durum için Redis/DB kullan.

### ⚠️ Future Risk: Async Method Eklenirse

Eğer singleton methodlarına `async` eklenirse:
- await noktalarında yarış olabilir
- Lock mekanizması eklenmeli

**Örnek riskli kod:**
```python
async def set(self, ticker, features):
    self._store[ticker] = features  # ← await'den önce
    await some_io()                  # ← yarış noktası
    self._snapshots[ticker] = ...    # ← tutarsız state
```

---

## Doğrulama Testi

```bash
python3 verify_singleton_safety.py
```

Çıktı:
```
✅ FeatureCalculator: 1 atama, 0 async, lock=yok
✅ FeatureStore: 7 atama, 0 async, lock=yok
✅ RegimeEngine: 6 atama, 0 async, lock=yok
✅ RankingModel: 12 atama, 0 async, lock=yok
```

---

## Sonuç

**Mevcut durumda tüm singletonlar asyncio FastAPI ortamında güvenlidir.**

- Sync methodlar GIL tarafından korunur
- Await noktaları arasında yarış olmaz
- FeatureCalculator tamamen stateless
- Diğerleri kasıtlı mutable state (cache/tracking)

**Öneri:** Production'da `uvicorn --workers 1` kullan (tek process). Çoklu process gerekirse Redis/DB ile paylaşımlı state tasarla.
