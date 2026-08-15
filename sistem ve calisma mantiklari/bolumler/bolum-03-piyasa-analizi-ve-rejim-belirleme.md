# Bölüm 3 — Piyasa Analizi ve Rejim Belirleme

## Amaç

Temizlenmiş verilerden piyasada şu anda hangi ortamın yaşandığını belirlemek. Hisse seçmeden önce piyasanın yönü, gücü ve risk seviyesi anlaşılır.

---

## Kullanılacak sistemler

- Technical Analysis
- Price Action
- Volume Analysis
- Volatility Engine
- Market Regime Detection
- Correlation Engine
- Macro Analysis
- Sector Analysis
- Relative Strength
- Anomaly Detection

---

## Çalışma mantığı

```
Temiz Veri
    ↓
Endeks Analizi
    ↓
Trend + Momentum
    ↓
Hacim
    ↓
Volatilite
    ↓
Makro Durum
    ↓
Sektör Dağılımı
    ↓
Korelasyonlar
    ↓
Anomali Kontrolü
    ↓
MARKET REGIME
```

---

## Neler hesaplanacak?

Örneğin:

- BIST100 trendi
- Momentum gücü
- Hacim artışı/azalışı
- Volatilite seviyesi
- Sektörlerin güçlü/zayıf olması
- Piyasanın risk-on / risk-off durumu
- Endeks ile sektörlerin ilişkisi
- Olağandışı fiyat/hacim hareketleri

---

## Rejim nasıl kullanılacak?

Sistem piyasayı örneğin:

- BULL
- BEAR
- SIDEWAYS
- HIGH_VOLATILITY
- RISK_ON
- RISK_OFF
- TRANSITION

gibi durumlarla sınıflandırabilir.

Bu sonuç sonraki bölümlerin davranışını değiştirecek.

Örneğin:

```
RISK-OFF
    ↓
Hisse bulma filtresi sıkılaşır
    ↓
Risk puanı yükseltilir
    ↓
Pozisyon büyüklüğü azaltılır
```

Ama:

```
RISK-ON + Güçlü sektör + Güçlü momentum
```

varsa uygun hisselerin önceliği artabilir.

---

## Çıktı

```
Piyasa rejimi:     RISK-OFF
Trend:             Negatif
Momentum:          Zayıf
Volatilite:        Yüksek
Güçlü sektörler:   ...
Zayıf sektörler:   ...
Piyasa riski:      Yüksek
```

Bu bölüm hisse önermez. Hisse bulma motoruna, "şu an nasıl bir piyasada seçim yapıyoruz?" bilgisini verir.
