# Bölüm 1 — Piyasa ve Veri Anlama

## Ana amaç

Sistem herhangi bir hisseyi analiz etmeye başlamadan önce piyasanın o anki gerçek fotoğrafını çıkaracak.

Buradaki bölümün görevi hisse seçmek değil; sonraki bütün motorlara güvenilir ve anlamlandırılmış bir piyasa ortamı sağlamaktır.

---

## 1. Kullanılacak veri kaynakları

Sistem mümkün olduğunca şu kaynakları birlikte kullanacak:

- **Fiyat/OHLCV:** Açılış, yüksek, düşük, kapanış, hacim
- **Endeksler:** BIST100, BIST30, sektör endeksleri vb.
- **Şirket finansalları:** Bilanço, gelir tablosu, nakit akışı
- **KAP:** Özel durum açıklamaları ve şirket bildirimleri
- **Haberler:** Şirket, sektör ve ekonomi haberleri
- **Sosyal medya:** Yatırımcı ilgisi ve sentiment
- **Makro veriler:** Faiz, enflasyon, döviz, CDS, emtia vb.
- **Sektör verileri:** Sektör performansı ve gelişmeleri
- **Corporate actions:** Temettü, bölünme, bedelsiz, sermaye artırımı
- **Trading calendar:** Seans, tatil ve piyasa açık/kapalı bilgisi
- **FX:** TRY/USD/EUR gibi kur verileri

### Veri kaynağı güvenilirlik sıralaması

Her veri kaynağı bir güvenilirlik skoruna sahip olacak:

```
Borsa İstanbul (resmi)    → 0.99
KAP (resmi açıklama)      → 0.98
Bloomberg / Reuters       → 0.97
Matriks / İş Yatırım      → 0.95
yfinance                  → 0.90
Bloomberg HT / AA         → 0.85
Dünya / Borsa Gündem      → 0.80
Sosyal medya              → 0.40
```

Kaynak güvenilirliği, veri kalitesi skoruna ve karar confidence'ına doğrudan etki eder.

### Örnek: Çoklu kaynak fiyat çekimi

```python
# services/core/reconciliation.py
from services.core.reconciliation import cross_source_reconciliation

# Aynı hisse fiyatı farklı kaynaklardan geliyor
sources = {
    "yfinance": 305.25,
    "matriks": 305.30,
    "kap": 305.20,
}

result = cross_source_reconciliation.reconcile_price(sources)

# Sonuç:
# - value: 305.28 (ağırlıklı ortalama)
# - source: matriks (en güvenilir kaynak)
# - quality_score: 100.0 (tutarlı)
# - is_consistent: True
# - anomaly_detected: False
```

Eğer kaynaklar arasında büyük fark varsa:

```python
sources = {
    "yfinance": 305.25,
    "matriks": 350.00,  # Anomali!
    "kap": 305.20,
}

result = cross_source_reconciliation.reconcile_price(sources)
# - anomaly_detected: True
# - quality_score: 65.0
# - matriks reddedildi, yfinance + kap ortalaması kullanıldı
```

---

## 2. Sistem bunları ayrı ayrı toplamakla kalmayacak

Veriler zaman damgasıyla sisteme girecek.

Örneğin:

- BIST100 → -%1.8
- Bankacılık → -%2.7
- USD/TRY → +%0.8
- Faiz → yüksek
- Sektör sentiment → negatif
- Hisse X → -%3.2
- Hisse X hacim → yüksek

Sistem bunları birlikte değerlendirerek:

> "Bugünkü piyasa ortamı risk-off, bankacılık sektörü piyasadan daha zayıf ve döviz hareketi yüksek."

gibi yapısal piyasa durumu oluşturacak.

### Örnek: Market State oluşturma

```python
# services/market_state/main.py
from services.intelligence.world_state import WorldStateManager

wsm = WorldStateManager()

# Makro verilerden world state güncelle
wsm.update_from_macro({
    "USD/TRY": {"price": 47.88},
    "VIX": {"price": 14.25},
    "Oil": {"price": 82.40},
})

# Event'ten güncelle
wsm.update_from_event("FED_RATE_HIKE", {})

# Mevcut durum
state = wsm.get_state_dict()
# {
#   "global_risk_appetite": 0.42,
#   "usd_strength": 0.58,
#   "us_rate_pressure": 0.65,
#   "turkey_macro_risk": 0.55,
#   "vix_level": 14.25,
#   ...
# }
```

---

## 3. Veriler birbirini nasıl etkileyecek?

Önemli nokta bu.

Örneğin:

```
Makro ↓ Sektör ↓ Şirket ↓ Hisse
```

ve:

```
Haber + KAP ↓ Şirket olayı ↓ Hisse üzerindeki potansiyel etki
```

ve:

```
BIST100 + Sektör Endeksi + Hisse ↓ Relative Strength
```

şeklinde ilişkiler kurulacak.

Yani sistem her veriyi bağımsız kolon olarak saklayıp bırakmayacak.

### Örnek: Macro → Sector → Company zinciri

```python
# services/intelligence/kap_extractor.py
from services.intelligence.kap_extractor import sector_chain

# Petrol fiyatları yükseldiğinde:
impacts = sector_chain.compute_chain_impact("ENERGY", 0.5)

# Sonuç:
# Enerji → Havacılık: -0.60 (yakıt maliyeti)
# Enerji → Perakende: -0.30 (lojistik maliyeti)
# Enerji → Metal:     -0.30 (üretim maliyeti)
# Enerji → İnşaat:    -0.20 (enerji maliyeti)
```

### Örnek: Relative Strength hesaplama

```python
# services/features/seven_motors.py
from services.features.seven_motors import RelativeStrengthMotor

motor = RelativeStrengthMotor()

features = motor.compute(
    ticker="THYAO",
    stock_close=stock_prices,      # Hisse fiyatları
    benchmark_close=bist100_prices, # BIST100 fiyatları
    sector_close=sector_prices,     # Sektör endeksi
)

# Sonuç:
# rs_vs_bist_5d:  +2.3%  (BIST'ten iyi)
# rs_vs_sector_5d: +1.1% (Sektörden iyi)
# rs_trend: +0.8 (güçleniyor)
```

---

## 4. Zaman boyutu

Her veri:

- Ne zaman oluştu?
- Ne zaman sisteme geldi?
- Hangi dönem için geçerli?

bilgileriyle tutulacak.

Bu özellikle daha sonra:

- backtest
- tahmin
- Monte Carlo
- haber analizi

sırasında geleceğin geçmişe sızmasını engelleyecek.

### Örnek: Point-in-Time veri saklama

```python
# services/core/pit_store.py
from services.core.pit_store import pit_store
from datetime import datetime, timezone

# Gün 1: İlk bilanço açıklandı
pit_store.insert("THYAO", "pe_ratio", 8.5,
    valid_from=datetime(2026, 3, 31, tzinfo=timezone.utc),
    source="kap")

# Gün 30: Bilanço düzeltildi
pit_store.insert("THYAO", "pe_ratio", 9.0,
    valid_from=datetime(2026, 4, 30, tzinfo=timezone.utc),
    source="kap")

# Backtest Gün 15'te karar verirken:
val = pit_store.get_as_of("THYAO", "pe_ratio",
    as_of_date=datetime(2026, 4, 15, tzinfo=timezone.utc))
# val = 8.5 (düzeltilmiş 9.0 henüz bilinmiyordu!)
```

**Kaynak:** Quant research — pandas index alignment ile gelecek veri sızıntısı (look-ahead bias) en yaygın backtest hatası.

---

## 5. Veri kalitesi her adımda kontrol edilecek

Veri sisteme girerken değil, **her adımda** kalite kontrol edilecek:

```
Kaynaktan geldi → Format kontrolü → Eksik veri kontrolü →
Anomali kontrolü → Kaynak karşılaştırması → Kalite skoru
```

### Örnek: Streaming anomali tespiti

```python
# services/core/streaming_anomaly.py
from services.core.streaming_anomaly import streaming_anomaly_detector

# Normal tick
result = streaming_anomaly_detector.check_price("THYAO", 305.25, 305.00)
# is_anomaly: False

# Ani sıçrama
result = streaming_anomaly_detector.check_price("THYAO", 350.00, 305.00)
# is_anomaly: True, severity: CRITICAL, zscore: 8.5

# Hacim anomalisi
result = streaming_anomaly_detector.check_volume("THYAO", 5000000)
# is_anomaly: True, zscore: 4.5
```

**Kaynak:** Confluent streaming data quality, Monte Carlo Data Quality Testing.

---

## 6. Çıktı ne olacak?

Bölüm 1 sonunda sistemin elinde şu bulunacak:

```
MARKET STATE
Piyasa rejimi:        ? (Bölüm 3'te belirlenecek)
Endeks durumu:        BIST100 -%1.8
Sektör durumu:        Bankacılık -%2.7, Enerji +%1.2
Makro durum:          USDTRY +%0.8, Faiz yüksek
Volatilite:           VIX 14.25, BIST ATR normal
Likidite:             Normal
Haber ortamı:         Pozitif (şirket bazlı)
KAP aktivitesi:       3 bildirim bugün
Sosyal sentiment:     Nötr
Kur ortamı:           USDTRY zayıflama trendi
Önemli olaylar:       TCMB faiz kararı yarın
Veri güncelliği:      Son güncelleme 2 dk önce
Veri kalite skoru:    %96
```

Bu çıktı Bölüm 2'nin veri kalitesi kontrolünden geçecek ve ardından:

- Piyasa Analizi
- Hisse Bulma
- Fundamental
- Haber
- Tahmin
- Risk

motorlarının girdisi olacak.

---

## Kısacası

**Bölüm 1 = Sistemin dünyayı algılama katmanı.**

Hisse seçmez, BUY vermez, tahmin yapmaz.

Önce:

> "Piyasa şu anda hangi ortamda, hangi olaylar yaşanıyor ve elimizde hangi bilgiler var?"

sorusunu mümkün olduğunca doğru cevaplar.

### Temel prensip

Bu bölüm **yorum yapmaz** ve **hisse önermez**.

Sadece:

> "Elimizde hangi güvenilir bilgiler var?"

sorusunun cevabını oluşturur.
