# 05 — Model, Öğrenme ve Araştırma Döngüsü

## 5.1 Sıralama (Ranking) yaklaşımı — neden "yarın X çıkar mı" değil

ALPHA'nın model katmanı klasik bir "yükselecek mi/düşecek mi" ikili
sınıflandırması değil, bir **sıralama (learning-to-rank)** problemidir:
"Bu evrendeki N hisseden hangileri, şu andaki rejim ve risk koşullarında,
en güçlü risk-ayarlı fırsatı sunuyor?" Bunun nedenleri:

- Portföy yönetimi doğası gereği görelidir — sınırlı sermaye, en iyi
  görece fırsatlara tahsis edilir.
- İkili sınıflandırma, hisseler arası göreli sıralamayı kaybeder ve
  eşik seçimine aşırı duyarlıdır.
- Sıralama modelleri (LambdaRank ve türevleri), finans literatüründe
  cross-sectional (kesitsel) faktör modelleriyle daha uyumludur.

`services/ml/ranking_model.py` bugün bir **LightGBM + rule-based
ensemble** kullanır; rule-based bileşen, ML modelinin veri yetersizliği
veya güven düşüklüğü durumunda devreye giren bir **fallback/güvenlik
ağıdır** — asla tek başına "gerçek zeka" olarak sunulmaz.

**Önemli kural (LambdaRank kuralı):** Bu sistemde düşük skor = üst
sıra. Bu, ranking loss fonksiyonunun iç sözleşmesidir ve tüm downstream
kod (Decision Engine, API, testler) bu sözleşmeye uymak zorundadır.
Geliştirme sürecinde bu kuralın unutulması, geçmişte gerçek bir
hataya (`tests/test_suite.py` içinde yanlış sıralama varsayımı) yol
açmıştır — bu, dokümantasyonun neden hem "ne" hem "neden" anlatması
gerektiğinin somut bir örneğidir.

## 5.2 Rejime duyarlı ağırzlıklandırma

Aynı feature seti, farklı piyasa rejimlerinde farklı öngörü gücüne
sahiptir. `RegimeEngine` (`services/intelligence/regime.py`), piyasa
genişliği (breadth), ortalama momentum, volatilite, risk iştahı gibi
girdilerden mevcut rejimi (BULL/BEAR/SIDEWAYS/HIGH_VOLATILITY vb.) tahmin
eder. Ranking modeli, her rejim için ayrı feature ağırlık setleri
(`_regime_feature_weights`) kullanır — yani "boğa piyasasında momentum
motoruna daha çok, yatay piyasada mean-reversion motoruna daha çok
ağırlık ver" gibi bir mantık, sabit kodlanmış kurallar yerine
kalibrasyona tabi parametreler olarak modellenir.

## 5.3 Walk-Forward doğrulama — sistemin "yalan söyleyip söylemediğinin" testi

Basit bir train/test bölmesi finansal zaman serilerinde yetersizdir çünkü
piyasa rejimi zamanla değişir (non-stationarity). ALPHA, **walk-forward**
metodolojisi kullanır (`services/backtest/walk_forward.py`):

1. Zaman ekseni ardışık **fold**'lara bölünür: eğitim penceresi (train) →
   test penceresi (test), pencere kaydırılarak (step) tekrarlanır.
2. **Purge**: Eğitim ve test pencereleri arasında, etiket hesaplamasında
   kullanılan ileri-bakışlı pencere (örn. "5 günlük ileri getiri")
   nedeniyle oluşabilecek örtüşme, `purge_days` kadar veri çıkarılarak
   engellenir.
3. **Embargo**: Test penceresinden hemen sonra da ek bir güvenlik boşluğu
   (`embargo_days`) bırakılır — otokorelasyonlu piyasa koşullarının
   sızıntı yaratmasını önlemek için.
4. Her fold için model **o foldun train penceresiyle sıfırdan/kalibre
   edilerek eğitilir**; tüm veri setiyle önceden eğitilmiş bir modelin
   sadece farklı zaman dilimlerinde "test edilmesi" walk-forward
   sayılmaz (bkz. `memory/CURRENT-STATE.md` madde 11 — bu ayrım bugün
   kod tabanında netleştirilmesi gereken bir noktadır).
5. Foldlar arası **istikrar skoru (stability score)** hesaplanır: model
   sadece bir dönemde iyi, diğerlerinde kötü çalışıyorsa bu düşük
   istikrar olarak işaretlenir ve modelin genel geçerliliği
   sorgulanır.

## 5.4 Champion / Challenger yaşam döngüsü

Hiçbir yeni model veya strateji doğrudan canlıya (paper trading
portföyüne sinyal üretecek şekilde) alınmaz. Yaşam döngüsü:

```
[Araştırma] → CANDIDATE → [Walk-Forward + İstatistiksel Test] → CHALLENGER
   → [Paralel gölge çalıştırma, gerçek sinyal üretmeden] → [Governance onayı]
   → CHAMPION (canlı) ←→ eski CHAMPION otomatik ARCHIVE'a alınır
```

- **CANDIDATE**: Araştırma Beyni'nin ürettiği, henüz doğrulanmamış model.
- **CHALLENGER**: Walk-forward ve istatistiksel anlamlılık testlerini
  geçmiş, ancak henüz gerçek zamanlı "gölge modda" (shadow mode —
  gerçek sinyal üretmeden, sadece izlenerek) kanıtlanmamış model.
- **CHAMPION**: Şu an canlı sinyal üreten, Governance Brain onaylı model.
- Bir CHALLENGER, belirlenen minimum gölge çalışma süresi (örn. en az
  birkaç ay, birden fazla rejim gözlemi) ve performans eşiği
  (bkz. Bölüm 07) olmadan CHAMPION olamaz.
- Terfi kararı **otomatik değildir** — Governance Brain / insan onayı
  zorunlu son adımdır.

## 5.5 Sürekli öğrenme döngüsü (feedback loop)

`services/learning/` modülü şu döngüyü işletir:

1. Her karar (tahmin) ile birlikte, gerçekleşmesi beklenen sonucun nasıl
   ölçüleceği (hangi ufuk, hangi referans) kaydedilir.
2. Zaman geçtikçe gerçekleşen sonuç (gerçekleşen getiri, doğru/yanlış
   yön) tahminle eşleştirilir.
3. Kalibrasyon hatası (tahmin edilen güven ile gerçekleşen isabet oranı
   arasındaki fark), feature importance drift'i ve model performans
   trendleri sürekli izlenir.
4. Belirlenen eşikler aşıldığında (örn. kalibrasyon hatası belirli bir
   sınırı geçerse, veya feature dağılımı önemli ölçüde kaydıysa —
   *data/concept drift*), model otomatik olarak **karantinaya alınır**
   ve yeniden eğitim/araştırma süreci tetiklenir.
5. Bu döngünün çıktısı yalnızca "modeli değiştir" değildir — aynı
   zamanda **neden** yanlış olduğuna dair bir teşhis (hangi rejimde,
   hangi feature grubunda, hangi sektörde) üretmesi beklenir. Bu,
   sistemi kör bir otomatik-yeniden-eğitim mekanizmasından, gerçek bir
   araştırma sürecine dönüştüren kısımdır.

## 5.6 Araştırma Beyni'nin uzun vadeli rolü (ileri faz)

Bugünkü kod tabanında `services/agents/` altında başlangıç seviyesinde
bir agent sistemi bulunmaktadır (bkz. Bölüm 09 — bu bileşenin bugünkü
olgunluk seviyesi sınırlıdır). Hedef mimaride Araştırma Beyni:

- yeni hipotezler üretir (örn. "sektör X'te belirli bir olay türü
  sonrası sistematik bir aşırı tepki var mı?"),
- bu hipotezleri geçmiş veride, sızıntısız şekilde test eder,
- sonuçları insan-okur formatında (kanıt + istatistik + sınırlamalar
  ile) raporlar,
- **kendi bulgularını asla kendisi canlıya almaz** — bulgu, Governance
  Brain'in bağımsız doğrulama sürecine bir "aday" olarak sunulur.

Bu, ALPHA'yı zamanla "insan bir kantitatif araştırmacının yaptığı işi
kısmen otomatikleştiren" bir sisteme dönüştürme hedefidir — ama bu,
projenin ileri fazlarına (bkz. Bölüm 08, Faz 5+) aittir ve bugünün
önceliği değildir.

## 5.7 Model karmaşıklığı disiplini

- Yeni bir model ailesi (örn. derin öğrenme, transformer tabanlı zaman
  serisi modelleri) yalnızca mevcut LightGBM+rule-based ensemble'ın
  ulaştığı performans tavanı net biçimde belgelenip aşılamadığı
  kanıtlandığında değerlendirilir.
- "Daha karmaşık = daha iyi" varsayımı reddedilir. Az veri + yüksek
  gürültü ortamında (ki BIST bireysel hisse verisi için bu geçerlidir),
  basit ve regularize edilmiş modeller genellikle daha sağlamdır.
- Her yeni model, aynı walk-forward + istatistiksel anlamlılık
  standardından geçmek zorundadır (Bölüm 07); "daha havalı" bir mimari
  olması ayrıcalık sağlamaz.
