# 04 — Feature Motorları ve Sinyal Üretimi

## 4.1 Felsefe: neden "motor" mimarisi

Tek bir dev feature fonksiyonu yerine, her biri belirli bir piyasa
gerçekliğini temsil eden bağımsız **motorlar** kullanılır. Bu yaklaşımın
avantajları:

- **Yorumlanabilirlik**: Bir sinyalin nereden geldiği (momentum mu, hacim
  mi, temel mi, haber mi) her zaman izlenebilir.
- **Bağımsız test edilebilirlik**: Her motor kendi girdisi/çıktısıyla
  izole test edilir (bkz. `tests/test_faz2_motors.py`).
- **Kademeli devre dışı bırakma**: Bir veri kaynağı (örn. haber
  sağlayıcısı) çökerse, sadece o motora bağımlı feature'lar etkilenir;
  sistemin geri kalanı çalışmaya devam eder.
- **Rejime duyarlı ağırlıklandırma**: Farklı motorlar farklı piyasa
  rejimlerinde farklı önem taşır (örn. momentum boğa piyasasında,
  mean-reversion yatay piyasada daha güçlü çalışır) — bkz. Bölüm 05.2.

## 4.2 Mevcut motor envanteri (kod tabanı ile isim/sorumluluk eşlemesi)

Not: Motor mimarisinin kod içi ismi tarihsel olarak "Seven Motor Engine"
olsa da, kod tabanında bugün **dokuz** motor sınıfı bulunmaktadır
(`services/features/seven_motors.py`). Bu doküman gerçek envanteri
yansıtır; isimlendirme tutarsızlığı bilinen bir teknik borçtur
(bkz. `09-MEVCUT-DURUM-VE-ACIK-ANALIZI.md`).

| # | Motor | Sorumluluk | Örnek feature'lar |
|---|---|---|---|
| 1 | `RelativeStrengthMotor` | Hissenin BIST endeksine ve sektörüne göre göreli gücü | `rs_vs_bist_5d/20d`, sektör-göreli getiri |
| 2 | `MomentumTrendMotor` | Fiyat trendi, momentum ivmesi | `trend_slope_20d`, `momentum_acceleration`, `roc_*` |
| 3 | `VolumeMicrostructureMotor` | Hacim davranışı, alım/satım baskısı, VWAP sapması | `volume_percentile_*`, `tick_rule_*`, `vwap_deviation_*`, `volume_zscore_*` |
| 4 | `FundamentalMotor` | Değerleme ve kalite oranları, sektör-normalize edilmiş | `raw_pe_ratio`, `sector_norm_pe_ratio`, `fcf_yield_pct` |
| 5 | `KAPNewsMotor` | KAP açıklamaları + haber sentiment, momentum ve tazelik | `sentiment_momentum`, `news_count_24h/7d`, KAP önem skoru |
| 6 | `CatalystMotor` | Yaklaşan/geçmiş kurumsal olaylar (temettü, bilanço takvimi vb.) | `catalyst_count`, olay yakınlığı |
| 7 | `WhyFallingMotor` | Bir düşüşün nedeni: piyasa geneli mi, şirkete özgü mi, likidite şoku mu, geçici mi kalıcı mı | `fall_market_selloff_5d`, `fall_company_specific_5d`, `fall_liquidity_event`, `falling_is_temporary` |
| 8 | `MeanReversionMotor` | Aşırı alım/satım, ortalamaya dönüş potansiyeli | Bollinger pozisyonu, RSI aşırılık skoru |
| 9 | `SeasonalityMotor` | Mevsimsellik / takvim etkileri | Ay/çeyrek bazlı tarihsel örüntüler |

`SevenMotorEngine.compute_all()` bu motorların çıktısını tek bir feature
sözlüğünde birleştirir ve rejim bilgisini (`regime` alanı) ekler.

## 4.3 "Neden Düşüyor" motoru — ayırt edici tasarım örneği

`WhyFallingMotor`, ALPHA'nın klasik teknik analiz botlarından farkını en
net gösteren bileşendir. Bir hissenin düşüşünü tek boyutlu ("fiyat
düştü, sat") değil, **nedensel olarak** sınıflandırır:

- **Piyasa geneli satışı (market selloff)**: Endeks de düşüyorsa, tekil
  hissenin düşüşü büyük olasılıkla geçicidir (piyasa toparlandığında
  hisse de toparlanır).
- **Şirkete özgü (company-specific)**: Piyasa/sektör sakinken hisse tek
  başına düşüyorsa, bu daha kalıcı, temel bir soruna işaret edebilir.
- **Likidite şoku**: Anormal yüksek hacimle birlikte sert düşüş,
  panik satışı veya büyük oyuncu çıkışına işaret edebilir; kısa
  vadeli aşırı tepki (overreaction) fırsatı olabilir.

Motor bu sınıflandırmalardan bir **"geçicilik skoru"** (`falling_is_temporary`,
0-1 arası) üretir; bu skor Karar Motoru'nda "bu düşüş bir alım fırsatı mı
yoksa kaçınılması gereken bir uyarı mı" ayrımında kullanılır.

## 4.4 Cross-Sectional (kesitsel) katman

Tekil hisse feature'larının yanında, evren genelinde **göreli** ölçümler
de üretilir (`services/*/cross_sectional*`): sektör momentumu, evren
içi percentile sıralaması gibi. Bu, "hisse X %5 arttı" bilgisinin tek
başına anlamsız olabileceği, oysa "hisse X, sektöründeki 30 hisse
arasında en yüksek 5. momentuma sahip" bilgisinin sıralama modelinde çok
daha güçlü bir sinyal olduğu ilkesine dayanır.

## 4.5 Mask-aware feature hesaplama

Bölüm 03.3'te açıklanan Tradability Mask, feature hesaplamasından
**önce** uygulanır. Pratikte bu şu demektir: bir enstrümanın belirli bir
gün "tradable değil" (halt, veri hatası, işlem görmüyor) olarak
işaretlenmesi durumunda, o günün fiyat/hacim verisi hareketli
ortalama/momentum gibi pencere hesaplamalarına **hiç girmez** — sadece
sonuçta `None` yapılmaz. Bu ayrım, görünüşte küçük ama istatistiksel
olarak kritik bir tasarım kararıdır (bkz. `tests/test_faz_v3.py::
test_mask_integration`).

## 4.6 Yeni motor ekleme süreci (disiplin)

Yeni bir feature motoru eklemek, varsayılan davranış değil, kanıtla
kazanılan bir haktır. Süreç:

1. **Hipotez**: Bu motorun temsil ettiği piyasa gerçekliği nedir? Hangi
   literatür/gözlem buna dayanak oluşturuyor?
2. **Point-in-time doğruluk**: Motor yalnızca t anında bilinebilecek
   veriyi kullandığını kanıtlamalı (birim testle).
3. **Marjinal katkı testi**: Motor, mevcut feature setine eklendiğinde
   out-of-sample sıralama/tahmin performansını (bkz. Bölüm 07) **istatistiksel
   olarak anlamlı** şekilde iyileştiriyor mu? İyileştirmiyorsa eklenmez —
   "belki işe yarar" gerekçesiyle motor sayısını şişirmek yasaktır
   (karmaşıklık kendi başına bir maliyettir: overfitting riski, bakım
   yükü, yorumlanabilirlik kaybı).
4. **Rejim duyarlılığı incelemesi**: Motorun farklı rejimlerde nasıl
   davrandığı belgelenir.
5. **Yönetişim onayı**: Governance Brain / insan onayı olmadan motor
   canlı ranking modeline giremez.

## 4.7 Bilinen sınırlamalar (bugün için dürüst not)

- Motorların bir kısmı şu an sentetik/test verisiyle doğrulanmıştır;
  gerçek piyasa verisiyle uzun dönemli marjinal katkı analizi henüz
  yapılmamıştır (bkz. Bölüm 09).
- `KAPNewsMotor`'un sentiment kalitesi, kullanılan NLP/LLM bileşeninin
  Türkçe finansal metindeki doğruluğuna bağlıdır; bu doğruluk henüz
  sistematik olarak ölçülmemiştir.
- Feature isimlendirme standardı (`_5d`, `_20d` gibi dönem sonekleri)
  motorlar arasında tam tutarlı değildir; bu bir temizlik/standardizasyon
  görevi olarak yol haritasına alınmalıdır.
