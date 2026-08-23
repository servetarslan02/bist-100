# 01 — Vizyon ve Manifesto

## 1.1 Tek cümlelik vizyon

ALPHA BIST; piyasayı sürekli gözlemleyen, dünya hakkında bir model kuran,
fırsatları olasılıksal olarak sıralayan, riskini yöneten, sanal bir portföyü
yıllarca kesintisiz işleten ve kendi hatalarından **kanıta dayalı** şekilde
öğrenen, otonom ama denetlenebilir bir yatırım araştırma sistemidir.

Nihai hedef bir "sinyal botu" değil; finansal muhakeme yapabilen, dünya
çapında sayılı seviyede bir **yatırım zekasının** temelini atmaktır.

## 1.2 Neden bu bir "bot" değil

Klasik bir algoritmik trading botu şu formülle çalışır:
`Eğer koşul X ise, işlem Y yap.` Bu yaklaşımın üç yapısal sınırı vardır:

1. **Rejim körlüğü.** Sabit kurallar, piyasa rejimi değiştiğinde
   (boğa → ayı, düşük volatilite → kriz) sessizce bozulur.
2. **Neden bilgisi yok.** "Fiyat düştü" ile "neden düştü" (piyasa geneli mi,
   şirkete özgü mü, likidite şoku mu, kalıcı mı geçici mi) arasındaki fark
   bir kural motorunda temsil edilemez; bir muhakeme sürecinde temsil
   edilebilir.
3. **Öğrenme yok.** Kurallar elle güncellenmediği sürece statiktir; piyasa
   ise sürekli adapte olan bir rakip ortamdır (adversarial, non-stationary).

ALPHA bunun yerine üç katmanlı bir zekayı hedefler: **gözlem** (dünya
modelini güncel tut) → **muhakeme** (rejim, neden-sonuç, olasılıksal
sıralama) → **öğrenme** (sonuçları ölç, modeli/politikayı kanıtla güncelle).
Bu, klasik "teknik analiz botu" ile bir araştırma kurumu arasındaki farktır.

## 1.3 Neden önce sanal para (paper trading)

Gerçek sermaye ile başlamak üç nedenle yanlıştır:

- **İstatistiksel güven eksikliği.** Birkaç haftalık/aylık gerçek getiri,
  şans ile beceriyi ayırt etmeye yetmez (bkz. Bölüm 07 — Deflated Sharpe,
  çoklu test düzeltmesi). Yıllarca çalışıp binlerce kararı biriktirmeden
  "bu sistem çalışıyor" denemez.
- **Geri döndürülemez hata riski.** Bir feature hesaplama hatası veya
  veri sızıntısı, gerçek parada geri alınamaz kayıplara yol açar; sanal
  ortamda ise ucuz bir öğrenme fırsatıdır.
- **Rejim çeşitliliği ihtiyacı.** Sistemin boğa, ayı, yatay, yüksek/düşük
  volatilite gibi farklı rejimlerde nasıl davrandığını görmek gerekir; bu
  da doğası gereği uzun bir zaman ufku (çok yıllı) ister.

Bu nedenle proje bilinçli olarak **"yıllarca sanal portföyle kendini
kanıtlama"** fazını, gerçek sermaye tartışmasının önüne koyar. Gerçek
sermaye kullanımı bu doküman setinin kapsamında **değildir** ve ayrı,
çok daha katı bir yönetişim/regülasyon incelemesi gerektirir (bkz. 10.6).

## 1.4 "Üç Beyin" felsefesi (mevcut MASTER-SPEC ile uyumlu, iş diliyle)

Sistemin kendini kandırmasının en büyük riski, aynı bileşenin hem strateji
üretip hem kendi başarısına karar vermesidir. Bu yüzden ALPHA üç ayrı
sorumluluk alanına bölünür — bunlar illa üç ayrı yapay zeka modeli değil,
üç ayrı **yetki ve sorumluluk sınırıdır**:

1. **Operasyon Beyni (Operating Brain)** — canlı gözlem, güncel durum,
   sıralama, risk uygulaması, sanal emir yürütme, portföy defteri,
   performans ölçümü, "safe-mode" (bir şeyler bozulduğunda kendini
   otomatik kısıtlama) davranışı. *Bugünü yönetir.*
2. **Araştırma Beyni (Research Brain)** — hipotez üretimi, yeni feature/
   faktör keşfi, model araştırması, sağlamlık (robustness) testleri,
   strateji keşfi, "aday" (challenger) model/strateji üretimi. *Geleceği
   araştırır ama asla kendi kendini terfi ettiremez.*
3. **Yönetişim Beyni (Governance Brain)** — veri soy kütüğü (lineage),
   sızıntı koruması, out-of-sample performans doğrulaması, tekrarlanabilirlik,
   risk politikası uygunluğu, terfi (promotion) kuralları, denetim
   bütünlüğü. *Hakemdir; ne strateji üretir ne de üretilen sonuçları
   uydurur — sadece bağımsızca doğrular veya reddeder.*

**Kural:** Araştırma Beyni kendi ürettiği stratejiyi canlıya alamaz.
Operasyon Beyni kendi risk kurallarını gevşetemez. Yönetişim Beyni
sonuç uydurup ikisini de "onaylayamaz." Bu ayrım, insan organizasyonlarındaki
"araştırma / masa (desk) / risk-uyum" ayrımının yazılım karşılığıdır.

## 1.5 Kapsam ilkesi: sabit tavan yok, ama sınırsız eşzamanlılık da yok

Sistem yalnızca BIST 100 ile sınırlı kalacak şekilde tasarlanmaz; hedef
kapsam tüm BIST evreni, KAP açıklamaları, Türkiye makro/politika verisi,
küresel makro ve ilgili küresel varlıklar, sektör/tedarik zinciri/rakip
ilişkileri ve haber/kamuya açık bilgi kaynaklarıdır (`docs/MASTER-SPEC.md`
ile birebir uyumlu). Ancak bu, her kaynağa her an eşit hesaplama gücü
verileceği anlamına gelmez — adaptif önceliklendirme (HOT/WARM/COLD katmanlar)
ve açık hesaplama bütçeleri kullanılır. "Sınırsız kapsam" bir mühendislik
disiplinsizliği bahanesi değildir.

## 1.6 Kırmızı çizgiler (asla yapılmaz)

1. **Sahte/uydurma veri asla gerçek gözlem gibi sunulmaz.** Sabit
   (hard-coded) "canlı görünen" piyasa değerleri; gerçek veri yoksa
   sistem bunu açıkça "eksik/bilinmiyor" olarak işaretler, uydurmaz.
2. **Geleceği gören (leakage) hiçbir özellik/model canlıya alınamaz.**
   Nokta-zamanlı (point-in-time) doğruluk kanıtlanmadan hiçbir feature
   üretim ortamına girmez.
3. **Kendi kendini terfi ettiren bileşen olamaz.** Yeni bir model/strateji,
   yalnızca Yönetişim Beyni'nin bağımsız doğrulamasından geçerse
   "champion" (üretimde kullanılan) statüsüne yükselir.
4. **Test sayısı veya dosya sayısı başarı kanıtı değildir.** "500 test
   geçti" cümlesi, testlerin gerçekten anlamlı assertion içerdiği
   kanıtlanmadan hiçbir yerde ilerleme kanıtı olarak kullanılmaz.
5. **Sır (secret) kaynak kodunda tutulmaz.** Şifre, token, API anahtarı
   asla repoya commit edilmez (bkz. Bölüm 10.2 — bu kural bu projede
   zaten bir kez ihlal edilmiştir ve düzeltilmesi gerekmektedir, bkz.
   `09-MEVCUT-DURUM-VE-ACIK-ANALIZI.md`).
6. **Gerçek para ile işlem, bu doküman setinin onayladığı bir hedef
   değildir.** Yıllar süren sanal doğrulama ve ayrı bir yönetişim/hukuki
   inceleme olmadan bu sınır aşılmaz.

## 1.7 Başarı neye benzer? (özet — detay Bölüm 07'de)

Kısa vadede (ilk 12-18 ay) başarı, **getiri değil süreç kalitesidir**:
veri boru hattının sızıntısız çalışması, sinyallerin nokta-zamanlı
doğrulanabilir olması, backtest/walk-forward metodolojisinin akademik
standartlarda olması, ve sistemin kendi hatalarını tespit edip
raporlayabilmesi. Getiri/Sharpe/precision gibi metrikler ancak bu temel
sağlandıktan **sonra** anlamlı hale gelir — aksi halde "iyi görünen ama
yanlış" bir sistem inşa etme riski çok yüksektir.

### 1.7.1 "Yıllık %X getiri" neden yanlış hedef çerçevesi

BIST'te bir getiri rakamını tek başına hedef koymak yanıltıcıdır, çünkü:

- **Nominal ≠ reel.** TL'nin yıllar içindeki değer kaybı, BIST100'ün
  nominal TL getirisini yapay olarak şişirir. Bir stratejinin "başarılı"
  sayılabilmesi için **BIST100 endeksinin aynı bazda (nominal-nominal
  veya dolar/reel-dolar/reel) karşılaştırılmış getirisinin üzerinde**
  olması gerekir — mutlak bir sayının kendisi değil.
- **Seçilmiş dönem (cherry-picking) riski.** Belirli bir boğa yılına
  bakıp "bu standarttır" demek istatistiksel olarak yanıltıcıdır. Aynı
  stratejinin ayı/yatay dönemdeki performansı da hesaba katılmadan
  hiçbir getiri iddiası anlamlı değildir.
- **Yıllık %100+ gibi "sabit/garantili" getiri iddiaları teknik olarak
  imkansızdır.** Böyle bir getiri gerçek olsaydı, piyasadaki her
  kurumsal oyuncu anında kopyalar ve avantaj kaybolurdu (etkin piyasa
  mantığı). Bu projede geçmişte üretilip gerçek testte başarısız olan
  "%300-700 CAGR" iddialı modeller (bkz. `memory/CURRENT-STATE.md`),
  bu ilkenin somut kanıtıdır — yüksek getiri iddiası olan bir model,
  incelendiğinde neredeyse her zaman overfitting veya veri sızıntısı
  içerir.

### 1.7.2 Somut, gerçekçi hedef aralığı (resmi hedef — bu belge bunu esas alır)

| Metrik | Hedef | Gerekçe |
|---|---|---|
| **BIST100 üzeri yıllık alfa** | %10-20 (endeksin üzerinde, aynı bazda) | Disiplinli sistematik stratejilerde bu seviye kurumsal standartlarda "çok iyi" sayılır. %50+ alfa iddiası, kanıtlanmadıkça overfitting şüphesiyle karşılanır (bkz. Bölüm 07 — Deflated Sharpe testi zorunludur). |
| **Sharpe Oranı** | 1.0–1.5, yıllar boyunca istikrarlı | 2 üzeri Sharpe'ı uzun vadede sürdürmek dünya çapında nadirdir (halka kapalı en iyi fonlar seviyesi); bu seviyeyi "kolay ulaşılabilir" varsaymak tehlikelidir. |
| **Maksimum Drawdown** | %25–35 altında | BIST'in doğal volatilitesi (tavan/taban limitleri, gap riski) göz önüne alınarak belirlenmiş makul bir bant. |
| **Doğrulama ufku** | En az 3 tam piyasa döngüsü (yükseliş + düşüş/düzeltme + yatay) | Tek bir iyi yıl hiçbir şey kanıtlamaz (bkz. Bölüm 07.6). |

BIST'in gerçek, sınırlı bir yapısal avantaj kaynağı sunabileceği kabul
edilir: gelişmiş piyasalara göre görece daha az yoğun kurumsal/algoritmik
rekabet ve perakende yatırımcı ağırlıklı akış (duygusal/momentum
hareketlerin daha belirgin olması). Bu, disiplinli bir sisteme **makul
bir ek alfa potansiyeli** sağlayabilir — ama bu potansiyel yukarıdaki
aralığın (%10-20 ek alfa) üzerine çıkan iddiaları haklı çıkarmaz.

**Bu tablo, projenin resmi hedef tanımıdır.** Sonraki hiçbir doküman,
sunum veya iddia bu aralığın üzerinde bir hedefi "resmi" olarak
sunamaz; üzerindeki her iddia Bölüm 07'deki istatistiksel anlamlılık
standardından geçmek zorundadır.

## 1.8 Bu vizyonun sahibi kim?

Ürün ve nihai karar sahibi projenin insan kurucusudur (Servet). ALPHA'nın
her bileşeni — Araştırma Beyni dahil — bu kişinin tanımladığı hedef
fonksiyonu, risk iştahını ve etik/yasal sınırları optimize eder; bunların
yerine geçmez veya bunları kendi başına genişletmez.
