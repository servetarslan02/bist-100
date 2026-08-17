# Ingestion Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** Apache Kafka Architecture (Instaclustr 2025), Event-Driven Architecture Patterns (Solace), Jane Street Data Engineer Guide (2026), Reddit AlgoTrading Best Practices (2025), arXiv Look-Ahead Bias Mitigation (2026), S&P DJI Corporate Actions Methodology

---

## 1. Mevcut Durum (Kod Analizi)

### Modüller (21 dosya, toplam 5,278 satır)

| Modül | Satır | Class | Fonksiyon | Durum |
|-------|-------|-------|-----------|-------|
| `universe_provider.py` | 806 | 5 | 38 | ✅ En büyük — KAP, yfinance, BIST web |
| `main.py` | 428 | 1 | 1 | ⚠️ Ingestion service |
| `corporate_actions.py` | 350 | 3 | 13 | ✅ Temettü, bölünme, bedelsiz |
| `realtime_provider.py` | 319 | 2 | 4 | ✅ Gerçek zamanlı veri |
| `bist_universe.py` | 309 | 2 | 17 | ✅ BIST evreni |
| `fundamental_provider.py` | 293 | 1 | 8 | ✅ Bilanço verisi |
| `yfinance_provider.py` | 264 | 1 | 9 | ✅ OHLCV verisi |
| `bist_stream.py` | 261 | 2 | 3 | ✅ BIST streaming |
| `news_provider.py` | 258 | 1 | 3 | ✅ RSS haber |
| `data_pipeline.py` | 204 | 3 | 8 | ⚠️ Pipeline |
| `universe_enhancements.py` | 204 | 5 | 10 | ✅ Evren geliştirmeleri |
| `data_validator.py` | 183 | 2 | 5 | ✅ Veri doğrulama |
| `macro_provider.py` | 139 | 1 | 1 | ⚠️ Basit |
| `provider_manager.py` | 131 | 3 | 3 | ⚠️ Basit |
| `social_provider.py` | 130 | 1 | 1 | ⚠️ Basit |
| `news_credibility.py` | 124 | 2 | 5 | ✅ Kaynak güvenilirliği |
| `kap_provider.py` | 111 | 1 | 1 | ⚠️ Basit |
| `tcmb_provider.py` | 104 | 1 | 1 | ⚠️ Basit |
| `bist_provider.py` | 87 | 1 | 2 | ⚠️ Basit |
| `matriks_provider.py` | 62 | 1 | 1 | ⚠️ Basit |
| `realtime.py` | 142 | 1 | 5 | ✅ Gerçek zamanlı |

### Sorunlar

1. **provider_manager.py**: Basit priority sistemi — failover otomatik değil
2. **data_validator.py**: Tek fiyat doğrulama — cross-source reconciliation yok
3. **kap_provider.py**: Tek fonksiyon — tüm KAP verisi çekme yok
4. **social_provider.py**: Sadece X/Twitter — Ekşi, Reddit yok
5. **tcmb_provider.py**: Basit API çağrısı — EVDS entegrasyonu eksik
6. **macro_provider.py**: Basit — detaylı makro veri yok
7. **main.py**: 428 satır ama 1 fonksiyon — monolitik
8. **Point-in-time validation** yok — data leakage riski
9. **Corporate actions adjustment** otomatik değil
10. **Rate limiting** yok — API limit aşılabilir
11. **Circuit breaker** yok — provider çökünce sistem durabilir
12. **Retry policy** yok — geçici hatalarda yeniden deneme yok

---

## 2. Data Ingestion Nedir? (Araştırma Bazlı)

### Tanım

Data ingestion, dış kaynaklardan veriyi toplama, doğrulama, dönüştürme ve saklama sürecidir. Trading sisteminde:

- **Market data**: OHLCV, bid/ask, volume → fiyat analizi
- **Fundamental data**: Bilanço, gelir tablosu → şirket analizi
- **News/KAP**: Haberler, şirket açıklamaları → event analizi
- **Macro data**: Faiz, enflasyon, döviz → makro analizi
- **Social data**: Sosyal medya → sentiment analizi

### Temel Prensipler (Araştırma Bazlı)

| Prensipler | Açıklama | Kaynak |
|------------|----------|--------|
| **Failover** | Bir provider çökünce diğerine geç | Kafka Architecture |
| **Idempotency** | Aynı veri iki kez işlenmesin | Event-Driven Patterns |
| **Point-in-time** | O anda bilinen veriyi kullan | Look-Ahead Bias (arXiv) |
| **Rate limiting** | API limit aşılmasın | Best Practices |
| **Circuit breaker** | Sürekli hata veren provider'ı durdur | Resilience Patterns |
| **Retry with backoff** | Geçici hatalarda tekrar dene | Error Handling |
| **Data quality gate** | Hatalı veriyi sisteme sokma | Data Quality |
| **Corporate actions** | Bölünme, temettü düzeltmesi | S&P DJI Methodology |

---

## 3. Nihai Ingestion Mimarisi

### 3.1 Data Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                    DATA SOURCES                              │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│ Market   │Fundament.│ News/KAP │  Macro   │ Social          │
│ yfinance │ yfinance │ RSS/API  │ TCMB/EVDS│ X/Ekşi/Reddit  │
│ BIST     │ KAP      │ KAP API  │ TÜİK    │ Investing.com   │
│ Matriks  │          │ Bloomberg│          │                 │
└────┬─────┴────┬─────┴────┬─────┴────┬─────┴─────┬───────────┘
     │          │          │          │           │
     └──────────┴──────────┴──────────┴───────────┘
                         │
                    ┌────┴────┐
                    │PROVIDER │  Her kaynak için adapter
                    │MANAGER  │  Priority + failover
                    └────┬────┘
                         │
                    ┌────┴────┐
                    │  RATE   │  API limit kontrolü
                    │ LIMITER │  Exponential backoff
                    └────┬────┘
                         │
                    ┌────┴────┐
                    │ CIRCUIT │  Provider sağlık kontrolü
                    │ BREAKER │  CLOSED → OPEN → HALF_OPEN
                    └────┬────┘
                         │
                    ┌────┴────┐
                    │  RETRY  │  Geçici hatalar için
                    │ POLICY  │  1s → 2s → 4s → 8s
                    └────┬────┘
                         │
                    ┌────┴────┐
                    │VALIDATOR│  Veri doğrulama
                    │         │  Fiyat, hacim, tarih
                    └────┬────┘
                         │
                    ┌────┴────┐
                    │RECONCIL.│  Cross-source doğrulama
                    │         │  Kaynaklar arası tutarlılık
                    └────┬────┘
                         │
                    ┌────┴────┐
                    │CORPORATE│  Bölünme, temettü
                    │ ACTIONS │  Fiyat düzeltmesi
                    └────┬────┘
                         │
                    ┌────┬────┐
                    │  STORE │  Database'e yaz
                    │        │  Event publish
                    └────────┘
```

### 3.2 Provider Manager (Nihai)

```python
class ProviderManager:
    """Provider yönetimi — failover, priority, health."""
    
    def __init__(self):
        self._providers = {}  # data_type → [(name, func, priority, health)]
        self._circuit_breakers = {}  # name → CircuitBreaker
    
    def register(self, data_type: str, name: str, func: Callable, priority: int = 0):
        """Provider kaydet."""
        if data_type not in self._providers:
            self._providers[data_type] = []
        self._providers[data_type].append({
            "name": name,
            "func": func,
            "priority": priority,
            "health": ProviderHealth(),
        })
        self._circuit_breakers[name] = CircuitBreaker(name=name)
    
    async def fetch(self, data_type: str, *args, **kwargs) -> ProviderResult:
        """Veri çek — priority sırasıyla dene."""
        providers = sorted(self._providers.get(data_type, []), key=lambda p: p["priority"])
        
        for provider in providers:
            cb = self._circuit_breakers[provider["name"]]
            
            # Circuit breaker kontrolü
            if cb.state == CircuitState.OPEN:
                logger.warning("Provider circuit open", provider=provider["name"])
                continue
            
            try:
                result = await asyncio.wait_for(provider["func"](*args, **kwargs), timeout=30)
                if result is not None:
                    cb.record_success()
                    return ProviderResult(
                        success=True,
                        data=result,
                        source=provider["name"],
                        latency_ms=0,
                    )
            except asyncio.TimeoutError:
                cb.record_failure()
                logger.warning("Provider timeout", provider=provider["name"])
            except Exception as e:
                cb.record_failure()
                logger.warning("Provider error", provider=provider["name"], error=str(e))
        
        return ProviderResult(success=False, error="All providers failed")
```

### 3.3 Rate Limiter (Nihai)

```python
class RateLimiter:
    """API rate limiting."""
    
    def __init__(self):
        self._limits = {}  # provider → (max_requests, window_seconds)
        self._requests = {}  # provider → [timestamps]
    
    def set_limit(self, provider: str, max_requests: int, window_seconds: int):
        """Rate limit ayarla."""
        self._limits[provider] = (max_requests, window_seconds)
    
    async def acquire(self, provider: str) -> bool:
        """Rate limit kontrolü."""
        if provider not in self._limits:
            return True
        
        max_req, window = self._limits[provider]
        now = time.time()
        
        # Eski istekleri temizle
        if provider in self._requests:
            self._requests[provider] = [t for t in self._requests[provider] if now - t < window]
        else:
            self._requests[provider] = []
        
        # Limit kontrolü
        if len(self._requests[provider]) >= max_req:
            wait_time = window - (now - self._requests[provider][0])
            logger.warning("Rate limit hit", provider=provider, wait=wait_time)
            await asyncio.sleep(wait_time)
        
        self._requests[provider].append(now)
        return True
```

### 3.4 Data Validator (Nihai)

```python
class DataValidator:
    """Veri doğrulama — point-in-time aware."""
    
    def validate_price(self, ticker: str, price: float, timestamp: str, source: str) -> Dict:
        """Fiyat doğrulama."""
        errors = []
        
        # 1. Pozitif kontrolü
        if price <= 0:
            errors.append(f"Invalid price: {price}")
        
        # 2. Mantık kontrolü (high >= low, vb.)
        # 3. Point-in-time kontrolü
        if self._is_future(timestamp):
            errors.append(f"Future data: {timestamp}")
        
        # 4. Kaynak güvenilirliği
        credibility = self._get_source_credibility(source)
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "quality_score": credibility if len(errors) == 0 else 0,
        }
    
    def validate_cross_source(self, prices: Dict[str, float]) -> Dict:
        """Kaynaklar arası doğrulama."""
        if len(prices) < 2:
            return {"conflict": False}
        
        values = list(prices.values())
        mean_price = np.mean(values)
        max_deviation = max(abs(p - mean_price) / mean_price for p in values)
        
        return {
            "conflict": max_deviation > 0.02,  # %2 sapma
            "max_deviation": round(max_deviation, 4),
            "sources": prices,
        }
```

### 3.5 Corporate Actions (Nihai)

```python
class CorporateActionsHandler:
    """Şirket olayları — fiyat düzeltmesi."""
    
    # Desteklenen olaylar
    ACTION_TYPES = [
        "DIVIDEND",           # Temettü
        "STOCK_SPLIT",        # Bölünme
        "BONUS_ISSUE",        # Bedelsiz sermaye artırımı
        "RIGHTS_ISSUE",       # Rüçhan hakkı
        "MERGER",             # Birleşme
        "ACQUISITION",        # Devralma
        "DELISTING",          # Borsadan çıkma
        "NAME_CHANGE",        # İsim değişikliği
    ]
    
    def adjust_price(self, ticker: str, price: float, action: CorporateAction) -> float:
        """Fiyat düzeltmesi."""
        if action.action_type == ActionType.DIVIDEND:
            # Temettü düşürülmesi
            return price - action.dividend_amount
        elif action.action_type == ActionType.STOCK_SPLIT:
            # Bölünme düzeltmesi
            return price / action.split_ratio
        elif action.action_type == ActionType.BONUS_ISSUE:
            # Bedelsiz düzeltmesi
            return price * (1 / (1 + action.bonus_ratio))
        return price
    
    def adjust_position(self, ticker: str, quantity: int, action: CorporateAction) -> int:
        """Pozisyon düzeltmesi."""
        if action.action_type == ActionType.STOCK_SPLIT:
            return int(quantity * action.split_ratio)
        elif action.action_type == ActionType.BONUS_ISSUE:
            return int(quantity * (1 + action.bonus_ratio))
        return quantity
```

---

## 4. Provider Detayları (Nihai)

### 4.1 Market Data Providers

| Provider | Veri | Frekans | Güvenilirlik | Failover |
|----------|------|---------|-------------|----------|
| **yfinance** | OHLCV, indeksler | Günlük | Yüksek | BIST, Matriks |
| **BIST** | Gerçek zamanlı | Tick | Yüksek | Matriks |
| **Matriks** | Gerçek zamanlı | Tick | Yüksek | BIST |
| **bist_stream** | Streaming | Gerçek zamanlı | Orta | yfinance |

### 4.2 Fundamental Data Providers

| Provider | Veri | Frekans | Güvenilirlik | Failover |
|----------|------|---------|-------------|----------|
| **yfinance** | Bilanço, gelir tablosu | Çeyreklik | Orta | KAP |
| **KAP** | Finansal tablolar | Çeyreklik | Yüksek | yfinance |

### 4.3 News/KAP Providers

| Provider | Veri | Frekans | Güvenilirlik | Failover |
|----------|------|---------|-------------|----------|
| **KAP API** | Şirket açıklamaları | Gerçek zamanlı | En yüksek | RSS |
| **RSS** | Haberler | Gerçek zamanlı | Orta | Web scraping |
| **Bloomberg HT** | Finansal haber | Gerçek zamanlı | Yüksek | RSS |

### 4.4 Macro Providers

| Provider | Veri | Frekans | Güvenilirlik | Failover |
|----------|------|---------|-------------|----------|
| **TCMB EVDS** | Faiz, enflasyon, döviz | Günlük | Yüksek | yfinance |
| **TÜİK** | İstihdam, GSYH | Aylık | Yüksek | TCMB |
| **yfinance** | VIX, S&P500, altın | Günlük | Yüksek | - |

### 4.5 Social Providers

| Provider | Veri | Frekans | Güvenilirlik | Failover |
|----------|------|---------|-------------|----------|
| **X/Twitter** | Sentiment | Gerçek zamanlı | Orta | Ekşi |
| **Ekşi Sözlük** | Sentiment | Saatlik | Orta | X |
| **Investing.com** | Hisse yorumları | Saatlik | Orta | X |

---

## 5. BIST'e Özgü Kurallar

### 5.1 BIST İşlem Saatleri

```
Seans 1: 09:30 - 12:30 (Tek fiyat)
Seans 2: 14:00 - 17:40 (Sürekli işlem)
Kapanış: 17:40 - 18:00 (Kapanış fiyatları)
```

### 5.2 BIST Fiyat Limitleri

```
Normal hisseler: ±%10
Volatil hisseler: ±%5 veya ±%20
İlk seansta limit yok
Devre kesici: ±%5 (gün içi), ±%10 (açılış)
```

### 5.3 BIST Veri Gecikmesi

```
yfinance: 15 dakika gecikmeli
KAP: Gerçek zamanlı
BIST web: 15 dakika gecikmeli
Matriks: Gerçek zamanlı (ücretli)
```

### 5.4 BIST Şirket Olayları

```
Temettü: KAP açıklaması + ödeme tarihi
Bölünme: KAP açıklaması + etkinlik tarihi
Bedelsiz: KAP açıklaması + etkinlik tarihi
Sermaye artırımı: KAP açıklaması + rüçhan hakkı kullanımı
```

---

## 6. Uygulama Planı

### Faz 1: Provider Manager (Hemen)
1. Failover mekanizması ekle
2. Priority-based provider seçimi
3. Health monitoring

### Faz 2: Rate Limiting + Circuit Breaker (1 hafta)
1. Her provider için rate limit
2. Circuit breaker entegrasyonu
3. Exponential backoff retry

### Faz 3: Data Quality (1 hafta)
1. Cross-source reconciliation
2. Point-in-time validation
3. Corporate actions otomatik düzeltme

### Faz 4: New Providers (1 hafta)
1. Ekşi Sözlük scraper
2. TCMB EVDS detaylı entegrasyon
3. Google Trends API
4. BKM kredi kartı verisi

### Faz 5: Pipeline Optimization (1 hafta)
1. main.py'yi modüler yap
2. Event-driven ingestion
3. Incremental updates (tam çekme yerine sadece yeni veri)
4. Cache optimization

---

## 7. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| Modül sayısı | 21 | 26 |
| Toplam satır | 5,278 | ~7,000 |
| Provider failover | ❌ | ✅ |
| Rate limiting | ❌ | ✅ |
| Circuit breaker | ❌ | ✅ |
| Retry policy | ❌ | ✅ |
| Cross-source reconciliation | ❌ | ✅ |
| Point-in-time validation | ❌ | ✅ |
| Corporate actions auto | ⚠️ Manuel | ✅ Otomatik |
| Ekşi Sözlük | ❌ | ✅ |
| TCMB EVDS detaylı | ⚠️ Basit | ✅ Detaylı |
| Google Trends | ❌ | ✅ |
| BKM kredi kartı | ❌ | ✅ |
| Incremental updates | ❌ | ✅ |
| Event-driven ingestion | ⚠️ Kısmen | ✅ Tam |
