# ALPHA BIST — ROADMAP v2.0

> **Felsefe:** "Yarın ne olacak?" değil → "Mevcut rejimde hangi risk-getiri profili avantajlı?"
> **Hedef:** Her gün BIST evrenini değerlendirip, risk-getiri açısından en avantajlı fırsatları sıralayan adaptif piyasa istihbarat sistemi.
> **Başlangıç:** 16 Ağustos 2026

---

## Mimari (v2.0)

```
PİYASA REJİMİ (BIST trend, volatilite, faiz, USDTRY, breadth, sektör rotasyonu, küresel)
    ↓
HER HİSSE İÇİN 7 MOTOR:
    1. Relatif Güç Motoru (1d/5d/20d/60d/120d vs BIST + sektör)
    2. Momentum + Trend Motoru (eğim, süreklilik, ivme, değişim yönü)
    3. Hacim + Mikroyapı Motoru (tick rule, VWAP sapma, hacim-fiyat ilişkisi)
    4. Fundamental Motor (sektörel normalize, FCF merkezli, bilanço kalitesi)
    5. KAP + Haber Motoru (LLM extraction: etki, süre, belirsizlik)
    6. Katalizör Motoru (yaklaşan olaylar, beklenmediklik)
    7. "Neden Düşüyor?" Motoru (market/sector/company/liquidity/panic)
    ↓
PROBABILISTIC RANKING
    P(5d relatif pozitif)    P(20d > sektör)
    P(20d > +5%)             P(max drawdown > X)
    P(yukarı devam)          P(aşağı devam)
    ↓
CROSS-SECTIONAL SIRALAMA (tüm BIST'te göreli)
    ↓
RİSK MOTORU (konsantrasyon, korelasyon, volatilite, likidite)
    ↓
PORTFÖY MOTORU (pozisyon büyüklüğü, rebalance)
    ↓
ÇIKTI: Sıralı fırsat listesi + neden + güven + risk profili
```

---

## Faz Planı

### FAZ 1: Hedef Fonksiyonu & Temel Yapı ⬜
**Amaç:** "Fiyat tahmini" → "Probabilistic ranking" dönüşümü
- [ ] Prediction target'ları tanımla (P(5d>sector), P(20d>+5%), vb.)
- [ ] Cross-sectional ranking motoru
- [ ] Label generation pipeline (gelecek getiri → target label)
- [ ] Walk-forward validation framework
- [ ] Metrik sistemi (Alpha, Precision@K, IC, Hit Rate, Sharpe)

### FAZ 2: Relatif Güç Motoru ⬜
**Amaç:** Hisse vs BIST + sektör karşılaştırması (çok ufuklu)
- [ ] 1d/5d/20d/60d/120d relatif getiri hesaplama
- [ ] Sektör relatif gücü
- [ ] Peer relatif gücü
- [ ] Relatif güç trendi (güçlüyor mu, zayıflıyor mı?)
- [ ] Cross-sectional rank (tüm BIST'te sıralama)

### FAZ 3: Momentum + Trend Motoru ⬜
**Amaç:** Momentum seviyesi değil, ivme ve değişim yönü
- [ ] Trend eğimi (lineer regresyon slope)
- [ ] Trend sürekliliği (R²)
- [ ] Momentum ivmesi (değişim yönü: azalan satış baskısı gibi)
- [ ] Yeni yüksek/düşük tespiti
- [ ] Breakout başarısızlığı tespiti
- [ ] Drawdown + toparlanma gücü
- [ ] Fiyatın hareketli ortalamalara göre konumu

### FAZ 4: Hacim + Mikroyapı Motoru ⬜
**Amaç:** Hacim yüksek ≠ anlamlı. Fiyat-hacim ilişkisi kritik.
- [ ] Normalleştirilmiş hacim (z-score değil, percentile)
- [ ] Hacim-fiyat yönü ilişkisi (yükseliş+patlama vs düşüş+patlama)
- [ ] Yükseliş günlerinde hacim vs düşüş günlerinde hacim
- [ ] Tick rule (aktif alış/aktif satış dengesi)
- [ ] VWAP sapması
- [ ] Hacim anomalisi (zaman bazlı)
- [ ] Turnover ve likidite skoru

### FAZ 5: Fundamental Motor ⬜
**Amaç:** Sektörel normalize + FCF merkezli
- [ ] F/K, PD/DD, FD/FAVÖK, F/Satış sektörel normalize
- [ ] ROE, ROIC, borçluluk
- [ ] FCF, faaliyet nakit akışı
- [ ] Kârlılık trendi (marj genişliyor/daralıyor)
- [ ] Satış büyüme trendi
- [ ] Bilanço kalitesi skoru
- [ ] Enflasyon muhasebesi düzeltmesi (TMS 29)
- [ ] Parasal pozisyon kâr/zarar arındırması

### FAZ 6: KAP + Haber Motoru ⬜
**Amaç:** Basit pozitif/negatif değil, yapılandırılmış extraction
- [ ] KAP metin çıkarma (şirket, olay türü, finansal etki)
- [ ] Beklenmediklik skoru (tarihsel ortalamaya göre)
- [ ] Etki yönü + büyüklüğü + süresi + belirsizliği
- [ ] Sektör zincirleme etkisi
- [ ] Haber duplication engelleme
- [ ] Sentiment momentum (seviye + değişim hızı)

### FAZ 7: Katalizör Motoru ⬜
**Amaç:** Yaklaşan olaylar ayrı skor
- [ ] Bilanço tarihi
- [ ] Temettü tarihi
- [ ] Bedelsiz/bedelli
- [ ] İhale, sözleşme, kapasite artışı
- [ ] Regülasyon, dava sonucu
- [ ] Geri alım
- [ ] Önemli yatırım
- [ ] Beklenmediklik + belirsizlik skoru

### FAZ 8: "Neden Düşüyor?" Motoru ⬜
**Amaç:** Düşen bıçağı tutma hatasını önle
- [ ] Market selloff tespiti (BIST genel düşüş)
- [ ] Sector selloff tespiti
- [ ] Company-specific bad news
- [ ] Earnings deterioration
- [ ] Liquidity event
- [ ] Technical breakdown
- [ ] Temporary panic
- [ ] Unknown
- [ ] Düşüş nedeni geçici mi kalıcı mı olasılığı

### FAZ 9: Probabilistic Ranking ⬜
**Amaç:** Tek skor değil, olasılık dağılımı
- [ ] P(5 günlük relatif pozitif getiri)
- [ ] P(20 günlük relatif pozitif getiri)
- [ ] P(20 günlük > +5%)
- [ ] P(20 günlük > sektör)
- [ ] P(max drawdown > X)
- [ ] P(yukarı hareket devamı)
- [ ] P(aşağı hareket devamı)
- [ ] Ensemble: 7 motorun çıktısını birleştir

### FAZ 10: Risk + Portföy Motoru ⬜
**Amaç:** Kurumsal kalite risk yönetimi
- [ ] Konsantrasyon riski (sektör, hisse)
- [ ] Korelasyon riski
- [ ] Volatilite riski
- [ ] Likidite riski
- [ ] Portföy optimizasyonu (risk-adjusted)
- [ ] Rebalance kuralları
- [ ] Pozisyon büyüklüğü (Kelly criterion benzeri)

### FAZ 11: Değerlendirme & Öğrenme ⬜
**Amaç:** Modeli doğru ölçmek
- [ ] Alpha hesaplama (BIST'e göre fazla getiri)
- [ ] Precision@K (ilk 5/10/20 hisseden kaç tanesi iyi)
- [ ] Information Coefficient (IC)
- [ ] Hit rate
- [ ] Sharpe ratio
- [ ] Max drawdown
- [ ] Turnover
- [ ] Walk-forward backtest
- [ ] Out-of-sample test
- [ ] Feature importance feedback

### FAZ 12: Dashboard & API ⬜
**Amaç:** Kullanılabilir arayüz
- [ ] Overview: rejim, breadth, fırsatlar, portföy
- [ ] Market Radar: tüm BIST tarama
- [ ] Fırsat detayı: 7 motor skoru + neden + güven
- [ ] Portföy: pozisyonlar, P&L, risk
- [ ] Backtest: strateji performansı
- [ ] Learning: model doğruluk, drift
- [ ] API endpoints

---

## Temel Prensipler

1. **Fiyat tahmini yapma** → Probabilistic ranking yap
2. **Sabit kriter kullanma** → Adaptif, öğrenen, rejime göre değişen
3. **Tek modele güvenme** → Ensemble (7 motor)
4. **Mutlak getiriye bakma** → Relatif getiri (vs BIST, vs sektör)
5. **Seviyeye bakma** → İvme ve değişim yönü
6. **Yükselen hacmi anlama** → Fiyat-hacim ilişkisi
7. **Düşeni al** → Önce "neden düştü?" sor
8. **Ölçemediğini yöneteme** → Doğru metrikler kullan
