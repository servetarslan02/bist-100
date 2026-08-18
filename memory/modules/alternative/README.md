# Alternative Data

**Modül sayısı:** 10 | **Test:** 46/46 passed | **Feature:** 60+

## Modüller

| Modül | Satır | Açıklama |
|-------|-------|----------|
| `base` | ~350 | BaseAdapter, RateLimiter, CircuitBreaker, DataQualityValidator, AdapterRegistry |
| `google_trends` | ~170 | Google Trends adapter (pytrends) — 9 feature |
| `bkm_adapter` | ~120 | BKM kredi kartı harcama adapter — 8 feature |
| `kariyer_net` | ~220 | Kariyer.net iş ilanı adapter — 5+ feature |
| `eksi_sozluk` | ~200 | Ekşi Sözlük sentiment adapter — 8 feature |
| `llm_sentiment` | ~220 | Ollama Türkçe LLM sentiment analizi |
| `feature_engine` | ~260 | Tüm kaynakları orkestre eder, 60+ feature |
| `social` | ~70 | Sosyal medya feature'ları (legacy) |
| `jobs` | ~30 | İş ilanı feature'ları (legacy) |
| `credit_card` | ~30 | Kredi kartı feature'ları (legacy) |
| `satellite` | ~30 | Uydu verisi feature'ları (legacy) |
| `web_scraping` | ~35 | Web scraping feature'ları (legacy) |

## Feature Listesi

### Google Trends (9)
- `google_trends_score`, `google_trends_avg_30d`, `google_trends_momentum_7d/30d`
- `google_trends_volatility`, `google_trends_percentile`, `google_trends_relative`
- `google_trends_trend`, `google_trends_zscore`

### BKM Credit Card (8)
- `cc_spend_growth`, `cc_spend_growth_mom`, `cc_transaction_count`, `cc_avg_transaction`
- `cc_online_ratio`, `cc_vs_sector`, `cc_seasonal_deviation`, `cc_foreign_ratio`

### Kariyer.net Jobs (5+)
- `job_posting_count`, `job_posting_growth`, `job_tech_ratio`
- `job_management_ratio`, `job_remote_ratio`, `job_diversity`

### Ekşi Sözlük (8)
- `eksi_sentiment`, `eksi_volume`, `eksi_positive_ratio`, `eksi_negative_ratio`
- `eksi_avg_favorites`, `eksi_max_favorites`, `eksi_sentiment_std`, `eksi_controversial`

### LLM Sentiment (6)
- `llm_kap_sentiment`, `llm_kap_confidence`, `llm_kap_impact`
- `llm_news_sentiment`, `llm_news_sentiment_std`, `llm_news_count`

### Composite (5)
- `alt_sentiment_avg`, `alt_sentiment_consensus`
- `alt_growth_avg`, `alt_growth_consensus`, `alt_data_coverage`

## Kullanım

```python
from services.alternative import alt_feature_engine

# Tüm adapter'ları başlat
alt_feature_engine.initialize()

# Feature hesapla
features = await alt_feature_engine.compute_all_features(
    ticker="THYAO",
    sector="ULAŞTIRMA",
    extra_data={"kap_announcements": [...], "news": [...]},
)
```
