# Bölüm 6 — Haber, KAP, Sosyal Medya ve Olay Analizi

## Amaç

Sayısal verilerin tek başına gösteremediği güncel gelişmeleri ve piyasa algısını analiz etmek.

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
Haber + KAP + Sosyal Medya
    ↓
NLP / Embedding
    ↓
Konu / Olay Tespiti
    ↓
Sentiment Analizi
    ↓
Etki Analizi
    ↓
Catalyst / Risk Tespiti
    ↓
Şirket Analizine Etki
```

---

## Nasıl çalışacak?

Örneğin bir şirket hakkında:

- KAP → Yeni büyük sözleşme
- Haber → Pozitif
- Sosyal medya → İlgi artıyor

Sistem bunları üç ayrı sinyal olarak görür; aynı haberin tekrar tekrar sayılıp sentiment'in yapay şekilde yükselmesine izin vermez.

Sonra olayın şirket üzerindeki etkisini değerlendirir:

- Gelire etkisi
- Kârlılığa etkisi
- Büyümeye etkisi
- Risk etkisi
- Beklentilere etkisi
- Geçici mi kalıcı mı olduğu

---

## KAP ve haber aynı ağırlıkta olmayacak

Özellikle birincil kaynak olan KAP, haber veya sosyal medya yorumundan daha güçlü kanıt kabul edilir.

Sosyal medya ise:

> "Piyasa bunu nasıl algılıyor?"

sorusuna yardımcı olur; tek başına gerçek kabul edilmez.

---

## Manipülasyon kontrolü

Aşırı sosyal medya hareketi, bot benzeri davranışlar, koordineli paylaşımlar veya olağandışı haber yoğunluğu varsa sentiment'in güveni düşürülür.

---

## Önceki bölümlerle etkileşim

```
Fundamental + Technical + News/KAP/Social
    ↓
Güncel şirket görünümü
```

Örneğin finansallar güçlü ama ciddi negatif KAP geldiyse sistem bunu gizlemez; şirketin mevcut değerlendirmesini aşağı çeker.

---

## Çıktı

```
News Sentiment:        +72
KAP Impact:            +85
Social Sentiment:      +61
Catalyst:              Güçlü
Event Risk:            Düşük
Manipulation Risk:     Düşük
Overall Event Impact:  Pozitif
Confidence:            %88
```

Bu sonuç Bölüm 7 — Değerleme ve daha sonra Tahmin/Risk motorlarına aktarılır.

---


---

**Kaynak:** Du (2026) — Adjusted-MSE loss for wrong-direction penalties. KAP: structured extraction (event type, financial impact, surprise, uncertainty). News: multi-source deduplication.


### Örnek: KAP sınıflandırma

```python
# services/intelligence/kap_extractor.py
from services.intelligence.kap_extractor import kap_extractor

result = kap_extractor.extract(
    ticker="THYAO", kap_id="K001",
    title="Şirketimiz yeni büyük sözleşme imzaladı. Tutar: 500M TL",
)
# result.event_type = "CONTRACT"
# result.financial_impact = 0.3
# result.surprise_score = 0.6
# result.time_horizon = "MEDIUM"
# result.affected_sectors = ["AVIATION"]
```

### Örnek: Sektör zincirleme etki

```python
from services.intelligence.kap_extractor import sector_chain

impacts = sector_chain.compute_chain_impact("ENERGY", 0.5)
# Enerji → Havacılık: -0.60 (yakıt maliyeti)
# Enerji → Perakende: -0.30 (lojistik)
```

## Temel prensip

Haberleri sadece "pozitif/negatif" diye etiketlemek değil, olayın şirketin gelecekteki finansal değerini ve riskini nasıl değiştirebileceğini ölçmek.
