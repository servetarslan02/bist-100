# intelligence/kap_extractor

**Dosya:** `services/intelligence/kap_extractor.py`
**Satır:** 296

## Açıklama

ALPHA BIST — KAP Extractor v1.0

KAP bildirimlerinden yapılandırılmış veri çıkarma:
- Olay türü sınıflandırması
- Finansal etki yönü + büyüklüğü
- Beklenmediklik skoru
- Belirsizlik skoru
- Sektör zincirleme etkisi

LLM varsa kullanır, yoksa kural tabanlı çalışır.

## Sınıflar (3)

- `KAPExtractedEvent`
- `KAPExtractor`
- `SectorChainImpact`

## Fonksiyonlar (7)

- `extract()`
- `_classify_event()`
- `_adjust_impact_from_text()`
- `_compute_surprise()`
- `_compute_uncertainty()`
- `_identify_affected_sectors()`
- `compute_chain_impact()`

