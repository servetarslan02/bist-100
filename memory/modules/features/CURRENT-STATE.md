# Features Katmanı — Güncel Durum

**Son güncelleme:** 2026-08-21
**Oturum:** features katmanı spec vs kod karşılaştırması + düzeltmeler

---

## Genel Durum

| Metrik | Değer |
|--------|-------|
| Modül sayısı | 17 |
| Spec maddesi | 22 |
| ✅ TAM | 15 |
| ⚠️ KISMİ → ÇÖZÜLDÜ | 5 |
| ❌ ÇELİŞKİLİ → ÇÖZÜLDÜ | 4 |
| Kalan açık | 0 (kritik) |

---

## Çözülen Sorunlar (2026-08-21)

1. **RSI tutarsızlığı** — technical_features.py Wilder's smoothing'e geçirildi
2. **MACD signal line** — gerçek 9-period EMA hesaplanıyor
3. **Incremental RSI sıfır** — `_last_bar_close` ile bar'lar arası değişim kullanılıyor
4. **BIST sector_rank placeholder** — gerçek sıralama hesaplanıyor
5. **VIF placeholder** — korelasyon matrisi tersinden gerçek VIF
6. **Macro percentile look-ahead** — current value hariç, bağımsız koşul
7. **Fundamental %1 heuristic** — otomatik dönüşüm kaldırıldı
8. **Pipeline singleton** — global feature_store kullanılıyor
9. **Sessiz except blokları** — gereksiz import blokları kaldırıldı

---

## Kalan Açık (Kritik Olmayan)

| Sorun | Öncelik | Not |
|-------|---------|-----|
| Feature discovery combinatorial explosion | P2 | 100+ feature'da 4950+ interaction üretilir |
| Bar engine / incremental_state kod tekrarı | P2 | Aynı OHLC bar logic iki yerde |
| Sentiment manipulation detection eşikleri | P2 | Hardcoded, tuning gerekli |

---

## Dosya Değişiklikleri

| Dosya | Değişiklik |
|-------|-----------|
| `services/features/technical_features.py` | RSI Wilder's smoothing + MACD signal line |
| `services/features/incremental_state.py` | `_last_bar_close` + RSI fix |
| `services/features/bist_features.py` | sector_rank gerçek hesaplama |
| `services/features/feature_selector.py` | VIF gerçek hesaplama |
| `services/features/macro.py` | Percentile look-ahead bias + koşul fix |
| `services/features/fundamental.py` | %1 heuristic kaldırıldı |
| `services/features/pipeline.py` | Singleton fix |
| `services/features/calculator.py` | Sessiz except blokları kaldırıldı |
| `memory/modules/features/FEATURES-NIHAI-SPEC.md` | Düzeltme kayıtları eklendi |
