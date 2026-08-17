# 08 — Yol Haritası ve Fazlar

## 8.1 Zaman ufku ve genel yaklaşım

Bu bir "3 ayda MVP çıkar" projesi değildir. Vizyon belgesinde (Bölüm 01)
belirtildiği gibi, gerçek kanıt yıllar alır. Yol haritası, **fazlar
arasında net "çıkış kapıları" (exit gates)** ile ilerler: bir sonraki
faza geçmek, takvimsel bir tarihe değil, önceki fazın kanıt
standardını (Bölüm 07) karşılamaya bağlıdır. Faz süreleri bu yüzden
**tahmini minimum**dur, tavan değildir.

## 8.2 Faz 0 — Temel Bütünlük (Foundation Integrity)

**Amaç:** Sistemin söylediğini yaptığından emin olmak. Yeni özellik
eklemeden önce mevcut olanın dürüst ve doğru çalıştığını kanıtlamak.

**Kapsam:**
- `09-MEVCUT-DURUM-VE-ACIK-ANALIZI.md` içindeki **tüm P0 açıklar** kapatılır:
  sahte/sabit veri temizliği, uydurma context değerlerinin kaldırılması,
  sırların (secrets) koddan çıkarılıp güvenli bir secret yönetimine
  taşınması, test paketinin gerçek assertion'larla yeniden yazılması,
  ranking model sözleşmesinin (date×ticker panel, ordering, confidence)
  netleştirilmesi.
- Tek bir canonical runtime / entry point netleştirilir; API nesil
  çakışması (`main.py` vs `server.py`) çözülür.
- CI'da otomatik çalışan, gerçek assertion içeren bir test paketi
  kurulur (bu doküman setinin hazırlandığı oturumda başlangıç
  düzeltmeleri yapılmıştır — bkz. 09.4).

**Çıkış kapısı:** P0 listesi boş; test paketi CI'da yeşil ve
`assert ... or True` tarzı sahte kontrol içermiyor; hiçbir endpoint
sabit/sahte veri döndürmüyor.

## 8.3 Faz 1 — Sızıntısız Veri ve Doğrulanabilir Backtest

**Amaç:** "Kağıt üzerinde iyi" ile "gerçekten iyi" arasındaki farkı
ölçebilecek bir altyapı kurmak.

**Kapsam:**
- Point-in-time veri disiplini uçtan uca kanıtlanır (Bölüm 03.1).
- Mask-First kuralı ihlali (P1) düzeltilir — feature hesaplaması her
  zaman maskelemeden sonra başlar.
- Walk-forward motoru, her fold'da modeli **gerçekten yeniden eğitecek**
  şekilde düzeltilir (P1 açığı kapatılır) — bkz. Bölüm 05.3.
- Backtest motorunda mark-to-market, drawdown süresi, exposure gibi
  basitleştirilmiş/eksik hesaplamalar gerçek finansal muhasebeye uygun
  hale getirilir (Bölüm 06.6).
- İlk uçtan uca "gerçek veriyle, sızıntısız" backtest çalıştırılır ve
  sonuçlar Bölüm 07 standardına göre raporlanır (iyi çıkması değil,
  **metodolojinin doğru olması** hedeftir).

**Çıkış kapısı:** Bağımsız bir gözden geçirme (Governance Brain rolü),
walk-forward + backtest metodolojisinin sızıntısız olduğunu kod
incelemesi ve testlerle onaylar.

## 8.4 Faz 2 — Sanal Portföy Canlıya Alma (Paper Trading Go-Live)

**Amaç:** Sistemi gerçek zamanlı, kesintisiz, sanal sermaye ile
çalışır hale getirmek.

**Kapsam:**
- Karar Motoru → Risk/Position Sizing → Execution Simülasyonu →
  Portföy Defteri zinciri uçtan uca, gerçek zamanlı veriyle çalışır.
- Safe-mode, veri kalitesi kesintisi, sağlayıcı arızası gibi senaryolar
  için dayanıklılık testleri yapılır.
- İlk "champion" model belirlenir (mevcut LightGBM+rule-based ensemble,
  Faz 1'de doğrulanmış haliyle).
- Gözlemlenebilirlik (dashboard, alerting) üretime alınır (Bölüm 07.8).

**Çıkış kapısı:** Sistem, insan müdahalesi olmadan en az 4-6 hafta
kesintisiz, hatasız (kritik hata sıfır) sanal portföyü işletir.

## 8.5 Faz 3 — Çok Rejimli Doğrulama (Multi-Regime Validation)

**Amaç:** Sistemin farklı piyasa koşullarında nasıl davrandığını
gözlemlemek; bu, takvimsel değil **rejim-tabanlı** bir fazdır.

**Kapsam:**
- Sanal portföy, en az bir belirgin yükseliş, bir düzeltme/düşüş ve bir
  yatay/düşük-hareketli dönem boyunca çalışır (bu, takvim zamanı olarak
  değişken sürebilir — piyasa buna karar verir, proje takvimi değil).
- Rejim tespiti (`RegimeEngine`) ve rejime duyarlı ağırlıklandırmanın
  (Bölüm 05.2) gerçek etkisi ölçülür.
- İlk "challenger" modeller/motorlar Araştırma Beyni tarafından
  üretilmeye başlanır ve gölge modda izlenir (Bölüm 05.4).

**Çıkış kapısı:** Bölüm 07.6'daki minimum kanıt eşiği (süre + örneklem +
out-of-sample tutarlılık) karşılanır; sistemin performansı istatistiksel
olarak şanstan ayırt edilebilir (Deflated/Probabilistic Sharpe ile).

## 8.6 Faz 4 — Kapsam Genişletme (Universe & Data Expansion)

**Amaç:** BIST 100 ötesine, tam BIST evrenine ve daha zengin bilgi
evrenine (Bölüm 03.2) genişlemek — ama disiplinli biçimde.

**Kapsam:**
- HOT/WARM/COLD katman modeli (Bölüm 02.7) üretime alınır; keyfi
  `[:N]` tavanları kaldırılır (P2 açığı kapatılır).
- Event Intelligence spesifikasyonu (materiality, expectation/surprise,
  event thread, company memory) koda yansıtılır.
- Küresel makro bağlam ve sektör/tedarik zinciri ilişki grafiği entegre
  edilir.

**Çıkış kapısı:** Genişletilmiş evrenin, dar evrene göre marjinal katkısı
(Bölüm 04.6'daki disiplinle) kanıtlanır; sadece "daha fazla veri" kendi
başına başarı sayılmaz.

## 8.7 Faz 5 — Araştırma Otomasyonunun Olgunlaşması (Research Brain Maturity)

**Amaç:** Bölüm 05.6'da tanımlanan tam Araştırma Beyni yeteneğine
ulaşmak — bugünkü sınırlı agent altyapısının (P2 açığı) ötesine geçmek.

**Kapsam:**
- Agent sistemi, gerçek hipotez üretme → sızıntısız test etme → kanıt
  raporlama döngüsünü otonom yürütür.
- Champion/Challenger yaşam döngüsü (Bölüm 05.4) tam otomatik hale
  gelir; yalnızca terfi kararı insan/Governance onayında kalır.
- Sürekli öğrenme döngüsü (Bölüm 05.5), teşhis kalitesi (neden yanlış
  olduğunu açıklayabilme) açısından olgunlaşır.

**Çıkış kapısı:** Araştırma Beyni'nin ürettiği en az bir challenger,
insan araştırmacı müdahalesi olmadan Bölüm 07 standardını geçip
champion'a terfi eder ve bu süreç denetlenebilir şekilde belgelenir.

## 8.8 Faz 6+ — Uzun Vadeli Ufuk (açık uçlu)

Bu fazdan itibaren yol haritası kasıtlı olarak **açık uçludur** — çünkü
buraya kadarki fazların sonuçları, bir sonraki adımın ne olması
gerektiğini belirleyecektir. Olası yönler (taahhüt değil, olasılık
olarak):

- Daha büyük sanal sermaye ölçeklerinde kapasite testi.
- Ek varlık sınıflarına (örn. döviz, emtia proxy'leri) kontrollü
  genişleme.
- Gerçek sermaye ile sınırlı, çok katı yönetişim altında bir pilot
  değerlendirmesi — **bu adım, ayrı bir hukuki/regülasyon incelemesi ve
  ayrı bir onay süreci gerektirir ve bu doküman setinin verdiği bir
  onay değildir** (bkz. Bölüm 01.3, 10.6).

## 8.9 Faz disiplini — sabit kurallar

1. Bir faz, önceki fazın çıkış kapısı kanıtlanmadan **resmi olarak**
   başlamış sayılmaz — paralel araştırma yapılabilir ama "Faz N
   tamamlandı" iddiası kanıtsız atılamaz.
2. Her faz sonunda, bu doküman seti (özellikle Bölüm 09) güncellenir.
3. Bir fazda kritik bir P0-seviye açık keşfedilirse, sonraki faz
   duraklatılır ve önce o açık kapatılır — takvim baskısı bu kuralı
   geçersiz kılamaz.
