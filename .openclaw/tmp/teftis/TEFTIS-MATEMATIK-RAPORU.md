# 🔬 BIST-100 ALPHA — Matematiksel & Finansal Hata Teftiş Raporu

**Tarih:** 2026-08-21  
**Kapsam:** services/risk, backtest, features, intelligence, macro, factors, event_study, ml, viop  
**Toplam Taranan Dosya:** ~40+ Python modülü  
**Toplam Tespit Edilen Hata:** 25

---

## ÖZET

| Öncelik | Sayı |
|---------|------|
| 🔴 KRİTİK | 6 |
| 🟠 YÜKSEK | 8 |
| 🟡 ORTA | 7 |
| 🟢 DÜŞÜK | 4 |

---

## 🔴 KRİTİK HATALAR

---

### HATA #1 — Monte Carlo Portföy Simülasyonu: Korelasyon Matrisi Yanlış Uygulanıyor

**Dosya:** `services/intelligence/monte_carlo.py`, satır ~158  
**Kod:**
```python
correlated_Z = np.einsum('ijk,lk->ijl', Z, L)  # Bu hatalı, düzelt
```

**Sorun:** `np.einsum('ijk,lk->ijl', Z, L)` ifadesi matematiksel olarak yanlış. Z'nin shape'i `(n_sims, horizon_days, n_assets)` ve L'nin shape'i `(n_assets, n_assets)`. Doğru einsum ifadesi `np.einsum('ijk,lk->ijl', Z, L)` değil, `Z @ L.T` olmalı (veya `np.einsum('ijk,lk->ijl', Z, L.T)`). Ayrıca yorumda "Bu hatalı, düzelt" yazıyor — kod bilinen bir hatayla deploy edilmiş.

**Doğru Formül:**
```python
correlated_Z = Z @ L.T  # (n_sims, horizon_days, n_assets) @ (n_assets, n_assets)
# VEYA
correlated_Z = np.einsum('ijk,lk->ijl', Z, L.T)
```

**Etki:** Korele edilmiş Monte Carlo simülasyonları tamamen yanlış sonuç üretir. Portföy riski yanlış hesaplanır.

**Önerilen Düzeltme:**
```python
correlated_Z = Z @ L.T
```

---

### HATA #2 — Position Sizing: Score Semantik Çelişkisi (İki Farklı Yorum)

**Dosya:** `services/risk/position_sizing.py`, satır ~127 ve ~135  
**Kod:**
```python
# Cold-start (satır ~127): score yüksek = iyi
base_weight = max(0.1, min(1.0, score / 20.0))  # score=100 → 1.0

# Score weight (satır ~135): score düşük = iyi (!)
score_weight = max(0.1, 1.0 - score / 20.0)  # score=100 → 0.1 (!)
```

**Sorun:** Aynı `score` değişkeni için iki zıt yorum kullanılıyor:
- Cold-start bloğunda: yüksek score → yüksek ağırlık (doğru)
- Score weight bloğunda: yüksek score → düşük ağırlık (yanlış!)

Bu çelişki nedeniyle final weight = `base_weight × score_weight` = `(score/20) × (1 - score/20)` olur. score=50 için: `2.5 × 0.5 = 1.25`, score=100 için: `5.0 × 0.1 = 0.5`. En iyi skorlu hisse EN DÜŞÜK ağırlığı alır!

**Doğru Formül:**
```python
# Her iki yerde de aynı semantik kullanılmalı
# score yüksek = iyi (ranking_model ile tutarlı)
score_weight = max(0.1, score / 100.0)  # score=100 → 1.0, score=0 → 0.1
```

**Etki:** En iyi hisselere en küçük pozisyon atanır — strateji tersine döner.

---

### HATA #3 — Backtest Engine v1.0: Equity Güncellemede Look-Ahead Bias

**Dosya:** `services/backtest/engine.py`, satır ~115  
**Kod:**
```python
# Equity güncelle
total_value = capital
for t, p in positions.items():
    # Güncel fiyat (signal'dan veya price_data'dan)
    current_price = price if t == ticker else p["avg_cost"]
    total_value += p["qty"] * current_price
```

**Sorun:** `price` değişkeni mevcut signal'ın fiyatıdır. Eğer signal THYAO için ise, THYAO pozisyonu güncel fiyatla değerlenir ama GARAN pozisyonu hâlâ `avg_cost` ile değerlenir — bu yanlış. Ayrıca `price` geleceğe ait olabilir (signal tarihindeki fiyat zaten biliniyor).

**Doğru Formül:**
```python
# Her pozisyon için o tarihteki kapanış fiyatını kullan
for t, p in positions.items():
    if t in price_data and date in price_data[t]:
        current_price = price_data[t][date]["close"]
    else:
        current_price = p["avg_cost"]  # Fallback
    total_value += p["qty"] * current_price
```

**Etki:** Equity curve ve tüm metrikler (Sharpe, drawdown, vb.) yanlış hesaplanır.

---

### HATA #4 — Covariance Estimator: Ledoit-Wolf Shrinkage Formülü Hatalı

**Dosya:** `services/risk/covariance.py`, satır ~85-95  
**Kod:**
```python
# Pi: Sample covariance variance
pi = 0
for i in range(n_assets):
    for j in range(n_assets):
        diff = returns[:, i] * returns[:, j] - sample_cov[i, j]
        pi += np.sum(diff ** 2)
pi /= n_samples  # ← HATALI

# Rho: Target bias
rho = np.sum((target - sample_cov) ** 2)  # ← HATALI

# Gamma: Target variance
gamma = np.sum(target ** 2)  # ← KULLANILMIYOR

# Optimal shrinkage
if pi + rho > 0:
    delta = max(0, min(1, pi / (pi + rho)))
```

**Sorunlar:**
1. `pi` hesabında `n_samples`'e bölünüyor ama doğru formül `pi = (1/n²) × Σᵢ Σⱼ (...)` şeklindedir — `n_samples²`'ye bölmeli.
2. `rho` hesabında `(target - sample_cov)²` kullanılıyor ama bu da `n_samples`'e bölünmeli.
3. `gamma` hesaplanıyor ama hiç kullanılmıyor — formülde gerekli.
4. Standart Ledoit-Wolf formülü: `δ = max(0, min(1, (π - ρ) / γ))` veya daha basit `δ = π / (π + ρ)` — ama normalize edilmiş hali.

**Doğru Formül (Ledoit-Wolf 2004):**
```python
pi = 0
for i in range(n_assets):
    for j in range(n_assets):
        diff = returns[:, i] * returns[:, j] - sample_cov[i, j]
        pi += np.sum(diff ** 2)
pi /= n_samples ** 2  # ← n²'ye böl

rho = np.sum((target - sample_cov) ** 2)  # Bu zaten doğru (scalar)

delta = max(0, min(1, pi / (pi + rho)))  # Basitleştirilmiş formül
```

**Etki:** Shrinkage intensity yanlış hesaplanır → kovaryans matrisi ya çok fazla ya çok az shrink edilir → portföy optimizasyonu bozulur.

---

### HATA #5 — RSI Hesaplaması: İki Farklı Implementasyon (Tutarsızlık)

**Dosya:** `services/features/calculator.py`, satır ~270 (`_rsi_masked`) vs `services/features/technical_features.py`, satır ~130 (`_rsi`)

**calculator.py (YANLIŞ):**
```python
def _rsi_masked(self, data, period=14):
    avg_gain = np.mean(gains[-period:])  # Basit ortalama
    avg_loss = np.mean(losses[-period:])
```

**technical_features.py (DOĞRU):**
```python
def _rsi(self, prices, period=14):
    avg_gain = np.mean(gains[:period])  # İlk ortalama
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period  # Wilder's smoothing
```

**Sorun:** `calculator.py` basit hareketli ortalama kullanırken, `technical_features.py` Wilder's exponential smoothing kullanır. Bu iki farklı formül farklı RSI değerleri üretir. Wilder's smoothing endüstri standardıdır.

**Etki:** Backtest ve live trading farklı RSI değerleri kullanır → sonuçlar tutarsız.

**Önerilen Düzeltme:** `calculator.py`'deki `_rsi_masked` metodunu Wilder's smoothing ile güncelle.

---

### HATA #6 — Monte Carlo: Global Random State Kullanımı (Reproducibility İhlali)

**Dosya:** `services/intelligence/monte_carlo.py`, satır ~55 ve ~130  
**Kod:**
```python
if seed is not None:
    np.random.seed(seed)  # ← GLOBAL STATE
```

**Sorun:** `np.random.seed()` global random state'i değiştirir. Eğer paralel işlemler veya başka modüller rastgele sayı üretiyorsa, bu çakışmalara ve reproducibility sorunlarına yol açar.

**Doğru Formül:**
```python
rng = np.random.default_rng(seed)  # Yerel RNG
Z = rng.standard_normal((n_sims, horizon_days))
```

**Etki:** Paralel çalışmalarda sonuçlar tekrarlanamaz. Aynı seed farklı sonuçlar üretebilir.

---

## 🟠 YÜKSEK HATALAR

---

### HATA #7 — Sortino Ratio: Downside Deviation Yanlış Hesaplanıyor

**Dosya:** `services/backtest/engine.py`, satır ~155  
**Kod:**
```python
downside_returns = np.minimum(returns, 0)
downside_std = np.sqrt(np.mean(downside_returns ** 2))
sortino = (np.mean(returns) / downside_std * np.sqrt(252)) if downside_std > 0 else 0
```

**Sorun:** `np.minimum(returns, 0)` tüm negatif getirileri alır ama pozitif getirileri 0 yapar. Bu doğru. Ancak standart Sortino formülünde downside deviation şu şekilde hesaplanır:

`DD = √(min(r - target, 0)²)` ortalama

Kod `target = 0` varsayıyor (makul). Ama `np.minimum(returns, 0)` yerine `np.minimum(returns - target, 0)` kullanılmalı (target=0 olduğunda aynı şey, ama esneklik yok).

**Asıl Sorun:** `downside_std` hesaplaması `np.sqrt(np.mean(downside_returns ** 2))` — bu tüm gözlemleri dahil ediyor (pozitif olanlar 0). Standart formül sadece negatif getirilerin karelerinin ortalamasını alır:

```python
# Doğru:
negative_returns = returns[returns < 0]
downside_std = np.sqrt(np.mean(negative_returns ** 2)) if len(negative_returns) > 0 else 0
```

**Etki:** Sortino ratio olduğundan yüksek görünür (daha az negatif getiri dahil edildiğinden std daha düşük çıkar).

---

### HATA #8 — CAGR Hesaplaması: Zaman Birimi Uyuşmazlığı

**Dosya:** `services/backtest/engine.py`, satır ~160  
**Kod:**
```python
cagr_pct=round(((final / initial_capital) ** (1 / max(len(equity_curve) / 252, 0.01)) - 1) * 100, 2)
```

**Sorun:** `len(equity_curve)` equity curve'deki nokta sayısıdır. Bu noktalar her signal için eklenir (her gün değil). Eğer bir günde 5 signal varsa, 5 equity noktası oluşur. Bu durumda `len(equity_curve) / 252` gerçek yıl sayısını vermez.

**Doğru Formül:**
```python
# Gerçek gün sayısı kullanılmalı
n_days = (end_date - start_date).days
years = max(n_days / 365.25, 0.01)
cagr = (final / initial_capital) ** (1 / years) - 1
```

**Etki:** CAGR yanlış hesaplanır — signal yoğunluğuna bağlı olarak olduğundan yüksek veya düşük çıkabilir.

---

### HATA #9 — Walk-Forward Deflated Sharpe: Standart Olmayan Uygulama

**Dosya:** `services/backtest/walk_forward.py`, satır ~175  
**Kod:**
```python
def _deflated_sharpe(self, sharpe, n_obs, n_trials=1):
    daily_sharpe = sharpe / np.sqrt(252)
    se = np.sqrt((1 + 0.5 * daily_sharpe**2) / n_obs)
    if n_trials > 1:
        adjusted_sharpe = daily_sharpe - se * np.sqrt(2 * np.log(n_trials))
    else:
        adjusted_sharpe = daily_sharpe
    return max(0, adjusted_sharpe * np.sqrt(252))
```

**Sorun:** Bu formül Bailey & López de Prado (2014) Deflated Sharpe Ratio'su değil, basit bir Bonferroni düzeltmesi. Gerçek DSR:
1. E[max_SR] hesaplamalı (N stratejiden beklenen max Sharpe)
2. SR'ın bu beklenen max'tan ne kadar uzak olduğunu test etmeli
3. Skewness ve kurtosis düzeltmesi uygulamalı

Ayrıca `deflated_sharpe.py` dosyasında zaten doğru bir implementasyon var — bu modül neden farklı bir formül kullanıyor?

**Etki:** Multiple testing düzeltmesi yanlış → overfitting tespit edilemeyebilir.

---

### HATA #10 — Macro Inflation: Yıllıklandırılmış Aylık Enflasyon Yanlış

**Dosya:** `services/macro/inflation.py`, satır ~60  
**Kod:**
```python
features["inf_cpi_annualized"] = round(float(cpi_monthly) * 12, 2)
```

**Sorun:** Aylık enflasyonu yıllıklaştırmak için basit çarpma (×12) yerine bileşik formül kullanılmalı:

**Doğru Formül:**
```python
features["inf_cpi_annualized"] = round(((1 + float(cpi_monthly) / 100) ** 12 - 1) * 100, 2)
```

**Örnek:** Aylık %3 enflasyon:
- Yanlış: %3 × 12 = %36
- Doğru: (1.03)^12 - 1 = %42.6

**Etki:** Yüksek enflasyon dönemlerinde yıllıklaştırma ciddi şekilde düşük kalır.

---

### HATA #11 — Fundamental Feature: Format Tespiti Kırılgan

**Dosya:** `services/features/fundamental.py`, satır ~55-75  
**Kod:**
```python
@staticmethod
def _detect_format(fundamentals):
    # ...
    if ratio >= 0.8 and len(values) >= 2:
        median_val = sorted(values)[len(values) // 2]
        if abs(median_val) < 1:
            return "decimal"
    return "percentage"
```

**Sorun:** Bu heuristic birçok durumda yanlış çalışır:
1. **Karışık format:** ROE=0.13 (decimal), gross_margin=35 (percentage) → heuristic "percentage" der → ROE = 0.13% olur (yanlış, %13 olmalı)
2. **Küçük ama geçerli percentage:** profit_margin=0.5 (%0.5) → heuristic "decimal" der → 0.5 × 100 = %50 olur (yanlış!)
3. **Negatif değerler:** ROE=-0.05 (decimal, zarar) → abs(-0.05) < 1 → "decimal" → -0.05 × 100 = -5% (doğru ama şans eseri)

**Önerilen Düzeltme:** Format tespiti kaldırılmalı. Kaynak veriye `format` metadata'sı eklenmeli veya varsayılan olarak percentage kullanılmalı.

---

### HATA #12 — Elder Ray: Bull Power = Bear Power (Aynı Formül)

**Dosya:** `services/features/extended_indicators.py`, satır ~115  
**Kod:**
```python
def compute_elder_ray(self, close, period=13):
    ema = self._ema(close, period)
    bull_power = close[-1] - ema
    bear_power = close[-1] - ema  # ← AYNI HESAPLAMA
```

**Sorun:** Elder Ray'de:
- **Bull Power** = High - EMA (yüksek fiyatın EMA'dan uzaklığı)
- **Bear Power** = Low - EMA (düşük fiyatın EMA'dan uzaklığı)

Kod her ikisi için de `close - EMA` kullanıyor — bu yanlış.

**Doğru Formül:**
```python
bull_power = high[-1] - ema
bear_power = low[-1] - ema
```

**Etki:** Elder Ray sinyalleri tamamen yanlış üretilir.

---

### HATA #13 — Monte Carlo Portföy: Performans Sorunu (O(n²) Loop)

**Dosya:** `services/intelligence/monte_carlo.py`, satır ~170-180  
**Kod:**
```python
for sim in range(num_simulations):
    for day in range(horizon_days):
        stock_returns = np.array([
            (returns_annual[i] - 0.5 * vols_annual[i] ** 2) * dt
            + correlated_Z[sim, day, i]
            for i in range(n)
        ])
        daily_returns[sim, day] = np.sum(weights * stock_returns)
```

**Sorun:** İç içe döngüler O(n_sims × horizon_days × n_assets) karmaşıklığa sahip. 10,000 simülasyon × 20 gün × 50 hisse = 10 milyon iterasyon. Bu çok yavaş.

**Doğru Formül (Vektörize):**
```python
drift = (returns_annual - 0.5 * vols_annual ** 2) * dt
daily_returns = np.einsum('ijk,k->ij', correlated_Z, weights) + np.sum(weights * drift)
```

**Etki:** Portföy Monte Carlo dakikalarca sürebilir, gerçek zamanlı kullanılamaz.

---

### HATA #14 — Kovaryans: Condition Number Hesabında np.max(np.min(...)) Sorunu

**Dosya:** `services/risk/covariance.py`, satır ~70  
**Kod:**
```python
eigvals = np.linalg.eigvalsh(shrunk_cov)
condition_number = np.max(eigvals) / np.max(np.min(eigvals), 1e-10)
```

**Sorun:** `np.max(np.min(eigvals), 1e-10)` — `np.min(eigvals)` bir skalar döndürür. `np.max()` tek argümanla çağrıldığında o skaları döndürür. Yani `np.max(np.min(eigvals), 1e-10)` aslında `np.max(scalar, 1e-10)` değil, `np.max(scalar)` — ikinci argüman göz ardı edilir.

**Doğru Formül:**
```python
condition_number = np.max(eigvals) / max(np.min(eigvals), 1e-10)
```

**Etki:** Negatif eigenvalue durumunda division by zero veya negatif condition number.

---

## 🟡 ORTA HATALAR

---

### HATA #15 — Parametrik VaR: Formül Yorumu Yanıltıcı

**Dosya:** `services/risk/var_cvar.py`, satır ~75  
**Kod:**
```python
# VaR = μ + σ × z_α × √t
z_alpha = norm.ppf(1 - confidence)  # 0.05 → -1.645
var_pct = mu + sigma * z_alpha * np.sqrt(holding_period_days)
var_amount = abs(var_pct * portfolio_value)
```

**Sorun:** Formül yorumu `VaR = μ + σ × z_α × √t` olarak yazılmış ama z_α negatif olduğundan var_pct negatif çıkar ve `abs()` ile pozitif yapılır. Yorumda bu belirtilmemiş.

**Doğru Yorum:**
```python
# VaR = -(μ + σ × z_α × √t)  [z_α negatif, VaR pozitif]
# VEYA
# VaR = |μ + σ × z_α × √t|
```

**Etki:** Kod doğru çalışıyor ama bakım yapan kişi formülü yanlış anlayabilir.

---

### HATA #16 — Piotroski F-Score: Normalize Yuvarlama Sorunu

**Dosya:** `services/factors/piotroski.py`, satır ~85  
**Kod:**
```python
normalized_score = round(score * 9 / max_score) if max_score > 0 else 0
```

**Sorun:** `round()` Python'da banker's rounding kullanır (0.5'te en yakın çift sayıya yuvarlar). Bu durumda:
- score=3.5, max_score=9 → 3.5 × 9/9 = 3.5 → round(3.5) = 4 (beklenen) Ama
- score=2.5 → round(2.5) = 2 (beklenen 3)

Daha önemlisi, ağırlıklı skorlama sisteminde bu yuvarlama kritik olabilir.

**Önerilen Düzeltme:**
```python
normalized_score = int(score * 9 / max_score + 0.5) if max_score > 0 else 0
```

**Etki:** Sınır durumlarda F-Score 1 puan yanlış olabilir → BUY/SELL sinyali değişebilir.

---

### HATA #17 — Walk-Forward: Sharpe Ratio Drawdown Hesabı Yanlış

**Dosya:** `services/backtest/walk_forward.py`, satır ~145  
**Kod:**
```python
cumulative = np.cumsum(returns_arr)
peak = np.maximum.accumulate(cumulative)
drawdown = (peak - cumulative) / np.maximum(peak, 1e-10)
max_dd = np.max(drawdown) * 100
```

**Sorun:** `cumulative = np.cumsum(returns_arr)` — bu kümülatif getiri değil, kümülatif toplam. Getiriler zaten yüzde ise (ör. 0.05 = %5), kümülatif toplam anlamlı değil. Kümülatif getiri olmalı:

**Doğru Formül:**
```python
cumulative = np.cumprod(1 + returns_arr)  # Kümülatif getiri
peak = np.maximum.accumulate(cumulative)
drawdown = (peak - cumulative) / peak
```

**Etki:** Drawdown hesaplaması yanlış → risk metrikleri güvenilir değil.

---

### HATA #18 — Altman Z-Score: Türkiye Düzeltmesi Standart Değil

**Dosya:** `services/factors/altman.py`, satır ~45  
**Kod:**
```python
z_adjusted = z_original * inf_adj * fx_adj * sec_adj
# inf_adj = 0.85, fx_adj = 0.90
```

**Sorun:** Orijinal Altman Z-Score (1968) ABD şirketleri için kalibre edilmiş. Türkiye'ye uyarlama:
1. Enflasyon düzeltmesi (×0.85) ve kur düzeltmesi (×0.90) standart literatürde yok
2. Bu çarpanlar nereden geldi? Referans yok
3. Sektör çarpanları da (BANKA=1.10, INSAAT=0.88) ampirik olarak doğrulanmamış

**Önerilen Düzeltme:** Türkiye'ye özgü Z-Score modeli için:
1. Kaynak/referans belirtilmeli
2. Veya orijinal Altman formülü kullanılmalı (turkey_adjusted=False)
3. Veya Türkiye verileriyle yeniden kalibre edilmeli

**Etki:** Z-Score eşikleri (2.99, 1.81) Türkiye için geçersiz olabilir.

---

### HATA #19 — Backtest Engine v4.0: Canonical Scoring'de CS Normalization Sırası

**Dosya:** `services/backtest/engine_v4.py`, satır ~1090+  
**Kod:**
```python
# SELL sinyalleri için features topla
features = self._get_features(ticker, date_str, df_until, effective_lookback, cfg)
# ...
score = self._compute_score(features, ...)
```

**Sorun:** SELL sinyallerinde `all_day_features` parametresi geçilmiyor (sadece `features` var). Canonical scoring modunda CS normalization uygulanamaz. BUY sinyallerinde `day_features_fast` geçiliyor ama SELL'de geçilmiyor.

**Etki:** SELL skorları ile BUY skorları farklı normalization kullanır → tutarsız kararlar.

---

### HATA #20 — Black-Scholes: Rho Formülü (Put)

**Dosya:** `services/viop/enhanced_options.py`, satır ~85  
**Kod:**
```python
# Put rho:
rho = -K * T * np.exp(-r * T) * norm.cdf(-d2) / 100
```

**Sorun:** Standart put rho formülü: `ρ_put = -K × T × e^(-rT) × N(-d₂)`. Bu doğru. Ancak `/100` böleni rho'yu "%1 faiz değişimi etkisi" formatına çeviriyor — bu convention farklı kaynaklarda farklı. Kodda call rho'da da `/100` var, tutarlı.

**Not:** Bu bir hata değil, convention notu. Ama kullanıcılar rho değerini doğrudan kullanırsa yanlış anlayabilir.

---

### HATA #21 — Macro Regime Detector: __import__ Kullanımı

**Dosya:** `services/macro/regime_detector.py`, satır ~180  
**Kod:**
```python
recent_transitions = [
    t for t in self._transitions
    if t.timestamp > (datetime.now(timezone.utc) - __import__("datetime").timedelta(days=30)).isoformat()
]
```

**Sorun:** `__import__("datetime")` runtime'da import yapıyor — bu kötü pratik ve performans sorunu. Ayrıca `datetime` zaten dosyanın başında import edilmiş.

**Doğru Formül:**
```python
from datetime import timedelta
# ...
recent_transitions = [
    t for t in self._transitions
    if t.timestamp > (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
]
```

---

## 🟢 DÜŞÜK HATALAR

---

### HATA #22 — NewsDuplicationEngine: hashlib Import Eksik

**Dosya:** `services/intelligence/forecasting.py`, satır ~195  
**Kod:**
```python
class NewsDuplicationEngine:
    def is_duplicate(self, title, source):
        title_hash = hashlib.md5(...)  # hashlib henüz import edilmemiş
```

**Sorun:** `import hashlib` dosyanın en altında (satır ~250) yapılıyor ama sınıf daha önce tanımlanmış. Eğer sınıf import edilmeden önce kullanılmaya çalışılırsa `NameError` verir.

**Önerilen Düzeltme:** `import hashlib`'i dosyanın başına taşı.

---

### HATA #23 — Sharpe Ratio: Risk-Free Rate Dahil Değil

**Dosya:** `services/backtest/engine.py`, satır ~150  
**Kod:**
```python
sharpe = (np.mean(returns) / np.std(returns) * np.sqrt(252)) if np.std(returns) > 0 else 0
```

**Sorun:** Sharpe ratio formülü: `SR = (R_p - R_f) / σ_p`. Risk-free rate (R_f) dahil edilmemiş. Türkiye'de risksiz faiz yüksek olduğundan (2024-2026: %40-50), bu önemli bir eksiklik.

**Doğru Formül:**
```python
daily_rf = annual_rf_rate / 252
excess_returns = returns - daily_rf
sharpe = (np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252)) if np.std(excess_returns) > 0 else 0
```

**Etki:** Sharpe ratio olduğundan yüksek görünür (risk-free rate düşülmemiş).

---

### HATA #24 — HMM Regime: Transition Entropy Normalize Yanlış

**Dosya:** `services/intelligence/hmm_regime.py`, satır ~200  
**Kod:**
```python
def _compute_transition_entropy(self):
    entropy = 0.0
    for row in self._transition_matrix:
        for p in row:
            if p > 0:
                entropy -= p * np.log2(p)
    return round(float(entropy / self.n_regimes), 4)
```

**Sorun:** Toplam entropy `n_regimes`'e bölünüyor. Standart normalize entropy: `H_norm = H / log2(n_states)`. Ayrıca her satır için ayrı entropy hesaplanmalı (row-stochastic matrix).

**Doğru Formül:**
```python
max_entropy = np.log2(self.n_regimes)
return round(float(entropy / (self.n_regimes * max_entropy)), 4)
```

---

### HATA #25 — SPAN Margin: Vega P&L Yorumu

**Dosya:** `services/viop/enhanced_options.py`, satır ~420  
**Kod:**
```python
# Vega P&L: vega zaten "per 1% vol" cinsinden (calculate_greeks'te /100)
# vol_change=0.02 demek %2 vol artışı demek
# vega * vol_change * 100 = vega * (vol_change * 100) = vega * yüzde_değişimi
vega_pnl = vega * scenario["vol_change"] * 100
```

**Sorun:** Yorum doğru ama karmaşık. `calculate_greeks`'te vega zaten `/100` ile bölünmüş (yani vega = %1 vol etkisi). `vol_change=0.02` = %2 vol artışı. Doğru formül: `vega_pnl = vega * (vol_change * 100)` = `vega * 2`. Bu doğru.

**Not:** Kod doğru, sadece yorum karmaşık. Bakım için açıklama yeterli.

---

## EK: KONTROL EDİLEN FORMÜLLER (DOĞRU)

| Formül | Dosya | Durum |
|--------|-------|-------|
| Black-Scholes Call/Put | enhanced_options.py | ✅ Doğru |
| Greeks (Delta, Gamma, Theta, Vega) | enhanced_options.py | ✅ Doğru |
| Implied Volatility (Newton-Raphson + Bisection) | enhanced_options.py | ✅ Doğru |
| Put-Call Parity | enhanced_options.py | ✅ Doğru |
| Futures-Spot Arbitrage (Cost of Carry) | enhanced_options.py | ✅ Doğru |
| Risk Parity Optimization | risk_parity.py | ✅ Doğru |
| Kelly Criterion | position_sizing.py | ✅ Doğru |
| Abnormal Return (Market Model) | abnormal_return.py | ✅ Doğru |
| CAR Significance Test (t-test) | statistical_test.py | ✅ Doğru |
| Bonferroni Correction | statistical_test.py | ✅ Doğru |
| Benjamini-Hochberg FDR | statistical_test.py | ✅ Doğru |
| Brier Score | calibration.py | ✅ Doğru |
| Expected Calibration Error (ECE) | calibration.py | ✅ Doğru |
| Platt Scaling | calibration.py | ✅ Doğru |
| HHI (Herfindahl-Hirschman) | enhanced_risk.py | ✅ Doğru |
| GBM (Geometric Brownian Motion) | monte_carlo.py | ✅ Doğru |
| Jump-Diffusion (Merton) | advanced_monte_carlo.py | ✅ Doğru |
| Student-t Simulation | advanced_monte_carlo.py | ✅ Doğru |
| Heston-lite Stochastic Vol | advanced_monte_carlo.py | ✅ Doğru |
| Fama-French Factor Scores | fama_french.py | ✅ Doğru |
| Cross-Sectional Z-Score | training_validator.py | ✅ Doğru |
| NDCG@k | training_validator.py | ✅ Doğru |
| Survivorship Bias Handler | survivorship.py | ✅ Doğru |
| Transaction Cost Model | transaction_costs.py | ✅ Doğru |
| Drawdown Response System | drawdown_response.py | ✅ Doğru |
| Tail Risk Hedging | tail_hedge.py | ✅ Doğru |

---

## ÖNERİLEN ÖNCELİKLI DÜZELTMELER

1. **HATA #1** (Monte Carlo korelasyon) — Acil. Korele simülasyonlar tamamen yanlış.
2. **HATA #2** (Position sizing score) — Acil. En iyi hisselere en küçük pozisyon.
3. **HATA #5** (RSI tutarsızlığı) — Yüksek. Backtest/live parity ihlali.
4. **HATA #3** (Look-ahead bias) — Yüksek. Backtest sonuçları güvenilir değil.
5. **HATA #4** (Ledoit-Wolf) — Yüksek. Kovaryans tahmini bozuk.
6. **HATA #7** (Sortino) — Orta. Risk metrikleri yanlış.
7. **HATA #10** (Enflasyon annualization) — Orta. Makro feature'lar yanlış.
8. **HATA #12** (Elder Ray) — Orta. Teknik sinyal yanlış.

---

*Rapor sonu. 2026-08-21 tarihinde otomatik matematiksel teftiş ile üretilmiştir.*
