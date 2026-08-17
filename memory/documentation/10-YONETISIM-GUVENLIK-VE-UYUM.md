# 10 — Yönetişim, Güvenlik ve Uyum

## 10.1 Governance Brain'in somut sorumlulukları

Bölüm 01.4'te tanımlanan Yönetişim Beyni, pratikte şu somut
mekanizmalarla var olur (bugün büyük ölçüde süreç/insan tarafından,
ileride kısmen otomasyonla desteklenerek):

- **Model/strateji terfi onayı**: Bölüm 05.4'teki Champion/Challenger
  geçişini bağımsızca doğrular.
- **Veri soy kütüğü (lineage) denetimi**: Bir feature/karar'ın hangi ham
  veriden, hangi kod versiyonuyla üretildiğini doğrulayabilir.
- **Sızıntı denetimi**: Yeni bir feature/model'in point-in-time
  kurallarına uyduğunu bağımsızca kontrol eder.
- **Risk politikası uygunluğu**: Bölüm 06'daki limitlerin kod
  seviyesinde gerçekten uygulandığını (bypass edilemediğini) doğrular.
- **Audit bütünlüğü**: Karar/işlem kayıtlarının değiştirilemez ve eksiksiz
  olduğunu doğrular.

## 10.2 Sır (secrets) yönetimi

**Kural:** Hiçbir şifre, API anahtarı, token veya kimlik bilgisi kaynak
kodunda, `docker-compose.yml` içinde veya repoya commit edilen herhangi
bir dosyada **açık metin olarak bulunamaz.**

Bu kural, projenin bugünkü durumunda zaten **ihlal edilmiş** durumdadır
(bkz. `09-MEVCUT-DURUM-VE-ACIK-ANALIZI.md` P0 listesi — `docker-compose.yml`
içinde hard-coded veritabanı/admin şifresi örnekleri) ve **Faz 0'ın
kapanması için zorunlu bir düzeltme maddesidir**. Doğru yaklaşım:

- Sırlar `.env` dosyalarında tutulur ve bu dosyalar `.gitignore` ile
  repo dışında tutulur.
- Üretim ortamında bir secret manager (örn. Docker/Compose secrets,
  bulut sağlayıcı secret manager'ı, veya en azından ortam değişkenleri
  üzerinden enjekte edilen değerler) kullanılır.
- Bir sırın yanlışlıkla commit edildiği tespit edilirse, o sır **geçersiz
  kılınıp (rotate) yenisiyle değiştirilir** — sadece dosyadan silmek
  yeterli değildir, çünkü git geçmişinde iz kalır.

**Not (bu projeye özel, kayda geçirilmiş uyarı):** Bu dokümantasyon
setinin hazırlandığı çalışma oturumunda, bir GitHub Personal Access
Token sohbet arayüzünde açık metin olarak paylaşılmıştır. Bu token ile
işlem yapılmıştır; kullanıcıya bu token'ın **derhal iptal edilip (revoke)
yenisiyle değiştirilmesi** birden fazla kez hatırlatılmıştır. Bu, sır
yönetimi disiplininin neden sadece bir "kod kuralı" değil, günlük
operasyonel bir alışkanlık olması gerektiğinin canlı bir örneğidir.

## 10.3 Denetim (audit) ve izlenebilirlik

- Her otonom karar (BUY/SELL/HOLD/NO_ACTION), o kararı üreten model
  versiyonu, kullanılan feature değerleri, rejim etiketi ve eşik
  parametreleriyle birlikte değiştirilemez şekilde kaydedilir (Bölüm
  02.4 — kanıt paketi).
- Risk limitlerinde, model versiyonlarında veya politika
  parametrelerinde yapılan her değişiklik, kim/ne zaman/neden bilgisiyle
  kayıt altına alınır.
- Sistem, geçmişteki herhangi bir kararı "neden böyle karar verdin?"
  sorusuna somut kanıtla cevap verebilecek şekilde tasarlanır — bu,
  hem hata ayıklama hem de gelecekte olası bir dış denetim/regülasyon
  incelemesi için zorunludur.

## 10.4 Fail-safe ve felaket senaryoları

| Senaryo | Beklenen davranış |
|---|---|
| Veri sağlayıcı tamamen çöker | İlgili feature'lar `None`/eksik işaretlenir; kritik eşik aşılırsa SAFE MODE (Bölüm 02.5) |
| Model beklenmedik/aşırı skor üretir (örn. NaN, sonsuz değer) | Karar Motoru bu tür girdileri reddeder, NO_ACTION döner, olay loglanır |
| Portföy drawdown kritik eşiği aşar | Otomatik risk azaltma modu (Bölüm 06.8); insan onayı olmadan yeni pozisyon açılmaz |
| Kod/altyapı hatası (exception) kritik bir yolda oluşur | `except: pass` gibi sessiz yutma **yasaktır** (bkz. P2 açığı, `event_bus.py`); hata loglanır, ilgili bileşen güvenli şekilde devre dışı kalır, sistemin geri kalanı çalışmaya devam eder |
| Sır/kimlik bilgisi sızıntısı tespit edilir | Derhal rotate edilir; etkilenen erişimler gözden geçirilir |

## 10.5 Kod inceleme ve değişiklik disiplini

- Risk limitleri, terfi kuralları ve veri kalite kapısı gibi
  "kırmızı çizgi" bileşenlerindeki değişiklikler, normal kod
  değişikliğinden daha yüksek bir inceleme standardına tabidir.
- "Testleri geçirmek için testi zayıflatmak" (örn. `assert ... or True`
  eklemek, ya da başarısız bir assertion'ı sessizce gevşetmek) açıkça
  yasaktır ve tespit edildiğinde geri alınır (bkz. Bölüm 07.3, ve bu
  projede zaten tespit edilmiş P0 örneği).
- Bir testin/kontrolün kaldırılması, her zaman **neden** kaldırıldığının
  gerekçesiyle birlikte belgelenir (bu doküman setindeki
  `test_faz3_ranking.py` skip kararı, bunun örnek bir uygulamasıdır —
  sessizce silinmek yerine, gerekçesiyle işaretlenerek devre dışı
  bırakılmıştır).

## 10.6 Gerçek sermaye sınırı — açık ve tekrar edilen uyarı

Bu doküman seti, **hiçbir aşamada gerçek sermaye ile işlem yapılmasını
onaylamaz veya tavsiye etmez.** Böyle bir geçiş söz konusu olursa, en
azından şunlar gerekir ve bunların hiçbiri bu projenin bugünkü
kapsamında değildir:

- Türkiye'de yatırım danışmanlığı/aracılık faaliyetlerini düzenleyen
  mevzuata (SPK ve ilgili düzenlemeler) uygunluk incelemesi.
- Algoritmik/otomatik işlem sistemlerine ilişkin borsa ve düzenleyici
  kurum gerekliliklerine uygunluk.
- Bağımsız, sistemin kendi ekibinden ayrı bir risk/uyum incelemesi.
- Bölüm 07.6'daki minimum kanıt eşiğinin, **birden fazla tam piyasa
  döngüsünü** kapsayacak şekilde fazlasıyla aşılmış olması.

Bu sınır, projenin hırsını azaltmak için değil, tam tersine — projenin
iddia ettiği "dünyada sayılı seviye" hedefine ancak bu disiplinle
ulaşılabileceği için buradadır. Disiplinsiz erken geçiş, hem sermaye
kaybı hem de projenin güvenilirliğinin kalıcı biçimde zedelenmesi
riskini taşır.

## 10.7 Şeffaflık ilkesi (kendine karşı da)

Sistemin ürettiği hiçbir rapor, dashboard veya özet, gerçekte var olmayan
bir başarıyı ima edecek şekilde sunulamaz. "Test geçti" demek, testin
anlamlı bir şeyi doğruladığı anlamına gelmelidir (Bölüm 07.3). "Backtest
Sharpe 2.0" demek, bunun hangi varsayımlarla, hangi maliyet
modelleriyle, kaç deneme sonucu elde edildiğinin de belirtildiği
anlamına gelmelidir (Bölüm 07.4). Bu ilke, hem dış paydaşlara hem de
projenin kendi ekibine karşı geçerlidir — bir sistemin kendi
sahibini yanıltması, dış bir tarafı yanıltmasından daha tehlikelidir,
çünkü düzeltici geri bildirim kaybolur.
