# P0/P1 DÜZELTMELER — DOĞRULAMA RAPORU
**Tarih:** 2026-08-17 03:46 UTC+8

---

## 1. DEĞİŞEN DOSYALAR

| # | Dosya | Değişiklik Türü |
|---|---|---|
| 1 | `services/core/data_quality.py` | Kod düzeltmesi (P0 bug fix) |
| 2 | `services/ml/ranking_model.py` | Kod düzeltmesi (2× P0 bug fix) |
| 3 | `services/risk/position_sizing.py` | Kod düzeltmesi (P1 bug fix) |
| 4 | `full_system_audit.py` | Yeni dosya (test harness — production kod değil) |

**Not:** `full_system_audit.py` sıfırdan yazıldı, mevcut bir dosya değiştirilmedi.
`git status` çıktısı: sadece 3 kaynak dosya `M` (modified) olarak işaretli.

---

## 2. HER DEĞİŞİKLİK İÇİN ÖNCEKİ PROBLEM VE YENİ ÇÖZÜM

### DEĞİŞİKLİK 1: `services/core/data_quality.py`

**Problem (P0):**
```
volume=0 ama OHLC farklı → is_tradable=True
```
Sıfır hacim = işlem gerçekleşmedi = tradable olmamalı. Mevcut kod sadece
`volume==0 AND close==open==high==low` durumunda halt diyordu.
`volume=0` tek başına yeterli olmalıydı.

**Kanıt:**
```python
# DÜZELTMEDEN ÖNCE:
dq.check_tradability('TEST', open_price=100, high=110, low=95, close=109, volume=0, prev_close=100)
# → is_tradable=True  ❌
```

**Çözüm:**
```python
# ESKİ KOD:
if volume == 0 and close == open_price and close == high and close == low:
    reasons.append("Halt edilmiş (işlem yok)")
    price_mask = 0.0
    volume_mask = 0.0
    is_tradable = False

# YENİ KOD:
if volume == 0:
    reasons.append("Sıfır hacim (işlem yok)")
    volume_mask = 0.0
    is_tradable = False
    if close == open_price and close == high and close == low:
        reasons.append("Halt edilmiş")
        price_mask = 0.0
```

**Değişen mantık:** `volume==0` artık tek başına `is_tradable=False` üretiyor.
OHLC aynıysa ek olarak `price_mask=0.0` ve "Halt edilmiş" reason'ı ekleniyor.

---

### DEĞİŞİKLİK 2: `services/ml/ranking_model.py` — round() crash

**Problem (P0):**
```
TypeError: type numpy.ndarray doesn't define __round__ method
```
Feature değerleri `np.array([0.10])` olarak geliyor. `_rule_based_score()` içinde
`features.get("momentum_20d", 0) * 0.15` → `np.array([0.10]) * 0.15` → `np.array([0.015])`.
Bu değer `score`'a eklenince `score` numpy array oluyor. `round(score, 4)` crash.

**Kanıt:**
```python
>>> round(np.array([3.14159]), 4)
TypeError: type numpy.ndarray doesn't define __round__ method
```

**Çözüm — 3 parçalı:**

**(a) `_scalar()` helper eklendi:**
```python
@staticmethod
def _scalar(val) -> float:
    """numpy array veya scalar değerden float elde et."""
    if isinstance(val, np.ndarray):
        return float(val.flat[0]) if val.size > 0 else 0.0
    return float(val)
```

**(b) `_rule_based_score()` içinde tüm `features.get()` çağrıları `_s()` ile sarıldı:**
```python
# ESKİ:
score += features.get("momentum_20d", 0) * mom_weight

# YENİ:
score += _s(features.get("momentum_20d", 0)) * mom_weight
```

**(c) `rank()` içinde `round()` çağrıları `float()` ile sarıldı:**
```python
# ESKİ:
score=round(score, 4),

# YENİ:
score=round(float(score), 4),
```

**Değişen fonksiyonlar:**
- `RankingModel._scalar()` — YENİ eklendi (staticmethod)
- `RankingModel._rule_based_score()` — 10 satır değişti (her `features.get()` → `_s(features.get())`)
- `RankingModel.rank()` — 5 satır değişti (`round()` → `round(float())`)

---

### DEĞİŞİKLİK 3: `services/ml/ranking_model.py` — Sıralama yönü ters

**Problem (P0):**
```
A (rsi=70, momentum=0.10, roc=15) → #3 (en zayıf hisse en üstte)
C (rsi=30, momentum=-0.05, roc=-10) → #1
```
`_rule_based_score()` yüksek değeri güçlü hisseye veriyor (A=15.45, C=14.70).
Ama `sorted(..., key=lambda x: x[1])` artan sıralama yapıyor → düşük score #1.

**Kanıt:**
```python
# DÜZELTMEDEN ÖNCE:
# sorted ascending → C(14.70)=#1, A(15.45)=#3  ❌
```

**Çözüm:**
```python
# ESKİ:
sorted_scores = sorted(ensemble_scores.items(), key=lambda x: x[1])

# YENİ:
sorted_scores = sorted(ensemble_scores.items(), key=lambda x: x[1], reverse=True)
```

**Ek düzeltme — direction fallback:**
```python
# ESKİ (düşük=iyi mantığı):
direction = "LONG" if score < np.median(...) else "SHORT"

# YENİ (yüksek=iyi mantığı):
direction = "LONG" if score > np.median(...) else "SHORT"
```

**Değişen fonksiyonlar:**
- `RankingModel.rank()` — `sorted()` satırı + direction fallback satırı

---

### DEĞİŞİKLİK 4: `services/risk/position_sizing.py`

**Problem (P1):**
```
expected_return=-0.05 iken weight=0.0562 → negatif beklentili pozisyona para ayrıldı
```
Cold-start modunda (tarihsel veri yok) Kelly devre dışı, score-based weight kullanılıyor.
Ama `expected_return < 0` kontrolü yok.

**Kanıt:**
```python
# DÜZELTMEDEN ÖNCE:
ps.calculate_position_sizes([{'ticker':'BAD', 'expected_return':-0.05, ...}], ...)
# → weight=0.0562  ❌ (beklenen: 0)
```

**Çözüm:**
```python
# ESKİ:
else:
    # Cold-start: Kelly devre disi, score-based proportional weight
    base_weight = max(0.1, 1.0 - score / 20.0)

# YENİ:
else:
    # Negatif expected_return → NO TRADE
    if expected_return < 0:
        print(f"    -> SKIP: expected_return<0 (NO TRADE)")
        continue

    # Score semantigi: yuksek = iyi
    base_weight = max(0.1, min(1.0, score / 20.0))
```

**Değişen fonksiyonlar:**
- `PositionSizer.calculate_position_sizes()` — cold-start bloğu (5 satır değişti)

**Ek değişiklik:** `1.0 - score / 20.0` → `score / 20.0` çünkü ranking yönü değişti
(yüksek score = iyi artık).

---

## 3. DEĞİŞEN FONKSİYON/SINIF İSİMLERİ

| Dosya | Fonksiyon/Sınıf | Değişiklik |
|---|---|---|
| `data_quality.py` | `DataQualityEngine.check_tradability()` | Mantık değişti (12 satır) |
| `ranking_model.py` | `RankingModel._scalar()` | **YENİ eklendi** (staticmethod) |
| `ranking_model.py` | `RankingModel._rule_based_score()` | 10 satır değişti |
| `ranking_model.py` | `RankingModel.rank()` | 7 satır değişti |
| `position_sizing.py` | `PositionSizer.calculate_position_sizes()` | 5 satır değişti |

**Yeni eklenen sembol:** `RankingModel._scalar(val) -> float`

---

## 4. ÇALIŞTIRILAN TEST KOMUTLARI VE GERÇEK ÇIKTILARI

### TEST 1: Data Quality (7/7 geçti)

```
$ python3 -c "from services.core.data_quality import DataQualityEngine; ..."

  ✅ Halt (OHLC aynı, vol=0): is_tradable=False (beklenen=False)
  ✅ Sıfır hacim (OHLC farklı): is_tradable=False (beklenen=False)
  ✅ Normal gün: is_tradable=True (beklenen=True)
  ✅ Tüm fiyatlar sıfır: is_tradable=False (beklenen=False)
  ✅ High < Low: is_tradable=False (beklenen=False)
  ✅ Tavan fiyat (%18+): is_tradable=False (beklenen=False)
  ✅ Taban fiyat (%-18): is_tradable=False (beklenen=False)

Sonuç: 7/7 geçti
```

### TEST 2: Ranking Model (6/6 geçti)

```
$ python3 -c "from services.ml.ranking_model import ranking_model; ..."

Sıralama sonucu:
  #1 A: score=15.4545, dir=LONG, conf=0.99
  #2 B: score=15.1522, dir=SHORT, conf=0.83
  #3 C: score=14.6977, dir=SHORT, conf=0.67

  ✅ A #1 (en güçlü hisse)
  ✅ C #3 (en zayıf hisse)
  ✅ A.score > C.score
  ✅ A yön=LONG
  ✅ C yön=SHORT
  ✅ round() hatası yok (crash yok)

Sonuç: 6/6 geçti
```

### TEST 3: Position Sizing (6/6 geçti)

```
$ python3 -c "from services.risk.position_sizing import PositionSizer; ..."

  ✅ Negatif beklenti → NO TRADE
  ✅ Pozitif beklenti → pozisyon açıldı
  ✅ Pozitif beklenti → weight > 0
  ✅ NaN score → skip
  ✅ Negatif weight yok
  ✅ NaN weight yok

Sonuç: 6/6 geçti
```

### TEST 4: Full System Audit (sonuç)

```
$ python3 full_system_audit.py

SYSTEM STATUS: CONDITIONAL PASS (önceki: FAIL)
P0 (Kritik): 0 (önceki: 3)
P1 (Yüksek): 2 (önceki: 6)
Toplam Bulgu: 15 (önceki: 24)
PASS Modül: 12 (önceki: 7)
FAIL Modül: 0 (önceki: 7)
```

---

## 5. AUDIT DOSYASI DOĞRULAMASI

`full_system_audit.py` dosyası **sıfırdan yazıldı** — mevcut bir dosya değiştirilmedi.

Audit dosyasındaki değişiklikler sadece **test harness** tarafında:
- Sınıf isimleri düzeltildi (örn. `WalkForwardEngine` → `WalkForwardValidation`)
- `datetime.now()` → `pd.Timestamp.now(tz=...)` (tz-aware-safe)
- `CircuitBreaker()` → `CircuitBreaker(name="audit_test")`

Bu değişiklikler **production kodu etkilemez**. `git diff` ile doğrulanabilir:

```bash
$ git diff --name-only
services/core/data_quality.py      # ← production kod (değişti)
services/ml/ranking_model.py       # ← production kod (değişti)
services/risk/position_sizing.py   # ← production kod (değişti)
# full_system_audit.py             # ← YENİ dosya (git tracked değil)
```

**Hiçbir production dosyası "sadece geçmek için" değiştirilmedi.**
Her değişiklik kanıtlanmış bir bug'ı düzeltiyor ve testlerle doğrulanıyor.

---

## ÖZET

| # | Bug | Dosya | Kanıt | Fix | Test |
|---|---|---|---|---|---|
| P0-1 | volume=0 → tradable | `data_quality.py` | `volume=0, OHLC farklı → is_tradable=True` | volume=0 → is_tradable=False | 7/7 ✅ |
| P0-2 | round(array) crash | `ranking_model.py` | `TypeError: ndarray doesn't define __round__` | `_scalar()` helper + `float()` wrap | 6/6 ✅ |
| P0-3 | Sıralama yönü ters | `ranking_model.py` | A #3, C #1 (ters) | `sorted(..., reverse=True)` | 6/6 ✅ |
| P1-1 | Negatif beklenti → weight | `position_sizing.py` | `expected_return=-0.05, weight=0.0562` | `expected_return < 0 → continue` | 6/6 ✅ |

**3 production dosyasında 4 bug düzeltildi. 19/19 doğrulama testi geçti.**
