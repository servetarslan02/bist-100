# Bölüm 1 — Piyasa ve Veri Anlama

## Ana amaç

Sistem herhangi bir hisseyi analiz etmeye başlamadan önce piyasanın o anki gerçek fotoğrafını çıkaracak.

Buradaki bölümün görevi hisse seçmek değil; sonraki bütün motorlara güvenilir ve anlamlandırılmış bir piyasa ortamı sağlamaktır.

**Kaynak:** QuestDB Backtesting Guide, arXiv Agentic Trading (2026), arXiv FinWorld (2025).

---

## Kullanılacak sistemler

- yfinance (OHLCV, endeksler, makro)
- KAP Provider (şirket bildirimleri)
- News Provider (RSS haberler)
- Social Provider (sosyal medya)
- TCMB Provider (makro veriler)
- Fundamental Provider (bilanço, gelir tablosu)
- Market Calendar (piyasa saatleri, tatiller)
- Corporate Actions (temettü, bölünme)
- Cross-Source Reconciliation (çoklu kaynak doğrulama)
- Data Quality Gate (kalite kontrol)
- Tradability Mask (işlem yapılabilirlik)
- PIT Store (point-in-time veri)
- Streaming Anomaly Detector (anomali tespiti)

---

## Çalışma mantığı

```
Veri Kaynakları → Provider'lar → Data Quality Gate → Tradability Mask →
Cross-Source Reconciliation → PIT Store → Anomaly Detection →
MARKET STATE (güvenilir, temiz, anlamlandırılmış veri)
```

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

### Araştırma bulgusu

**QuestDB:** "Use high-quality, clean historical data. Account for all transaction costs. Test across different market conditions."

**arXiv Agentic Trading (2026):** Multi-source data pipeline with event-time framework. Her veri iki timestamp taşımalı: effective date (ne zaman bilindi) ve event date (ne zaman oluştu).

### Örnek: Çoklu kaynak fiyat çekimi

```python
# services/core/reconciliation.py
from services.core.reconciliation import cross_source_reconciliation

sources = {"yfinance": 305.25, "matriks": 305.30, "kap": 305.20}
result = cross_source_reconciliation.reconcile_price(sources)
# value: 305.28, source: matriks, quality_score: 100, is_consistent: True

# Anomali durumu
sources = {"yfinance": 305.25, "matriks": 350.00, "kap": 305.20}
result = cross_source_reconciliation.reconcile_price(sources)
# anomaly_detected: True, matriks reddedildi
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
# services/intelligence/world_state.py
from services.intelligence.world_state import WorldStateManager

wsm = WorldStateManager()
wsm.update_from_macro({"USD/TRY": {"price": 47.88}, "VIX": {"price": 14.25}})
wsm.update_from_event("FED_RATE_HIKE", {})

state = wsm.get_state_dict()
# global_risk_appetite: 0.42, usd_strength: 0.58, vix_level: 14.25
```

---

## 3. Veriler birbirini nasıl etkileyecek?

Önemli nokta bu.

```
Makro ↓ Sektör ↓ Şirket ↓ Hisse
Haber + KAP ↓ Şirket olayı ↓ Hisse üzerindeki potansiyel etki
BIST100 + Sektör Endeksi + Hisse ↓ Relative Strength
```

### Örnek: Macro → Sector → Company zinciri

```python
# services/intelligence/kap_extractor.py
from services.intelligence.kap_extractor import sector_chain

impacts = sector_chain.compute_chain_impact("ENERGY", 0.5)
# Enerji → Havacılık: -0.60 (yakıt maliyeti)
# Enerji → Perakende: -0.30 (lojistik)
```

---

## 4. Zaman boyutu

Her veri:

- Ne zaman oluştu?
- Ne zaman sisteme geldi?
- Hangi dönem için geçerli?

bilgileriyle tutulacak.

**Araştırma bulgusu:** QuestDB — "Point-in-time backtesting uses only data that would have been available at each historical moment, preventing look-ahead bias."

### Örnek: Point-in-Time veri saklama

```python
# services/core/pit_store.py
from services.core.pit_store import pit_store
from datetime import datetime, timezone

# Bilanço düzeltmesi
pit_store.insert("THYAO", "pe_ratio", 8.5, valid_from=datetime(2026, 3, 31, tzinfo=timezone.utc), source="kap")
pit_store.insert("THYAO", "pe_ratio", 9.0, valid_from=datetime(2026, 4, 30, tzinfo=timezone.utc), source="kap")

# Backtest'te sadece o tarihte bilinen veriyi gör
val = pit_store.get_as_of("THYAO", "pe_ratio", as_of_date=datetime(2026, 4, 15, tzinfo=timezone.utc))
# val = 8.5 (düzeltilmiş 9.0 henüz bilinmiyordu!)
```

---

## 5. Veri kalitesi her adımda kontrol edilecek

```
Kaynaktan geldi → Format kontrolü → Eksik veri kontrolü →
Anomali kontrolü → Kaynak karşılaştırması → Kalite skoru
```

### Örnek: Streaming anomali tespiti

```python
# services/core/streaming_anomaly.py
from services.core.streaming_anomaly import streaming_anomaly_detector

result = streaming_anomaly_detector.check_price("THYAO", 350.0, 305.0, volatility=0.25)
# is_anomaly: True, severity: CRITICAL, zscore: 8.5
```

---

## 6. FX Dönüşümü

Farklı para birimindeki verileri ortak para birimine çevirmek ve kur etkisini takip etmek için kullanılır.

### Örnek: Para birimi dönüşümü

```python
# services/portfolio/enhancements.py
from services.portfolio.enhancements import multi_currency

try_amount = multi_currency.convert(1000, "USD", "TRY")
# try_amount = 47880 (USD/TRY = 47.88)

fx_impact = multi_currency.get_fx_impact(
    [
        {"value": 10000, "currency": "TRY"},
        {"value": 5000, "currency": "USD"},
    ]
)
# fx_impact = {"total_try": 249400, "total_usd": 5220}
```

FX etkisi portföy değerlemesinde ve risk hesaplamalarında sürekli takip edilir.

---

## 7. Trading Calendar

Piyasanın açık/kapalı olduğunu kontrol eder. Sistem kapalı piyasada veri çekmez veya işlem yapmaz.

### Örnek: Piyasa durumu kontrolü

```python
# services/core/market_calendar.py
from services.core.market_calendar import market_calendar

info = market_calendar.get_info()
# is_trading_day: True
# is_market_open: True
# session: MORNING

market_calendar.is_trading_day(date(2026, 1, 1))  # False (Yılbaşı)
market_calendar.is_market_open(datetime(2026, 8, 16, 11, 15))  # True
```

---

## 8. Çıktı

```
MARKET STATE
Endeks durumu:        BIST100 -%1.8
Sektör durumu:        Bankacılık -%2.7, Enerji +%1.2
Makro durum:          USDTRY +%0.8, Faiz yüksek
Volatilite:           VIX 14.25
Haber ortamı:         Pozitif
KAP aktivitesi:       3 bildirim bugün
Veri kalite skoru:    %96
```

---

## Temel prensip

Bu bölüm **yorum yapmaz** ve **hisse önermez**.

Sadece:

> "Elimizde hangi güvenilir bilgiler var?"

sorusunun cevabını oluşturur.

---

## Türkiye Makro Göstergeleri Entegrasyonu

**Kaynak:** Bölüm 28 — Turkish Macro Indicators

Bu bölümün topladığı makro veriler, Bölüm 28'deki detaylı analiz motorlarına girdi sağlar:

| Veri | Bölüm 28 Motoru | Kullanım |
|------|----------------|----------|
| TCMB faiz | `macro/tcmb.py` | Reel faiz, policy stance |
| TÜFE/ÜFE | `macro/inflation.py` | Enflasyon trendi, TMS29 |
| USDTRY | `macro/fx.py` | Kur volatilitesi, BIST korelasyon |
| CDS | `macro/cds.py` | Ülke riski seviyesi |
| Kredi büyümesi | `macro/credit.py` | Ekonomik aktivite |
| Cari açık | `macro/current_account.py` | Döviz dengesi |
| Makro takvim | `macro/calendar.py` | TCMB PPK, TÜFE açıklama tarihleri |

### Örnek: Makro → Piyasa rejimi zinciri

```python
# 1. Veri çek (Bölüm 1)
tcmb_data = tcmb_provider.get_data()
inflation_data = macro_provider.get_inflation()

# 2. Makro feature hesapla (Bölüm 28)
from services.macro.tcmb import compute_tcmb_features
from services.macro.inflation import compute_inflation_features
from services.macro.fx import compute_fx_features

tcmb_features = compute_tcmb_features(tcmb_data)
inflation_features = compute_inflation_features(inflation_data)
fx_features = compute_fx_features(fx_data, stock_data)

# 3. Rejim tespitine girdi olarak kullan (Bölüm 3)
regime_input = {**tcmb_features, **inflation_features, **fx_features}
regime = regime_engine.detect_regime(regime_input)
```

---

## Alternative Data Entegrasyonu

**Kaynak:** Bölüm 26 — Alternative Data

Bu bölümün veri toplama motoru, Bölüm 26'daki alternatif kaynaklarla genişler:

| Veri | Bölüm 26 Motoru | Bölüm 1 Kullanımı |
|------|----------------|-------------------|
| Web scraping | `alternative/web_scraping.py` | İş ilanı, fiyat |
| Social | `alternative/social.py` | Sentiment |
| Jobs | `alternative/jobs.py` | Büyüme sinyali |
| Credit card | `alternative/credit_card.py` | Satış verisi |
| Satellite | `alternative/satellite.py` | Fabrika trafiği |

### Örnek: Alt data → Market state

```python
from services.alternative.web_scraping import compute_web_features
from services.alternative.jobs import compute_job_features

web_features = compute_web_features(scraped_data, "THYAO")
job_features = compute_job_features(job_data, "THYAO")

# Market state'e ekle
market_state["alt_data"] = {**web_features, **job_features}
```
