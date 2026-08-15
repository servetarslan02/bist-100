# Bölüm 18 — Veri / AI Gerçeklik ve Kanıt Doğrulama

## Amaç

Sistemin uydurma bilgi, yanlış veri veya kanıtsız çıkarımlarla karar üretmesini engellemek.

---

## Kullanılacak sistemler

- Evidence Verification
- Source Verification
- Fact Checking
- Data Cross-Check
- Timestamp Validation
- Claim Extraction
- Citation / Provenance
- AI Hallucination Detection
- Confidence Scoring

---

## Çalışma mantığı

```
AI / Agent Çıktısı
    ↓
Claim'leri ayır
    ↓
Kaynak bul
    ↓
Kaynak güvenilirliği
    ↓
Veriyle karşılaştır
    ↓
Tarih / zaman kontrolü
    ↓
Çelişki kontrolü
    ↓
Evidence Score
    ↓
Verified / Unverified / Rejected
```

---

## Nasıl kullanılacak?

Agent:

> "Şirket X yeni bir fabrika yatırımı açıkladı."

derse sistem bunu doğrudan gerçek kabul etmeyecek.

Önce:

1. KAP var mı?
2. Resmî açıklama var mı?
3. Tarih doğru mu?
4. Haber kaynakları doğruluyor mu?
5. Finansal verilerle uyumlu mu?

kontrollerini yapacak.

---

## Kaynak önceliği

Genel olarak:

```
Resmî / Birincil Kaynak
    ↓
Güvenilir Finansal Veri
    ↓
Güvenilir Haber
    ↓
Analiz / Araştırma
    ↓
Sosyal Medya
```

Sosyal medyada çok konuşulması gerçeklik kanıtı olarak kabul edilmeyecek.

---

## AI çıkarımları da doğrulanacak

Örneğin:

> "Bu KAP şirketin kârını %20 artıracak."

Bu doğrudan kaynakta yazmıyorsa fact değil, model çıkarımı olarak işaretlenecek.

Yani sistem:

- **FACT**
- **INFERENCE**
- **PREDICTION**
- **OPINION**

ayrımını koruyacak.

---

## Çıktı

```
Claim:            Yeni fabrika yatırımı
Source:           KAP
Source Reliability: High
Timestamp:        Verified
Cross-check:      Passed
Claim Type:       FACT
Evidence Score:   98/100
```

Kanıt bulunamazsa:

> **UNVERIFIED**

olarak işaretlenir ve kritik kararların dayanağı yapılamaz.

---


---

**Kaynak:** Evidence verification — claim extraction. Source reliability. FACT/INFERENCE/PREDICTION/OPINION classification.


### Örnek: Claim verification

```python
# services/intelligence/evidence_engine.py
from services.intelligence.evidence_engine import evidence_engine, Claim, SourceReliability

claim = Claim(
    claim_id="C1", text="Şirket yeni sözleşme imzaladı",
    source="kap.org.tr", source_type=SourceReliability.PRIMARY,
)
result = evidence_engine.verify_claim(claim)
# result.result = VERIFIED
# result.evidence_score = 95
# result.claim_type = FACT
```

## Temel prensip

**AI'nın söylediği şey doğru olduğu için değil, kanıtlanabildiği ölçüde doğru kabul edilir.**
