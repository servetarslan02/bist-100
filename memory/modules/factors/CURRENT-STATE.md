# Factors Modülü — Güncel Durum Raporu

**Tarih:** 2026-08-21
**Analiz:** Kod tabanı envanteri

---

## Genel Durum

| Metrik | Değer |
|--------|-------|
| Modül sayısı | 10 |
| Toplam satır | ~2,500 |
| Test sayısı | 12 |
| Faktör sayısı | 8 (Fama-French) + 9 (Piotroski) + 8+ (BIST anomalies) |

---

## Modül Olgunluk Durumu

| Modül | Durum | Not |
|-------|-------|-----|
| fama_french.py | ✅ TAM | 8 faktör, cross-sectional z-score |
| piotroski.py | ✅ TAM | 9 kriter, ağırlıklı, detaylı |
| altman.py | ✅ TAM | TR düzeltmeli Z-Score |
| beneish.py | ✅ TAM | 8 bileşen M-Score |
| bist_anomalies.py | ✅ TAM | 8+ BIST'e özgü anomaly |
| factor_rotation.py | ✅ TAM | Rejim bazlı rotasyon |
| ranking.py | ✅ TAM | Çok faktörlü sıralama |
| factor_correlation.py | ✅ TAM | Korelasyon matrisi, VIF |
| factor_time_series.py | ✅ TAM | Trend, momentum, mevsimsellik |
| performance.py | ✅ TAM | 10+ metrik, benchmark karşılaştırma |

---

## Çözülen Sorunlar (2026-08-21)

1. **Yön düzeltmesi** — `abs()` kaldırıldı; ihracatçı/ithalatçı şirketler artık farklı skor alıyor
2. **Risk cezası formülü** — `total_score × risk_score/100` → `1 - risk_score/100 × risk_aversion`

---

## Bilinen Sınırlamalar

| Sınırlama | Öncelik | Açıklama |
|-----------|---------|----------|
| Statik ağırlık | P2 | Dinamik ağırlık optimizasyonu (Black-Litterman) yok |
| Altman TR düzeltmesi sabit | P2 | Enflasyon/kur değişimine göre dinamik ayarlama gerekli |
| Beneish 2 dönem | P2 | Çok dönemli trend analizi yok |
| BIST anomalies beta | P2 | Piyasa verisi yoksa varsayılan 0 |
| Factor rotation basit | P2 | HMM veya ML tabanlı rejim tespiti gerekli |
| Risk aversion sabit | P2 | Yatırımcı tercihine göre dinamik ayarlama yok |
