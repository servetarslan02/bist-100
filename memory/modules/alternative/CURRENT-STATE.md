# Alternative Data Modülü — Güncel Durum Raporu

**Tarih:** 2026-08-21
**Analiz:** Kod tabanı envanteri

---

## Genel Durum

| Metrik | Değer |
|--------|-------|
| Modül sayısı | 17 |
| Toplam satır | ~3,116 |
| Test sayısı | 18 |
| Kaynak sayısı | 8+ (Google Trends, BKM, Kariyer.net, Ekşi, Investing, Satellite, LLM, Social) |
| Feature sayısı | 60+ |

---

## Modül Olgunluk Durumu

| Modül | Durum | Not |
|-------|-------|-----|
| BaseAdapter + Registry | ✅ TAM | Circuit breaker, rate limiter, quality validator |
| GoogleTrendsAdapter | ✅ TAM | pytrends ile 9 feature |
| BKMAdapter | ✅ TAM | Web scraping, 8 feature |
| KariyerNetAdapter | ✅ TAM | Web scraping, 6 feature |
| EksiSozlukAdapter | ✅ TAM | Keyword-based sentiment, 8 feature |
| InvestingAdapter | ✅ TAM | Web scraping, 6 feature |
| SatelliteAdapter | ✅ TAM | Copernicus Sentinel-2, 9 feature |
| LLMSentimentAnalyzer | ✅ TAM | Ollama + keyword-based fallback |
| Social | ✅ TAM | 8 feature |
| CrossSourceReconciler | ✅ TAM | Güvenilirlik skoru, consensus |
| FeatureStore | ✅ TAM | PIT-safe, versioning |
| AlternativeFeatureEngine | ✅ TAM | 60+ feature orchestrator |

---

## Bilinen Sınırlamalar

| Sınırlama | Öncelik | Açıklama |
|-----------|---------|----------|
| Scraping kararsızlığı | P1 | HTML yapısı değişirse scraper bozulur |
| Uydu verisi gecikme | P2 | Sentinel-2 revizyon süresi 5 gün |
| BKM verisi aylık | P2 | Günlük analiz için uygun değil |
| Google Trends rate limit | P2 | pytrends 10 istek/dk |
| Şirket mapping sabit | P2 | 20-30 şirket için hardcoded |
