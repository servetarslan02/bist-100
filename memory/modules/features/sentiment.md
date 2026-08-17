# features/sentiment

**Dosya:** `services/features/sentiment.py`
**Satır:** 307

## Açıklama

ALPHA BIST — Sentiment Feature Engine v1.0

Haber, KAP ve sosyal medya verilerinden feature üretir:
- News sentiment (aggregated, momentum, credibility-weighted)
- KAP sentiment (category-based, importance-weighted)
- Social sentiment (volume, engagement, manipulation detection)
- Sentiment momentum (trend, acceleration)

FAZ 2.4: Sentiment Features

## Sınıflar (1)

- `SentimentFeatureEngine`

## Fonksiyonlar (10)

- `__init__()`
- `add_news_event()`
- `add_kap_event()`
- `add_social_event()`
- `compute_news_features()`
- `compute_kap_features()`
- `compute_social_features()`
- `_detect_manipulation()`
- `compute_all_sentiment_features()`
- `_is_recent()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `alternative/social`
- `alternative/jobs`
- `alternative/satellite`
- `alternative/web_scraping`
- `alternative/credit_card`

