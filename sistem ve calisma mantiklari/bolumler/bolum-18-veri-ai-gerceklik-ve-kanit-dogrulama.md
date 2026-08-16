# Bölüm 18 — Veri/AI Gerçeklik ve Kanıt Doğrulama

## Amaç

Sistemin uydurma bilgi, yanlış veri veya kanıtsız çıkarımlarla karar üretmesini engellemek.

**Kaynak:** arXiv FinGround (2026) Financial Hallucination Detection, Springer (2026) Fact-checking and Factuality, ScienceDirect (2026) Mitigating Hallucinations.

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
AI/Agent Çıktısı → Claim'leri ayır → Kaynak bul → Kaynak güvenilirliği →
Veriyle karşılaştır → Tarih kontrolü → Çelişki kontrolü → Evidence Score →
Verified / Unverified / Rejected
```

---

## 1. Claim Extraction

**Araştırma bulgusu:** arXiv FinGround (2026) — "Claim verification with financial table-cell attribution and hallucination-triggered regeneration."

### Claim türleri:
- **FACT:** Kaynakta doğrudan yazan
- **INFERENCE:** Veriden çıkarılan
- **PREDICTION:** Gelecek tahmini
- **OPINION:** Yorum/değerlendirme

### Örnek: Claim sınıflandırma

```python
# services/intelligence/evidence_engine.py
from services.intelligence.evidence_engine import evidence_engine

claim_type = evidence_engine._classify_claim("KAP açıklandı")  # FACT
claim_type = evidence_engine._classify_claim("Tahminime göre yükselecek")  # PREDICTION
claim_type = evidence_engine._classify_claim("Bence bu iyi")  # OPINION
```

---

## 2. Source Reliability

Kaynak güvenilirlik sıralaması:

```
KAP (resmi) → 0.98
Bloomberg/Reuters → 0.97
Haber siteleri → 0.80-0.85
Sosyal medya → 0.40
```

---

## 3. Hallucination Detection

**Araştırma bulgusu:** Springer (2026) — "Claim detection, evidence retrieval, and fact verification. RAG for hallucination mitigation."

### Örnek: Hallucination tespiti

```python
halluc = evidence_engine.detect_hallucination(
    "THYAO 500 TL olacak ve ASELS %20 artacak", {})
# tickers_mentioned: ["THYAO", "ASELS"]
# prices_mentioned: ["500"]
# hallucination_detected: True (fiyat uydurma)
```

---

## 4. Evidence Scoring

### Örnek: Verification

```python
from services.intelligence.evidence_engine import Claim, SourceReliability

claim = Claim(claim_id="C1", text="Şirket yeni sözleşme imzaladı",
    source="kap.org.tr", source_type=SourceReliability.PRIMARY)
result = evidence_engine.verify_claim(claim)
# result: VERIFIED, evidence_score: 95, claim_type: FACT
```

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

## Temel prensip

> "AI'nın söylediği şey doğru olduğu için değil, kanıtlanabildiği ölçüde doğru kabul edilir."
