# Bölüm 2 — Veri Kalitesi ve Gerçeklik

## Amaç

Bölüm 1'in topladığı verilerin gerçekten kullanılabilir olup olmadığını belirlemek.

**Kaynak:** Monte Carlo Data Quality Testing (7 Essential Tests), Confluent Streaming Quality, Quant Research (look-ahead bias, survivorship bias).

---

## Kullanılacak sistemler

- Data Validation
- Data Quality Engine
- Source Reliability
- Duplicate Detection
- Point-in-Time Data
- Look-Ahead Bias Protection
- Survivorship Bias Protection
- Data Reconciliation
- Data Lineage
- Anomaly Detection

---

## Çalışma mantığı

```
Bölüm 1 verileri
    ↓
Format / tip kontrolü
    ↓
Eksik veri kontrolü
    ↓
Kaynak karşılaştırması
    ↓
Tarih-zaman kontrolü
    ↓
Duplicate kontrolü
    ↓
Anomali kontrolü
    ↓
Bias kontrolü
    ↓
Güvenilirlik skoru
    ↓
ANALİZE HAZIR VERİ
```

---

## 1. Format ve tip kontrolü

Her veri sisteme girerken kontrol edilecek:

- Fiyat > 0 olmalı
- Hacim >= 0 olmalı
- Timestamp geçerli olmalı
- OHLC tutarlı olmalı (High >= Low, High >= Close, Low <= Close)

### Örnek: Tradability mask

```python
# services/core/tradability_mask.py
from services.core.tradability_mask import tradability_mask
import numpy as np

close = np.array([100, 101, 0, 103, -5, 105])
volume = np.array([1000, 1200, 0, 1100, 800, 900])
high = np.array([102, 103, 0, 105, -3, 107])
low = np.array([99, 100, 0, 101, -7, 103])
open_ = np.array([100, 101, 0, 103, -5, 105])

mask = tradability_mask.compute_mask("TEST", open_, high, low, close, volume)

# Sonuç:
# mask.mask = [1, 1, 0, 1, 0, 1]
# mask.reason[2] = "zero_volume"
# mask.reason[4] = "zero_negative_price"
# mask.valid_pct = 66.7
```

**Kaynak:** Du (2026) — mask-first design tek başına +0.44 Sharpe katkısı.

---

## 2. Eksik veri kontrolü

Eksik veri sıfır olarak değerlendirilmez.

```
VALID    → Veri var ve kullanılabilir
MISSING  → Veri yok
STALE    → Veri çok eski (>5 dakika)
INVALID  → Veri mantıksız (negatif fiyat)
DUPLICATE → Aynı veri tekrar geldi
OUT_OF_ORDER → Zaman sırası bozuk
FUTURE   → Gelecekten timestamp
```

### Örnek: Missing ≠ Zero

```python
# services/core/data_quality.py
from services.core.data_quality import data_quality_gate, DataValidity

# Sıfır hacim → INVALID (MISSING değil!)
result = data_quality_gate.check_tick("THYAO", 305.25, 0, datetime.now(timezone.utc))
# result.validity = DataValidity.INVALID
# result.passed = False

# Eksik veri → MISSING olarak işaretlenir, sıfır atanmaz
```

**Kaynak:** Monte Carlo — NULL values test, missing data handling.

---

## 3. Kaynak karşılaştırması

Aynı veri birden fazla kaynaktan geldiğinde:

- Kaynak güvenilirliği kontrol edilir
- Uyuşmazlık tespit edilir
- Anomali kontrolü yapılır
- En güvenilir kaynak seçilir

### Örnek: Cross-source reconciliation

```python
# services/core/reconciliation.py
from services.core.reconciliation import CrossSourceReconciliation

rec = CrossSourceReconciliation()

# Tutarlı kaynaklar
result = rec.reconcile_price({"yfinance": 305.25, "matriks": 305.30, "kap": 305.20})
# is_consistent: True, quality_score: 100

# Uyuşmazlık
result = rec.reconcile_price({"yfinance": 305.25, "matriks": 350.00})
# is_consistent: False, discrepancy_pct: 13.7%

# Anomali
result = rec.reconcile_price({"yfinance": 305.25, "matriks": 305.30, "kap": 400.00})
# anomaly_detected: True, kap reddedildi
```

**Kaynak:** Monte Carlo Data Quality — multi-source consistency checks.

---

## 4. Tarih-zaman kontrolü

Her veri zaman damgasıyla tutulacak:

- Ne zaman oluştu?
- Ne zaman sisteme geldi?
- Hangi dönem için geçerli?

### Örnek: Gelecek timestamp tespiti

```python
from datetime import datetime, timezone, timedelta

# Gelecek timestamp → FUTURE olarak işaretlenir
future = datetime.now(timezone.utc) + timedelta(seconds=20)
result = data_quality_gate.check_tick("THYAO", 305.25, 100000, future)
# result.validity = DataValidity.FUTURE
# result.passed = False
```

### Örnek: Point-in-Time veri

```python
# services/core/pit_store.py
from services.core.pit_store import pit_store

# Bilanço düzeltmesi
pit_store.insert("THYAO", "pe_ratio", 8.5, datetime(2026, 3, 31), "kap")
pit_store.insert("THYAO", "pe_ratio", 9.0, datetime(2026, 4, 30), "kap")

# Backtest'te sadece o tarihte bilinen veriyi gör
val = pit_store.get_as_of("THYAO", "pe_ratio", datetime(2026, 4, 15))
# val = 8.5 (düzeltilmiş 9.0 henüz bilinmiyordu)
```

**Kaynak:** Quant research — look-ahead bias en yaygın backtest hatası.

---

## 5. Duplicate kontrolü

Aynı veri birden fazla kez gelirse tekilleştirilecek.

### Örnek: Time-windowed duplicate detection

```python
# services/core/data_quality.py
from datetime import datetime, timezone

# Aynı tick 1 dakika içinde tekrar gelirse → DUPLICATE
result1 = data_quality_gate.check_tick("THYAO", 305.25, 100000, datetime.now(timezone.utc))
result2 = data_quality_gate.check_tick("THYAO", 305.25, 100000, datetime.now(timezone.utc))
# result2.validity = DataValidity.DUPLICATE
# result2.passed = False
```

**Kaynak:** Monte Carlo — uniqueness tests.

---

## 6. Anomali kontrolü

Veri ingestion anında anomali tespiti yapılacak:

- Fiyat anomalisi (ani sıçrama)
- Hacim anomalisi (anormal hacim)
- Spread anomalisi (aşırı spread)

### Örnek: Streaming anomali tespiti

```python
# services/core/streaming_anomaly.py
from services.core.streaming_anomaly import streaming_anomaly_detector

# Normal fiyat
result = streaming_anomaly_detector.check_price("THYAO", 305.25, 305.00)
# is_anomaly: False

# Ani sıçrama (4 sigma)
result = streaming_anomaly_detector.check_price("THYAO", 350.00, 305.00)
# is_anomaly: True, severity: CRITICAL, zscore: 8.5

# Hacim anomalisi
for i in range(20):
    streaming_anomaly_detector.check_volume("THYAO", 100000)
result = streaming_anomaly_detector.check_volume("THYAO", 5000000)
# is_anomaly: True, zscore: 4.5
```

**Kaynak:** Confluent streaming data quality, Monte Carlo anomaly detection.

---

## 7. Bias kontrolü

### Survivorship Bias

Borsadan çıkmış şirketler tarihsel analizde tutulmalı.

```python
# services/ingestion/universe_enhancements.py
from services.ingestion.universe_enhancements import survivorship_bias

survivorship_bias.mark_delisted("OLD_COMPANY", "2025-01-01", "bankruptcy")

# Aktif evren (delisted şirketler hariç)
active = survivorship_bias.get_active_universe(
    ["THYAO", "OLD_COMPANY", "ASELS"],
    "2026-01-01"
)
# active = ["THYAO", "ASELS"] (OLD_COMPANY çıkarıldı)
```

**Kaynak:** Elton, Gruber, Blake (1996) — survivorship bias yıllık %0.9-3 getiri çarpıtması.

### Look-Ahead Bias

Gelecekteki veri bugünkü karara sızamaz.

```python
# PIT store ile engellenir (Bölüm 1, Madde 4)
# Backtest'te sadece o tarihte bilinen veri kullanılır
```

**Kaynak:** Quant research — pandas index alignment ile gelecek veri sızıntısı.

---

## 8. Güvenilirlik skoru

Her veri için bir güvenilirlik skoru hesaplanacak:

```
Güvenilirlik = kaynak_güvenilirliği × veri_kalitesi × güncellik × tutarlılık
```

### Örnek: Veri kalite skoru

```python
# Veri kalite bileşenleri
source_reliability = 0.90    # yfinance
data_quality = 0.95          # Format OK, eksik yok
freshness = 0.98             # 2 dk önce güncellendi
consistency = 1.00           # Kaynaklar tutarlı

reliability = source_reliability * data_quality * freshness * consistency
# reliability = 0.837 → %83.7 güvenilirlik
```

---

## 9. Çıktı

Her veri için kabaca:

- Değer
- Kaynak
- Zaman
- Güncellik
- Güvenilirlik
- Kalite

oluşacak.

Örneğin:

```
Hisse fiyatı:   125.40
Kaynak:         yfinance (güvenilirlik: 0.90)
Güncellik:      2 dk önce
Kalite:         %98
Güven:          Yüksek
Bias:           Yok
Anomali:        Yok
```

---

## 10. Kritik prensipler

### Bu bölüm analiz yapmaz

Sadece sonraki motorlara:

> "Bu veri güvenilir, bu veri şüpheli, bu veri kullanılamaz."

şeklinde temiz ve ölçülebilir bir veri zemini sağlar.

### Kalite önce feature'dan önce

Feature hesaplamadan önce veri kalitesi kontrol edilmeli. Kalitesiz veri → kalitesiz feature → kalitesiz karar.

**Kaynak:** Connie Zhou (2026) — "Always validate data quality before feature engineering."

### Garbage in, garbage out

Finansal piyasalarda bu kural en acımasız şekilde işler. Kötü veri ile eğitilen model, gerçek parayla işlem yaptığında kaybettirir.

---

## Kısacası

**Bölüm 2 = Veri filtreleme ve doğrulama katmanı.**

Analiz yapmaz, hisse seçmez.

Sadece:

> "Bu veri güvenilir mi ve kullanılabilir mi?"

sorusunu cevaplar.

Böylece sonraki Piyasa Analizi bölümü yanlış veya geleceğe ait verilerle karar vermez.
