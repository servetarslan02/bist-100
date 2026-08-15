# Bölüm 17 — Memory + Knowledge Graph

## Amaç

Sistemin geçmiş analizleri, şirket ilişkilerini, olayları ve tahmin sonuçlarını kaybedip her seferinde sıfırdan başlamasını önlemek.

---

## Kullanılacak sistemler

- Research Memory
- Long-Term Memory
- Vector Database
- Embeddings
- Knowledge Graph
- Entity / Relationship Store
- Historical Event Store
- Prediction & Outcome Memory

---

## Çalışma mantığı

```
Yeni Veri / Analiz
    ↓
Entity + Event çıkarımı
    ↓
Embedding
    ↓
Memory + Knowledge Graph
    ↓
Geçmiş bilgilerle ilişkilendirme
    ↓
Güncel analiz
```

---

## Memory ne tutacak?

Örneğin Hisse X için:

```
Şirket
├─ Finansal geçmiş
├─ KAP açıklamaları
├─ Haberler
├─ Önemli olaylar
├─ Sektör ilişkileri
├─ Önceki tahminler
├─ Gerçekleşen sonuçlar
└─ Önceki analizlerin nedenleri
```

---

## Knowledge Graph ne yapacak?

Sadece metin saklamayacak; **ilişki kuracak**.

Örneğin:

```
Şirket X
    ↓ ait
Sektör Y
    ↓ etkileniyor
Faiz
    ↓ etkiliyor
Banka kârlılığı
```

ve:

```
KAP Olayı
    ↓ bildirildi
Şirket X
    ↓ etkiliyor
Gelir beklentisi
    ↓ etkiliyor
Forecast
    ↓ gerçekleşti
Gerçekleşen sonuç
```

gibi ilişkiler tutulacak.

---

## Embedding neden kullanılacak?

Haber, KAP ve analiz gibi metinsel bilgilerin **anlamsal olarak aranabilmesi** için.

Örneğin sistem:

> "Bu şirket daha önce benzer bir sözleşme açıklamış mı?"

diye sorduğunda sadece aynı kelimeleri değil, **anlam olarak benzer olayları** da bulabilecek.

---

## En önemli prensip

**Memory karar motoru değildir.**

Geçmiş bilgiyi sağlar.

Güncel veri ile geçmiş bilgi çelişirse:

**güncel ve doğrulanmış veri önceliklidir.**

---

## Çıktı

```
Relevant Past Events:        14
Similar Historical Cases:     6
Previous Predictions:         9
Prediction Accuracy History: %72
Related Entities:             23
Memory Confidence:            %91
```

Böylece sistem:

> "Bu olay yeni ama tamamen benzersiz değil; geçmişte benzer 6 olay yaşandı ve sonuçları şunlardı."

diyebilir.

---

## Temel prensip

**Memory** geçmişi saklar, **Knowledge Graph** ilişkileri saklar, **Embedding** sistemi anlam üzerinden geçmişi bulur; **karar ise güncel analiz motorları tarafından verilir.**
