# 07 — Değerlendirme ve Başarı Kriterleri

## 7.1 Neden bu belge en kritik belgelerden biri

"Sistem çalışıyor mu?" sorusuna dürüst bir cevap vermek, iyi bir sistem
kurmaktan daha zordur. Kantitatif finansın tarihi, geriye dönük olarak
mükemmel görünüp canlıda tamamen başarısız olan sayısız strateji
örneğiyle doludur. Bu belge, ALPHA'nın kendi kendini kandırmasını
önlemek için kullanılacak somut istatistiksel ve süreçsel standartları
tanımlar.

## 7.2 Katmanlı değerlendirme — üç ayrı soru

Sistem üç ayrı, birbirine indirgenemeyen soru üzerinden değerlendirilir:

1. **Süreç doğru mu?** (Process validity) — Sızıntı yok mu, point-in-time
   disiplini var mı, testler gerçek assertion içeriyor mu, veri kalitesi
   kontrol ediliyor mu?
2. **Model istatistiksel olarak anlamlı mı?** (Statistical validity) —
   Gözlenen performans şans eseri mi, yoksa gerçek bir edge mi?
3. **Getiri iş açısından anlamlı mı?** (Economic significance) — İstatistiksel
   olarak anlamlı olsa bile, işlem maliyeti/slipaj sonrası, gerçekçi
   sermaye ölçeğinde anlamlı bir getiri sunuyor mu?

**Kural: 1. soru "hayır" ise, 2. ve 3. sorular değerlendirilmez.** Sızıntılı
bir sistemin "harika Sharpe oranı" hiçbir anlam taşımaz.

## 7.3 Süreç doğrulama kontrol listesi

- [ ] Her feature'ın point-in-time doğruluğu birim testle kanıtlanmış mı?
- [ ] Etiket üretimi ile feature üretimi arasında purge+embargo uygulanmış mı?
- [ ] Walk-forward her fold'da modeli gerçekten yeniden eğitiyor mu (bkz. 05.3)?
- [ ] Test paketinde "her zaman geçen" (`assert ... or True` tarzı) sahte
      assertion var mı? (Varsa bu testler geçersiz sayılır.)
- [ ] Sabit/hard-coded "canlı görünen" veri var mı? (Varsa bu bir üretim
      engelleyicisidir — bkz. `memory/CURRENT-STATE.md` madde 4.)
- [ ] Veri kalite kapısı (mask) feature hesaplamasından önce mi uygulanıyor?

## 7.4 İstatistiksel anlamlılık standartları

Basit bir "backtest Sharpe oranı 2.0 çıktı, harika" yaklaşımı **kabul
edilmez**. Aşağıdaki kontroller zorunludur:

- **Deflated Sharpe Ratio (DSR)**: Çok sayıda strateji/parametre
  denendiğinde (multiple testing), gözlemlenen en iyi Sharpe oranının
  şans eseri elde edilme olasılığı hesaba katılır. Kaç farklı
  strateji/parametre kombinasyonu denendiği **kayıt altında tutulmalıdır**
  ("deneme sayısını saymayan" bir araştırma süreci güvenilmezdir).
- **Probabilistic Sharpe Ratio (PSR)**: Gözlemlenen Sharpe oranının
  belirli bir eşiği (örn. 0) gerçekten aştığına dair istatistiksel güven
  aralığı.
- **Bootstrap / block-bootstrap güven aralıkları**: Getiri serisinin
  otokorelasyonunu koruyarak (blok bootstrap) performans metriklerinin
  güven aralığı tahmin edilir; tek nokta tahmini ("Sharpe = 1.8") asla
  tek başına yeterli kanıt sayılmaz.
- **Information Coefficient (IC)**: Sıralama modelinin tahmin ettiği
  skor ile gerçekleşen getiri arasındaki (Spearman) korelasyon; zaman
  içindeki IC ortalaması ve istikrarı (IC Information Ratio) izlenir.
- **Precision@K / NDCG**: "En iyi K fırsat" olarak seçilen hisselerin
  gerçekten en iyi performans gösterenler arasında olup olmadığı.
- **Fold-arası istikrar**: Walk-forward fold'ları arasındaki performans
  varyansı; yalnızca 1-2 fold'da iyi olan bir model "genel olarak iyi"
  sayılmaz.

## 7.5 Ekonomik anlamlılık kontrolleri

- İşlem maliyeti, slipaj ve gerçekçi likidite kısıtları **düşüldükten
  sonraki** net getiri esas alınır (bkz. Bölüm 06.5).
- Kapasite analizi: Strateji, hedeflenen sermaye ölçeğinde (örn.
  ilerleyen fazlarda daha büyük sanal portföy büyüklükleri) hâlâ
  uygulanabilir mi, yoksa yalnızca çok küçük pozisyon büyüklüklerinde mi
  işe yarıyor?
- Piyasa rejimine bağımlılık: Getirinin büyük kısmı tek bir dönemden
  (örn. tek bir güçlü boğa piyasası ayı) mı geliyor? Öyleyse bu, genel
  bir "edge" değil, o döneme özgü bir şans olabilir.

## 7.6 Zaman ufku ve minimum kanıt eşiği

Sistemin "gerçekten çalışıyor" denilebilmesi için asgari şu koşullar
**birlikte** sağlanmalıdır — bunlardan biri eksikse iddia zayıftır:

- **Süre**: En az 2-3 farklı piyasa rejimini (yükseliş, düşüş/düzeltme,
  yatay/düşük volatilite) kapsayan, kesintisiz çok yıllık sanal
  operasyon.
- **Örneklem büyüklüğü**: İstatistiksel çıkarım yapmaya yetecek sayıda
  bağımsız karar/işlem (birkaç düzine işlem yeterli değildir; literatürde
  güvenilir performans değerlendirmesi genellikle yüzlerce-binlerce
  bağımsız gözlem gerektirir).
- **Out-of-sample tutarlılık**: Modelin eğitildiği dönemden tamamen
  ayrı, hiç görmediği dönemlerde de benzer performans göstermesi.
- **Canlı-vs-backtest tutarlılığı**: Gölge modda (shadow mode, gerçek
  sinyal üretmeden izlenen) ölçülen performansın, aynı dönem için
  backtest'in öngördüğü performansla yakın olması (büyük bir sapma,
  backtest metodolojisinde bir sorun olduğunun işaretidir).

## 7.7 "Başarısızlık" da bir sonuçtur ve raporlanmalıdır

Bir hipotez/model/motor test edilip işe yaramadığında, bu **gizlenmez**;
aksine dokümantasyona (örn. bir "araştırma günlüğü") kaydedilir: ne
denendi, neden işe yaramadı, hangi ders çıkarıldı. Bu, hem gelecekte aynı
hatanın tekrar denenmesini önler hem de sistemin gerçek araştırma
olgunluğunun bir göstergesidir. "Her şey harika gidiyor" anlatısı, ciddi
bir araştırma kurumunun değil, pazarlamanın diliydir — ALPHA bunu
reddeder (bkz. `01-VIZYON-VE-MANIFESTO.md` §1.7).

## 7.8 Gösterge paneli (dashboard) metrikleri — asgari set

Yönetim ve araştırma ekibinin her an görebilmesi gereken metrikler:

- Güncel rejim ve rejim geçiş geçmişi
- Portföy: değer, günlük/aylık/yıllık getiri, drawdown, volatilite
- Model: güncel champion versiyonu, son walk-forward IC/Sharpe, drift
  durumu
- Veri kalitesi: maskelenen enstrüman oranı, sağlayıcı gecikme/hata
  oranı
- Karar istatistikleri: günlük üretilen BUY/SELL/HOLD/NO_ACTION
  dağılımı, ortalama güven
- Açık riskler: sektör/tek pozisyon yoğunlaşması, mevcut limitlere
  yakınlık
