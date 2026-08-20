# Alternative Data

**Modül sayısı:** 16 | **Toplam satır:** ~2,540 | **Test sayısı:** 63

## Modüller

| Modül | Dosya | Açıklama |
|-------|-------|----------|
| Base Infrastructure | `base.py` | BaseAdapter, RateLimiter, CircuitBreaker, DataQualityValidator, AdapterRegistry |
| Google Trends | `google_trends.py` | pytrends ile Google Trends verisi (9 feature) |
| BKM Credit Card | `bkm_adapter.py` | BKM kredi kartı adapter'ı (veri kaynağı bekleniyor) |
| Kariyer.net | `kariyer_net.py` | İş ilanı web scraping (5+ feature) |
| Ekşi Sözlük | `eksi_sozluk.py` | Sentiment scraping (8 feature) |
| Investing.com | `investing_adapter.py` | Hisse yorumları scraping (6 feature) |
| LLM Sentiment | `llm_sentiment.py` | Ollama Türkçe sentiment analizi |
| Reconciliation | `reconciliation.py` | Cross-source veri uzlaştırma |
| Feature Store | `feature_store.py` | Feature versioning + point-in-time correctness |
| Feature Engine | `feature_engine.py` | 60+ feature computation orchestrator |
| Social (legacy) | `social.py` | Sosyal medya feature fonksiyonu |
| Jobs (legacy) | `jobs.py` | İş ilanı feature fonksiyonu |
| Credit Card (legacy) | `credit_card.py` | Kredi kartı feature fonksiyonu |
| Satellite (legacy) | `satellite.py` | Uydu verisi feature fonksiyonu |
| Web Scraping (legacy) | `web_scraping.py` | Web scraping feature fonksiyonu |

## Spec Uyumu

| Spec Maddesi | Durum | Not |
|-------------|-------|-----|
| Data Collection Pipeline | ✅ TAM | BaseAdapter + RateLimiter + CircuitBreaker + DataQuality |
| Google Trends | ✅ TAM | pytrends entegrasyonu, 9 feature |
| BKM Credit Card | ⚠️ KISMİ | Adapter var, veri kaynağı yok (honest gap) |
| Kariyer.net | ✅ TAM | Web scraping + feature computation |
| Ekşi Sözlük | ✅ TAM | Web scraping + keyword sentiment |
| Investing.com | ✅ TAM | Web scraping + sentiment |
| LLM Sentiment | ✅ TAM | Ollama + keyword fallback |
| Data Quality | ✅ TAM | 7 kontrollü validator |
| Cross-Source Reconciliation | ✅ TAM | Consensus + reliability scoring |
| Feature Store | ✅ TAM | Versioning + point-in-time + persistence |
| Feature Engine | ✅ TAM | 60+ feature, paralel toplama |
| Satellite Imagery | ⚠️ KISMİ | Legacy feature fonksiyonu, Sentinel-2 entegrasyonu yok |

## Düzeltilen Bug'lar

1. **`_clamp(None)` crash** — `social.py`'deki `_clamp` fonksiyonu None değerinde crash oluyordu
2. **Google Trends int type** — `compute_features` int değerler döndürüyordu, float olmalıydı
3. **Bare `except:pass`** — `base.py`'deki stale exception handler temizlendi
