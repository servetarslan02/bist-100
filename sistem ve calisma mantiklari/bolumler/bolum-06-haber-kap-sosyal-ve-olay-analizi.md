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

result = kap_extractor.extract("THYAO", "K001",
    "Şirketimiz yeni büyük sözleşme imzaladı. Tutar: 500M TL")
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
engine.add_news_event("THYAO", {
    "sentiment": 0.8, "importance": 0.7, "credibility": 0.9,
    "timestamp": datetime.now(timezone.utc).isoformat(),
})
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
