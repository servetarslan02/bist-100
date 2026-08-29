# Quantitative Rules, Data Handling & ML

> bist-100 projesi için veri bütünlüğü ve ML standartları.

1. **Point-In-Time (PIT) & Sızıntı Koruması:**
   - Geleceğe ait veri (lookahead bias / leakage) kesinlikle yasaktır.
   - Her zaman purge + embargo kullanılmalı.
   - Mask-first: filtreleme feature hesaplamasından önce uygulanmalıdır.

2. **Veri Kütüphaneleri:**
   - `polars >= 1.30.0` ana veri motorudur.
   - Yüksek hacimli veri dönüşümlerinde Pandas KULLANILMAZ.
   - `numpy >= 2.5.0`, `duckdb >= 1.3.0`.

3. **Modeller:**
   - Şampiyon model: `lightgbm`.
   - Challenger modeller: `xgboost`, `catboost`.
   - Hiperparametre optimizasyonu: `optuna`.
   - Modellerin kalibrasyonu (Brier score, ECE, Platt/Isotonic) zorunludur.

4. **Veri Kalitesi (Fail-Closed):**
   - Eksik veri durumunda tahmin/varsayım yapılmaz, "eksik" olarak işaretlenir.
   - Hata durumunda veri temizleme/kalite motoru hata fırlatmalı, hatayı yutmamalıdır.
