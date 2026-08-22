# Market State Modülü — Güncel Durum Raporu

**Tarih:** 2026-08-21
**Analiz:** Kod tabanı envanteri

---

## Genel Durum

| Metrik | Değer |
|--------|-------|
| Modül sayısı | 11 |
| Toplam satır | ~3,646 |
| Test sayısı | 15 |
| Breadth göstergesi | 7 |
| Bileşen state | 8 |
| Ensemble yöntem | 3 |

---

## Modül Olgunluk Durumu

| Modül | Durum | Not |
|-------|-------|-----|
| main.py | ✅ TAM | Event consumer, pipeline |
| breadth_engine.py | ✅ TAM | 7 gösterge + döviz izolasyonu |
| component_states.py | ✅ TAM | 8 state + Fear/Greed |
| ensemble_regime.py | ✅ TAM | 3 yöntem weighted voting |
| transition_tracker.py | ✅ TAM | Stability, matrix, alerts |
| risk_appetite.py | ✅ TAM | 6 faktör [0,1] |
| multi_timeframe.py | ✅ TAM | Daily/Weekly/Monthly |
| output_formatter.py | ✅ TAM | MarketStateOutput |
| api.py | ✅ TAM | 7 REST endpoint |
| monitoring.py | ✅ TAM | Prometheus + Grafana |

---

## Bilinen Sınırlamalar

| Sınırlama | Öncelik | Açıklama |
|-----------|---------|----------|
| HMM soğuk başlangıç | P1 | 63 günden az veri ile eğitilemez |
| GMM opsiyonel | P2 | sklearn yoksa devre dışı |
| Weekly aggregate basit | P2 | Gerçek haftalık OHLCV aggregation yok |
| In-memory state | P2 | Restart sonrası sıfırlanır |
| Sektörel breadth manuel | P2 | Otomatik sektör tespiti yok |
| Sentiment basit | P2 | Sosyal medya entegrasyonu sınırlı |
| ClickHouse opsiyonel | P2 | Yoksa insert sessizce başarısız |
