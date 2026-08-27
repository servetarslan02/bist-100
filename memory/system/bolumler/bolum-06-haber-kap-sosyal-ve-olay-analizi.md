# Bölüm 6 — Haber, KAP, Sosyal Medya ve Olay Analizi

## Amaç

Sayısal verilerin tek başına gösteremediği güncel gelişmeleri ve piyasa algısını analiz etmek.

**Kaynak:** Springer (2025) Stock Sentiment Rank Metric, NLP-based financial event extraction.

---

## Kullanılacak sistemler

- News Analysis
- KAP Analysis
- Social Sentiment
- Event Detection
- Catalyst Detection
- NLP / Embedding
- Source Verification
- Manipulation Detection

---

## Çalışma mantığı

```
Haber + KAP + Sosyal Medya → NLP/Embedding → Konu/Olay Tespiti →
Sentiment Analizi → Etki Analizi → Catalyst/Risk Tespiti →
Şirket Analizine Etki
```

---

## 1. KAP Analizi

**Yapılandırılmış extraction** — sadece pozitif/negatif değil.

### Örnek: KAP sınıflandırma

```python
# services/intelligence/kap_extractor.py
from services.intelligence.kap_extractor import kap_extractor

result = kap_extractor.extract("THYAO", "K001", "Şirketimiz yeni büyük sözleşme imzaladı. Tutar: 500M TL")
# event_type: CONTRACT
# financial_impact: +0.3
# surprise_score: 0.6
# time_horizon: MEDIUM
# affected_sectors: ["AVIATION"]
```

### Örnek: Sektör zincirleme etki

```python
from services.intelligence.kap_extractor import sector_chain

impacts = sector_chain.compute_chain_impact("ENERGY", 0.5)
# Enerji → Havacılık: -0.60 (yakıt maliyeti)
```

---

## 2. Haber Analizi

### Örnek: Haber feature'ları

```python
# services/features/sentiment.py
from services.features.sentiment import SentimentFeatureEngine

engine = SentimentFeatureEngine()
engine.add_news_event(
    "THYAO",
    {
        "sentiment": 0.8,
        "importance": 0.7,
        "credibility": 0.9,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    },
)
features = engine.compute_all_sentiment_features("THYAO")
# news_sentiment: 0.8, composite_sentiment: 0.7
```

---

## 3. Manipülasyon Kontrolü

### Örnek: Manipülasyon tespiti

```python
features = engine.compute_social_features("SUSPECT")
# social_manipulation_score: 0.6 (yüksek = şüpheli)
```

---

## 4. Catalyst Detection

Yaklaşan olayları takip eder ve potansiyel etkisini ölçer.

### Örnek: Catalyst tespiti

```python
# services/features/seven_motors.py → Motor 6
from services.features.seven_motors import CatalystMotor

motor = CatalystMotor()
catalysts = [
    {"type": "earnings", "importance": 0.9, "days_until": 5},
    {"type": "dividend", "importance": 0.7, "days_until": 15},
]
features = motor.compute("THYAO", catalysts)
# catalyst_count: 2
# catalyst_importance: 0.9
# catalyst_days_nearest: 5
```

---

## 5. Kaynak Doğrulama

Her bilginin kaynağını ve güvenilirliğini doğrular.

### Örnek: Kaynak güvenilirliği

```python
# services/ingestion/providers/news_provider.py
np = NewsProvider()
credibility = np.compute_credibility("Bloomberg")  # 0.95
credibility = np.compute_credibility("twitter")  # 0.40
```

---

## Çıktı

```
News Sentiment:        +72
KAP Impact:            +85
Social Sentiment:      +61
Catalyst:              Güçlü
Manipulation Risk:     Düşük
Overall Event Impact:  Pozitif
```

---

## Temel prensip

Haberleri sadece "pozitif/negatif" diye etiketlemek değil, olayın şirketin gelecekteki finansal değerini ve riskini nasıl değiştirebileceğini ölçmek.

---

## Event Study Entegrasyonu

**Kaynak:** Bölüm 31 — Event Study Methodology

Bu bölümün olay analizi, Bölüm 31'deki istatistiksel yöntemlerle derinleştirilir:

| Analiz | Bölüm 31 Motoru | Bölüm 6 Kullanımı |
|--------|----------------|-------------------|
| Expected Return | `event_study/expected_return.py` | Normal getiri tahmini |
| Abnormal Return | `event_study/abnormal_return.py` | Olağandışı getiri |
| CAR | `event_study/car.py` | Kümülatif etki |
| Statistical Test | `event_study/statistical_test.py` | Anlamlılık testi |
| KAP Event | `event_study/kap_event.py` | KAP açıklaması etkisi |

### Örnek: KAP → Event Study zinciri

```python
from services.event_study.kap_event import analyze_kap_event

# KAP açıklaması geldiğinde
result = analyze_kap_event("THYAO", "CONTRACT", event_date)
# result["car_5d"]: +3.2% (kümülatif abnormal getiri)
# result["significant"]: True (p < 0.05)

# Bu sonucu sentiment skoruna ekle
event_impact = result["car_5d"] * (1.5 if result["significant"] else 0.5)
```

### UYARI: Araştırma sonuçları production kuralı OLMAZ

Bölüm 31'deki CAR değerleri (örn. +1.2%) sabit olarak kullanılmamalı.
Her KAP açıklaması için event study yeniden hesaplanmalı.
