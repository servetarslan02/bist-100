# ALPHA BIST — Kurumsal Dokümantasyon Seti

**Durum:** Yaşayan doküman seti (living document set) — kod ilerledikçe güncellenmelidir.
**Kapsam:** Bu klasör, "dünyada sayılı" seviyede otonom, kendi kendini eğiten bir
yatırım araştırma ve portföy yönetim sisteminin (ALPHA) ne olduğunu, neden var
olduğunu, nasıl inşa edileceğini, hangi standartlarla değerlendirileceğini ve
hangi risklere karşı korunacağını tanımlayan kapsamlı plandır.
**Dil:** Türkçe (kod içi mevcut İngilizce spec dosyalarıyla — `docs/`, `memory/` —
çelişki durumunda, iş/ürün kararlarında bu doküman seti, teknik sözleşme
detaylarında ise `docs/MASTER-SPEC.md` ve `memory/ROADMAP-v4.md` esas alınır.
Bu setin amacı o teknik belgeleri **çelişkiye düşürmek değil, onları bir iş ve
mühendislik programına oturtmaktır**.)

---

## Bu doküman seti neden var?

Büyük yatırım/kantitatif firmaları (Renaissance, Two Sigma, Citadel, DE Shaw
tarzı organizasyonlar) yeni bir strateji veya sistem kurarken önce koda değil,
şu sorulara cevap veren bir programa yatırım yaparlar:

1. Ne inşa ediyoruz ve **neden** — hangi problem, hangi edge (avantaj)?
2. Sistemin **doğruluğunu nasıl kanıtlarız** — hangi kanıt kabul edilir,
   hangisi edilmez?
3. **Hangi hatalar bizi öldürür** (sermaye kaybı, yanlış güven, overfitting,
   veri sızıntısı, kural ihlali) ve bunlara karşı hangi kontroller var?
4. Sistem büyüdükçe **kim neyi onaylar**, kim "hayır" diyebilir?
5. **Ne zaman gerçek başarı sayılır** — hangi metrik, hangi eşik, hangi süre?

Bu dokümantasyon seti, ALPHA BIST projesini tam olarak bu disiplinle ele alır.
Repo içinde zaten **çok değerli** ön çalışmalar var (`docs/MASTER-SPEC.md`,
`docs/TARGET-ARCHITECTURE.md`, `docs/EVENT-INTELLIGENCE-SPEC.md`,
`memory/ROADMAP-v4.md`, `memory/CURRENT-STATE.md`, `memory/WORKING_RULES.md`).
Bu set onları **tekrar etmez**; onların üzerine iş stratejisi, değerlendirme
metodolojisi, yönetişim modeli ve dürüst bir "şu an neredeyiz" haritası ekler,
hepsini tek bir okunabilir program haline getirir.

## Okuma sırası

| # | Dosya | İçerik | Kime hitap eder |
|---|-------|--------|------------------|
| 01 | `01-VIZYON-VE-MANIFESTO.md` | Neden bu proje var, hangi problemi çözüyor, "üç beyin" felsefesi, kırmızı çizgiler | Herkes — başlangıç noktası |
| 02 | `02-SISTEM-MIMARISI.md` | Uçtan uca mimari, katmanlar, veri akışı, teknoloji seçimleri ve gerekçeleri | Mühendislik |
| 03 | `03-VERI-VE-BILGI-EVRENI.md` | Veri kaynakları, dünya modeli, olay grafiği, point-in-time disiplini | Veri/mühendislik |
| 04 | `04-FEATURE-MOTORLARI-VE-SINYAL-URETIMI.md` | 7 motor feature mimarisi, sinyal üretim mantığı | Kantitatif araştırma |
| 05 | `05-MODEL-OGRENME-VE-ARASTIRMA-DONGUSU.md` | Ranking modeli, rejim tespiti, walk-forward, champion/challenger, sürekli öğrenme | Kantitatif araştırma / ML |
| 06 | `06-RISK-PORTFOY-VE-EXECUTION.md` | Pozisyon boyutlandırma, risk limitleri, portföy yönetimi, execution simülasyonu | Risk / portföy yönetimi |
| 07 | `07-DEGERLENDIRME-VE-BASARI-KRITERLERI.md` | Başarı nasıl ölçülür, hangi istatistiksel testler, ne zaman "gerçek" denir | Yönetim / araştırma |
| 08 | `08-YOL-HARITASI-VE-FAZLAR.md` | Çok yıllı, fazlı yol haritası, çıkış kapıları (exit gates), zaman ufku | Herkes — planlama |
| 09 | `09-MEVCUT-DURUM-VE-ACIK-ANALIZI.md` | Bugün kod tabanında gerçekte ne var, ne yok — dürüst envanter | Herkes — gerçeklik kontrolü |
| 10 | `10-YONETISIM-GUVENLIK-VE-UYUM.md` | Governance Brain, sır yönetimi, denetim, felaket senaryoları, düzenleyici çerçeve | Yönetim / güvenlik |
| 11 | `11-SOZLUK.md` | Terimler sözlüğü | Herkes — referans |
| 12 | `12-ACIK-SORULAR.md` | Şüpheli iş mantığı / finansal tasarım kararları — sistem sahibinin karar vermesi gereken açık sorular (kod değişikliği içermez) | Sistem sahibi — karar bekleyen konular |

## Temel ilkeler (bu setin her belgesinde geçerlidir)

1. **Dürüstlük > iddia.** Bir özelliğin dosyada var olması, onun çalıştığı
   veya doğru olduğu anlamına gelmez. "Tamamlandı" demek için kanıt
   (geçen test + gerçek veri + bağımsız doğrulama) gerekir.
2. **Sanal para, gerçek disiplin.** Paper trading gerçek para riski
   taşımaz ama gerçek karar disiplini taşımalıdır — aksi halde öğrenilen
   şey işe yaramaz.
3. **Sızıntı (leakage) ölümdür.** Geleceği görmüş bir model her zaman
   iyi görünür ve her zaman yanlıştır. Bu, tüm sistemin en büyük
   düşmanıdır ve her doküman bunu tekrar hatırlatır.
4. **Basit ve doğru, karmaşık ve şüpheli olandan iyidir.** Yeni bir
   motor/model eklemek varsayılan davranış değildir; kanıtla kazanılan
   bir ayrıcalıktır (bkz. `07-DEGERLENDIRME-VE-BASARI-KRITERLERI.md`).
5. **Kapak yok, sınır (cap) yok — ama önceliklendirme var.** BIST 100 ile
   sınırlı kalmak nihai hedef değildir; ama sınırsız kapsam, sınırsız
   eşzamanlı işi haklı çıkarmaz. Adaptif önceliklendirme kullanılır.
6. **Otonomluk, gözetimsizlik değildir.** Sistem kendi kendine öğrenip
   karar alacak ama insan; hedefleri, risk sınırlarını ve "dur" düğmesini
   her zaman elinde tutacaktır.

## Bu belgeler ne değildir

- Bu bir pazarlama materyali değildir; iddialı ama kanıtsız cümle
  kullanılmaz.
- Bu, "yapay zekaya her şeyi bırak" tarzı bir vaat değildir. AI/ML burada
  karar destek ve örüntü keşfi aracıdır; nihai risk sorumluluğu insan
  tarafından tanımlanan politikalardadır (bkz. Bölüm 10).
- Bu bir yatırım tavsiyesi değildir ve gerçek para ile işlem yapılması
  bu doküman setinin kapsamında değildir — bkz. `01-VIZYON-VE-MANIFESTO.md`
  içindeki "Kapsam Dışı" bölümü.
