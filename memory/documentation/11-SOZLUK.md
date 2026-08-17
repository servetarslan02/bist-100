# 11 — Sözlük

**Alpha (fırsat skoru anlamında)**: Piyasa ortalamasının/beklenenin
üzerinde risk-ayarlı getiri potansiyeli; bu projede aynı zamanda sistemin
adıdır.

**Backtest**: Bir stratejinin geçmiş veri üzerinde, o veriyi "canlıymış
gibi" simüle ederek test edilmesi.

**Champion / Challenger**: Sırasıyla şu an canlıda kullanılan model
(champion) ve onu geçmeye aday, henüz doğrulanmakta olan model
(challenger). Bkz. Bölüm 05.4.

**Cross-Sectional (kesitsel)**: Tek bir zaman noktasında, evrendeki
tüm enstrümanlar arasında karşılaştırmalı (göreli) analiz.

**Data/Concept Drift**: Zaman içinde veri dağılımının veya
değişkenler-arası ilişkilerin değişmesi; modelin eskiyip
performansının düşmesine yol açabilir.

**Deflated Sharpe Ratio (DSR)**: Çok sayıda strateji/parametre
denemesinin (multiple testing) yol açtığı şans başarısını düzelten,
Sharpe oranının istatistiksel anlamlılığını ölçen metrik.

**Drawdown**: Bir portföyün tepe değerinden itibaren yaşadığı düşüş
yüzdesi; maksimum drawdown, en kötü düşüş anıdır.

**Embargo (walk-forward bağlamında)**: Test penceresinden hemen sonra
bırakılan, otokorelasyon kaynaklı sızıntıyı önlemek için kullanılan
ek güvenlik boşluğu.

**Fold**: Walk-forward doğrulamada zaman ekseninin ardışık eğitim/test
parçalarından her biri.

**IC (Information Coefficient)**: Modelin tahmin ettiği sıralama/skor
ile gerçekleşen getiri arasındaki (genellikle Spearman) korelasyon.

**KAP**: Kamuyu Aydınlatma Platformu — Türkiye'de halka açık şirketlerin
zorunlu bildirimlerini yayınladığı resmi platform.

**Kelly Kriteri**: Bir bahsin/pozisyonun teorik olarak uzun vadeli
sermaye büyümesini maksimize eden büyüklüğünü hesaplayan formül;
uygulamada aşırı volatiliteyi önlemek için genellikle "kesirli" (fractional)
biçimde kullanılır.

**Leakage (Sızıntı)**: Bir modelin, karar anında aslında bilinemeyecek
gelecek bilgiye (doğrudan veya dolaylı) erişmesi; backtest sonuçlarını
yapay olarak iyileştirir, canlıda aynı performans tekrarlanmaz.

**Materiality (Önemlilik)**: Bir olayın (haber, KAP açıklaması vb.)
fiyat/karar üzerinde ne kadar etkili olması beklendiğinin ölçüsü.

**Paper Trading (sanal işlem)**: Gerçek sermaye kullanmadan, gerçek
piyasa koşullarını simüle ederek yapılan işlem/portföy takibi.

**Point-in-Time (PIT)**: Bir veri noktasının, tarihte o an gerçekten
bilinebilir olduğu haliyle (sonraki revizyonlar olmadan) kullanılması
ilkesi.

**Precision@K**: Bir sıralama modelinin önerdiği ilk K sonucun ne
kadarının gerçekten "doğru/başarılı" olduğunun oranı.

**Purge (walk-forward bağlamında)**: Eğitim ve test pencereleri arasında,
etiket hesaplama penceresinin neden olabileceği örtüşmeyi önlemek için
çıkarılan veri aralığı.

**Regime (Rejim)**: Piyasanın o anki genel karakteri (boğa, ayı, yatay,
yüksek/düşük volatilite gibi); modelin davranışını buna göre uyarlaması
beklenir.

**Sharpe Oranı**: Risk-ayarlı getiri ölçütü; getirinin, getirinin
standart sapmasına (volatilite) oranı.

**Slipaj (Slippage)**: Bir emrin, karar anındaki fiyattan farklı bir
fiyattan gerçekleşmesi; genellikle emir büyüklüğü ve piyasa likiditesine
bağlıdır.

**Tradability Mask**: Bir enstrümanın belirli bir zaman diliminde
güvenilir/işlem yapılabilir kabul edilip edilmediğini işaretleyen,
feature hesaplamasından önce uygulanması gereken veri kalite katmanı.

**Walk-Forward**: Zaman serisi verisinde, art arda kayan eğitim/test
pencereleriyle, her adımda modelin gerçekten yeniden eğitilip
değerlendirildiği doğrulama metodolojisi.
