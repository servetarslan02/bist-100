# ALPHA BIST QUANT LAB — FINAL RESEARCH REPORT
**Tarih:** 2026-08-22
**Kapsam:** 9-Fazlı Otonom Araştırma (Veri Doğrulama, Multi-Strategy, Walk-Forward, Robustness, Monte Carlo)

==================================================
FAZ 9 — FİNAL KARAR
==================================================

**Kanıtlanmış alpha bulunamadı.**

Test edilen 17 strateji ailesi (Momentum, Mean Reversion, Trend, Low Volatility, 52-W High) arasından pozitif getiri sağlayanlar olsa da, **hiçbiri basit BIST100 Al-Tut veya Rastgele Seçim stratejilerini geçemedi.** 

Bulunan en dayanıklı aday modelin (En azından iflas etmeyen ve sermaye koruyan) detayları aşağıdadır:

MODEL: MOM_6M_Top5_Q (Çeyreklik Rebalans)

STRATEJİ: 6 Aylık Momentum, En İyi 5 Hisse, %10 Stop-Loss, 1.0x Kaldıraç

VERİ ARALIĞI: 2015-06-01 → 2025-07-31 (10.0 yıl, 101 hisse)

GERÇEK CAGR: +22.41%

SHARPE: 0.066 (rf=%30 TL risksiz faiz)

MAX DD: -40.55%

ALPHA: -17.3% (vs BIST100 Eşit Ağırlıklı: +39.7%) | -30.6% (vs Rastgele Portföy: +53.0%)

WALK FORWARD BAŞARI: Başarısız (Hiçbir yıl risksiz getiriyi ve benchmark'ı düzenli yenemedi)

MONTE CARLO WORST 5%: -1.5% CAGR, -71.6% Max Drawdown (10.000 simülasyon)

BIAS SEVİYESİ: ORTA (yfinance delist hisseleri tam içermediği için kısmi survivorship bias mevcut)

OVERFIT SEVİYESİ: ZAYIF / OVERFIT (36 parametre kombinasyonunun sadece %28'i pozitif, küçük değişimlerde model çöküyor)

PRODUCTION KARARI:
HAYIR

==================================================
ÖZET ANALİZ:
Gerçek piyasa koşulları (kayma, komisyon, BSMV, tavan/taban kilitleri) ve risksiz faiz oranı eklendiğinde, standart fiyat bazlı stratejilerin (Momentum, RSI, Low Vol) Türkiye piyasasında uzun vadeli ve sürdürülebilir bir "Alpha" yaratmadığı kanıtlanmıştır. Rastgele seçilen 10 hisselik bir portföy bile karmaşık modellere göre daha iyi performans (+53.0% CAGR) göstermektedir.
