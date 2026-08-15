# Bölüm 7 — Değerleme

## Amaç

Şirket kaliteli ve geleceği olumlu görünse bile, mevcut fiyatının bu beklentilere göre ucuz mu pahalı mı olduğunu belirlemek.

---

## Kullanılacak sistemler

- DCF
- Relative Valuation
  - P/E, P/B, EV/EBITDA vb. çarpanlar
- Fair Value Engine
- Growth Assumptions
- Margin of Safety
- Sector Valuation Comparison

---

## Çalışma mantığı

```
Şirket Analizi + Haber / KAP / Olaylar + Sektör + Makro
    ↓
Gelecek finansal varsayımlar
    ↓
DCF + Çarpan Analizi
    ↓
Fair Value
    ↓
Mevcut Fiyat
    ↓
Upside / Downside
    ↓
Margin of Safety
```

---

## Nasıl kullanılacak?

Örneğin sistem şirket için:

- Büyüme: %25
- Marj: iyileşiyor
- FCF: güçlü
- Risk: orta

gibi Bölüm 5 ve 6'dan gelen bilgileri kullanarak geleceğe yönelik finansal varsayımlar oluşturur.

Sonra tek bir yönteme güvenmez.

Örneğin:

- DCF Fair Value → 150 TL
- P/E Fair Value → 142 TL
- EV/EBITDA Value → 155 TL
- Sector Comparison → 148 TL

Bunları karşılaştırarak daha sağlam bir fair value aralığı oluşturur.

Örneğin:

```
Current Price:    110 TL
Fair Value Range: 142–155 TL
Expected Upside:  +29–41%
```

---

## Çok önemli prensip

**İyi şirket ≠ iyi yatırım.**

Şirket mükemmel olabilir ama fiyatı aşırı pahalıysa sistem bunu fırsat olarak değerlendirmemeli.

Aynı şekilde ucuz görünen bir hisse de sadece ucuz olduğu için önerilmemeli.

---

## Diğer bölümlerle etkileşim

- **Fundamental** → DCF varsayımlarını besler.
- **Haber/KAP** → Gelecek gelir, büyüme veya risk varsayımlarını değiştirebilir.
- **Makro** → İskonto oranı ve büyüme varsayımlarını etkiler.
- **Sektör** → Çarpanların karşılaştırılacağı referansı sağlar.
- **Risk** → Fair value'nun güven aralığını etkiler.

---

## Çıktı

```
Fair Value:           142–155 TL
Current Price:        110 TL
Upside:               +29–41%
Valuation:            Ucuz
Margin of Safety:     Orta/Yüksek
Valuation Confidence: %84
```

Bu da Bölüm 8 — Gelecek Tahmini için başlangıç girdilerinden biri olur.

---

## Temel prensip

Sistem sadece "hisse ucuz" demeyecek; "hangi varsayımlarla, hangi yöntemlerle, ne kadar ucuz ve bu hesabın güveni ne?" sorularını cevaplayacak.
