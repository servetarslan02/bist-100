# 🔍 BIST-100 ALPHA — Veri Pipeline Teftiş Raporu

**Tarih:** 2026-08-21  
**Kapsam:** services/ingestion, services/data, services/features, services/alternative, services/labels, data/  
**Toplam Taranan Dosya:** 45+ Python modülü, 3 JSON veri dosyası

---

## ÖZET

| Kategori | Kritik | Yüksek | Orta | Düşük | Toplam |
|----------|--------|--------|------|-------|--------|
| Mock/Placeholder Veri | 3 | 4 | 3 | 2 | 12 |
| Hardcoded Değerler | 1 | 3 | 4 | 2 | 10 |
| Data Leakage | 2 | 1 | 1 | 0 | 4 |
| Missing Data Handling | 1 | 3 | 4 | 2 | 10 |
| Data Type Mismatch | 1 | 2 | 1 | 0 | 4 |
| Timezone Issues | 0 | 2 | 2 | 1 | 5 |
| Deduplication | 0 | 1 | 2 | 1 | 4 |
| Data Validation | 1 | 2 | 3 | 1 | 7 |
| Cache Invalidation | 0 | 2 | 2 | 1 | 5 |
| Retry Logic | 0 | 1 | 1 | 1 | 3 |
| **TOPLAM** | **9** | **21** | **23** | **11** | **64** |

---

## 1. MOCK / PLACEHOLDER VERİLER

### 1.1 [KRİTİK] BIST-100 Evren Listesi Hardcoded (Sadece 20 Hisse)

**Dosya:** `services/data/data_source.py`  
**Satır:** ~105-110  
**Kod:**
```python
def get_bist100_universe(self) -> List[str]:
    """BIST 100 hisse listesini getir."""
    # TODO: Gerçek BIST 100 listesi
    # Şimdilik örnek liste
    return [
        "THYAO.IS",
        "GARAN.IS",
        "ISCTR.IS",
        "AKBNK.IS",
        "YKBNK.IS",
        "BIMAS.IS",
        "KCHOL.IS",
        "SAHOL.IS",
        "TUPRS.IS",
        "EREGL.IS",
        "ASELS.IS",
        "SISE.IS",
        "TOASO.IS",
        "ARCLK.IS",
        "KRDMD.IS",
        "PETKM.IS",
        "PGSUS.IS",
        "TAVHL.IS",
        "TKFEN.IS",
        "VAKBN.IS",
    ]
```

**Sorun:** BIST-100 yerine sadece 20 hisse döndürüyor. `TODO` bırakılmış, hiçbir zaman gerçek veriyle değiştirilmemiş.  
**Etki:** Tüm pipeline sadece 20 hisse üzerinde çalışır, 80 hisse göz ardı edilir.  
**Düzeltme:** `data/bist_universe_cache.json` dosyasındaki gerçek BIST-100 listesini kullan. Zaten 100+ ticker var o dosyada.

---

### 1.2 [KRİTİK] TCMB BIST-100 Serisi Yanlış Eşlenmiş (CPI Verisi)

**Dosya:** `services/ingestion/providers/tcmb_provider.py`  
**Satır:** ~30  
**Kod:**
```python
SERIES = {
    ...
    "bist_100": "TP.TUFE1YI1",  # ← BU CPI (TÜFE) VERİSİ!
}
```

**Sorun:** `bist_100` anahtarı TÜFE (CPI) serisine (`TP.TUFE1YI1`) bağlı. BIST-100 endeksi ile hiçbir ilgisi yok.  
**Etki:** BIST-100 endeksi olarak enflasyon verisi kullanılıyor — tamamen yanlış sinyal.  
**Düzeltme:** BIST-100 endeks verisi için doğru TCMB serisi kullanılmalı veya bu anahtar kaldırılmalı.

---

### 1.3 [KRİTİK] TCMB `fetch_all_macro` Async/Sync Uyumsuzluğu

**Dosya:** `services/ingestion/providers/tcmb_provider.py`  
**Satır:** ~95-110  
**Kod:**
```python
async def fetch_all_macro(self) -> Dict[str, Any]:
    for name, series in self.SERIES.items():
        try:
            ...
            data = self._make_request(series, start_date, end_date)  # ← await YOK!
```

**Sorun:** `_make_request` bir async fonksiyon ama `await` olmadan çağrılıyor. Coroutine objesi döner, gerçek veri değil.  
**Etki:** `fetch_all_macro` hiçbir zaman gerçek veri döndürmez — hep boş/hatalı sonuç.  
**Düzeltme:** `await self._make_request(...)` olarak değiştir.

---

### 1.4 [YÜKSEK] Macro Provider Başarısızlıkta Sıfır Değer Döndürüyor

**Dosya:** `services/ingestion/providers/yfinance_provider.py`  
**Satır:** ~170-180  
**Kod:**
```python
except Exception as e:
    results[name] = {"price": 0, "change_pct": 0}
```

**Aynı sorun:** `services/ingestion/providers/macro_provider.py` satır ~100  
```python
return name, {"price": 0, "change_pct": 0, "source": "yahoo", "error": str(e)}
```

**Sorun:** API hatası durumunda fiyat=0, değişim=0 döndürülüyor. Bu değerler gerçek veriymiş gibi pipeline'a girer.  
**Etki:** USD/TRY=0, Altın=0, VIX=0 → tüm makro feature'lar yanlış hesaplanır. Risk appetite her zaman "HIGH" olur.  
**Düzeltme:** Hata durumunda `None` döndür veya `{"price": None, "error": "..."}` kullan. Çağrılar `None` kontrolü yapmalı.

---

### 1.5 [YÜKSEK] Satellite Features Sabit Sıfır Değerler

**Dosya:** `services/alternative/satellite.py`  
**Satır:** ~15-25  
**Kod:**
```python
def compute_satellite_features(sat_data: Dict[str, Any], ticker: str) -> Dict[str, float]:
    features = {}
    if not sat_data:
        return features
    features["factory_traffic_change"] = sat_data.get("factory_traffic", 0)
    features["store_traffic_change"] = sat_data.get("store_traffic", 0)
    features["parking_lot_occupancy"] = sat_data.get("parking_occupancy", 0)
    features["port_activity"] = sat_data.get("port_activity", 0)
    features["construction_progress"] = sat_data.get("construction_progress", 0)
    return features
```

**Sorun:** `sat_data` boş dict ise tüm feature'lar 0 döner. Bu 0'lar gerçek uydu verisiymiş gibi işlenir.  
**Etki:** Uydu verisi olmayan hisselerde bile "factory_traffic_change=0" feature'ı üretilir — model yanıltılır.  
**Düzeltme:** Veri yoksa boş dict döndür (zaten yapıyor ama `sat_data` boş dict ise 0'lar üretiliyor). `sat_data.get("factory_traffic")` kullan, `None` ise feature üretme.

---

### 1.6 [YÜKSEK] Web Scraping Features Sabit Sıfır Değerler

**Dosya:** `services/alternative/web_scraping.py`  
**Satır:** ~15-25  
**Kod:**
```python
def compute_web_features(scraped_data: Dict[str, Any], ticker: str) -> Dict[str, float]:
    features = {}
    if not scraped_data:
        return features
    features["web_traffic_change"] = scraped_data.get("web_traffic_change", 0)
    features["app_ranking_change"] = scraped_data.get("app_ranking_change", 0)
    ...
```

**Sorun:** Aynı sorun — veri yoksa 0 döner.  
**Düzeltme:** `None` default kullan veya feature üretme.

---

### 1.7 [YÜKSEK] Credit Card Features Sabit Sıfır Değerler

**Dosya:** `services/alternative/credit_card.py`  
**Satır:** ~15-25  
**Kod:**
```python
def compute_cc_features(cc_data: Dict[str, Any], ticker: str) -> Dict[str, float]:
    features = {}
    if not cc_data:
        return features
    features["cc_spend_growth"] = cc_data.get("spend_growth", 0)
    ...
```

**Sorun:** Aynı pattern — veri yoksa 0 döner.  
**Düzeltme:** Aynı.

---

### 1.8 [ORTA] BIST Provider Fiyat Default'ları 0

**Dosya:** `services/ingestion/providers/bist_provider.py`  
**Satır:** ~65-80  
**Kod:**
```python
return {
    "ticker": ticker,
    "price": data.get("lastPrice", 0),
    "change_pct": data.get("changePercent", 0),
    "volume": data.get("volume", 0),
    ...
}
```

**Sorun:** API'den gelen veride eksik alan varsa 0 kullanılıyor. Fiyat=0 pozisyon açmaya neden olabilir.  
**Düzeltme:** Kritik alanlar (`price`, `volume`) için `None` kontrolü ekle.

---

### 1.9 [ORTA] Kariyer.net Placeholder Yapı

**Dosya:** `services/alternative/kariyer_net.py`  
**Satır:** ~85  
**Kod:**
```python
async def _scrape_postings(self, company: str, ticker: str) -> Dict[str, Any]:
    """...
    Production'da: aiohttp + BeautifulSoup ile Kariyer.net'ten çekilecek.
    Şimdilik: Placeholder yapı — veri çekme mantığı eklenecek.
    """
```

**Sorun:** Docstring'te "placeholder" olarak belirtilmiş. Scraping mantığı var ama Kariyer.net'in HTML yapısı değişirse çalışmaz.  
**Düzeltme:** Integration test ekle, HTML selector'ları periyodik doğrula.

---

### 1.10 [DÜŞÜK] BKM Adapter Placeholder Kontrolü

**Dosya:** `services/alternative/bkm_adapter.py`  
**Satır:** ~120  
**Kod:**
```python
def compute_features(self, data: Dict[str, Any], ticker: str) -> Dict[str, float]:
    if not data:
        return {}
    # Placeholder veri kontrolü
    if data.get("data_source") == "placeholder":
        return {}
```

**Sorun:** Placeholder veri kontrolü var ama `_scrape_bkm_page` hiçbir zaman `"data_source": "placeholder"` döndürmez. Ölü kod.  
**Düzeltme:** Ya placeholder mekanizmasını kaldır ya da gerçekten placeholder döndüren kod ekle.

---

### 1.11 [DÜŞÜK] Realtime Market Stream Sessiz Hata Yönetimi

**Dosya:** `services/ingestion/providers/realtime_provider.py`  
**Satır:** ~180  
**Kod:**
```python
except Exception as e:
    pass  # Intentional: silent error handling
```

**Sorun:** Market stream'de hata tamamen yutuluyor. Hangi hisselerin başarısız olduğu bilinmiyor.  
**Düzeltme:** `logger.debug(...)` ekle.

---

### 1.12 [DÜŞÜK] Feature Store In-Memory Only

**Dosya:** `services/alternative/feature_store.py`  
**Satır:** ~50  
**Kod:**
```python
class FeatureStore:
    def __init__(self, store_path: Optional[str] = None):
        self._store_path = store_path
        self._manifests: Dict[str, FeatureManifest] = {}
        self._feature_values: Dict[str, Dict[str, Dict[str, float]]] = {}
```

**Sorun:** Feature store sadece in-memory. Restart sonrası tüm veri kaybolur. `save()` ve `load()` metodları var ama otomatik çağrılmıyor.  
**Düzeltme:** Otomatik persistence mekanizması ekle (periyodik save veya shutdown hook).

---

## 2. HARDCODED DEĞERLER

### 2.1 [KRİTİK] Feature Calculator Varsayılan Değerler (RSI=50, ADX=25)

**Dosya:** `services/features/calculator.py`  
**Satır:** ~200-250 (çeşitli metodlar)  
**Kod:**
```python
def _rsi_masked(self, data, period=14):
    valid = data[~np.isnan(data)]
    if len(valid) < period + 1:
        return 50  # ← Hardcoded nötr değer

def _adx_masked(self, data, period=14):
    ...
    if len(c) < period * 2:
        return 25  # ← Hardcoded nötr değer

def _stochastic_masked(self, ...):
    if len(c) < k_period:
        return 50, 50  # ← Hardcoded nötr değer
```

**Sorun:** Yeterli veri yoksa nötr değerler (50, 25) döndürülüyor. Bu değerler gerçek hesaplama sonucuymuş gibi feature'a eklenir.  
**Etki:** Kısa geçmişi olan hisselerde RSI her zaman 50, ADX her zaman 25 → model bu hisseleri "nötr" olarak sınıflandırır.  
**Düzeltme:** Yeterli veri yoksa `None`/`NaN` döndür veya o feature'ı üretme.

---

### 2.2 [YÜKSEK] Macro Risk Appetite Sabit Eşikler

**Dosya:** `services/ingestion/providers/macro_provider.py`  
**Satır:** ~180-195  
**Kod:**
```python
vix = indicators.get("vix", {}).get("price", 0)
if vix:
    if vix < 15:
        indicators["risk_appetite"] = "HIGH"
    elif vix < 25:
        indicators["risk_appetite"] = "MODERATE"
    else:
        indicators["risk_appetite"] = "LOW"

dxy = indicators.get("dxy", {}).get("price", 0)
if dxy:
    if dxy > 105:
        indicators["dollar_strength"] = "STRONG"
    elif dxy > 100:
        indicators["dollar_strength"] = "MODERATE"
    else:
        indicators["dollar_strength"] = "WEAK"
```

**Sorun:** VIX ve DXY eşikleri hardcoded. Piyasa rejimi değiştiğinde (örn: 2020'de VIX 80'e çıktı) bu eşikler anlamsızlaşır.  
**Düzeltme:** Eşikleri percentile-based yap (son 1 yılın dağılımına göre).

---

### 2.3 [YÜKSEK] Historical Adapter Sabit Puanlama Kuralları

**Dosya:** `services/data/historical_adapter.py`  
**Satır:** ~60-100  
**Kod:**
```python
# balance_sheet_quality
quality_score = 50
if debt_eq:
    if debt_eq < 0.3:
        quality_score += 25
    elif debt_eq < 0.5:
        quality_score += 15
    elif debt_eq > 2:
        quality_score -= 25
...
# value_score
if pe and pe > 0 and pe < 15:
    value_score += 30
elif pe and pe < 25:
    value_score += 15
```

**Sorun:** Tüm değerleme kuralları hardcoded. Sektör farkı yok (bankacılık PE=5 normal, teknoloji PE=30 normal).  
**Etki:** Bankalar aşırı "değerli", teknoloji şirketleri aşırı "pahalı" görünür.  
**Düzeltme:** Sektörel normalize ekle veya percentile-based scoring kullan.

---

### 2.4 [YÜKSEK] KAP Sentiment Keyword Listesi Sabit

**Dosya:** `services/ingestion/providers/kap_provider.py`  
**Satır:** ~130-145  
**Kod:**
```python
positive = ["artış", "büyüme", "kâr", "rekor", "yükseliş", "pozitif", "başarı"]
negative = ["düşüş", "kayıp", "zarar", "azalma", "gerileme", "iptal", "risk"]
```

**Sorun:** Sadece 7 pozitif ve 7 negatif kelime. Finansal Türkçe'de yüzlerce sentiment taşıyan kelime var.  
**Etki:** "sermaye artırımı" → nötr (pozitif olmalı), "iflas erteleme" → nötr (negatif olmalı).  
**Düzeltme:** Genişletilmiş Türkçe finansal sentiment sözlüğü kullan (en az 50+ kelime).

---

### 2.5 [ORTA] Social Provider Sentiment Sabit Kelime Listeleri

**Dosya:** `services/ingestion/providers/social_provider.py`  
**Satır:** ~15-35  
**Kod:**
```python
TURKISH_POSITIVE = ["yükseliş", "artış", "kazanç", "rekor", ...]
TURKISH_NEGATIVE = ["düşüş", "kayıp", "zarar", "gerileme", ...]
```

**Sorun:** Kelime listeleri iyi ama `_analyze_sentiment` basit keyword counting yapıyor. N-gram veya bağlam analizi yok.  
**Etki:** "düşüş yok" → negatif sayılır (yanlış).  
**Düzeltme:** Negation handling ekle ("değil", "yok", "olmayan").

---

### 2.6 [ORTA] LLM Sentiment Fallback Keyword Listesi

**Dosya:** `services/alternative/llm_sentiment.py`  
**Satır:** ~120-140  
**Kod:**
```python
positive = [
    "artış",
    "yükseliş",
    "büyüme",
    "kâr",
    "rekor",
    "başarı",
    "arttı",
    "yükseldi",
    "güçlü",
    "olumlu",
    "destek",
    "teşvik",
    ...,
]
negative = ["düşüş", "kayıp", "zarar", "azalma", "gerileme", "kriz", ...]
```

**Sorun:** LLM yoksa keyword fallback kullanılıyor. Aynı negation sorunu.  
**Düzeltme:** Negation handling ekle.

---

### 2.7 [ORTA] Ekşi Sözlük Sentiment Keyword Listesi

**Dosya:** `services/alternative/eksi_sozluk.py`  
**Satır:** ~120-140  
**Kod:**
```python
positive_words = ["güzel", "harika", "mükemmel", "başarılı", "iyi", "yükseliş", ...]
negative_words = ["kötü", "berbat", "başarısız", "düşüş", "kayıp", "zarar", ...]
```

**Sorun:** Aynı pattern. Ekşi Sözlük'te ironi/sarkasm çok yaygın — keyword-based sentiment yanıltıcı olabilir.  
**Düzeltme:** LLM-based sentiment tercih et (zaten `llm_sentiment.py` var).

---

### 2.8 [ORTA] Investing.com Sentiment Keyword Listesi

**Dosya:** `services/alternative/investing_adapter.py`  
**Satır:** ~100-110  
**Kod:**
```python
def _basic_sentiment(self, text: str) -> float:
    pos = ["yükseliş", "artış", "güçlü", "olumlu", "al", "hedef", "potansiyel", "kâr"]
    neg = ["düşüş", "zarar", "zayıf", "sat", "risk", "tehlike", "kısa", "short"]
```

**Sorun:** Sadece 8 pozitif ve 8 negatif kelime.  
**Düzeltme:** Ortak sentiment sözlüğü kullan (tüm adapter'lar aynı sözlüğü paylaşsın).

---

### 2.9 [DÜŞÜK] News Provider RSS Feed Fallback

**Dosya:** `services/ingestion/providers/news_provider.py`  
**Satır:** ~185-195  
**Kod:**
```python
def _load_rss_feeds(self) -> List[str]:
    try:
        from services.core.observability import config_manager

        feeds = config_manager.get("news.rss_feeds")
        if feeds:
            return feeds
    except Exception:
        pass
    return [
        "https://www.bloomberght.com/rss",
        "https://www.foreks.com/rss",
        "https://www.paraanaliz.com/rss",
        "https://www.borsagundem.com/rss",
    ]
```

**Sorun:** Config yoksa 4 hardcoded RSS feed kullanılıyor. Bu URL'ler değişebilir veya erişilemez olabilir.  
**Düzeltme:** URL'lerin erişilebilirliğini kontrol et, alternatif feed'ler ekle.

---

### 2.10 [DÜŞÜK] Company Name Map Sabit

**Dosya:** `services/ingestion/providers/news_provider.py`  
**Satır:** ~20-120  
**Kod:**
```python
COMPANY_NAME_MAP = {
    "thyao": "Turk Hava Yollari",
    "garan": "Garanti BBVA",
    ...
    "quagr": "Qua Granite",  # ← Duplicate key!
    "rtalb": "Rotal Yatirim",  # ← Duplicate key!
    ...
}
```

**Sorun:** Duplicate key'ler var (`quagr`, `rtalb`, `konya`, `ttrak`). Python dict'te son değer kazanır.  
**Düzeltme:** Duplicate'leri kaldır.

---

## 3. DATA LEAKAGE (GELECEK VERİ SIZINTISI)

### 3.1 [KRİTİK] Label Generator Forward Return — Doğru Ama Dikkatli Olunmalı

**Dosya:** `services/labels/generator.py`  
**Satır:** ~50-70  
**Kod:**
```python
for period in self.FORWARD_PERIODS:
    forward_ret = np.full(n, np.nan)
    for i in range(n - period):
        if mask[i] == 1 and mask[i + period] == 1 and close[i] > 0 and close[i + period] > 0:
            forward_ret[i] = (close[i + period] / close[i] - 1) * 100
    labels[f"y_{period}d"] = forward_ret
```

**Sorun:** Forward return hesaplama doğru yapılıyor (gelecek fiyat bugünkü fiyatla karşılaştırılıyor). AMA bu label'lar training'de feature'larla birlikte kullanılırsa data leakage olur.  
**Etki:** Model gelecek fiyatı "görür" → backtest sonuçları gerçek performansı göstermez.  
**Düzeltme:** Label'lar sadece training target olarak kullanılmalı, feature olarak ASLA kullanılmamalı. Bu kuralı `feature_contract.py`'de zorla.

---

### 3.2 [KRİTİK] Data Adapter PIT Kontrolü Karmaşık

**Dosya:** `services/features/data_adapter.py`  
**Satır:** ~120-150  
**Kod:**
```python
# Point-in-time kontrolü
# KRİTİK: fetch_date, verinin ÇEKİLME tarihidir, yayınlanma tarihi değil.
# yfinance gibi real-time kaynaklarda fetch_date her zaman "şimdi"dir.
# PIT kontrolü sadece "published_date" veya "report_date" varsa uygulanır.
pub_date = raw.get("publication_date", "") or raw.get("report_date", "")
if as_of_date and pub_date:
    pub_day = pub_date[:10]
    if pub_day > as_of_date:
        return self._empty_fundamental(ticker, "future_data_blocked")
```

**Sorun:** PIT kontrolü sadece `publication_date` veya `report_date` varsa yapılıyor. yfinance'dan gelen verilerde bu alanlar genellikle boş → PIT kontrolü atlanıyor.  
**Etki:** Backtest'te gelecek fundamental veri kullanılabilir (örn: gelecek çeyrek bilançosu).  
**Düzeltme:** yfinance verisi için de PIT kontrolü ekle (fetch_date > as_of_date ise reddet).

---

### 3.3 [YÜKSEK] Fundamental Freshness Check Ters Mantık

**Dosya:** `services/features/data_adapter.py`  
**Satır:** ~180-200  
**Kod:**
```python
def _check_fundamental_freshness(self, fetch_ts, as_of_date):
    ...
    d_fetch = datetime.strptime(fetch_day, "%Y-%m-%d")
    d_ref = datetime.strptime(as_of_date, "%Y-%m-%d")
    age_days = (d_ref - d_fetch).days

    if age_days < 0:
        # Gelecek tarihli fetch — STALE (kullanılabilir ama güven düşük)
        return FeatureStatus.STALE  # ← GELECEK VERİ STALE OLMAMALI, MISSING OLMALI!
```

**Sorun:** `age_days < 0` → veri gelecekte çekilmiş. Bu durumda STALE döndürüyor ama MISSING döndürmeli.  
**Etki:** Backtest'te gelecek tarihli veri "kullanılabilir" olarak işaretleniyor.  
**Düzeltme:** `return FeatureStatus.MISSING` olarak değiştir.

---

### 3.4 [ORTA] Catalyst Event Date Tahmini

**Dosya:** `services/data/ingestion_pipeline.py`  
**Satır:** ~180-190  
**Kod:**
```python
# Event date: published_at + 30 gün (tahmini)
try:
    pub_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    event_dt = pub_dt + timedelta(days=30)
    event_date = event_dt.strftime("%Y-%m-%d")
except (ValueError, TypeError):
    event_date = published_at[:10]
```

**Sorun:** Catalyst event date'i publication date + 30 gün olarak tahmin ediliyor. Gerçek event date bilinmiyor.  
**Etki:** Yanlış `days_until` hesaplaması → catalyst feature'ları yanlış.  
**Düzeltme:** KAP'tan gerçek event date'i çek (ex-date, record-date gibi).

---

## 4. MISSING DATA HANDLING

### 4.1 [KRİTİK] Feature Calculator 0 Döndürüyor (None Yerine)

**Dosya:** `services/features/calculator.py`  
**Satır:** ~200-300 (çeşitli metodlar)  
**Kod:**
```python
def _sma_masked(self, data, period):
    valid = data[~np.isnan(data)]
    if len(valid) < period:
        return valid[-1] if len(valid) > 0 else 0  # ← 0 döndürüyor


def _roc_masked(self, data, period):
    valid = data[~np.isnan(data)]
    if len(valid) <= period:
        return 0  # ← 0 döndürüyor


def _volume_zscore_masked(self, volume):
    valid = volume[~np.isnan(volume)]
    if len(valid) < 20:
        return 0  # ← 0 döndürüyor
```

**Sorun:** Yeterli veri yoksa 0 döndürülüyor. 0, "değişim yok" anlamına gelir — bu yanlış bir sinyal.  
**Etki:** Model, veri olmayan hisseleri "değişmeyen" hisseler olarak algılar.  
**Düzeltme:** `None`/`NaN` döndür veya `_enforce_scalar_features` zaten bunları filtreliyor — ama 0'ları filtrelemiyor.

---

### 4.2 [YÜKSEK] YFinance Batch OHLCV Column Name Inconsistency

**Dosya:** `services/ingestion/providers/yfinance_provider.py`  
**Satır:** ~100-120 (fetch_ohlcv) vs ~140-180 (fetch_batch_ohlcv)  
**Kod:**
```python
# fetch_ohlcv — Capitalized columns
df = df.rename(
    columns={
        "Date": "timestamp",
        "Open": "Open",
        "High": "High",
        "Low": "Low",
        "Close": "Close",
        "Volume": "Volume",
    }
)

# fetch_batch_ohlcv — Lowercase columns
col_map = {}
for col in ticker_data.columns:
    cl = col.lower()
    if cl == "date":
        col_map[col] = "timestamp"
    elif cl in ("open", "high", "low", "close", "volume"):
        col_map[col] = cl  # ← lowercase!
```

**Sorun:** `fetch_ohlcv` Capitalized column'lar döndürür (`Open`, `Close`), `fetch_batch_ohlcv` lowercase döndürür (`open`, `close`).  
**Etki:** `FeatureCalculator` `df["Close"]` bekler ama batch'ten gelen veride `df["close"]` var → KeyError.  
**Düzeltme:** Tutarlı column naming kullan (hepsi lowercase veya hepsi capitalized).

---

### 4.3 [YÜKSEK] YFinance fetch_ohlcv Pandas vs Polars

**Dosya:** `services/ingestion/providers/yfinance_provider.py`  
**Satır:** ~100 vs ~140  
**Kod:**
```python
# fetch_ohlcv → Pandas DataFrame döndürüyor (yfinance default)
df = df.reset_index()
return df[["Ticker", "timestamp", "Open", "High", "Low", "Close", "Volume"]]

# fetch_batch_ohlcv → Polars DataFrame döndürüyor
pl_df = pl.from_pandas(ticker_data[required])
results[ticker] = pl_df
```

**Sorun:** Aynı provider farklı formatlarda veri döndürüyor.  
**Etki:** Çağrılar hangi formatı bekleyeceğini bilemez → runtime error.  
**Düzeltme:** Tutarlı format kullan (hepsi Polars veya hepsi Pandas).

---

### 4.4 [YÜKSEK] Data Source Column Name Inconsistency

**Dosya:** `services/data/data_source.py`  
**Satır:** ~150-170 (YahooFinanceSource)  
**Kod:**
```python
def fetch(self, ticker, ...):
    df.columns = [c[0].upper() + c[1:].lower() if c else c for c in df.columns]
    return df
```

**Sorun:** Column name transform `c[0].upper() + c[1:].lower()` → "Open", "High", "Low", "Close", "Volume". Ama "Stock Splits" → "Stock splits" (inconsistent).  
**Düzeltme:** Standart column mapping kullan.

---

### 4.5 [ORTA] Fundamental Provider None Check Eksik

**Dosya:** `services/ingestion/providers/fundamental_provider.py`  
**Satır:** ~60-80  
**Kod:**
```python
async def fetch_fundamentals(self, ticker):
    cached = self._cache.get(ticker)
    if cached:
        cached_time = cached.get("_cached_at", 0)
        if (datetime.now(timezone.utc).timestamp() - cached_time) < self._cache_ttl_seconds:
            return cached
```

**Sorun:** Cache'de `_cached_at` yoksa `0` kullanılır → cache asla expire olmaz (epoch 0'dan beri "taze").  
**Düzeltme:** `_cached_at` yoksa cache'i ignore et.

---

### 4.6 [ORTA] Data Pipeline Column Assumption

**Dosya:** `services/ingestion/data_pipeline.py`  
**Satır:** ~100-110  
**Kod:**
```python
mask = self._tm.compute_mask(
    ticker,
    df["Open"].values,
    df["High"].values,
    df["Low"].values,
    df["Close"].values,
    df["Volume"].values,
)
```

**Sorun:** `df['Open']` gibi Capitalized column'lar bekliyor ama `fetch_batch_ohlcv` lowercase döndürüyor.  
**Etki:** KeyError crash.  
**Düzeltme:** Column name normalization ekle.

---

### 4.7 [ORTA] TCMB EVDS Response Parse

**Dosya:** `services/ingestion/providers/tcmb_provider.py`  
**Satır:** ~55-65  
**Kod:**
```python
async def _make_request(self, series_code, start_date, end_date):
    ...
    resp = await self._client.get_json(url)
    resp.raise_for_status()  # ← get_json dict döndürür, response objesi değil!
    data = resp
```

**Sorun:** `get_json` zaten parse edilmiş JSON döndürür, HTTP response objesi değil. `raise_for_status()` AttributeError fırlatır.  
**Etki:** TCMB verisi hiçbir zaman çekilemez.  
**Düzeltme:** `raise_for_status()` satırını kaldır.

---

### 4.8 [DÜŞÜK] Sentiment Feature Engine Import

**Dosya:** `services/features/calculator.py`  
**Satır:** ~350  
**Kod:**
```python
from services.features.sentiment import SentimentFeatureEngine
```

**Sorun:** Absolute import kullanıyor ama proje yapısına göre relative import olmalı.  
**Düzeltme:** `from .sentiment import SentimentFeatureEngine` kullan.

---

### 4.9 [DÜŞÜK] Macro Feature Import

**Dosya:** `services/features/calculator.py`  
**Satır:** ~360  
**Kod:**
```python
from services.features.macro import compute_all_macro_features
```

**Sorun:** Aynı sorun — absolute import.  
**Düzeltme:** Relative import kullan.

---

### 4.10 [DÜŞÜK] Cross-Sectional Import

**Dosya:** `services/features/calculator.py`  
**Satır:** ~380  
**Kod:**
```python
from services.features.cross_sectional import cross_sectional_engine
```

**Sorun:** Aynı sorun.  
**Düzeltme:** Relative import kullan.

---

## 5. DATA TYPE MISMATCHES

### 5.1 [KRİTİK] YFinance Polars vs Pandas Çatışması

**Dosya:** `services/ingestion/providers/yfinance_provider.py`  
**Satır:** ~100 vs ~140  

**Sorun:** `fetch_ohlcv` Pandas DataFrame, `fetch_batch_ohlcv` Polars DataFrame döndürüyor. Feature calculator Pandas bekliyor.  
**Etki:** Polars DataFrame ile `df["Close"].values` çağırmak farklı sonuç verir veya hata fırlatır.  
**Düzeltme:** Tüm pipeline'da tek format kullan.

---

### 5.2 [YÜKSEK] String/Float Karışıklığı — TCMB Verisi

**Dosya:** `services/ingestion/providers/tcmb_provider.py`  
**Satır:** ~60  
**Kod:**
```python
items = data.get("items", [])
if items:
    latest = items[-1]
    return name, {
        "value": latest.get("value"),  # ← String olabilir!
```

**Sorun:** TCMB EVDS API'si değerleri string olarak döndürebilir. `float()` dönüşümü yapılmıyor.  
**Etki:** Feature hesaplamasında string * float → TypeError.  
**Düzeltme:** `float(latest.get("value", 0))` kullan.

---

### 5.3 [YÜKSEK] FRED Verisi Float Dönüşümü

**Dosya:** `services/ingestion/providers/macro_provider.py`  
**Satır:** ~130  
**Kod:**
```python
"value": float(latest.get("value", 0)),
```

**Sorun:** FRED API'si `"."` (nokta) string'i döndürebilir (veri yoksa). `float(".")` → ValueError.  
**Düzeltme:** Try/except ile float dönüşümü yap.

---

### 5.4 [ORTA] KAP Sentiment Float Precision

**Dosya:** `services/ingestion/providers/kap_provider.py`  
**Satır:** ~140  
**Kod:**
```python
return round((pos - neg) / total, 3)
```

**Sorun:** `pos` ve `neg` integer, `total` integer → Python 2'de integer division, Python 3'de float division. Proje Python 3 kullanıyor ama dikkatli olunmalı.  
**Düzeltme:** `round((pos - neg) / float(total), 3)` kullan (garanti için).

---

## 6. TIMEZONE ISSUES

### 6.1 [YÜKSEK] YFinance Timestamp Timezone Belirsiz

**Dosya:** `services/ingestion/providers/yfinance_provider.py`  
**Satır:** ~80  
**Kod:**
```python
"timestamp": datetime.now(timezone.utc).isoformat(),
```

**Sorun:** Timestamp "şimdi" (UTC) olarak ayarlanıyor ama yfinance verisi market saat diliminde (UTC+3 İstanbul).  
**Etki:** PIT kontrolünde timezone farkı nedeniyle veri "gelecekte" görünebilir.  
**Düzeltme:** Timestamp'i yfinance'dan gelen veri timestamp'i ile eşle.

---

### 6.2 [YÜKSEK] TCMB Tarih Formatı Non-Standard

**Dosya:** `services/ingestion/providers/tcmb_provider.py`  
**Satır:** ~75  
**Kod:**
```python
end_date = datetime.now().strftime("%d-%m-%Y")
start_date = (datetime.now() - timedelta(days=days)).strftime("%d-%m-%Y")
```

**Sorun:** TCMB EVDS API'si `dd-mm-YYYY` formatı bekliyor ama bu format Türkiye'ye özgü. API değişirse format değişebilir.  
**Düzeltme:** API dokümanına göre formatı doğrula.

---

### 6.3 [ORTA] BIST Provider Timestamp UTC

**Dosya:** `services/ingestion/providers/bist_provider.py`  
**Satır:** ~75  
**Kod:**
```python
"timestamp": datetime.now(timezone.utc).isoformat(),
```

**Sorun:** BIST verisi İstanbul saatinde ama timestamp UTC.  
**Düzeltme:** BIST verisi için `timezone(timedelta(hours=3))` kullan.

---

### 6.4 [ORTA] News Date Parse RFC 2822

**Dosya:** `services/features/data_adapter.py`  
**Satır:** ~540  
**Kod:**
```python
from email.utils import parsedate_to_datetime

dt = parsedate_to_datetime(raw_date)
return dt.strftime("%Y-%m-%d")
```

**Sorun:** RFC 2822 parse doğru ama timezone bilgisi kayboluyor (sadece tarih alınıyor).  
**Düzeltme:** Gerekirse timezone bilgisini de koru.

---

### 6.5 [DÜŞÜK] Reddit Timestamp

**Dosya:** `services/ingestion/providers/social_provider.py`  
**Satır:** ~200  
**Kod:**
```python
"created_at": datetime.fromtimestamp(
    post_data.get("created_utc", 0), tz=timezone.utc
).isoformat(),
```

**Sorun:** `created_utc` 0 ise epoch (1970-01-01) döner.  
**Düzeltme:** 0 kontrolü ekle.

---

## 7. DEDUPLICATION

### 7.1 [YÜKSEK] Realtime Engine Hash Truncation

**Dosya:** `services/ingestion/providers/realtime_provider.py`  
**Satır:** ~60  
**Kod:**
```python
def _is_new(self, event: DataEvent) -> bool:
    if event.content_hash in self._seen_hashes:
        return False
    self._seen_hashes.add(event.content_hash)
    if len(self._seen_hashes) > 50000:
        self._seen_hashes = set(list(self._seen_hashes)[-25000:])
    return True
```

**Sorun:** 50.000 hash'e ulaşınca son 25.000 tutuluyor. İlk 25.000 hash siliniyor → bu veriler tekrar "yeni" olarak görünebilir.  
**Etki:** Duplicate event'ler tekrar işlenebilir.  
**Düzeltme:** LRU cache kullan (time-based eviction).

---

### 7.2 [ORTA] Deduplication Cleanup Periyodu

**Dosya:** `services/ingestion/deduplication.py`  
**Satır:** ~80  
**Kod:**
```python
def _cleanup_if_needed(self):
    if self._stats.total_checked % 100 != 0:
        return
```

**Sorun:** Cleanup sadece her 100 kontrolde bir yapılıyor. Düşük trafikte eski hash'ler çok uzun süre kalır.  
**Düzeltme:** Time-based cleanup ekle (her 5 dakikada bir).

---

### 7.3 [ORTA] Event Dedup Hash Collision

**Dosya:** `services/ingestion/deduplication.py`  
**Satır:** ~35  
**Kod:**
```python
def _compute_hash(self, event_data):
    key_parts = [
        str(event_data.get("event_type", "")),
        str(event_data.get("source", "")),
        str(event_data.get("ticker", "")),
        str(event_data.get("price", "")),
        str(event_data.get("timestamp", "")),
        str(event_data.get("kap_id", "")),
        str(event_data.get("social_id", "")),
    ]
    key = "|".join(key_parts)
    return hashlib.md5(key.encode("utf-8")).hexdigest()
```

**Sorun:** MD5 hash collision riski düşük ama var. Ayrıca `price` ve `timestamp` string olarak join ediliyor — floating point precision farkı farklı hash üretebilir.  
**Düzeltme:** Price'ı round et (2 decimal) önce.

---

### 7.4 [DÜŞÜK] Seen URLs Memory Limit

**Dosya:** `services/ingestion/providers/realtime_provider.py`  
**Satır:** ~160  
**Kod:**
```python
if len(seen_urls) > 10000:
    seen_urls = set(list(seen_urls)[-5000:])
```

**Sorun:** Aynı truncation sorunu.  
**Düzeltme:** LRU cache kullan.

---

## 8. DATA VALIDATION

### 8.1 [KRİTİK] Data Validator Sadece Fiyat Doğruluyor

**Dosya:** `services/ingestion/providers/data_validator.py`  
**Satır:** ~30-80  
**Kod:**
```python
class DataValidator:
    def validate_price(self, ticker, prices): ...
```

**Sorun:** Sadece fiyat doğrulaması var. Volume, OHLC tutarlılığı (High >= Low, Close aralığı), timestamp doğrulaması yok.  
**Etki:** High < Low olan veri pipeline'a girer. Volume=0 olan günler feature hesaplamasına katılır.  
**Düzeltme:** Aşağıdaki kontrolleri ekle:
- `High >= Low`
- `Low <= Close <= High`
- `Volume >= 0`
- `Open > 0`
- Timestamp artan sırada

---

### 8.2 [YÜKSEK] Feature Contract Validation Yetersiz

**Dosya:** `services/features/pipeline.py`  
**Satır:** ~250-280  
**Kod:**
```python
def _validate_contract(self, features, ticker):
    for name, value in features.items():
        if not isinstance(value, (int, float)):
            invalid.append(name)
            continue
        if value != value:  # NaN
            invalid.append(name)
            continue
        if value == float("inf") or value == float("-inf"):
            invalid.append(name)
            continue
        if abs(value) > 1e12:
            warnings.append(...)
```

**Sorun:** Range validation çok geniş (`1e12`). RSI 0-100 aralığında olmalı, ATR pozitif olmalı, volume negatif olmamalı — bu kontroller yok.  
**Düzeltme:** Feature-specific range validation ekle.

---

### 8.3 [YÜKSEK] OHLCV Veri Tutarlılık Kontrolü Yok

**Dosya:** `services/ingestion/providers/yfinance_provider.py`  
**Satır:** Genel  

**Sorun:** yfinance'dan gelen veri için OHLCV tutarlılık kontrolü yapılmıyor:
- `High >= Low` kontrolü yok
- `Close` aralık dışı olabilir
- `Volume` negatif olabilir (corporate actions)
- `Open` 0 olabilir (halted stock)

**Düzeltme:** `data_validator.py`'ye OHLCV validation ekle.

---

### 8.4 [ORTA] Alternative Data Quality Validator Yetersiz

**Dosya:** `services/alternative/base.py`  
**Satır:** ~120-180  
**Kod:**
```python
class DataQualityValidator:
    def validate(self, data, source, expected_fields, max_age_hours):
        # 4. Zero-value check
        numeric_values = [v for v in data.values() if isinstance(v, (int, float))]
        if numeric_values and all(v == 0 for v in numeric_values):
            issues.append("All numeric values are zero")
```

**Sorun:** "All zeros" kontrolü var ama tek tek alan kontrolü yok. `google_trends_score=0` geçerli olabilir ama `cc_spend_growth=0` şüpheli.  
**Düzeltme:** Alan-specific validation ekle.

---

### 8.5 [ORTA] BIST Universe Cache Doğrulama Yok

**Dosya:** `data/bist_universe_cache.json`  

**Sorun:** Cache dosyası var ama ne zaman güncellendiği, ne kadar geçerli olduğu bilinmiyor.  
**Düzeltme:** Cache'e `updated_at` ve `valid_until` alanları ekle.

---

### 8.6 [ORTA] System Snapshot Doğrulama Yok

**Dosya:** `data/system_snapshot.json`  

**Sorun:** Snapshot'ta `total_predictions: 101`, `total_resolved: 0`, `overall_accuracy: 0`. 101 tahmin yapılmış ama hiçbiri resolve edilmemiş.  
**Etki:** Learning pipeline çalışmıyor olabilir.  
**Düzeltme:** Outcome tracker'ın çalıştığını doğrula.

---

### 8.7 [DÜŞÜK] Learning State Validation

**Dosya:** `data/learning_state.json`  

**Sorun:** Prediction'larda `outcome: null` ve `resolved: false`. Feature snapshot'lar var ama outcome tracking eksik.  
**Düzeltme:** Outcome tracking mekanizmasını doğrula.

---

## 9. CACHE INVALIDATION

### 9.1 [YÜKSEK] Fundamental Provider Cache TTL Sabit

**Dosya:** `services/ingestion/providers/fundamental_provider.py`  
**Satır:** ~25  
**Kod:**
```python
self._cache_ttl_seconds = 3600  # 1 saat cache
```

**Sorun:** Cache TTL 1 saat. Bilanço sezonunda veri daha sık güncellenir, normal zamanda 1 saat yeterli. Sabit TTL her iki durumda da optimal değil.  
**Düzeltme:** Dinamik TTL (bilanço sezonunda daha kısa, normal zamanda daha uzun).

---

### 9.2 [YÜKSEK] Data Source Cache TTL 24 Saat

**Dosya:** `services/data/data_source.py`  
**Satır:** ~20  
**Kod:**
```python
cache_ttl_hours: int = (24,)
```

**Sorun:** 24 saat cache. Intraday trading'de bu çok uzun.  
**Düzeltme:** Interval'e göre TTL ayarla (1d → 24 saat, 1m → 1 dakika).

---

### 9.3 [ORTA] Alternative Feature Engine Cache

**Dosya:** `services/alternative/feature_engine.py`  
**Satır:** ~60  
**Kod:**
```python
cache_key = f"{ticker}:{','.join(sorted(sources or []))}"
if cache_key in self._feature_cache:
    return self._feature_cache[cache_key]
```

**Sorun:** Cache TTL yok. Feature'lar bir kez hesaplandıktan sonra session boyunca cache'de kalır.  
**Düzeltme:** TTL ekle (örn: 1 saat).

---

### 9.4 [ORTA] Base Adapter Cache TTL

**Dosya:** `services/alternative/base.py`  
**Satır:** ~200  
**Kod:**
```python
def _set_cached(self, key, value, ttl_seconds=3600):
    self._cache[key] = value
    self._cache_ttl[key] = time.time() + ttl_seconds
```

**Sorun:** TTL 1 saat (default). Tüm adapter'lar aynı TTL'i kullanıyor ama bazı veriler daha sık güncellenmeli (sosyal medya → 10 dakika, BKM → 1 ay).  
**Düzeltme:** Her adapter için farklı TTL tanımla.

---

### 9.5 [DÜŞÜK] LLM Sentiment Cache

**Dosya:** `services/alternative/llm_sentiment.py`  
**Satır:** ~60  
**Kod:**
```python
self._cache[cache_key] = result
if len(self._cache) > 1000:
    keys = list(self._cache.keys())
    for k in keys[:500]:
        del self._cache[k]
```

**Sorun:** Cache boyut limiti var ama TTL yok. 1000 entry'ye ulaşınca ilk 500 siliniyor (FIFO).  
**Düzeltme:** TTL-based eviction kullan.

---

## 10. RETRY LOGIC

### 10.1 [YÜKSEK] TCMB Async/Sync Karışımı

**Dosya:** `services/ingestion/providers/tcmb_provider.py`  
**Satır:** ~95-110  
**Kod:**
```python
async def fetch_all_macro(self) -> Dict[str, Any]:
    for name, series in self.SERIES.items():
        data = self._make_request(series, start_date, end_date)  # ← await yok!
```

**Sorun:** `_make_request` async ama `await` olmadan çağrılıyor. Retry logic çalışmaz çünkü coroutine execute edilmiyor.  
**Düzeltme:** `await self._make_request(...)`.

---

### 10.2 [ORTA] Retry Policy Max Delay Çok Düşük

**Dosya:** `services/ingestion/retry_policy.py`  
**Satır:** ~150  
**Kod:**
```python
BIST_RETRY_POLICIES = {
    "yfinance": RetryPolicy(max_attempts=3, base_delay_s=1.0, max_delay_s=15.0),
    "kap": RetryPolicy(max_attempts=3, base_delay_s=2.0, max_delay_s=30.0),
    ...
}
```

**Sorun:** 429 (rate limit) durumunda 15-30 saniye yeterli olmayabilir. API'ler bazen 60+ saniye bekler.  
**Düzeltme:** 429 durumunda `Retry-After` header'ını oku veya max_delay'i 60 saniyeye çıkar.

---

### 10.3 [DÜŞÜK] Retry Stats Thread Safety

**Dosya:** `services/ingestion/retry_policy.py`  
**Satır:** ~100  
**Kod:**
```python
self.stats.total_calls += 1
self.stats.total_retries += 1
```

**Sorun:** Stats güncelleme thread-safe değil. Concurrent kullanımda stats yanlış olabilir.  
**Düzeltme:** `threading.Lock` kullan veya atomic operations.

---

## 11. EK SORUNLAR

### 11.1 [YÜKSEK] Duplicate Import

**Dosya:** `services/ingestion/providers/tcmb_provider.py`  
**Satır:** ~5  
**Kod:**
```python
import structlog
from ...core.async_http import get_client
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import structlog  # ← Duplicate!
```

**Sorun:** `structlog` iki kez import edilmiş.  
**Düzeltme:** İkinci import'u kaldır.

---

### 11.2 [ORTA] News Provider Duplicate Key'ler

**Dosya:** `services/ingestion/providers/news_provider.py`  
**Satır:** ~20-120  
**Kod:**
```python
COMPANY_NAME_MAP = {
    ...
    "quagr": "Qua Granite",  # ← 2. kez tanımlanmış
    "rtalb": "Rotal Yatirim",  # ← 2. kez tanımlanmış
    "konya": "Konya Cimento",  # ← 2. kez tanımlanmış
    "ttrak": "Turk Traktor",  # ← 2. kez tanımlanmış
    ...
}
```

**Sorun:** 4 duplicate key. Python dict'te son değer kazanır ama bu muhtemelen kasıtsız.  
**Düzeltme:** Duplicate'leri kaldır.

---

### 11.3 [ORTA] BIST Universe Cache vs Data Source Universe Farkı

**Dosya:** `data/bist_universe_cache.json` vs `services/data/data_source.py`  

**Sorun:** `bist_universe_cache.json` 100+ ticker içeriyor ama `data_source.py`'deki `get_bist100_universe()` sadece 20 ticker döndürüyor.  
**Etki:** Pipeline sadece 20 hisse üzerinde çalışıyor.  
**Düzeltme:** `get_bist100_universe()` cache dosyasını okusun.

---

### 11.4 [DÜŞÜK] Feature Store Auto-Registration

**Dosya:** `services/alternative/feature_store.py`  
**Satır:** ~80  
**Kod:**
```python
for name, value in features.items():
    if name not in self._manifests:
        self.register_feature(
            FeatureManifest(
                feature_name=name,
                version="v1",
                source=source,
                description=f"Auto-registered from {source}",
                dtype="float",
                range_min=-100,
                range_max=100,
            )
        )
```

**Sorun:** Feature'lar otomatik olarak `range_min=-100, range_max=100` ile kaydediliyor. Bu aralık birçok feature için yanlış (örn: `market_cap` milyarlarca olabilir).  
**Düzeltme:** Feature-specific range tanımla veya auto-registration'da range tahmin et.

---

## 12. ÖNERİLEN DÜZELTMELER (Öncelik Sırasına Göre)

### Acil (KRİTİK)
1. **TCMB async/await fix** — `tcmb_provider.py` satır ~100
2. **TCMB BIST-100 series fix** — `tcmb_provider.py` satır ~30
3. **BIST-100 universe fix** — `data_source.py` satır ~105
4. **YFinance column name consistency** — `yfinance_provider.py`
5. **PIT control for yfinance data** — `data_adapter.py` satır ~120
6. **Fundamental freshness future data** — `data_adapter.py` satır ~180
7. **Feature calculator None vs 0** — `calculator.py` tüm helper metodlar
8. **OHLCV validation** — `data_validator.py`
9. **Macro provider zero fallback** — `yfinance_provider.py`, `macro_provider.py`

### Yüksek
10. **Column name standardization** — tüm provider'lar
11. **Polars vs Pandas standardization** — `yfinance_provider.py`
12. **Sentiment keyword expansion** — tüm sentiment modülleri
13. **Dynamic cache TTL** — tüm cache'ler
14. **Range validation** — `pipeline.py`
15. **Duplicate key cleanup** — `news_provider.py`

### Orta
16. **Negation handling** — sentiment modülleri
17. **Sector-relative scoring** — `historical_adapter.py`
18. **Time-based dedup cleanup** — `deduplication.py`
19. **Feature store persistence** — `feature_store.py`
20. **Retry-After header** — `retry_policy.py`

### Düşük
21. **Relative imports** — `calculator.py`
22. **Thread-safe stats** — `retry_policy.py`
23. **Silent error logging** — `realtime_provider.py`
24. **Feature manifest range** — `feature_store.py`

---

## 13. VERİ AKIŞ DİYAGRAMI (Sorunlu Noktalar)

```
┌─────────────────────────────────────────────────────────────────┐
│                    VERİ KAYNAKLARI                               │
├──────────┬──────────┬──────────┬──────────┬──────────┬──────────┤
│ yfinance │   KAP    │   BIST   │  TCMB    │  News    │  Social  │
│ ✅/⚠️    │   ✅     │   ⚠️    │  ❌      │   ⚠️    │   ⚠️    │
│ Column   │ Async   │ API      │ Async/   │ RSS      │ Keyword  │
│ name     │ OK      │ untested │ await    │ fallback │ sentiment│
│ mismatch │         │          │ broken   │ hardcoded│ weak     │
├──────────┴──────────┴──────────┴──────────┴──────────┴──────────┤
│                    INGESTION PIPELINE                            │
│  ✅ Retry Policy    ✅ Circuit Breaker    ⚠️ Dedup truncation   │
│  ✅ Rate Limiter    ✅ PIT Validator      ❌ OHLCV validation   │
├─────────────────────────────────────────────────────────────────┤
│                    FEATURE PIPELINE                              │
│  ⚠️ Calculator: 0 instead of None    ⚠️ Hardcoded thresholds   │
│  ⚠️ Column name assumptions          ✅ Mask-aware design       │
│  ✅ Contract validation              ⚠️ Range validation weak   │
├─────────────────────────────────────────────────────────────────┤
│                    ALTERNATIVE DATA                              │
│  ⚠️ All adapters: 0 on no data       ⚠️ Keyword sentiment weak │
│  ✅ Circuit breaker                   ✅ Rate limiter            │
│  ⚠️ Feature store in-memory only      ⚠️ Cache no TTL          │
├─────────────────────────────────────────────────────────────────┤
│                    LABEL GENERATION                              │
│  ✅ Forward returns correct           ⚠️ No leakage guard       │
│  ✅ Cross-sectional ranks             ✅ Mask-aware              │
└─────────────────────────────────────────────────────────────────┘

Legend: ✅ İyi  ⚠️ Sorunlu  ❌ Kırık
```

---

**Rapor Sonu**  
**Toplam Bulgu:** 64 (9 Kritik, 21 Yüksek, 23 Orta, 11 Düşük)
