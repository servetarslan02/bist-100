# Bölüm 1 — Piyasa ve Veri Anlama

## Ana amaç

Sistem herhangi bir hisseyi analiz etmeye başlamadan önce piyasanın o anki gerçek fotoğrafını çıkaracak.

Buradaki bölümün görevi hisse seçmek değil; sonraki bütün motorlara güvenilir ve anlamlandırılmış bir piyasa ortamı sağlamaktır.

---

## 1. Kullanılacak veri kaynakları

Sistem mümkün olduğunca şu kaynakları birlikte kullanacak:

- **Fiyat/OHLCV:** Açılış, yüksek, düşük, kapanış, hacim
- **Endeksler:** BIST100, BIST30, sektör endeksleri vb.
- **Şirket finansalları:** Bilanço, gelir tablosu, nakit akışı
- **KAP:** Özel durum açıklamaları ve şirket bildirimleri
- **Haberler:** Şirket, sektör ve ekonomi haberleri
- **Sosyal medya:** Yatırımcı ilgisi ve sentiment
- **Makro veriler:** Faiz, enflasyon, döviz, CDS, emtia vb.
- **Sektör verileri:** Sektör performansı ve gelişmeleri
- **Corporate actions:** Temettü, bölünme, bedelsiz, sermaye artırımı
- **Trading calendar:** Seans, tatil ve piyasa açık/kapalı bilgisi
- **FX:** TRY/USD/EUR gibi kur verileri

---

## 2. Sistem bunları ayrı ayrı toplamakla kalmayacak

Veriler zaman damgasıyla sisteme girecek.

Örneğin:

- BIST100 → -%1.8
- Bankacılık → -%2.7
- USD/TRY → +%0.8
- Faiz → yüksek
- Sektör sentiment → negatif
- Hisse X → -%3.2
- Hisse X hacim → yüksek

Sistem bunları birlikte değerlendirerek:

> "Bugünkü piyasa ortamı risk-off, bankacılık sektörü piyasadan daha zayıf ve döviz hareketi yüksek."

gibi yapısal piyasa durumu oluşturacak.

---

## 3. Veriler birbirini nasıl etkileyecek?

Önemli nokta bu.

Örneğin:

```
Makro ↓ Sektör ↓ Şirket ↓ Hisse
```

ve:

```
Haber + KAP ↓ Şirket olayı ↓ Hisse üzerindeki potansiyel etki
```

ve:

```
BIST100 + Sektör Endeksi + Hisse ↓ Relative Strength
```

şeklinde ilişkiler kurulacak.

Yani sistem her veriyi bağımsız kolon olarak saklayıp bırakmayacak.

---

## 4. Zaman boyutu

Her veri:

- Ne zaman oluştu?
- Ne zaman sisteme geldi?
- Hangi dönem için geçerli?

bilgileriyle tutulacak.

Bu özellikle daha sonra:

- backtest
- tahmin
- Monte Carlo
- haber analizi

sırasında geleceğin geçmişe sızmasını engelleyecek.

---

## 5. Çıktı ne olacak?

Bölüm 1 sonunda sistemin elinde şu bulunacak:

```
MARKET STATE
Piyasa rejimi: ?
Endeks durumu: ?
Sektör durumu: ?
Makro durum: ?
Volatilite: ?
Likidite: ?
Haber ortamı: ?
KAP aktivitesi: ?
Sosyal sentiment: ?
Kur ortamı: ?
Önemli olaylar: ?
Veri güncelliği: ?
```

Bu çıktı Bölüm 2'nin veri kalitesi kontrolünden geçecek ve ardından:

- Piyasa Analizi
- Hisse Bulma
- Fundamental
- Haber
- Tahmin
- Risk

motorlarının girdisi olacak.

---

## Kısacası

**Bölüm 1 = Sistemin dünyayı algılama katmanı.**

Hisse seçmez, BUY vermez, tahmin yapmaz.

Önce:

> "Piyasa şu anda hangi ortamda, hangi olaylar yaşanıyor ve elimizde hangi bilgiler var?"

sorusunu mümkün olduğunca doğru cevaplar.
