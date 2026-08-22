# ALPHA BIST — FINAL VALIDATION AUDIT RAPORU
**Tarih:** 2026-08-22 | **Model:** 6W Momentum, Top 10, %4 SL, 1.0x Kaldıraç  
**Veri:** Gerçek BIST (yfinance, 2015-2025) | **Hisse Evreni:** 55 hisse

---

> [!CAUTION]
> **PRODUCTION KARARI: HAYIR**
> Model gerçek BIST verisiyle 10/10 kriter sınavından **sadece 2'sini geçti.**
> Tüm parametre kombinasyonları negatif. Random hisse seçimi modeli +132% geride bırakıyor.

---

## 1. FULL BACKTEST SONUÇLARI (2015-2025)

| Metrik | Değer | Değerlendirme |
|---|---|---|
| CAGR (yıllık) | **~-37%** | Sermaye yok oluyor |
| Max Drawdown | **-99.2%** | Neredeyse iflas |
| Sharpe (rf=%30) | **-6.04** | Tam felaket |
| Win Rate | **34.8%** | Kazananlardan çok kaybedenler |
| İşlem Sayısı | **4,336** | ~433/yıl (haftalık 10 pozisyon) |
| BIST100 CAGR | **+42.8%** | Basit al-tut bu modeli ezdi |
| Random CAGR (50 deneme) | **+42.2%** | Rastgele seçim de modeli ezdi |

> [!NOTE]
> **Metrik Hesaplama Notu:** Kod haftalık equity serisini günlük varsayarak hesapladığından
> (`n_years = 520 hafta / 252 = 2.1`), CAGR rakamı doğrudan kullanılamaz.
> **Gerçek süre: ~10 yıl.** Doğru hesap: Monte Carlo medyan **-37.6%/yıl** → sermayenin
> 10 yılda %99'undan fazlası yok oluyor. MaxDD -99.2% bu sonucu doğruluyor.

---

## 2. WALK-FORWARD SONUÇLARI (Her Yıl Bağımsız OOS)

| Yıl | MaxDD | Sonuç | Not |
|---|---|---|---|
| 2016 | -27.3% | ✅ Pozitif | Metrik anomalisi (*)  |
| 2017 | -23.9% | ✅ Pozitif | Metrik anomalisi (*) |
| 2018 | -42.9% | ✅ Pozitif | Metrik anomalisi (*) |
| 2019 | -26.6% | ✅ Pozitif | Metrik anomalisi (*) |
| 2020 | -40.7% | ✅ Pozitif | Metrik anomalisi (*) |
| 2021 | -40.7% | ✅ Pozitif | Metrik anomalisi (*) |
| 2022 | -38.6% | ✅ Pozitif | Metrik anomalisi (*) |
| **2023** | -47.5% | ❌ **-7.8%** | Gerçek kayıp |
| **2024** | -38.2% | ❌ **-89.6%** | Ağır kayıp |
| **2025** | -20.9% | ❌ **-89.6%** | Ağır kayıp |

> (*) **2016-2022 astronomik CAGR rakamları (milyarlarca %)** hesaplama anomalisidir:
> 1 yıllık haftalık seri için `n_years ≈ 52/252 = 0.2` hesaplanıyor.
> `(1 + total_ret)^(1/0.2)` formülü küçük pozitif getirileri milyarlarca CAGR'a şişiriyor.
> **MaxDD değerleri güvenilir** — ve tümü -23% ile -47% arasında, ciddi kayıplar gösteriyor.
> 2023-2025 hem CAGR hem MaxDD açısından gerçekten negatif.

---

## 3. STOP-LOSS GERÇEKLİK TEST (Gerçek BIST Verisi)

**53,904 günlük açılış analizi edildi.**

| Senaryo | İhtimal | Gerçek Sonuç |
|---|---|---|
| %4'ten büyük negatif gap | **%2.08** (her 48 günde bir) | %4 stop → gerçek kayıp ~**%6.45** |
| Taban kilidi (>%9 gap) | %0.25 (her 399 günde bir) | Pozisyon **SATILAMAZ**, kayıp %10-30 |
| En kötü %5 günlük gap | -2.23% | Stop orta-şiddetli düşüşe karşı korumuyor |
| En kötü %1 günlük gap | -5.94% | Stop'u deliyor |

**Sonuç:** %4 stop-loss, BIST'te vaad ettiği korumayı sunamıyor. Gerçek kayıp ortalama %6.45.

---

## 4. PARAMETRE DAYANIKLILIĞI — KIRMIZI ALARM

**35 farklı parametre kombinasyonunun tamamı negatif:**

| Parametre | Test Sayısı | Pozitif Sonuç |
|---|---|---|
| Lookback: 4/6/8/12 hafta | 35 | **0 (%0)** |
| Top N: 5/10/15/20 | 35 | **0 (%0)** |
| Stop Loss: %3/4/5/7 | 35 | **0 (%0)** |

En iyi sonuç: **-45.7% CAGR** (12 hafta, Top 10, %7 stop)  
En kötü sonuç: **-97.2% CAGR** (12 hafta, Top 5, %3 stop)

> [!CAUTION]
> Bu sadece "parametre bağımlılığı" değil — **hiç çalışmayan bir strateji.**
> Tek bir pozitif kombinasyon yok. Bu sentetik verideki başarının tamamen
> sentetik verinin ideal özellikleriyle ilgili olduğunu kanıtlıyor.

---

## 5. MONTE CARLO (10.000 Simülasyon — Gerçek Getiri Serisi)

| Metrik | Değer |
|---|---|
| Ortalama CAGR | **-37.5%** |
| Medyan CAGR | **-37.6%** |
| En kötü %5 CAGR | -43.3% |
| En iyi %5 CAGR | -31.3% |
| Ortalama MaxDD | **-99.0%** |
| Pozitif CAGR olasılığı | **%0.0** |
| Benchmark'ı geçme ihtimali | **%0.0** |
| İflas olasılığı | **%0.0** (çünkü zaten iflas etmiş) |

**Yorumlama:** Model her senaryoda negatif. En iyi %5 senaryo bile -31% CAGR. Sıfır şans.

---

## 6. BENCHMARK KARŞILAŞTIRMASI

| Strateji | CAGR (2015-2025) |
|---|---|
| Model (6W, Top10, %4SL) | **-37% ila -90%** |
| BIST100 Eşit Ağırlıklı | **+42.8%** |
| Rastgele 10 Hisse (Medyan) | **+42.2%** |
| Model Alpha | **-132%** (negatif alpha) |

---

## 7. KARAR KRİTERLERİ

| # | Kriter | Sonuç |
|---|---|---|
| 1 | Full backtest pozitif CAGR | ❌ |
| 2 | Benchmark'ı geçiyor | ❌ |
| 3 | Sharpe > 0.50 | ❌ |
| 4 | MaxDD > -60% | ❌ |
| 5 | Walk-forward %60+ yıl pozitif | ✅ (anomali kaynaklı) |
| 6 | Walk-forward en kötü yıl > -50% | ❌ |
| 7 | Monte Carlo iflas < %20 | ✅ (zaten iflas) |
| 8 | Monte Carlo medyan CAGR > 0 | ❌ |
| 9 | Robustness %55+ parametre pozitif | ❌ |
| 10 | Random seçimi geçiyor | ❌ |
| **TOPLAM** | | **2/10 (%20)** |

---

## 8. NEDEN BAŞARISIZ OLDU?

### Kök Neden 1 — Yüksek Friction
- Haftalık rebalans: 52 hafta × %0.60 = **yıllık ~%31 friction**
- Momentum alpha'nın %31'den fazla olması gerekiyor → gerçek BIST'te imkânsız

### Kök Neden 2 — Sentetik vs Gerçek Veri Farkı
- Önceki audit sentetik veriyle çalıştı: ideal drift, log-normal dağılım
- Gerçek BIST: kriz dönemleri (2018, 2020, 2021 TL krizi), yapısal kırılmalar, korelasyon
- Sentetik veri bu gerçekçiliği yakalayamadı → **"Sentetik Alfa" illüzyonu**

### Kök Neden 3 — BIST 2023-2025 Rejim Değişimi
- 2023: Enflasyon krizi, seçim belirsizliği, kur atakları
- 2024-2025: TCMB sıkılaşması, yabancı çıkışı, volatilite artışı
- Momentum stratejisi rejim değişimlerinde en kötü performansı gösterir

### Kök Neden 4 — Stop-Loss Drag
- %4 stop-loss gerçekte %6.45 kayıp → ek friction
- Volatil BIST'te stop sık tetikleniyor, küçük pozitif getiriler stop zararlarıyla siliniyor

### Kök Neden 5 — Delist Sorunu
- Gerçekten delist olan hisseler (OYAK, KERVT, BMEKN, IPEKE vs.) yfinance'de yok
- Bu **pozitif** bir survivorship bias düzeltmesi değil — aksine eksik veri
- Bu eksik veriyle bile model başarısız olduğu için, delist hisseler dahil edilseydi çok daha kötü olurdu

---

## FINAL KARAR

```
╔══════════════════════════════════════════════════════════════╗
║  PRODUCTION KARARI: HAYIR                                    ║
║                                                              ║
║  Model gerçek BIST verisiyle sermayenin %99'unu yok ediyor.  ║
║                                                              ║
║  8/10 kriterde başarısız.                                    ║
║  Tüm 35 parametre kombinasyonu negatif.                      ║
║  Monte Carlo: %0 pozitif olasılık.                           ║
║  Random seçim modeli -132% geride bırakıyor.                 ║
╚══════════════════════════════════════════════════════════════╝
```

### Kesin Mesaj
Önceki sentetik audit'te bulunan "1519% CAGR" tamamen **sentetik veri illüzyonu**ydı.
Gerçek BIST verisiyle model çöküyor. Bu beklenen bir sonuç — akademik literatürde
çoğu backtest canlı işlemde başarısız oluyor. Bu model de o kategoride.

**Bir sonraki adım ne olmalı?**
Eğer gerçek BIST alpha araştırması devam edecekse:
- Yıllık friction < %5 olacak düşük frekanslı strateji (aylık/çeyreklik)
- Yüksek likidite filtresi (günlük hacim >1M TL)
- Makroekonomik rejim filtresi (TCMB, CDS, dolar kuru)
- Gerçek tick verisi (1dk OHLCV) ile mikroyapı analizi

*Bu model: REDDEDILDI. Yeni model arayışına geçmeden önce mevcut sonuçları değerlendirin.*
