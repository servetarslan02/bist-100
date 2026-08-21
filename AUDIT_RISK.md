# ALPHA BIST — Risk, Portföy, Backtest & Destekleyici Servisler Derinlemesine Kod Kalitesi Analizi

**Tarih:** 2026-08-22  
**Kapsam:** `services/risk/`, `services/portfolio/`, `services/backtest/`, `services/paper_trading/`, `services/simulation/`, `services/scheduler/`, `services/agents/`, `services/events/`, `services/data/`, `services/market_state/`, `workers/`

---

## ÖZET

| Öncelik | Bulgu Sayısı |
|---------|-------------|
| **P0 (Kritik)** | 12 |
| **P1 (Yüksek)** | 18 |
| **P2 (Orta/Düşük)** | 14 |
| **Toplam** | **44** |

---

## 1. BACKTEST MOTORU — Mark-to-Market Basitleştirmeleri

### Bulgu 1.1 — `holding_days=1` Sabit Değer (P0)

**Dosya:** `services/backtest/engine.py`, **Satır:** ~142  
**Kod:**
```python
holding_days=1,  # Basitleştirilmiş
```
**Açıklama:** Her trade'in `holding_days` değeri sabit `1` olarak atanıyor. Gerçek holding süresi hesaplanmadığı için:
- CAGR hesabı yanlış (yıllıklaştırma etkilenir)
- Vergi modeli (kısa/uzun vadeli ayrımı) çalışmaz
- Ortalama holding süresi metriği yanıltıcıdır

**Düzeltme:** `entry_date` ve `exit_date` arasındaki farkı gün olarak hesapla:
```python
from datetime import datetime
d1 = datetime.strptime(pos["entry_date"], "%Y-%m-%d")
d2 = datetime.strptime(date, "%Y-%m-%d")
holding_days = max(1, (d2 - d1).days)
```

---

### Bulgu 1.2 — CAGR = Total Return Basitleştirmesi (P0)

**Dosya:** `services/backtest/engine.py`, **Satır:** ~155  
**Kod:**
```python
cagr_pct=round(((final / initial_capital) ** (1 / max((len(equity_curve) - 1) / 252, 0.01)) - 1) * 100, 2)
```
**Açıklama:** CAGR hesaplaması equity curve nokta sayısı üzerinden yapılıyor. Ancak equity_curve her signal'da bir nokta ekliyor (günlük değil), bu da yıllıklaştırma parametresini yanlış yapıyor. 100 trade varsa `100/252 ≈ 0.4 yıl` kabul ediliyor, oysa gerçek süre farklı olabilir.

**Düzeltme:** Gerçek tarih aralığını kullan:
```python
start_dt = datetime.strptime(signals[0]["date"], "%Y-%m-%d")
end_dt = datetime.strptime(signals[-1]["date"], "%Y-%m-%d")
years = max((end_dt - start_dt).days / 365.25, 0.01)
```

---

### Bulgu 1.3 — Drawdown Süresi Hesaplanmaması (P1)

**Dosya:** `services/backtest/engine.py`, **Satır:** ~162  
**Kod:**
```python
max_drawdown_duration_days=0,
```
**Açıklama:** `max_drawdown_duration_days` sabit `0` olarak döndürülüyor. Drawdown'ın ne kadar sürdüğü kritik bir risk metriğidir. Sistem bu bilgiyi hiç üretmiyor.

**Düzeltme:** Equity curve üzerinde peak'ten recovery'ye kadar olan süreyi hesaplayan bir fonksiyon ekle.

---

### Bulgu 1.4 — Exposure Hesaplanmaması (P1)

**Dosya:** `services/backtest/engine.py`, **Satır:** ~163  
**Kod:**
```python
exposure_pct=0.0,
```
**Açıklama:** `exposure_pct` sabit `0.0`. Portföyün ne kadar süreyle piyasada exposed olduğu bilinmiyor. Bu, Sharpe ratio'nun piyasaya göre ayarlanmasını imkansız kılar.

**Düzeltme:** Her gün için invested/toplam_equity oranını hesapla ve ortalamasını al.

---

### Bulgu 1.5 — Equity Curve'de Güncel Fiyat Eksikliği (P1)

**Dosya:** `services/backtest/engine.py`, **Satır:** ~125-130  
**Kod:**
```python
for t, p in positions.items():
    current_price = price if t == ticker else p["avg_cost"]
    total_value += p["qty"] * current_price
```
**Açıklama:** Sadece işlem yapılan ticker'ın fiyatı güncelleniyor. Diğer açık pozisyonlar `avg_cost` üzerinden değerleniyor. Bu, equity curve'u ve drawdown hesaplamasını yanlış yapar.

**Düzeltme:** `price_data` dictionary'sinden güncel fiyatları çek:
```python
current_price = price_data[t][-1]["close"] if t in price_data else p["avg_cost"]
```

---

## 2. WALK-FORWARD — Eğitim Yenileme Eksikliği

### Bulgu 2.1 — Her Fold'da Gerçek Yeniden Eğitim Yapılmaması (P0)

**Dosya:** `services/backtest/walk_forward.py`, **Satır:** ~120-140  
**Açıklama:** `run_walk_forward()` metodu, her fold için sadece mevcut tahminleri filtreliyor. Train seti üzerinde yeni bir model eğitilmiyor — sadece mevcut predictions_subset kullanılıyor. Bu, walk-forward validation'ın temel amacını (her periyotta yeniden eğitim) ortadan kaldırır.

```python
train_preds = [
    p for p in predictions
    if fold["train_start"] <= p.get("date", "") <= fold["train_end"]
]
```

**Düzeltme:** Her fold'da modeli train verisiyle yeniden eğit ve test verisi üzerinde tahmin üret. Bu, bir `model_fn` callback parametresi gerektirir:
```python
def run_walk_forward(self, data, model_fn, ...):
    for fold in folds:
        model = model_fn(train_data)  # Yeniden eğitim
        predictions = model.predict(test_data)
```

---

### Bulgu 2.2 — Enhanced Walk-Forward'da Aynı Sorun (P0)

**Dosya:** `services/backtest/enhanced_walk_forward.py`, **Satır:** ~90-110  
**Açıklama:** `PurgeEmbargoWalkForward.run()` metodu da aynı soruna sahip. `predictions` ve `actuals` array'leri önceden veriliyor, fold'larda yeniden eğitim yapılmıyor. Purge/embargo mantığı doğru implemente edilmiş ama model yenilemesi yok.

**Düzeltme:** Aynı — `model_fn` callback ile her fold'da yeniden eğitim.

---

### Bulgu 2.3 — Walk-Forward Singleton Çakışması (P2)

**Dosya:** `services/backtest/walk_forward.py` (satır ~230) + `services/backtest/enhanced_walk_forward.py` (satır ~270)  
**Açıklama:** Her iki dosya da `walk_forward_engine` adında singleton tanımlıyor. Import sırasında hangisinin kullanılacağı belirsiz.

**Düzeltme:** İsimleri farklılaştır: `walk_forward_engine_v3` ve `purge_embargo_wf_engine`.

---

## 3. PORTFÖY DEFTERİ — Muhasebe Sorunları

### Bulgu 3.1 — Double-Entry Muhasebe Eksikliği (P1)

**Dosya:** `services/portfolio/portfolio_manager.py`, **Satır:** genel  
**Açıklama:** Cash ledger ve position history ayrı ayrı tutuluyor ama çift-entry (debit/credit) mantığı yok. Her işlem tek taraflı kaydediliyor:
- BUY: cash azalır, position artar → ama cash ledger'da sadece cash tarafı var
- SELL: cash artar, position azalır → ama sadece cash tarafı kaydediliyor

Bu, muhasebe invariant'ını (`EQUITY = CASH + MARKET_VALUE`) manuel doğrulama gerektirir.

**Düzeltme:** Her işlem için çift-entry kayıt:
```python
# BUY için:
debit("POSITION", cost)  # Pozisyon artar
credit("CASH", cost)     # Cash azalır
debit("COMMISSION", fee) # Komisyon
credit("CASH", fee)      # Cash azalır
```

---

### Bulgu 3.2 — `_record_equity()` Tetiklenme Sorunu (P2)

**Dosya:** `services/portfolio/portfolio_manager.py`, **Satır:** ~280  
**Açıklama:** `_record_equity()` sadece `update_prices()` ve `open_position()`'da çağrılıyor. `close_position()`'da çağrılmıyor, bu yüzden kapanış sonrası equity curve güncellenmeyebilir.

**Düzeltme:** `close_position()` sonunda da `_record_equity()` çağır.

---

### Bulgu 3.3 — Realized P&L ve Commission Çift Sayım Riski (P2)

**Dosya:** `services/portfolio/main.py`, **Satır:** ~200-210  
**Açıklama:** `_load_state()` içinde `_commission_total` hem `portfolio` tablosundan hem de `position_history` SUM'dan yükleniyor. Eğer bu iki kaynak tutarsızsa, toplam commission yanlış olur.

**Düzeltme:** Tek kaynak kullan (tercihen `position_history` SUM), ve `portfolio` tablosunu bu değerle senkronize et.

---

## 4. EXECUTION SİMÜLASYONU — Gerçekçilik Sorunları

### Bulgu 4.1 — Sabit Slippage Modeli (P1)

**Dosya:** `services/backtest/engine.py`, **Satır:** ~95  
**Kod:**
```python
slippage_pct: float = 0.05,
```
**Açıklama:** Slippage sabit %0.05. Oysa gerçek slippage hacme, volatiliteye, emir büyüklüğüne ve piyasa koşullarına bağlıdır. `EnhancedExecutionSimulator` ve `PaperExecutionEngine` daha gerçekçi modeller sunuyor ama backtest motoru bunları kullanmıyor.

**Düzeltme:** Backtest motorunda da `ExecutionSimulator._compute_slippage()` veya daha iyisi `EnhancedExecutionSimulator` kullan.

---

### Bulgu 4.2 — Likidite Kısıtı Eksik (P1)

**Dosya:** `services/backtest/engine.py`, **Satır:** ~100-110  
**Açıklama:** Backtest motorunda günlük hacim kontrolü yok. Kağıt üzerinde milyarlarca TL'lik işlem yapılabilir. `PaperExecutionEngine` hacim kısıtı uyguluyor (%10 kuralı) ama backtest'te bu yok.

**Düzeltme:** `price_data`'dan volume bilgisini al ve `max_qty = int(avg_volume * 0.1)` kontrolü ekle.

---

### Bulgu 4.3 — Spread Maliyeti Eksik (P2)

**Dosya:** `services/backtest/engine.py`, **Satır:** genel  
**Açıklama:** Sadece komisyon ve slippage uygulanıyor. Bid-ask spread maliyeti dahil değil. BIST'te spread özellikle küçük hacimli hisselerde önemli bir maliyet kalemidir.

**Düzeltme:** `TransactionCostAnalyzer` (enhancements.py) kullan veya spread parametresi ekle.

---

### Bulgu 4.4 — Paper Trading'de Sabit Volatilite (P2)

**Dosya:** `services/paper_trading/paper_orchestrator.py`, **Satır:** ~175  
**Kod:**
```python
volatility=0.25, spread_pct=0.1,
```
**Açıklama:** Her ticker ve her gün için sabit volatilite (0.25) ve spread (0.1%) kullanılıyor. Gerçek değerler büyük farklılık gösterir.

**Düzeltme:** Her ticker için tarihsel volatilite hesapla (örn. son 20 günün std'si).

---

## 5. RİSK LİMİTLERİNİN BYPASS EDİLEBİLİRLİĞİ

### Bulgu 5.1 — `_risk_limits_loaded` Flag'inin Manipülasyonu (P0)

**Dosya:** `services/risk/main.py`, **Satır:** ~55-70  
**Açıklama:** `_load_risk_limits()` başarısız olursa `_risk_limits_loaded = False` yapılıyor ve `_on_decision()` BLOCK döndürüyor. Bu doğru (fail-closed). Ancak:
1. `_risk_limits` boş dict olarak kalıyor, `_check_position_limit()`'de `self._risk_limits.get("max_position_pct", 10.0)` → **varsayılan 10%** kullanılıyor
2. Eğer DB'den partial yükleme olursa (bazı limitler yüklenir, bazıları yüklenmez), `_risk_limits_loaded = True` olur ama eksik limitler varsayılan değerlerle doldurulur

**Düzeltme:** Her limit için ayrı bir loaded flag tut veya eksik limitler için de fail-closed uygula.

---

### Bulgu 5.2 — Risk Gate Exception'da Fail-Open Riski (P0)

**Dosya:** `services/risk/main.py`, **Satır:** ~100-130  
**Açıklama:** `_on_decision()`'ın outer try-except bloğunda exception yakalanıp BLOCK ediliyor (fail-closed). Ancak `_check_position_limit()`, `_check_sector_concentration()` gibi alt fonksiyonlarda DB hatası olursa ve exception yükselirse, outer catch yakalar. Bu doğru.

Ancak `_check_sector_concentration()`'da `sector` bulunamazsa (DB'de yoksa) → BLOCK ediliyor. Bu da doğru.

**Değerlendirme:** Genel yapı fail-closed, ancak Bulgu 5.1'deki partial load riski kritik.

---

### Bulgu 5.3 — Paper Risk Gate'te SELL Side Bypass (P1)

**Dosya:** `services/paper_trading/paper_risk_gate.py`, **Satır:** ~130  
**Kod:**
```python
if side == "SELL":
    return {"check_name": "position_size", "result": "PASS", ...}
```
**Açıklama:** SELL tarafında pozisyon büyüklüğü kontrolü atlanıyor. Bu genellikle doğru (zaten var olan pozisyonu satıyorsun), ama yanlışlıkla büyük short pozisyon açılmasını engellemez.

**Düzeltme:** SHORT pozisyon açılması durumunda kontrol uygula.

---

### Bulgu 5.4 — Drawdown Response Reset Kolaylığı (P1)

**Dosya:** `services/risk/drawdown_response.py`, **Satır:** ~180  
**Kod:**
```python
def reset(self):
    self._peak_equity = 0.0
    ...
```
**Açıklama:** `reset()` metodu herhangi bir kimlik doğrulaması olmadan çağrılabilir. Kill switch aktifken bile resetlenebilir. Bu, acil durum mekanizmasını bypass eder.

**Düzeltme:** Reset için bir `force=True` parametresi ekle ve log'a CRITICAL seviyesinde kayıt düş.

---

## 6. WALK-FORWARD İSTATİSTİKSEL SORUNLAR

### Bulgu 6.1 — Deflated Sharpe Hesaplama Farklılıkları (P1)

**Dosya:** `services/backtest/walk_forward.py` vs `services/backtest/enhanced_walk_forward.py`  
**Açıklama:** İki farklı `_deflated_sharpe()` implementasyonu var:
- `walk_forward.py`: Bailey & López de Prado (2014) formülü — `se = sqrt((1 + 0.5*ds²)/n)`
- `enhanced_walk_forward.py`: Basitleştirilmiş — `E[max(SR)] ≈ sqrt(2 * log(n_trials))`

Farklı formüller farklı sonuçlar verir. Hangisi doğru?

**Düzeltme:** Tek bir canonical `_deflated_sharpe()` fonksiyonu oluştur ve her iki modül de onu kullansın.

---

### Bulgu 6.2 — Sharpe Ratio Hesaplamasında Yıllıklaştırma (P2)

**Dosya:** `services/backtest/engine.py`, **Satır:** ~150  
**Kod:**
```python
sharpe = (np.mean(returns) / np.std(returns) * np.sqrt(252))
```
**Açıklama:** `returns` equity curve'den hesaplanıyor ama equity_curve her signal'da bir nokta ekliyor (günlük değil). 252 ile yıllıklaştırma sadece günlük returns için doğrudur. Signal-bazlı returns için farklı bir faktör gerekir.

**Düzeltme:** Returns'in frekansını tespit et ve ona göre yıllıklaştır.

---

## 7. AGENT SİSTEMİ OLGUNLUK EKSİKLİKLERİ

### Bulgu 7.1 — Paralel Çalıştırma Eksikliği (P1)

**Dosya:** `services/agents/agent_system.py`, **Satır:** ~280  
**Kod:**
```python
for role in research_roles:
    agent = self._agents.get(role) or BaseAgent(role, llm_client=client)
    result = await agent.execute(task, client)
```
**Açıklama:** `run_research_pipeline()` agent'ları sırayla çalıştırıyor, paralel değil. Yorum satırında "paralel Faz 1'de eklenecek" denmiş ama eklenmemiş. 4 agent × 120s timeout = potansiyel 8 dakika gecikme.

**Düzeltme:** `asyncio.gather()` ile paralel çalıştır.

---

### Bulgu 7.2 — Hallucination Protection Etkinliği Şüpheli (P2)

**Dosya:** `services/agents/agent_system.py`, **Satır:** ~180-220  
**Açıklama:** `AIOutputValidator.validate()` 5 katmanlı koruma iddia ediyor ama:
1. Range validation sadece confidence ve score için (0-1 veya 0-100)
2. Domain validation sadece `risk_level` enum kontrolü
3. Source validation sadece URL formatı
4. Asıl hallucination (uydurma fiyat, tarih, olay) tespiti yok

**Düzeltme:** Fiyat makul aralık kontrolü, tarih doğrulama, bilinen şirket ismi eşleme ekle.

---

### Bulgu 7.3 — Agent Memory Persistence Eksikliği (P2)

**Dosya:** `services/agents/agent_pipeline.py`, **Satır:** ~60  
**Kod:**
```python
path = f"{memory_path}/{role}_memory.json" if memory_path else None
```
**Açıklama:** Eğer `memory_path=None` (varsayılan), persistence_path de None olur ve memory sadece in-memory tutulur. Restart sonrası tüm agent hafızası kaybolur.

**Düzeltme:** Varsayılan bir persistence path belirle (örn. `data/agent_memory/`).

---

### Bulgu 7.4 — LLM Client Fallback Zinciri Belirsiz (P2)

**Dosya:** `services/agents/agent_system.py`, **Satır:** ~260  
**Kod:**
```python
client = llm_client or self.llm_client
```
**Açıklama:** Eğer hem parametre hem instance client None ise, `AIFallback.rule_based_analysis()` kullanılıyor. Ama bu durum sessizce gerçekleşiyor, log'da bile belirtilmiyor. Üretim sisteminde LLM bağlantısı koparsa, kullanıcı bunu fark etmeyebilir.

**Düzeltme:** Fallback durumunda WARNING log ekle ve sonuçta `source: "rule_based_fallback"` alanını koru (zaten var ama log eksik).

---

## 8. DEAD CODE & KULLANILMAYAN MODÜLLER

### Bulgu 8.1 — `_PositionSizerCompat` Sınıfı (P2)

**Dosya:** `services/risk/position_sizing.py`, **Satır:** ~190-240  
**Açıklama:** `_PositionSizerCompat` sınıfı "geriye uyumluluk" için eklenmiş ama `PositionSizer`'ın asıl API'si (`calculate_position_sizes`) ile farklı bir arayüz sunuyor. `position_sizer` singleton'ı bu compat sınıfının instance'ı. Ancak `calculate()` metodu sadece tek pozisyon hesaplıyor — çoklu pozisyon hesaplayan `calculate_position_sizes()`'ı hiç kullanılmıyor olabilir.

**Düzeltme:** Hangi API'nin kullanıldığını tespit et ve kullanılmayanı kaldır.

---

### Bulgu 8.2 — `get_backtest_systems()` Exception Swallowing (P1)

**Dosya:** `services/backtest/engine.py`, **Satır:** ~175-220  
**Kod:**
```python
except ImportError:
    pass
except Exception as e:
    logger.warning("Failed to load module", ...)
```
**Açıklama:** Her modül import'u için hem `ImportError` hem `Exception` yakalanıyor. Bu, ciddi hataların (syntax error, circular import) gizlenmesine neden olur.

**Düzeltme:** Sadece `ImportError` yakala; diğer exception'ların yükselmesine izin ver.

---

### Bulgu 8.3 — `events/` Dizininde Dosya Yok (P2)

**Dosya:** `services/events/`  
**Açıklama:** Task'te belirtilen `services/events/` dizini mevcut değil (muhtemelen `services/core/event_bus.py` ve `services/core/event_schema.py` kullanılıyor). Bu, ya dead code ya da yanlış dizin referansı.

---

## 9. HARD-CODED SABİTLER & UYDURMA DEĞERLER

### Bulgu 9.1 — Sabit Volatilite ve Spread Değerleri (P0)

**Dosya:** `services/paper_trading/paper_orchestrator.py`, **Satır:** ~175  
**Kod:**
```python
volatility=0.25, spread_pct=0.1,
```
**Dosya:** `services/backtest/engine.py`, **Satır:** ~95  
**Kod:**
```python
slippage_pct: float = 0.05,
```
**Açıklama:** Volatilite %25, spread %0.1, slippage %0.05 sabit değerler. BIST hisseleri arasında volatilite %15-80 arasında değişir. Bu sabitler backtest sonuçlarını büyük ölçüde yanıltır.

**Düzeltme:** Her ticker için tarihsel volatilite hesapla. Spread'i ADV'ye göre ayarla.

---

### Bulgu 9.2 — `execute_auto_rebalance()` Hard-Coded Sinyaller (P0)

**Dosya:** `services/portfolio/portfolio_manager.py`, **Satır:** ~520-540  
**Kod:**
```python
signals = [
    {"ticker": "POLTK", "price": 14600.0, "score": 96, ...},
    {"ticker": "SDTTR", "price": 284.00, "score": 93, ...},
    # 19 hard-coded hisse
]
```
**Açıklama:** `execute_auto_rebalance()` fonksiyonu parametre olarak `signals` almıyor varsayılan olarak, bunun yerine 19 hard-coded hisse senedi fiyatı ve skoru kullanıyor. Bu değerler güncel değil ve production'da kullanılamaz.

**Düzeltme:** Hard-coded default'ları kaldır. `signals` parametresini zorunlu yap veya DB'den oku.

---

### Bulgu 9.3 — FX Kurları Hard-Coded (P1)

**Dosya:** `services/portfolio/enhancements.py`, **Satır:** ~230  
**Kod:**
```python
self._rates: Dict[str, float] = {"TRY": 1.0, "USD": 47.88, "EUR": 55.38}
```
**Açıklama:** Döviz kurları hard-coded. Bu değerler zamanla geçerliliğini yitirir.

**Düzeltme:** API'den canlı kur çek (örn. TCMB API).

---

### Bulgu 9.4 — Risk-Free Rate Sabit (P2)

**Dosya:** `services/portfolio/enhancements.py`, **Satır:** ~165  
**Kod:**
```python
risk_free_rate: float = 0.15,  # %15 yıllık (Türkiye)
```
**Açıklama:** Risksiz faiz oranı sabit %15. TCMB faizleri sık sık değişir.

**Düzeltme:** Config'den oku veya API'den çek.

---

### Bulgu 9.5 — Holiday Takvimi Sadece 2026 (P1)

**Dosya:** `services/scheduler/unified_scheduler.py`, **Satır:** ~90  
**Kod:**
```python
_FALLBACK_2026: set = frozenset({...})
```
**Açıklama:** Hardcoded fallback sadece 2026 tatillerini içeriyor. 2027 ve sonrası için dinamik kaynak yoksa scheduler yanlış çalışır.

**Düzeltme:** Yıllık otomatik güncelleme mekanizması ekle veya fallback'i genişlet.

---

### Bulgu 9.6 — `data_source.py` BIST 100 Universe Hard-Coded (P2)

**Dosya:** `services/data/data_source.py`, **Satır:** ~100  
**Kod:**
```python
return [
    "THYAO.IS", "GARAN.IS", "ISCTR.IS", ...
]
```
**Açıklama:** BIST 100 hisse listesi hard-coded ve sadece 20 hisse içeriyor. Dinamik olarak BIST'ten çekilmeli.

**Düzeltme:** BIST API'den güncel listeyi çek ve cache'le.

---

## 10. SESSİZ HATA YÖNETİMİ (except: pass)

### Bulgu 10.1 — Portfolio Service Stop'ta Exception Swallowing (P0)

**Dosya:** `services/portfolio/main.py`, **Satır:** ~90  
**Kod:**
```python
except Exception as e:
    logger.debug("Handled exception", error=str(e), context="main.py:90")
    pass
```
**Açıklama:** `stop()` metodunda equity snapshot kaydedilirken oluşan hatalar `debug` seviyesinde loglanıyor ve yutuluyor. Bu, servis durdurulurken son equity verisinin kaybolmasına neden olabilir.

**Düzeltme:** `logger.warning()` kullan ve hata detayını logla.

---

### Bulgu 10.2 — Price Update'te Exception Swallowing (P0)

**Dosya:** `services/portfolio/main.py`, **Satır:** ~430-445  
**Kod:**
```python
except Exception as e:
    logger.debug("Handled exception", error=str(e), context="main.py:432")
    pass
```
**Açıklama:** `update_prices()` içinde 3 ayrı `try-except` bloğu var ve hepsi exception'ları debug seviyesinde yutuyor. Fiyat güncelleme hatası sessizce geçiliyor, bu da pozisyon değerlemesinin yanlış kalmasına neden olur.

**Düzeltme:** Her bir exception için ayrı handling stratejisi belirle. DB yazma hatası → retry. Fiyat bulunamadı → warning.

---

### Bulgu 10.3 — Daily P&L Exception Swallowing (P1)

**Dosya:** `services/portfolio/main.py`, **Satır:** ~175  
**Kod:**
```python
except Exception as e:
    pass  # daily_pnl tablosu yoksa atla
```
**Açıklama:** `_load_state()` içinde daily_pnl yükleme hatası tamamen yutuluyor. Tablo yoksa tamam ama başka bir hata (bozuk veri, disk hatası) da yutulur.

**Düzeltme:** `except sqlite3.OperationalError:` gibi spesifik exception yakala.

---

### Bulgu 10.4 — Risk Limit Yüklemede JSON Parse Swallowing (P1)

**Dosya:** `services/risk/main.py`, **Satır:** ~65  
**Kod:**
```python
except Exception as e:
    pass  # Intentional: silent error handling
```
**Açıklama:** Risk limit değerleri JSON parse edilirken oluşan hatalar yutuluyor. Yorum satırında "intentional" denmiş ama bu, bozuk bir config değerinin sessizce `0` olarak kullanılmasına neden olur.

**Düzeltme:** JSON parse hatasında varsayılan güvenli değer kullan ve WARNING log ekle.

---

### Bulgu 10.5 — Config Change Handler Exception Swallowing (P2)

**Dosya:** `services/portfolio/main.py`, **Satır:** ~100  
**Kod:**
```python
except Exception as e:
    logger.warning("Config change handler failed", error=str(e))
```
**Açıklama:** Config değişikliği handler'ı başarısız olursa sadece warning loglanıyor. Risk limitleri güncellenmemiş olabilir.

**Düzeltme:** Config güncelleme hatasında eski config'i koru ve alert gönder.

---

### Bulgu 10.6 — Equity Snapshot Save Exception Swallowing (P1)

**Dosya:** `services/portfolio/main.py`, **Satır:** ~450  
**Kod:**
```python
except Exception as e:
    logger.warning("Equity snapshot save failed", error=str(e))
```
**Açıklama:** Equity snapshot kaydedilemezse sadece warning. Bu, drawdown hesaplamasının yanlış kalmasına neden olur.

**Düzeltme:** Retry mekanizması ekle veya in-memory queue'ya al.

---

## 11. EK BULGULAR

### Bulgu 11.1 — Backtest Motorunda Pozisyon Boyutu Basitleştirmesi (P1)

**Dosya:** `services/backtest/engine.py`, **Satır:** ~105  
**Kod:**
```python
risk_pct = 2.0 * confidence
position_value = capital * (risk_pct / 100)
```
**Açıklama:** Pozisyon büyüklüğü sadece confidence'a bağlı. Volatilite, korelasyon, rejim gibi faktörler dahil değil. `PositionSizer` sınıfı var ama backtest motoru bunu kullanmıyor.

**Düzeltme:** Backtest motorunda da `PositionSizer` veya `KellyCriterion` kullan.

---

### Bulgu 11.2 — Virtual Portfolio'da Komisyon Dahil Maliyet Yanlışlığı (P1)

**Dosya:** `services/paper_trading/virtual_portfolio.py`, **Satır:** ~85  
**Kod:**
```python
avg_with_commission = (quantity * price + commission) / quantity
```
**Açıklama:** Yeni pozisyonda komisyon maliyete dahil ediliyor (`avg_cost`'a yansıyor). Bu, realized P&L hesabında komisyonun çift sayılmasına neden olabilir (bir kez avg_cost'ta, bir kez close_position'da).

**Düzeltme:** Komisyonu ayrı tut (PortfolioManager v2.0'daki gibi `entry_commission` alanı).

---

### Bulgu 11.3 — Scheduler DB Erişim Kontrolü Yanlış (P2)

**Dosya:** `services/scheduler/unified_scheduler.py`, **Satır:** ~300  
**Kod:**
```python
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(0.5)
result = s.connect_ex(('127.0.0.1', 5432))
```
**Açıklama:** PostgreSQL erişimi socket connect ile kontrol ediliyor. Port açık olabilir ama DB erişimi olmayabilir (authentication failure, database doesn't exist). Ayrıca bu yöntem her call'da socket açıyor.

**Düzeltme:** Async DB health check kullan veya sadece bir kez kontrol et.

---

### Bulgu 11.4 — `risk_gate.py` Dosyası Mevcut Değil (P2)

**Dosya:** `services/risk/risk_gate.py`  
**Açıklama:** Task'te belirtilen `risk_gate.py` dosyası mevcut değil. Risk gate işlevselliği `services/risk/main.py` (RiskEngine) ve `services/paper_trading/paper_risk_gate.py` (PaperRiskGate) arasında dağılmış.

---

### Bulgu 11.5 — Portfolio Simülasyonu ile Backtest Motoru Farklılıkları (P2)

**Dosya:** `services/backtest/engine.py` vs `services/backtest/portfolio_sim.py`  
**Açıklama:** İki farklı portfolio simülasyon mantığı var:
- `engine.py`: Basit, signal-bazlı, tek pozisyon
- `portfolio_sim.py` (v3.0): Daha gelişmiş, invariant doğrulama ile

Backtest engine v1.0 daha basit ama production'da kullanılıyor olabilir.

**Düzeltme:** Tek portfolio simülasyon mantığı kullan (v3.0).

---

### Bulgu 11.6 — Monte Carlo'da Sabit Seed Kullanılmaması (P2)

**Dosya:** `services/simulation/monte_carlo_enhanced.py`, **Satır:** genel  
**Açıklama:** Varsayılan olarak `seed=None` kullanılıyor. Bu, her çalıştırmada farklı sonuçlar üretir ve reproducibility sağlanması zor.

**Düzeltme:** Production'da seed kullan veya sonuçları cache'le.

---

### Bulgu 11.7 — Stress Test Senaryoları Statik (P2)

**Dosya:** `services/risk/stress_test.py`, **Satır:** ~30-80  
**Açıklama:** Tüm senaryolar hard-coded (2008, 2020, 2022, 2018). Yeni bir kriz olduğunda güncelleme gerekir. Ayrıca sektör etkileri tahmini değerler.

**Düzeltme:** Senaryoları config dosyasından yükle ve düzenli güncelle.

---

### Bulgu 11.8 — Paper Trading State Store'da Atomic Write Eksikliği (P2)

**Dosya:** `services/paper_trading/state_store.py`, **Satır:** genel  
**Açıklama:** Docstring'te "Atomic write (write-to-temp + rename)" deniyor ama implementasyonda sadece `conn.execute()` + `conn.commit()` var. Crash durumunda veri bozulabilir.

**Düzeltme:** WAL mode kullan veya write-to-temp + rename implemente et.

---

### Bulgu 11.9 — Performance Tracker'da `_max_drawdown_from_history` Yanlışlığı (P1)

**Dosya:** `services/paper_trading/performance_tracker.py`, **Satır:** ~160  
**Kod:**
```python
def _compute_max_drawdown_from_history(self) -> float:
    if not self._daily_perf_cache:
        return 0.0
    return max((p["max_drawdown_pct"] for p in self._daily_perf_cache), default=0.0)
```
**Açıklama:** Bu fonksiyon sadece cache'teki günlük max drawdown'ların en büyüğünü döndürüyor. Ancak gerçek max drawdown, equity curve üzerinden peak-to-trough hesaplanmalıdır. Günlük max drawdown'lar birbiriyle kümülatif olarak ilişkili olmayabilir.

**Düzeltme:** Equity curve'den gerçek max drawdown hesapla.

---

### Bulgu 11.10 — Multi-Currency Handler'da Sabit Kurlar (P2)

**Dosya:** `services/portfolio/enhancements.py`, **Satır:** ~230  
**Kod:**
```python
self._rates: Dict[str, float] = {"TRY": 1.0, "USD": 47.88, "EUR": 55.38}
```
**Açıklama:** Döviz kurları hard-coded. `update_rate()` metodu var ama hiçbir yerden çağrılmıyor.

**Düzeltme:** Startup'ta API'den kur çek.

---

## 12. ÖNERİLEN ÖNCELİKLI DÜZELTMELER

### P0 (Hemen — 1-2 hafta)

1. **Walk-forward'da yeniden eğitim** (Bulgu 2.1, 2.2) — En kritik bulgu. Walk-forward validation'ın temel amacı реализize edilmemiş.
2. **Hard-coded volatilite/spread** (Bulgu 9.1) — Backtest sonuçları güvenilir değil.
3. **Hard-coded rebalance sinyalleri** (Bulgu 9.2) — Production'da kullanılamaz.
4. **Exception swallowing** (Bulgu 10.1, 10.2) — Sessiz hatalar ciddi sorunlara yol açar.
5. **Risk limit partial load** (Bulgu 5.1) — Eksik limitler varsayılanlarla dolduruluyor.
6. **holding_days=1 sabit** (Bulgu 1.1) — CAGR ve vergi hesaplamaları yanlış.

### P1 (2-4 hafta)

7. **Exposure ve drawdown süresi** (Bulgu 1.3, 1.4) — Kritik risk metrikleri eksik.
8. **Equity curve güncel fiyat** (Bulgu 1.5) — Drawdown hesaplaması yanlış.
9. **Double-entry muhasebe** (Bulgu 3.1) — Muhasebe doğruluğu için.
10. **Slippage modeli** (Bulgu 4.1) — Backtest gerçekçiliği için.
11. **Likidite kısıtı** (Bulgu 4.2) — Backtest gerçekçiliği için.
12. **FX kurları** (Bulgu 9.3) — Doğru muhasebe için.
13. **Deflated Sharpe birleştirme** (Bulgu 6.1) — Tutarlılık için.
14. **Agent paralel çalıştırma** (Bulgu 7.1) — Performans için.

### P2 (1-3 ay)

15. **Dead code temizliği** (Bulgu 8.1, 8.2)
16. **Holiday takvimi genişletme** (Bulgu 9.5)
17. **BIST 100 dinamik liste** (Bulgu 9.6)
18. **Agent memory persistence** (Bulgu 7.3)
19. **Monte Carlo reproducibility** (Bulgu 11.6)

---

## 13. MİMARİ ÖNERİLER

1. **Backtest Engine v1.0 → v4.0 migration**: v4.0 daha gelişmiş (deterministik, persistence, invariant doğrulama) ama v1.0 hâlâ kullanımda. Tam migration planlanmalı.

2. **Risk Gate Unified Interface**: `RiskEngine` (async, DB-backed) ve `PaperRiskGate` (sync, in-memory) arasında unified bir interface tanımlanmalı.

3. **Execution Simulator Consolidation**: 3 farklı execution simülatörü var (v1.0, enhanced, paper). Tek bir configurable simülatör kullanılmalı.

4. **Config-driven Defaults**: Hard-coded sabitler (volatilite, spread, komisyon oranları, risk limitleri) merkezi bir config dosyasından okunmalı.

5. **Observability**: Exception swallowing yerine structured logging + metrics + alerting sistemi kurulmalı.

---

*Bu analiz, kod tabanının belirli bir snapshot'ı üzerinden yapılmıştır. Runtime davranışları, test coverage ve performans profili dahil edilmemiştir.*
