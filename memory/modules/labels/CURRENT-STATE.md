# Labels Modülü — Güncel Durum Raporu

**Tarih:** 2026-08-21
**Analiz:** Kod tabanı envanteri

---

## Genel Durum

| Metrik | Değer |
|--------|-------|
| Modül sayısı | 2 |
| Toplam satır | ~242 |
| Test sayısı | 6 |
| Label sayısı | 14 |

---

## Modül Olgunluk Durumu

| Modül | Durum | Not |
|-------|-------|-----|
| generator.py | ✅ TAM | 14 label, purge gap, mask-aware |

---

## Label Olgunluk Durumu

| Label | Durum | Not |
|-------|-------|-----|
| y_1d, y_5d, y_10d, y_20d | ✅ TAM | Forward return |
| y_5d_binary, y_20d_binary | ✅ TAM | Binary classification |
| y_5d_vs_sector, y_20d_vs_sector | ✅ TAM | Sector relative |
| y_5d_vs_benchmark, y_20d_vs_benchmark | ✅ TAM | Benchmark relative |
| y_5d_outperform, y_20d_outperform | ✅ TAM | Outperform binary |
| y_max_dd_20d | ✅ TAM | Max drawdown |
| y_volatility_20d | ✅ TAM | Forward volatilite |

---

## Bilinen Sınırlamalar

| Sınırlama | Öncelik | Açıklama |
|-----------|---------|----------|
| Tek dosya | P2 | Büyük universe'de paralelleştirme gerekli |
| Sektör getiri opsiyonel | P2 | Sağlanmazsa sector-relative label'lar üretilmez |
| Benchmark getiri opsiyonel | P2 | Sağlanmazsa benchmark-relative label'lar üretilmez |
| Purge gap sabit | P2 | Otomatik feature penceresi boyutuna göre ayarlanmaz |
| Max drawdown basit | P2 | Intra-day drawdown hesaplanmaz |
| Forward volatilite yıllık | P2 | Günlük volatilite istenirse ayrı hesaplanmalı |
| Cross-sectional rank toplu | P2 | Incremental rank güncellemesi yok |
