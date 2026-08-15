# Bölüm 10 — Risk Motoru

## Amaç

Bir hissenin sadece ne kadar kazandırabileceğini değil, ne kadar ve hangi koşullarda kaybettirebileceğini belirlemek.

---

## Kullanılacak sistemler

- Risk Engine
- VaR / CVaR
- Maximum Drawdown
- Volatility
- Liquidity Risk
- Concentration Risk
- Factor Exposure
- Stress Test sonuçları
- Monte Carlo sonuçları
- Position Sizing

---

## Çalışma mantığı

```
Hisse + Monte Carlo + Volatilite + Market Regime + Fundamental Risk + Liquidity + Portfolio
    ↓
RISK ENGINE
    ↓
Risk Score + Maximum Loss + Drawdown + Position Limit + Risk/Reward
```

---

## Neler kontrol edilir?

Örneğin:

- Normal koşullarda ne kadar oynuyor?
- Kötü senaryoda ne kadar kaybedebilir?
- Likiditesi yeterli mi?
- Portföydeki başka hisselerle aynı riski taşıyor mu?
- Aynı sektörde fazla yoğunlaşma var mı?
- Hangi faktörlere aşırı maruz?
- Monte Carlo'nun kötü sonuçları ne kadar olası?
- Büyük düşüşten toparlanması ne kadar sürebilir?

---

## En önemli nokta

Risk motoru sadece risk puanı üretmez.

**Pozisyon büyüklüğünü de etkiler.**

Örneğin:

- Düşük Risk → %10 pozisyon mümkün
- Orta Risk → %5 pozisyon
- Yüksek Risk → %2 pozisyon
- Aşırı Risk → NO_TRADE

Gerçek oranlar sabit olmayacak; portföy ve risk limitlerine göre hesaplanacak.

---

## Önceki bölümlerle etkileşim

```
Monte Carlo → Downside → Risk Engine → Position Size
```

Ayrıca:

```
Market Regime + Portfolio Correlation + Liquidity
```

risk seviyesini değiştirebilir.

---

## Çıktı

```
Risk Score:            34/100
Risk Level:            Orta
VaR:                   X%
CVaR:                  Y%
Max Drawdown Estimate: Z%
Liquidity Risk:        Düşük
Concentration Risk:    Orta
Position Limit:        %5
Risk/Reward:           2.8
```

Bu çıktı Bölüm 11 — Portföy Etkisi ve Optimizasyon bölümüne gider.

---

## Temel prensip

Sistem "bu hisse iyi mi?" sorusundan önce **"bu fırsatı hangi riskle ve portföyün ne kadarını kullanarak değerlendirmeliyiz?"** sorusunu cevaplar.
