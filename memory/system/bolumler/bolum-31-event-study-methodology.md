# Bölüm 31 — Event Study Methodology

## Amaç

KAP açıklamalarının, makro olayların ve şirket haberlerinin fiyata etkisini akademik yöntemlerle ölçmek.

**Kaynak:** Event Study Methodology (MacKinlay, 1997), arXiv (2026) Event-Driven Trading.

---

## Kullanılacak sistemler

- Event Detector
- Abnormal Return Calculator
- Statistical Tester
- Event Window Manager
- Cumulative Abnormal Return (CAR) Calculator
- Event Impact Scorer

---

## Çalışma mantığı

```
Olay tespit et (KAP, haber, makro) → Event window belirle →
Abnormal return hesapla → CAR hesapla → İstatistiksel test →
Olayın fiyata etkisini ölç
```

---

## 1. Event Study Nedir?

Bir olayın hisse fiyatı üzerindeki etkisini ölçmek için kullanılan akademik yöntem:

```
1. Olay tarihi (t=0): KAP açıklaması, haber, makro karar
2. Event window: [t-5, t+5] (olaydan 5 gün önce ve sonra)
3. Estimation window: [t-250, t-6] (250 günlük tahmin dönemi)
4. Expected return: Normal getiri tahmini
5. Abnormal return: Gerçek - Beklenen getiri
6. CAR: Kümülatif abnormal getiri
```

---

## 2. Expected Return Hesaplama

### Market Model:
```
E[R_it] = α_i + β_i × R_mt + ε_it

R_it: Hisse getirisi
R_mt: Piyasa getirisi (BIST-100)
α_i, β_i: Tahmin parametreleri
```

### Örnek: Expected return

```python
# services/event_study/expected_return.py
import statsmodels.api as sm


def calculate_expected_return(stock_returns, market_returns, estimation_window):
    # Estimation window ile parametreleri tahmin et
    X = sm.add_constant(market_returns[estimation_window])
    model = sm.OLS(stock_returns[estimation_window], X).fit()

    alpha = model.params[0]
    beta = model.params[1]

    return alpha, beta
```

---

## 3. Abnormal Return Hesaplama

### Formül:
```
AR_it = R_it - E[R_it]

AR_it: Abnormal return
R_it: Gerçek getiri
E[R_it]: Beklenen getiri
```

### Örnek: Abnormal return

```python
# services/event_study/abnormal_return.py
def calculate_abnormal_return(stock_returns, market_returns, alpha, beta, event_window):
    expected = alpha + beta * market_returns[event_window]
    abnormal = stock_returns[event_window] - expected
    
    return abnormal
```

---

## 4. Cumulative Abnormal Return (CAR)

### Formül:
```
CAR[t1, t2] = Σ AR_it (t1'den t2'ye)
```

### Örnek: CAR hesaplama

```python
# services/event_study/car.py
def calculate_car(abnormal_returns, event_window):
    car = abnormal_returns.cumsum()
    
    return car
```

---

## 5. İstatistiksel Test

### t-test:
```
t = CAR / SE(CAR)

SE(CAR): Standart hata
p < 0.05 → Anlamlı
```

### Örnek: İstatistiksel test

```python
# services/event_study/statistical_test.py
from scipy import stats


def test_significance(car, std_error):
    t_stat = car / std_error
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=len(car) - 2))

    return {"t_statistic": t_stat, "p_value": p_value, "significant": p_value < 0.05}
```

---

## 6. KAP Açıklamaları için Event Study

### KAP olay türleri:
```
1. Finansal sonuçlar (çeyreklik, yıllık)
2. Temettü açıklaması
3. Sermaye artırımı
4. Sözleşme açıklaması
5. Yönetim değişikliği
6. Birleşme/devralma
7. Bedelsiz/bedelli sermaye artırımı
8. Geri alım programı
```

### Örnek: KAP event study

```python
# services/event_study/kap_event.py
def analyze_kap_event(ticker, event_type, event_date):
    # Veriyi al
    stock_data = get_stock_data(ticker, event_date - timedelta(days=300), event_date + timedelta(days=10))
    market_data = get_market_data(event_date - timedelta(days=300), event_date + timedelta(days=10))

    # Estimation window
    est_window = (stock_data.index >= event_date - timedelta(days=250)) & (
        stock_data.index < event_date - timedelta(days=5)
    )

    # Event window
    event_window = (stock_data.index >= event_date - timedelta(days=5)) & (
        stock_data.index <= event_date + timedelta(days=5)
    )

    # Expected return
    alpha, beta = calculate_expected_return(stock_data["returns"][est_window], market_data["returns"][est_window])

    # Abnormal return
    ar = calculate_abnormal_return(stock_data["returns"], market_data["returns"], alpha, beta, event_window)

    # CAR
    car = calculate_car(ar, event_window)

    # Significance test
    result = test_significance(car[-1], ar.std() / (len(ar) ** 0.5))

    return {
        "ticker": ticker,
        "event_type": event_type,
        "event_date": event_date,
        "car_5d": car[-1],
        "ar_day0": ar[0],
        "t_statistic": result["t_statistic"],
        "p_value": result["p_value"],
        "significant": result["significant"],
        "interpretation": "POSITIVE" if car[-1] > 0 else "NEGATIVE",
    }
```

---

## 7. Makro Olaylar için Event Study

### TCMB faiz kararı:
```
Event window: [t-2, t+2]
Beklenti: Piyasa beklentisi (anket)
Sürpriz: Gerçek - Beklenti
Etki: CAR = f(sürpriz büyüklüğü)
```

### Örnek: TCMB event study

```python
# services/event_study/macro_event.py
def analyze_tcmb_event(rate_actual, rate_expected, market_returns):
    surprise = rate_actual - rate_expected

    # Event window: faiz kararından 2 gün önce ve sonra
    event_window = market_returns[-5:]  # Son 5 gün

    # CAR hesapla
    car = event_window.cumsum()

    # Sürpriz ile CAR ilişkisi
    correlation = np.corrcoef([surprise], [car[-1]])[0, 1]

    return {
        "rate_actual": rate_actual,
        "rate_expected": rate_expected,
        "surprise": surprise,
        "car_5d": car[-1],
        "correlation": correlation,
        "interpretation": "POSITIVE" if surprise > 0 and car[-1] > 0 else "NEGATIVE",
    }
```

---

## 8. Event Impact Scoring

### Olay etkisi skoru:
```
Impact = |CAR| × Statistical_Significance × Volume_Change

|CAR|: Kümülatif abnormal getirinin mutlağı
Statistical_Significance: p < 0.05 → 1.0, p < 0.01 → 1.5
Volume_Change: Hacim değişimi katsayısı
```

### Örnek: Impact scoring

```python
# services/event_study/impact.py
def calculate_event_impact(car, p_value, volume_change):
    significance_multiplier = 1.5 if p_value < 0.01 else (1.0 if p_value < 0.05 else 0.5)

    impact = abs(car) * significance_multiplier * (1 + volume_change)

    # Skor: 0-100
    score = min(impact * 100, 100)

    return {
        "impact_score": score,
        "magnitude": "HIGH" if score > 50 else ("MEDIUM" if score > 20 else "LOW"),
        "direction": "POSITIVE" if car > 0 else "NEGATIVE",
    }
```

---

## 9. BIST için Event Study Bulguları

### Bulgular:
```
1. KAP açıklamaları: CAR[0,+1] = +1.2% (ortalama, anlamlı)
2. Temettü açıklaması: CAR[0,+1] = +0.8% (anlamlı)
3. TCMB faiz sürprizi: CAR[-1,+1] = -2.5% (100bp artış için)
4. Döviz kuru şoku: CAR[0,+2] = -3.1% (%5+ USDTRY artışı)
5. Sermaye artırımı: CAR[-5,0] = -2.8% (beklenti fiyatlaması)
```

---

## Çıktı

```
Event Type:           KAP - Finansal Sonuçlar
Ticker:               THYAO
CAR[-5,+5]:           +3.2%
AR[0]:                +1.8%
t-statistic:          2.45
p-value:              0.014
Significant:          Yes (p < 0.05)
Impact Score:         72/100 (HIGH)
Direction:            POSITIVE
```

---

## Temel prensip

Event study, olayların fiyata etkisini akademik rigor ile ölçer. **KAP açıklamalarının, TCMB kararlarının ve döviz şoklarının BIST üzerindeki etkisini ölçmek için standart bir yöntemdir.**

> Kaynak: MacKinlay (1997) Event Studies in Economics and Finance, arXiv (2026) Event-Driven Trading
