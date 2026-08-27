# Bölüm 2 — Veri Kalitesi ve Gerçeklik

## Amaç

Bölüm 1'in topladığı verilerin gerçekten kullanılabilir olup olmadığını belirlemek.

**Kaynak:** QuestDB Backtesting Guide, arXiv FinWorld (2025), arXiv Agentic Trading (2026), Susan Potter Backtest Lies Taxonomy (2026).

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
Bölüm 1 verileri → Format/tip kontrolü → Eksik veri kontrolü →
Kaynak karşılaştırması → Tarih-zaman kontrolü → Duplicate kontrolü →
Anomali kontrolü → Bias kontrolü → Güvenilirlik skoru → ANALİZE HAZIR VERİ
```

---

## 1. Format ve tip kontrolü

Her veri sisteme girerken kontrol edilecek.

**Kontroller:**
- Fiyat > 0 olmalı
- Hacim >= 0 olmalı
- Timestamp geçerli olmalı
- OHLC tutarlı olmalı (High >= Low, High >= Close, Low <= Close)

**Araştırma bulgusu:** QuestDB — "Implement realistic trading constraints. Account for all transaction costs."

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
# mask.mask = [1, 1, 0, 1, 0, 1]
# mask.reason[2] = "zero_volume"
# mask.reason[4] = "zero_negative_price"
```

---

## 2. Eksik veri kontrolü

Eksik veri sıfır olarak değerlendirilmez.

**Durumlar:**
- VALID → Veri var ve kullanılabilir
- MISSING → Veri yok
- STALE → Veri çok eski (>5 dakika)
- INVALID → Veri mantıksız (negatif fiyat)
- DUPLICATE → Aynı veri tekrar geldi
- OUT_OF_ORDER → Zaman sırası bozuk
- FUTURE → Gelecekten timestamp

### Örnek: Missing ≠ Zero

```python
# services/core/data_quality.py
from services.core.data_quality import data_quality_gate, DataValidity

# Sıfır hacim → INVALID (MISSING değil!)
result = data_quality_gate.check_tick("THYAO", 305.25, 0, datetime.now(timezone.utc))
# result.validity = DataValidity.INVALID
# result.passed = False
```

---

## 3. Kaynak karşılaştırması

Aynı veri birden fazla kaynaktan geldiğinde kontrol edilecek.

**Kontroller:**
- Kaynak güvenilirliği
- Uyuşmazlık tespiti
- Anomali kontrolü
- En güvenilir kaynak seçimi

### Örnek: Cross-source reconciliation

```python
# services/core/reconciliation.py
from services.core.reconciliation import CrossSourceReconciliation

rec = CrossSourceReconciliation()

# Tutarlı
result = rec.reconcile_price({"yfinance": 305.25, "matriks": 305.30, "kap": 305.20})
# is_consistent: True, quality_score: 100

# Uyuşmazlık
result = rec.reconcile_price({"yfinance": 305.25, "matriks": 350.00})
# is_consistent: False, discrepancy_pct: 13.7%
```

---

## 4. Tarih-zaman kontrolü

Her veri zaman damgasıyla tutulacak.

**Araştırma bulgusu:** Susan Potter (2026) — "Every data point carries two timestamps: the effective date (when known) and the event date (when happened)."

### Örnek: Point-in-Time koruma

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

**Kaynak:** QuestDB — "Point-in-time backtesting uses only data available at each historical moment."

---

## 5. Duplicate kontrolü

Aynı veri birden fazla kez gelirse tekilleştirilecek.

### Örnek: Time-windowed duplicate detection

```python
# services/core/data_quality.py
result1 = data_quality_gate.check_tick("THYAO", 305.25, 100000, datetime.now(timezone.utc))
result2 = data_quality_gate.check_tick("THYAO", 305.25, 100000, datetime.now(timezone.utc))
# result2.validity = DataValidity.DUPLICATE
# result2.passed = False
```

---

## 6. Anomali kontrolü

Veri ingestion anında anomali tespiti yapılacak.

**Kontroller:**
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

# Ani sıçrama
result = streaming_anomaly_detector.check_price("THYAO", 350.00, 305.00)
# is_anomaly: True, severity: CRITICAL, zscore: 8.5
```

---

## 7. Bias kontrolü

### Survivorship Bias

Borsadan çıkmış şirketler tarihsel analizde tutulmalı.

**Araştırma bulgusu:** arXiv (2026) — "Backtests must address survivorship bias, look-ahead bias, and data-snooping bias explicitly."

```python
# services/ingestion/universe_enhancements.py
from services.ingestion.universe_enhancements import survivorship_bias

survivorship_bias.mark_delisted("OLD_COMPANY", "2025-01-01", "bankruptcy")
active = survivorship_bias.get_active_universe(["THYAO", "OLD_COMPANY", "ASELS"], "2026-01-01")
# active = ["THYAO", "ASELS"] (OLD_COMPANY çıkarıldı)
```

### Look-Ahead Bias

Gelecekteki veri bugünkü karara sızamaz.

**Araştırma bulgusu:** QuestDB — "The structural fix is an event-time framework where every data point carries two timestamps."

```python
# PIT store ile engellenir (Bölüm 1, Madde 4)
# Backtest'te sadece o tarihte bilinen veri kullanılır
```

---

## 8. Data Lineage

Her verinin kaynağını ve dönüşüm geçmişini takip eder.

### Örnek: Veri izleme

```python
# services/intelligence/research_memory.py
from services.intelligence.research_memory import data_lineage, LineageNode

# Ham veri → Feature → Model → Prediction zinciri
data_lineage.add_node(LineageNode("raw_data", "price_THYAO", "2026-08-15T10:00:00"))
data_lineage.add_node(LineageNode("feature", "rsi_THYAO", "2026-08-15T10:00:01", parent_ids=["raw_data:price_THYAO"]))
data_lineage.add_node(LineageNode("prediction", "pred_THYAO", "2026-08-15T10:00:02", parent_ids=["feature:rsi_THYAO"]))

# İleriye doğru izle (raw → feature → prediction)
forward = data_lineage.trace_forward("raw_data", "price_THYAO")
# forward: [raw_data, feature, prediction]

# Geriye doğru izle (prediction → feature → raw)
backward = data_lineage.trace_backward("prediction", "pred_THYAO")
# backward: [prediction, feature, raw_data]
```

Bu sayede herhangi bir kararın hangi veriye dayandığı izlenebilir.

---

## 9. Güvenilirlik skoru

Her veri için bir güvenilirlik skoru hesaplanacak.

**Formül:**
```
Güvenilirlik = kaynak_güvenilirliği × veri_kalitesi × güncellik × tutarlılık
```

---

## 9. Çıktı

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

Sadece sonraki motorlara temiz ve ölçülebilir bir veri zemini sağlar.

### Kalite önce feature'dan önce

**Kaynak:** Connie Zhou (2026) — "Always validate data quality before feature engineering."

### Garbage in, garbage out

Finansal piyasalarda bu kural en acımasız şekilde işler.

---

## Temel prensip

Bu bölüm analiz yapmaz ve hisse seçmez. Sadece sonraki motorlara temiz ve ölçülebilir bir veri zemini sağlar.

## 11. BIST'e Özel Anomali Tespiti

BIST'te devre kesici sonrası fiyat sıçramaları normal olabilir, sistem bunu bilmeli:

### Devre kesici sonrası anomali kontrolü:
```python
# services/core/bist_anomaly.py
def is_normal_after_halt(price_change, halt_duration_minutes):
    # Devre kesici 5-30 dakika sürdüyse, ilk dakikalardaki sıçrama normal
    if halt_duration_minutes <= 30 and abs(price_change) < 0.05:
        return True, "Normal post-halt volatility"
    
    # 30 dakikadan uzun durdurma sonrası daha büyük hareket normal
    if halt_duration_minutes > 30 and abs(price_change) < 0.10:
        return True, "Extended halt normal volatility"
    
    return False, "Anomalous post-halt movement"
```

### Brüt takas sonrası anomali kontrolü:
```python
def is_normal_gross_settlement(spread_pct, avg_spread_pct):
    # Brüt takasta spread genişlemesi normal
    if spread_pct < avg_spread_pct * 3:
        return True, "Normal gross settlement spread"
    
    return False, "Excessive spread in gross settlement"
```
