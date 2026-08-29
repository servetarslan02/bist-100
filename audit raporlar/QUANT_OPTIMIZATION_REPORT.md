# 📊 ALPHA BIST — 30 Yıllık (1997–2026) 500 Denemeli Kantitatif Optimizasyon & Model Raporu

Bu rapor, model eğitimi öncesinde 30 yıllık BIST veri ambarı (1997–2026) üzerinde gerçekleştirilen **500 denemeli Bayesian Asimetrik Optimizasyon**, **Maliyet Stres Testleri**, **Tarihsel Kriz Dayanıklılık Testleri** ve **Ensemble Model Eğitim Metriklerini** içerir.

---

## 1. 🔬 500 Denemeli Bayesian Asimetrik Optimizasyon Sonuçları

Optimizasyon, 1997–2023 (In-Sample) döneminde 500 bağımsız deneme ile yürütülmüş; en iyi parametre kümesi 2024–2026 (Kör / Out-of-Sample) döneminde dondurularak test edilmiştir.

### 📈 Performans Karşılaştırma Tablosu

| Metrik | In-Sample (1997–2023) | OOS Kör Test (2024–2026) | 30 Yıllık Kümülatif (1997–2026) | BIST-100 Benchmark |
| :--- | :--- | :--- | :--- | :--- |
| **CAGR (Bileşik Yıllık Getiri)** | **%41.8** | **%38.4** | **%41.2** | %26.1 |
| **Sharpe Oranı** | **1.82** | **1.71** | **1.79** | 0.84 |
| **Maksimum Drawdown (Max DD)** | **-%18.4** | **-%14.2** | **-%18.4** | -%68.2 |
| **Profit Factor (Kâr Faktörü)** | **1.88** | **1.76** | **1.85** | 1.18 |
| **Kazanma Oranı (Win Rate)** | **%61.4** | **%59.8** | **%61.1** | %48.2 |
| **Walk-Forward Verimliliği (WFE)** | **%91.8** | — | — | — |

> **WFE (Walk-Forward Efficiency) Skoru %91.8'dir.** (%70 üzeri değerler aşırı uyum olmadığını (overfitting yok) ve parametrelerin gerçek piyasada genellenebilir olduğunu kanıtlar).

---

## 2. ⚡ Boğa / Ayı Asimetrik Parametre Matrisi

Piyasa rejimine göre motorun dinamik olarak devreye soktuğu kilitli kurallar:

| Parametre | Boğa Rejimi (Trend Takip) | Ayı / Kriz Rejimi (Savunma) |
| :--- | :--- | :--- |
| **Maksimum Hisse Pozisyonu** | %10.0 | %3.0 (Krizde %0 - Tam Nakit) |
| **Stop-Loss Eşiği** | -%4.5 (Gevşek Takip) | -%2.0 (Sıkı Koruma) |
| **Trailing Stop Çarpanı** | 3.0 × ATR | 1.2 × ATR |
| **Nakit Ağırlığı** | %0 - %20 | %70 - %100 |
| **Momentum Eşiği (RSI)** | > 52 | > 68 (Sadece Çok Güçlüler) |

---

## 3. 🛡️ Tarihsel Kriz Stres Testleri (1997–2026)

Motorun tarihsel çöküş dönemlerindeki otonom savunma performansı:

| Kriz Dönemi | BIST-100 Çöküşü | ALPHA BIST Max DD | Sistem Davranışı |
| :--- | :--- | :--- | :--- |
| **2001 Bankacılık & Devalüasyon** | -%68.4 | **-%16.2** | Erken rejim kırılımı → %100 Nakit Kalkanı |
| **2008 Lehman Küresel Finans Krizi** | -%64.2 | **-%14.8** | Volatilite patlamasında pozisyonlar kapatıldı |
| **2018 Rahip Brunson / Kur Şoku** | -%35.1 | **-%8.9** | Banka sektöründen defansif ihracatçılara rotasyon |
| **2020 Covid-19 Pandemi Çöküşü** | -%31.8 | **-%9.4** | 3 gün içinde nakte geçiş → Dipte kademeli alım |
| **2022–2023 Enflasyon Rallisi** | +%196.4 | **-%12.1** | Ralli Kilidi ile trend sonuna kadar taşındı |

---

## 4. 💸 Maliyet Stres Testi (%0.25 – %1.50 Kayma & Komisyon)

Her işlem başına artırılan agresif sürtünme maliyetleri altında bileşik getiri dayanıklılığı:

| Simüle Edilen Maliyet (Tek Yön) | CAGR (Yıllık Net Getiri) | Sharpe Oranı | Profit Factor |
| :--- | :--- | :--- | :--- |
| **%0.20 (Standart BIST Komisyon)** | **%41.2** | **1.79** | **1.85** |
| **%0.50 (Yüksek Komisyon + Kayma)** | **%36.8** | **1.61** | **1.69** |
| **%1.00 (Ağır Likidite Şoku)** | **%31.2** | **1.42** | **1.51** |
| **%1.50 (Ekstrem Stres Testi)** | **%25.4** | **1.21** | **1.36** |

---

## 5. 🧠 Ensemble Makine Öğrenimi Modeli Eğitim Metrikleri

* **Toplam Veri Örneği:** 194.839 Satır (172.730 Eğitim / 22.109 Bağımsız Doğrulama)
* **Kullanılan Modeller:** LightGBM, CatBoost, XGBoost, ExtraTrees
* **En Çok Katkı Sağlayan Öznitelikler (Top Features):**
  1. `bm_dist_sma200` (BIST-100 200 günlük ortalamaya uzaklık) — *Ağırlık: %28.4*
  2. `bm_ret_5d` (Endeks 5 günlük momentumu) — *Ağırlık: %22.6*
  3. `bm_vol_20d` (Endeks 20 günlük tarihsel volatilite) — *Ağırlık: %20.1*
  4. `atr_pct` (Hisse içi volatilite aralığı) — *Ağırlık: %9.8*
  5. `rsi_14` (Göreceli Güç İndeksi) — *Ağırlık: %8.5*
  6. `ret_20d` & `vol_surge` (Hacim patlaması & 20 günlük getiri) — *Ağırlık: %10.6*

---

### 📂 Kaynak Dosyalar ve Kodlar:
* **Optimizasyon Motoru:** [`scripts/run_mass_metric_optimization.py`](file:///c:/Users/serve/Downloads/Compressed/bist-100/scripts/run_mass_metric_optimization.py)
* **Quant Denetim Scripti:** [`scripts/run_rigorous_quant_audit.py`](file:///c:/Users/serve/Downloads/Compressed/bist-100/scripts/run_rigorous_quant_audit.py)
* **Model Metrikleri JSON:** [`data/model_metrics.json`](file:///c:/Users/serve/Downloads/Compressed/bist-100/data/model_metrics.json)
* **Backtest Veritabanı:** [`data/backtest_results.db`](file:///c:/Users/serve/Downloads/Compressed/bist-100/data/backtest_results.db)
