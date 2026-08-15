# Bölüm 18 — Veri / AI Gerçeklik ve Kanıt Doğrulama

## Amaç

Sistemin uydurma bilgi, yanlış veri veya kanıtsız çıkarımlarla karar üretmesini engellemek.

**Kaynak:** Claim extraction, source verification, hallucination detection.

## Çalışma mantığı

```
AI/Agent Çıktısı → Claim'leri ayır → Kaynak bul → Kaynak güvenilirliği →
Veriyle karşılaştır → Tarih kontrolü → Çelişki kontrolü → Evidence Score
```

### Örnek: Claim verification

```python
from services.intelligence.evidence_engine import evidence_engine, Claim, SourceReliability

claim = Claim(claim_id="C1", text="Şirket yeni sözleşme imzaladı",
    source="kap.org.tr", source_type=SourceReliability.PRIMARY)
result = evidence_engine.verify_claim(claim)
# result: VERIFIED, evidence_score: 95, claim_type: FACT
```

## Temel prensip

AI'nın söylediği şey doğru olduğu için değil, kanıtlanabildiği ölçüde doğru kabul edilir.
