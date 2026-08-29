# BIST-100 ALPHA — MANTIKSAL HATA RAPORU

**Tarih:** 2026-08-21  
**Kapsam:** services/core/, services/scanner/, services/portfolio/, services/risk/, services/simulation/, main.py, run_system.py  
**Toplam Hata:** 37

---

## İÇİNDEKİLER

1. [KRİTİK Hatalar (8)](#kritik-hatalar)
2. [YÜKSEK Önemli Hatalar (12)](#yüksek-hatalar)
3. [ORTA Önemli Hatalar (11)](#orta-hatalar)
4. [DÜŞÜK Önemli Hatalar (6)](#düşük-hatalar)

---

## KRİTİK HATALAR

### HATA-01: `run_pipeline()` — `sector_map` Tanımsız Değişken Kullanımı

**Dosya:** `services/core/orchestrator.py`, satır ~260  
**Önem:** [KRİTİK]

```python
# run_pipeline() metodunda:
agent_pipeline_result = _asyncio.run(
    agent_pipe.run(
        ticker=ticker,
        features=features,
        sector=sector_map.get(ticker, "UNKNOWN"),  # ← sector_map TANIMSIZ
        regime=regime,
        price=float(prices[-1]) if len(prices) > 0 else 0,
    )
)
```

**Sorun:** `run_pipeline()` metodunun imzası `def run_pipeline(self, ticker: str, market_data: Dict)` şeklindedir — `sector_map` parametresi yoktur. Agent pipeline çağrısında `sector_map.get(ticker, "UNKNOWN")` kullanılmaktadır. Bu, `NameError` exception'ı fırlatır ve agent pipeline'ın çalışmasını engeller.

**Etki:** Agent pipeline hiçbir zaman çalışamaz, tüm agent analiz sonuçları boş kalır.

**Düzeltme:** `run_pipeline()` metoduna `sector_map: Optional[Dict[str, str]] = None` parametresi ekleyin veya `market_data` içinden çıkarın.

---

### HATA-02: `run_pipeline()` — Async/Sync Çakışması (Nested Event Loop)

**Dosya:** `services/core/orchestrator.py`, satır ~245-270  
**Önem:** [KRİTİK]

```python
try:
    loop = _asyncio.get_running_loop()
    # Zaten bir loop içinde — nested çalıştır
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(
            _asyncio.run,  # ← YENİ loop oluşturur
            agent_pipe.run(...),
        )
        agent_pipeline_result = future.result(timeout=180)
except RuntimeError:
    # Loop yok
    agent_pipeline_result = _asyncio.run(...)
```

**Sorun:** `asyncio.get_running_loop()` bir loop varken `RuntimeError` fırlatmaz — loop'u döndürür. Yani `try` bloğu her zaman ilk dalı çalıştırır. `asyncio.run()` yeni bir loop oluşturur ama zaten çalışan bir loop içinde bu `RuntimeError` fırlatır. `ThreadPoolExecutor` ile çözüm doğru yönde ama `get_running_loop()` davranışı yanlış anlaşılmış.

**Etki:** Sync context'te (ana thread) `get_running_loop()` `RuntimeError` fırlatır → `except` dalına düşer → doğru çalışır. Ama async context'te (bir async fonksiyon içinde çağrılırsa) `ThreadPoolExecutor` içinde `asyncio.run()` çalıştırılır ki bu da ayrı bir thread'de yeni loop oluşturur — bu durumda çalışır ama gereksiz karmaşıklık yaratır.

**Düzeltme:** `run_pipeline()` metodunu async yapın veya sync kalacaksa `asyncio.get_event_loop().run_until_complete()` kullanın.

---

### HATA-03: `run_full_pipeline()` — Tanımsız `macro_impact_analyzer` Kullanımı

**Dosya:** `services/core/orchestrator.py`, satır ~610  
**Önem:** [KRİTİK]

```python
if macro_analysis.get("regime"):
    sector = sector_map.get(ticker, "OTHER")
    try:
        impact = macro_impact_analyzer.compute_cumulative_impact(ticker, sector)
        # ← macro_impact_analyzer import edilmemiş, tanımsız
```

**Sorun:** `macro_impact_analyzer` değişkeni hiçbir yerde tanımlanmamıştır. `from services.macro import ...` bloğunda import edilenler arasında yoktur. Bu, `NameError` fırlatır.

**Etki:** Macro impact hesaplaması hiçbir zaman çalışmaz. `features["macro_cumulative_impact"]` hiçbir zaman set edilmez.

**Düzeltme:** Import bloğuna `from services.macro.impact_analyzer import macro_impact_analyzer` ekleyin veya ilgili modülü import edin.

---

### HATA-04: `main.py` — Var Olmayan Metod Çağrıları

**Dosya:** `main.py`, satır ~105 ve ~290  
**Önem:** [KRİTİK]

```python
# run_daily_pipeline() içinde:
json_report = orchestrator.export_daily_report_json(date)  # ← METOD YOK

# run_health_check() içinde:
stats = orchestrator.get_pipeline_stats()  # ← METOD YOK
```

**Sorun:** `MasterOrchestrator` sınıfında `export_daily_report_json()` ve `get_pipeline_stats()` metodları tanımlı değildir. Bu fonksiyonlar çağrıldığında `AttributeError` fırlatır.

**Etki:** `daily` modu rapor kaydetme aşamasında crash eder. `health` modu sağlık kontrolü yapamaz.

**Düzeltme:** İlgili metodları `MasterOrchestrator` sınıfına ekleyin veya çağrıları kaldırın.

---

### HATA-05: Portfolio Manager — SHORT Pozisyon Kapatmada Yanlış Nakit Hesabı

**Dosya:** `services/portfolio/portfolio_manager.py`, satır ~380  
**Önem:** [KRİTİK]

```python
def close_position(self, ticker, price, commission=0.0):
    # ...
    if pos.direction == "LONG":
        self._cash += net_revenue
    else:
        self._cash += pos.cost_basis + realized_pnl  # ← YANLIŞ
```

**Sorun:** SHORT pozisyon kapatmada nakit hesabı yanlış. SHORT'ta: açılışta `cash += revenue` (satış geliri), kapatmada `cash -= buy_back_cost`. Doğru formül: `self._cash -= (quantity * price + commission)` olmalı. Mevcut kod `cost_basis + realized_pnl` ekliyor ki bu double-counting'e neden olur.

**Etki:** SHORT pozisyon kapatıldığında nakit hesabı şişer, muhasebe tutarsızlığı oluşur.

**Düzeltme:** SHORT kapatma için: `self._cash -= (pos.quantity * price + commission)`

---

### HATA-06: Portfolio Manager — `_reduce_position()` SHORT Nakit Hesabı Yanlış

**Dosya:** `services/portfolio/portfolio_manager.py`, satır ~440  
**Önem:** [KRİTİK]

```python
# Kısmi kapatmada:
if pos.direction == "LONG":
    self._cash += net_revenue
else:
    self._cash += close_qty * (2 * pos.entry_price - price) - commission  # ← YANLIŞ
```

**Sorun:** SHORT pozisyon kısmi kapatmada formül tamamen yanlış. `2 * entry_price - price` ifadesi matematiksel olarak anlamsız. SHORT'ta kısmi kapatma: `cash -= close_qty * price + commission` olmalı (geri alış maliyeti).

**Etki:** SHORT pozisyon azaltmalarında nakit hesabı ciddi şekilde bozulur.

**Düzeltme:** `self._cash -= (close_qty * price + commission)`

---

### HATA-07: Decision Engine — `_determine_direction()` HOLD Döndüğünde Bile BUY/SELL Yapılabilir

**Dosya:** `services/core/decision_engine.py`, satır ~175  
**Önem:** [KRİTİK]

```python
def _determine_action(self, inp, direction):
    if inp.ml_confidence < self._min_confidence:
        return "NO_ACTION"
    if direction == "LONG":
        return "BUY"
    elif direction == "SHORT":
        return "SELL"
    return "HOLD"
```

**Sorun:** `_determine_direction()` 3 bullish veya 3 bearish sinyal yoksa `"HOLD"` döndürür. Ama `_determine_action()` HOLD için `"HOLD"` döndürür — bu doğru. Ancak `decide()` metodunda HOLD action'ı bile `score >= min_score` ve `ml_confidence >= min_confidence` koşullarını geçerse bir `Decision` objesi döndürür. Bu Decision'ın `action="HOLD"` olması gereken yerde, `trade_plan` ve `risk_check` adımları HOLD için de çalışır ve gereksiz işlem yapar.

**Etki:** HOLD sinyali için bile trade plan ve risk check çalıştırılır, performans kaybı.

**Düzeltme:** `decide()` metodunda HOLD action için erken dönüş yapın.

---

### HATA-08: `main.py` — `run_daily_pipeline` Import Hatası

**Dosya:** `main.py`, satır ~105  
**Önem:** [KRİTİK]

```python
from services.core.orchestrator import orchestrator
# Ama orchestrator.py'de singleton adı "master_orchestrator"
```

**Sorun:** `orchestrator.py` dosyasında singleton `master_orchestrator = MasterOrchestrator()` olarak tanımlıdır. `main.py`'de `from services.core.orchestrator import orchestrator` kullanılmaktadır. Bu isim mevcut değil — `AttributeError` fırlatır.

**Etki:** `daily`, `backtest`, `paper`, `full` modlarının hiçbiri çalışamaz.

**Düzeltme:** `from services.core.orchestrator import master_orchestrator as orchestrator` kullanın.

---

## YÜKSEK HATALAR

### HATA-09: Orchestrator — Analysis Engines Sadece String Atıyor, Hesaplama Yapmıyor

**Dosya:** `services/core/orchestrator.py`, satır ~210  
**Önem:** [YÜKSEK]

```python
# ━━━ 5. ANALYSIS ENGINES ━━━
analysis = {}
try:
    pa = self._services.get("price_action")
    if pa: analysis["price_action"] = "computed"  # ← Sadece string
    ve = self._services.get("volume_engine")
    if ve: analysis["volume"] = "computed"  # ← Sadece string
```

**Sorun:** Analysis engine'ler (price_action, volume_engine, sector_engine, relative_strength) varlıkları kontrol ediliyor ama hiçbir hesaplama yapılmıyor. Sadece `"computed"` string'i atanıyor.

**Etki:** Tüm analiz sonuçları boş/anlamsız. Pipeline'ın analiz aşaması tamamen işlevsiz.

**Düzeltme:** Her engine için gerçek hesaplama çağrısı yapın: `analysis["price_action"] = pa.analyze(features)` gibi.

---

### HATA-10: Orchestrator — Forecasting ve Monte Carlo Placeholder

**Dosya:** `services/core/orchestrator.py`, satır ~225-240  
**Önem:** [YÜKSEK]

```python
# ━━━ 6. FORECASTING + PROBABILITY ━━━
forecast = {}
try:
    fe = self._services.get("forecasting")
    if fe:
        forecast = {"horizons": [1, 5, 20]}  # ← Placeholder, hesaplama yok
```

**Sorun:** Forecasting engine var ama hiçbir tahmin yapılmıyor. Sadece sabit bir dict atanıyor. Aynı sorun Monte Carlo için de geçerli: `monte_carlo = {"simulated": True}`.

**Etki:** Forecast ve Monte Carlo sonuçları tamamen sahte/boş.

**Düzeltme:** `forecast = fe.predict(features, horizons=[1, 5, 20])` gibi gerçek çağrı yapın.

---

### HATA-11: Decision Engine — Ağırlıkların Toplamı 1.0 Değil

**Dosya:** `services/core/decision_engine.py`, satır ~120  
**Önem:** [YÜKSEK]

```python
components = {
    "ml_score": ml_component * 0.22,
    "agent": agent_component * 0.13,
    "technical": self._technical_score(inp) * 0.18,
    "fundamental": self._fundamental_score(inp) * 0.13,
    "sentiment": self._sentiment_score(inp) * 0.08,
    "regime": self._regime_score(inp) * 0.08,
    "macro": self._macro_score(inp) * 0.10,
    "risk": self._risk_score(inp) * 0.08,
}
# Toplam: 0.22 + 0.13 + 0.18 + 0.13 + 0.08 + 0.08 + 0.10 + 0.08 = 1.00 ✓
```

**Sorun:** Ağırlıklar toplamı 1.0 görünüyor ama her bileşen 0-100 arası skor döndürüyor. Ağırlıklı toplam `0-100` arası olmalı. Ancak `ml_return_5d` ve `ml_return_20d` bonus/cezaları (`+5` veya `-5`) toplamdan SONRA ekleniyor, bu da skoru 100'ün üzerine çıkarabilir veya 0'ın altına düşürebilir. `min(100, max(0, total))` ile sınırlandırılıyor ama bu durumda ağırlıkların anlamı bozuluyor.

**Etki:** ML return bonusları ağırlık dengesini bozar. Yüksek pozitif return'lerde skor şişirilir.

**Düzeltme:** ML return bonuslarını da ağırlıklı sisteme dahil edin veya bonus miktarlarını küçültün.

---

### HATA-12: Position Sizing — Cold-Start `base_weight` ve `score_weight` Çelişkisi

**Dosya:** `services/risk/position_sizing.py`, satır ~120-135  
**Önem:** [YÜKSEK]

```python
# Cold-start bloğu:
base_weight = max(0.1, min(1.0, score / 20.0))  # score=100 → 1.0

# Sonra:
score_weight = max(0.1, 1.0 - score / 20.0)  # score=100 → 0.1 (TERS!)

# Final:
weight = base_weight * score_weight * vol_adj * leverage
```

**Sorun:** `base_weight` yüksek score → yüksek ağırlık veriyor. `score_weight` ise yüksek score → DÜŞÜK ağırlık veriyor (ters mantık). İkisi çarpıldığında `score=100` için `1.0 * 0.1 = 0.1` oluyor — en iyi hisse en düşük ağırlığı alıyor!

**Etki:** Cold-start durumunda en iyi skorlu hisseler en küçük pozisyonu alır, tam tersi olmalı.

**Düzeltme:** `score_weight` hesabını düzeltin: `score_weight = max(0.1, score / 100.0)` veya `score_weight`'ı tamamen kaldırın.

---

### HATA-13: VaR Calculator — Historical VaR Index Hesabı Off-by-One

**Dosya:** `services/risk/var_cvar.py`, satır ~120  
**Önem:** [YÜKSEK]

```python
def calculate_historical_var(self, returns, confidence=0.95, ...):
    sorted_returns = np.sort(returns)
    index = int((1 - confidence) * len(sorted_returns))
    index = max(0, min(index, len(sorted_returns) - 1))
    var_pct = abs(sorted_returns[index])
```

**Sorun:** `confidence=0.95` için `index = int(0.05 * n)`. Örneğin `n=100` için `index=5`. Ama `np.sort` artan sırada sıraladığı için `sorted_returns[5]` en kötü %5'in DEĞİL, %5-10 arasındaki getiriyi verir. Doğru index `int(0.05 * n) - 1` olmalı (0-indexed) veya `np.percentile(returns, 5)` kullanılmalı.

**Etki:** VaR hafifçe düşük hesaplanır (gerçek risk olduğundan az gösterilir).

**Düzeltme:** `index = max(0, int((1 - confidence) * len(sorted_returns)) - 1)` veya `np.percentile` kullanın.

---

### HATA-14: Circuit Breaker — `RetryPolicy.execute_with_retry` Sync Fonksiyonu Async Context'te Kullanıyor

**Dosya:** `services/core/circuit_breaker.py`, satır ~130  
**Önem:** [YÜKSEK]

```python
async def execute_with_retry(self, func, *args, **kwargs):
    for attempt in range(self.max_retries + 1):
        try:
            result = func(*args, **kwargs)  # ← Sync çağrı
            return result
        except Exception as e:
            # ...
            await asyncio.sleep(delay)  # ← Async bekleme
```

**Sorun:** `func` sync bir fonksiyon olarak çağrılıyor ama `execute_with_retry` async. Eğer `func` async ise `result` bir coroutine olur ve `return result` coroutine'i döndürür, sonucu değil. Ayrıca `ProtectedProvider.execute()` bu metodu `await` ile çağırıyor ama `func`'ın async olup olmadığını kontrol etmiyor.

**Etki:** Async fonksiyonlar düzgün çalıştırılmaz, sonuç yerine coroutine döndürülür.

**Düzeltme:** `func`'ın async olup olmadığını kontrol edin: `if asyncio.iscoroutinefunction(func): result = await func(...)`.

---

### HATA-15: Event Bus — `_check_and_mark_published` Her Seferinde Yeni Redis Bağlantısı Açıyor

**Dosya:** `services/core/event_bus.py`, satır ~265  
**Önem:** [YÜKSEK]

```python
async def _check_and_mark_published(event_id: str) -> bool:
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, decode_responses=True)  # ← YENİ BAĞLANTI
        key = f"event_published:{event_id}"
        result = await r.set(key, "1", ex=3600, nx=True)
        await r.close()  # ← Hemen kapat
```

**Sorun:** Her event publish edilirken yeni bir Redis bağlantısı açılıp kapatılıyor. Bu, yüksek throughput'ta ciddi performans sorunu yaratır (connection overhead). Ayrıca bağlantı havuzu kullanılmıyor.

**Etki:** Yüksek event throughput'unda Redis bağlantı patlaması, performans düşüşü.

**Düzeltme:** Mevcut Redis bağlantısını kullanın veya connection pool oluşturun.

---

### HATA-16: Event Bus — `publish_event` Sync Fonksiyonda `asyncio.create_task` Kullanımı

**Dosya:** `services/core/event_bus.py`, satır ~230  
**Önem:** [YÜKSEK]

```python
def publish_event(event: CanonicalEvent, key: Optional[str] = None):
    # ... (sync fonksiyon)
    try:
        asyncio.create_task(_publish_with_idempotency(event))  # ← Loop yoksa hata
    except Exception as e:
        pass
```

**Sorun:** `publish_event` sync bir fonksiyon. `asyncio.create_task()` çalışabilmesi için aktif bir event loop gerektirir. Sync context'te (ana thread, loop yoksa) `RuntimeError` fırlatır. `except` ile yakalanıyor ama event sessizce kayboluyor.

**Etki:** Sync context'te event'ler publish edilemez, sessizce kaybolur.

**Düzeltme:** `publish_event`'i async yapın veya `asyncio.get_event_loop().create_task()` kullanın.

---

### HATA-17: Regime Detector — LOW_VOL Rejimi Asla Tespit Edilemiyor

**Dosya:** `services/core/regime_detector.py`, satır ~160  
**Önem:** [YÜKSEK]

```python
scores = {
    "BULL": bull_score,
    "BEAR": bear_score,
    "SIDEWAYS": sideways_score,
    "HIGH_VOL": high_vol_score,
    # ← LOW_VOL eksik!
}
regime = max(scores, key=scores.get)
```

**Sorun:** `REGIMES` listesinde `"LOW_VOL"` var ama `scores` dict'inde hiç hesaplanmıyor. Düşük volatilite durumunda `vol_score < -30` iken sadece `sideways_score += 20` ekleniyor — LOW_VOL asla seçilmez.

**Etki:** Düşük volatilite piyasaları yanlış tespit edilir (SIDEWAYS olarak).

**Düzeltme:** `scores` dict'ine `"LOW_VOL"` ekleyin ve düşük volatilite durumunda puan verin.

---

### HATA-18: Portfolio Manager — `get_metrics()` Sortino Ratio Yanlış Hesaplanıyor

**Dosya:** `services/portfolio/portfolio_manager.py`, satır ~520  
**Önem:** [YÜKSEK]

```python
downside = dr[dr < 0]
if len(downside) > 0 and np.std(downside) > 0:
    sortino = (np.mean(dr) / np.std(downside)) * np.sqrt(252)
```

**Sorun:** Sortino ratio'nun paydası "downside deviation" olmalı — yani `sqrt(mean(min(r, 0)^2))`. Mevcut kod `np.std(downside)` kullanıyor ki bu sadece negatif getirilerin standart sapması. Bu, negatif getirilerin ortalamasını sıfır kabul etmez ve farklı bir metrik hesaplar.

**Etki:** Sortino ratio yanlış hesaplanır, olduğundan yüksek veya düşük görünebilir.

**Düzeltme:** `downside_dev = np.sqrt(np.mean(np.minimum(dr, 0) ** 2))` kullanın.

---

### HATA-19: Risk Gate — `_daily_pnl` Asla Otomatik Sıfırlanmıyor

**Dosya:** `services/core/risk_gate.py`, satır ~30  
**Önem:** [YÜKSEK]

```python
class RiskGate:
    def __init__(self, ...):
        self._daily_pnl = 0.0
        # ...
    
    def reset_daily(self):
        self._daily_pnl = 0.0
```

**Sorun:** `reset_daily()` metodu var ama hiçbir scheduler veya cron tarafından çağrılmıyor. `_daily_pnl` bir kez negatif olduktan sonra asla sıfırlanmaz, günlük kayıp limiti kalıcı olarak tetiklenir.

**Etki:** Bir günlük kayıptan sonra sistem sonsuza kadar yeni pozisyon açmayı reddedebilir.

**Düzeltme:** Günlük scheduler'a `risk_gate.reset_daily()` çağrısı ekleyin.

---

### HATA-20: Scanner — `run_full_scan()` Instance Oluşturuyor Ama Kullanmıyor

**Dosya:** `services/scanner/opportunity_engine.py`, satır ~310  
**Önem:** [YÜKSEK]

```python
def run_full_scan(universe, market_data=None):
    results = []
    try:
        from .alpha_engine import AlphaEngine

        alpha = AlphaEngine()  # ← Instance oluşturuluyor
        results.append({"engine": "alpha", "status": "available"})  # ← Sadece status
    except ImportError:
        pass
```

**Sorun:** Her scanner engine için instance oluşturuluyor ama hiçbir tarama yapılmıyor. Sadece `"status": "available"` ekleniyor. Fonksiyon adı `run_full_scan` ama aslında sadece hangi modüllerin mevcut olduğunu kontrol ediyor.

**Etki:** Bu fonksiyon çağrıldığında gerçek tarama yapılmaz, sadece modül durumları döndürülür.

**Düzeltme:** Her engine için `alpha.scan(universe, market_data)` gibi gerçek tarama çağrısı yapın.

---

### HATA-21: Orchestrator — `run_full_pipeline` Import Hataları Sessizce Yutuluyor

**Dosya:** `services/core/orchestrator.py`, satır ~560  
**Önem:** [YÜKSEK]

```python
try:
    from services.macro import (
        macro_surprise_model,
        macro_regime_detector,
        macro_impact_analyzer,
        macro_stress_test,
        macro_correlation_tracker,
        macro_factor_decomposition,
    )
    from services.features.macro import macro_feature_engine
    # ...
except Exception as e:
    logger.warning("Macro pipeline failed", error=str(e))
```

**Sorun:** `services.macro` modülü mevcut olmayabilir (import hatası). Ama `except Exception` bloğu sadece log yazıyor ve devam ediyor. Bu durumda `macro_analysis` boş kalıyor ama `run_full_pipeline` sağlıklı çalışıyor gibi rapor veriyor.

**Etki:** Macro pipeline başarısız olduğunda kullanıcı bilgilendirilmez, rapor eksik veriyle üretilir.

**Düzeltme:** Macro pipeline kritikse hata fırlatın, değilse `system_health`'e `"macro": "unavailable"` ekleyin.

---

## ORTA HATALAR

### HATA-22: Event Consumer — `_processed_ids` Memory Leak Riski

**Dosya:** `services/core/event_bus.py`, satır ~340  
**Önem:** [ORTA]

```python
def _handle_event(self, event):
    if event.event_id in self._processed_ids:
        return
    # ...
    self._processed_ids.add(event.event_id)
    if len(self._processed_ids) > 50000:
        self._processed_ids = set(list(self._processed_ids)[-25000:])
```

**Sorun:** `_processed_ids` bir `set`. `set(list(...)[-25000:])` işlemi set'i listeye çevirir, son 25000 elemanı alır, tekrar set yapar. Bu, 50000 elemanlı set'i listeye çevirir (memory spike) ve sonra 25000'e düşürür. Ayrıca set'in sırası garantili olmadığı için "son 25000" kavramı anlamsız.

**Etki:** Periyodik memory spike'ları ve potansiyel duplicate processing.

**Düzeltme:** LRU cache veya TTL-based set kullanın.

---

### HATA-23: Portfolio Manager — `_record_equity()` Günlük Sayaçları Erken Sıfırlıyor

**Dosya:** `services/portfolio/portfolio_manager.py`, satır ~310  
**Önem:** [ORTA]

```python
def _record_equity(self):
    # ...
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today != self._last_snapshot_date:
        # Snapshot al
        snapshot = EquitySnapshot(
            realized_pnl_today=self._daily_realized_pnl,
            commission_today=self._daily_commission,
            # ...
        )
        # Günlük sayaçları sıfırla
        self._daily_realized_pnl = 0.0  # ← Erken sıfırlama
        self._daily_commission = 0.0
```

**Sorun:** `_record_equity()` her `update_prices()` çağrısında çalışır. İlk çağrıda (yeni gün) snapshot alınır ve sayaçlar sıfırlanır. Ama eğer gün içinde birden fazla `update_prices()` çağrısı varsa ve ilk çağrıdan önce gerçekleşen trade'ler varsa, bu trade'ler snapshot'a dahil olur ama sayaçlar sıfırlandıktan sonraki trade'ler bir sonraki güne kayar.

**Etki:** Günlük P&L snapshot'ları eksik veya yanlış olabilir.

**Düzeltme:** Sayaçları snapshot aldıktan SONRA sıfırlayın (zaten öyle) ama snapshot'ı günün sonunda alın, her `update_prices`'da değil.

---

### HATA-24: Compliance — SELL İşlemleri İçin Yanlış Pozisyon Hesabı

**Dosya:** `services/core/compliance.py`, satır ~60  
**Önem:** [ORTA]

```python
if action == "BUY":
    new_position_pct = current_position_pct + (amount / portfolio_value)
else:
    new_position_pct = current_position_pct  # ← SELL'de pozisyon azalır ama hesaplanmıyor
```

**Sorun:** SELL işleminde pozisyon yüzdesi azalır ama `new_position_pct` mevcut pozisyona eşit olarak kalıyor. Bu, SELL işleminin %5 veya %10 eşiğini aşıp aşmadığını kontrol etmeyi imkansızlaştırır.

**Etki:** SELL işlemlerinde SPK uyumluluk kontrolü yapılamaz.

**Düzeltme:** `else: new_position_pct = current_position_pct - (amount / portfolio_value)`

---

### HATA-25: Short Selling — `can_short_sell()` Uptick Rule Eksik Parametre

**Dosya:** `services/core/short_selling.py`, satır ~70  
**Önem:** [ORTA]

```python
def can_short_sell(self, ticker, current_price=0, last_trade_price=0):
    # ...
    if current_price > 0 and last_trade_price > 0:
        if current_price < last_trade_price:
            return ShortSellingDecision(allowed=False, ...)
```

**Sorun:** `risk_gate.py`'deki çağrıda `last_trade_price` parametresi verilmiyor:
```python
ss = short_selling_monitor.can_short_sell(ticker, price)  # Sadece 2 argüman
```
Bu durumda `last_trade_price=0` kalır ve uptick rule asla tetiklenmez.

**Etki:** Uptick rule kontrolü bypass edilir, yasadışı açığa satış yapılabilir.

**Düzeltme:** `risk_gate.py`'de `last_trade_price` parametresini geçirin.

---

### HATA-26: Monte Carlo — `np.random.seed()` Global State Kirliliği

**Dosya:** `services/simulation/monte_carlo_enhanced.py`, satır ~50  
**Önem:** [ORTA]

```python
def simulate(self, ..., seed=None):
    if seed is not None:
        np.random.seed(seed)  # ← Global random state'i değiştirir
```

**Sorun:** `np.random.seed()` global random state'i değiştirir. Eğer birden fazla Monte Carlo simülasyonu paralel çalışıyorsa, birbirlerinin random sequence'lerini bozarlar.

**Etki:** Paralel simülasyonlarda sonuçlar tekrarlanamaz veya korele olur.

**Düzeltme:** `np.random.default_rng(seed)` kullanarak lokal RNG oluşturun.

---

### HATA-27: Database — Global Pool Değişkenleri Thread-Safe Değil

**Dosya:** `services/core/database.py`, satır ~40  
**Önem:** [ORTA]

```python
_pg_pool = None
_pg_healthy = False


async def get_pg_pool():
    global _pg_pool, _pg_healthy
    if _pg_pool is None:
        _pg_pool = await asyncpg.create_pool(...)
```

**Sorun:** `get_pg_pool()` async fonksiyonu global `_pg_pool` değişkenini kontrol ediyor ve oluşturuyor. Eğer iki coroutine aynı anda çağırırsa, ikisi de `_pg_pool is None` kontrolünü geçebilir ve iki pool oluşturulabilir (race condition).

**Etki:** Nadir durumlarda iki pool oluşturulabilir, bağlantı sızıntısı.

**Düzeltme:** `asyncio.Lock()` kullanarak pool oluşturmayı kilitleyin.

---

### HATA-28: Worker — `_db_available()` Socket Bağlantısı Her Seferinde Açılıyor

**Dosya:** `services/core/worker.py`, satır ~180  
**Önem:** [ORTA]

```python
@staticmethod
def _db_available() -> bool:
    try:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        result = s.connect_ex(("127.0.0.1", 5432))
        s.close()
        return result == 0
    except Exception:
        return False
```

**Sorun:** Her job işlemi için TCP socket açılıp kapatılıyor. Bu, yüksek job throughput'unda overhead yaratır. Ayrıca sadece port'un açık olup olmadığını kontrol eder, DB'nin gerçekten çalışıp çalışmadığını değil.

**Etki:** Gereksiz network overhead, false positive (port açık ama DB çalışmıyor olabilir).

**Düzeltme:** Sonucu kısa süre cache'leyin (örn. 5 saniye TTL).

---

### HATA-29: Orchestrator — `run_pipeline` Agent Event Publish'de `get_event_loop()` Deprecated

**Dosya:** `services/core/orchestrator.py`, satır ~300  
**Önem:** [ORTA]

```python
try:
    _asyncio.get_event_loop().create_task(eb.publish("agent.analysis", event))
except RuntimeError:
    pass
```

**Sorun:** `asyncio.get_event_loop()` Python 3.10+ deprecation uyarısı verir ve aktif loop yoksa yeni bir loop oluşturmaz (RuntimeError). Ayrıca `create_task()` çalıştırılmamış task oluşturur, event sessizce kaybolabilir.

**Etki:** Agent event'leri publish edilemeyebilir.

**Düzeltme:** `publish_event()` fonksiyonunu kullanın veya event bus'ın sync publish metodunu çağırın.

---

### HATA-30: System Governor — Auto-Recovery RECOVERY State'inden FULL'e Geçemiyor

**Dosya:** `services/core/system_governor.py`, satır ~200  
**Önem:** [ORTA]

```python
elif self._state in (SystemState.DEGRADED, SystemState.READ_ONLY):
    if unhealthy_ratio < self._degradation_threshold:
        self.transition(SystemState.FULL, ...)
```

**Sorun:** `RECOVERY` state'i auto-recovery kontrolünde yok. Sistem `RECOVERY` state'ine geçtiğinde, otomatik olarak `FULL`'e dönemez — sadece `DEGRADED` ve `READ_ONLY`'den dönüş kontrol ediliyor.

**Etki:** Sistem RECOVERY'de kalabilir, manuel müdahale gerekir.

**Düzeltme:** `elif self._state in (SystemState.DEGRADED, SystemState.READ_ONLY, SystemState.RECOVERY):` yapın.

---

### HATA-31: DLQ — `_total_retried` Asla Artırılmıyor

**Dosya:** `services/core/dead_letter_queue.py`, satır ~150  
**Önem:** [ORTA]

```python
class DeadLetterQueue:
    def __init__(self):
        self._total_retried: int = 0  # ← Tanımlı ama asla artırılmıyor
    
    async def retry_failed(self, batch_size=100):
        # ...
        if handler:
            # Success
            self._total_resolved += 1  # ← resolved artırılıyor
            retried += 1
            # Ama _total_retried artırılmıyor!
```

**Sorun:** `_total_retried` sayaç tanımlı ama hiçbir yerde artırılmıyor. `get_stats()`'ta bu değer her zaman 0 olarak raporlanır.

**Etki:** DLQ istatistikleri eksik — retry edilen toplam sayısı bilinemez.

**Düzeltme:** `self._total_retried += 1` ekleyin (retry denemesi yapıldığında).

---

## DÜŞÜK HATALAR

### HATA-32: Regime Detector — `detect_regime` Type Hint `any` (Küçük harf)

**Dosya:** `services/core/regime_detector.py`, satır ~45  
**Önem:** [DÜŞÜK]

```python
def detect_regime(
    self,
    market_data: Dict[str, any],  # ← any → Any olmalı
```

**Sorun:** `any` Python built-in fonksiyonu, type hint olarak `typing.Any` kullanılmalı.

**Etki:** Çalışma zamanında etkisi yok ama type checker'lar uyarı verir.

**Düzeltme:** `Dict[str, Any]` yapın.

---

### HATA-33: Fee Calculator — BSMV Sadece Broker Fee Üzerinden Hesaplanıyor

**Dosya:** `services/core/fee_calculator.py`, satır ~60  
**Önem:** [DÜŞÜK]

```python
bsmv = broker_fee * self.BSMV_RATE  # Sadece broker fee
```

**Sorun:** BSMV (Banka ve Sigorta Muameleleri Vergisi) gerçekte toplam komisyon (broker + exchange + MKK) üzerinden hesaplanır. Mevcut kod sadece broker fee üzerinden hesaplıyor.

**Etki:** BSMV hafifçe düşük hesaplanır (MKK ve BIST payları hariç).

**Düzeltme:** `bsmv = (broker_fee + bist_fee + mkk_fee) * self.BSMV_RATE`

---

### HATA-34: Portfolio Manager — `get_risk_metrics()` İçinde `get_metrics()` Çağrısı Performans Sorunu

**Dosya:** `services/portfolio/portfolio_manager.py`, satır ~560  
**Önem:** [DÜŞÜK]

```python
def get_risk_metrics(self):
    # ...
    max_dd = self.get_metrics().get("max_drawdown_pct", 0)  # ← Pahalı çağrı
```

**Sorun:** `get_risk_metrics()` içinde `get_metrics()` çağrılıyor. `get_metrics()` tüm equity curve'i, trade'leri ve snapshot'ları işliyor — bu pahalı bir işlem. `get_risk_metrics()` API endpoint'inden çağrılırsa her istekte tüm metrikler yeniden hesaplanır.

**Etki:** Gereksiz CPU kullanımı, yavaş API yanıtları.

**Düzeltme:** `max_drawdown`'ı ayrı bir değişken olarak önbelleğe alın.

---

### HATA-35: Scanner — `_generate_signal()` REVERSAL Yön Mantığı Ters Olabilir

**Dosya:** `services/scanner/alpha_scanner.py`, satır ~220  
**Önem:** [DÜŞÜK]

```python
if r.signal_type == SignalType.REVERSAL:
    r.signal_direction = "LONG" if r.rsi < 35 else "SHORT"
```

**Sorun:** REVERSAL sinyali `r.rsi < 25 and r.roc_20d < -10` koşuluyla tetikleniyor (aşırı satım + güçlü düşüş). Ama yön belirlemede `r.rsi < 35` kullanılıyor — bu, REVERSAL tetiklenme koşulundan farklı bir eşik. Ayrıca `r.rsi >= 35` ise SHORT veriyor ama REVERSAL zaten aşırı satımda tetikleniyor.

**Etki:** REVERSAL sinyallerinde yön tutarsızlığı olabilir.

**Düzeltme:** REVERSAL tetiklenme koşuluyla aynı eşiği kullanın: `r.signal_direction = "LONG" if r.rsi < 25 else "SHORT"`

---

### HATA-36: Execution Simulator — Limit Emir Reddi Çok Agresif

**Dosya:** `services/simulation/execution_simulator.py`, satır ~90  
**Önem:** [DÜŞÜK]

```python
if order.side == OrderSide.BUY:
    fill_price = min(order.price, market_price * (1 + slippage))
    if order.price < market_price * (1 - spread_pct / 100):
        order.status = OrderStatus.REJECTED
        order.notes = "Limit price too far from market"
```

**Sorun:** BUY limit emrinde, limit fiyat piyasanın `spread_pct` altındaysa reddediliyor. Ama limit emirlerin amacı zaten piyasanın altından almak — bu kontrol çok agresif. `%0.1` spread için piyasadan sadece `%0.1` düşük limit bile reddedilir.

**Etki:** Normal limit emirler reddedilir.

**Düzeltme:** Eşiği `%5` gibi daha makul bir değere çıkarın veya spread yerine sabit bir tolerans kullanın.

---

### HATA-37: Streaming Anomaly — `check_price` Z-score Hesabında Tarihsel Veri Kullanılmıyor

**Dosya:** `services/core/streaming_anomaly.py`, satır ~50  
**Önem:** [DÜŞÜK]

```python
def check_price(self, ticker, price, previous_price, volatility=0.25):
    history = self._price_history[ticker]
    history.append(price)
    
    if len(history) >= 10:
        mean = np.mean(history)
        std = np.std(history)
        zscore = abs(price - mean) / std if std > 0 else 0
```

**Sorun:** Z-score hesabında mevcut fiyat (`price`) da history'ye dahil ediliyor. Bu, mevcut fiyatın ortalamayı ve standart sapmayı kendisinin etkilemesine neden olur — outlier detection'ı zayıflatır.

**Etki:** Anomali tespiti gecikmeli veya kaçırılabilir.

**Düzeltme:** Z-score hesabından önce `price`'ı history'ye ekleyin, sonra `history[:-1]` ile hesaplayın.

---

## ÖZET TABLO

| Önem | Sayı | Kategori |
|------|------|----------|
| KRİTİK | 8 | Tanımsız değişken, crash, yanlış muhasebe |
| YÜKSEK | 12 | İşlevsiz kod, yanlış hesaplama, memory leak |
| ORTA | 11 | Race condition, performans, eksik kontrol |
| DÜŞÜK | 6 | Tip hatası, kozmetik, minor optimizasyon |
| **TOPLAM** | **37** | |

## EN KRİTİK 5 SORUN (Öncelik Sırasıyla)

1. **HATA-08:** `main.py` import hatası — sistem hiç başlayamaz
2. **HATA-01:** `sector_map` tanımsız — agent pipeline çöker
3. **HATA-05/06:** SHORT pozisyon muhasebesi yanlış — finansal kayıp
4. **HATA-12:** Position sizing ters mantık — en iyi hisse en küçük pozisyon
5. **HATA-03:** `macro_impact_analyzer` tanımsız — macro pipeline çöker
