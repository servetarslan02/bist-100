# 09 — Mevcut Durum ve Açık Analizi (Dürüst Envanter)

**Kaynak:** Bu belge `memory/CURRENT-STATE.md` içindeki teknik audit
bulgularını temel alır ve bunları iş/öncelik diliyle yeniden sunar. Kod
tabanı değiştikçe hem `memory/CURRENT-STATE.md` hem bu belge yeniden
gözden geçirilmelidir — bu bir "bir kere yazılır, unutulur" belge
değildir.

## 9.1 Genel tablo

Repoda çok değerli fikirler, isimlendirmeler ve kısmi implementasyonlar
var — ancak kod tabanı, farklı geliştirme oturumlarının üst üste
binmesiyle oluşmuş, iç tutarlılığı henüz tam sağlanmamış bir yapı.
**Bir dosyanın/sınıfın var olması, o özelliğin üretime hazır veya doğru
çalıştığı anlamına gelmez.** README, eski yol haritaları veya "düzeltme
raporu" belgelerindeki "tamamlandı/production-ready" iddiaları bağımsız
kanıt sayılmaz; kanıt yalnızca 07 numaralı belgedeki standartlarla
doğrulanmış sonuçlardır.

## 9.2 Öncelik matrisi — hangi açık, hangi sırada kapatılmalı

Aşağıdaki tablo, gap'leri "sistemi yanıltıcı kılma riski" ve "düzeltme
maliyeti" eksenlerinde önceliklendirir.

### P0 — Kritik / Yanıltıcı (önce bunlar kapatılmalı)

| Açık | Özet | Neden P0 |
|---|---|---|
| Sahte/sabit canlı veri | `services/api/server.py` içinde bazı market endpoint'lerinde sabit BIST endeks değeri/değişim/breadth/volatilite gibi "canlı görünen" ama aslında hard-coded değerler var | Kullanıcıyı veya sistemin kendisini gerçek gözlem sanılan sahte veriyle yanıltır — kırmızı çizgi ihlali (bkz. 01.6) |
| Uydurma (fabricated) context değerleri | Bazı analiz yollarında gerçek veriden gelmeyen sabit `correlation_to_index`, `amihud`, `regime`, `kap_sentiment` değerleri downstream'e veriliyor | Model/karar süreci gerçek olmayan girdiyle "çalışıyormuş" görünebilir |
| Sırların (secrets) repoda tutulması | `docker-compose.yml` içinde hard-coded veritabanı/admin şifresi örnekleri tespit edildi | Güvenlik ihlali; kırmızı çizgi (bkz. 01.6, 10.2) |
| Test kalitesi — sahte assertion | `tests/test_faz3_ranking.py` gibi dosyalarda `assert ... or True` tarzı her zaman geçen kontroller bulundu | "500 test geçti" iddiası anlamsızlaşır; yanlış güven yaratır |
| Ranking model sözleşme belirsizliği | Date × ticker panel contract'ı net değil; grouping/ordering uyuşmazlığı riski; "Adjusted-MSE" adı ile gerçek eğitim hedefi arasında tutarsızlık; confidence hesaplaması keyfi olabiliyor | Model "Champion" sayılamaz; sıralama sonuçlarına güvenilemez |

### P1 — Yapısal / Metodolojik (kanıt kalitesini doğrudan etkiler)

| Açık | Özet |
|---|---|
| Walk-forward gerçekliği | `enhanced_walk_forward.py` önceden hesaplanmış prediction/actual üzerinde fold değerlendirmesi yapıyor; her fold'da modelin gerçekten yeniden eğitildiği kanıtlanmadı — bu haliyle "leakage-safe walk-forward" sayılmaz (bkz. Bölüm 05.3) |
| Mask-First ihlali | `data_quality.py` bazı feature'ları hesapladıktan **sonra** None yapan post-hoc mask yaklaşımı içeriyor; canonical kural mask'in feature hesaplamasından **önce** uygulanmasıdır (bkz. Bölüm 03.3, 04.5) |
| Backtest finansal doğruluğu | `backtest/engine.py`'de açık pozisyonlar için mark-to-market basitleştirilmiş; `holding_days=1` sabit; CAGR = total return basitleştirmesi; drawdown süresi ve exposure hesaplanmıyor (0) | 
| Label contract tutarsızlığı | `services/labels/generator.py` cross-sectional rank fonksiyonunda belgelenen girdi şekli ile gerçek kullanım arasında uyuşmazlık var |
| Regime mantığı hatası | `services/api/main.py` fallback breadth mantığında `breadth > 65` koşulu, sonraki `breadth > 70` koşulunu erişilemez kılıyor (mantık hatası) |

### P2 — Olgunluk / Kapsam (bilinçli, aşamalı olarak büyütülecek alanlar)

| Açık | Özet |
|---|---|
| Canonical runtime eksikliği | Tek, doğrulanmış bir başlangıç noktası (entry point) henüz yok; `start.py`/`run_system.py` gibi referanslar tutarsız |
| API nesil çakışması | `services/api/main.py` ve `services/api/server.py` iki ayrı API nesli olarak var; hangisinin gerçek production server olduğu belirsiz |
| Universe hard-cap'ler | Bazı kodlarda `BIST_STOCKS[:50]` tarzı keyfi ilk-N sınırlamaları var; bunlar 02.7'deki HOT/WARM/COLD modeliyle değiştirilmeli |
| Agent/Araştırma Beyni olgunluğu | `services/agents/agent_system.py` çok sayıda rol tanımlıyor ama gerçek davranış büyük ölçüde ortak `BaseAgent` + rule-based fallback'e dayanıyor; tam bir "agentic research organization" değil |
| Öğrenme döngüsü olgunluğu | `services/learning/integrated_learning.py` esasen in-memory tahmin/sonuç kaydı ve basit accuracy/drift istatistiği tutuyor; gerçek yeniden-eğitim ve governed champion/challenger döngüsü henüz kanıtlanmamış |
| Sessiz hata yönetimi | `services/core/event_bus.py` içinde `except: pass` gibi sessiz/fail-open davranışlar var; kritik veri/olay yollarında bu davranış gözlemlenebilir hataya dönüştürülmeli |
| Bağımlılık/mimari uyumsuzluğu | Eski mimari belgeleri bazı teknolojileri zorunlu gösteriyor ama `requirements.txt` bunları içermiyor; bazı dosyalar eksik bağımlılıkları import etmeye çalışıyor (bu proje kapsamında `polars`, `httpx`, `pytest-timeout` gibi birkaç örnek zaten tespit edilip düzeltildi — bkz. commit geçmişi) |
| Event Intelligence olgunluğu | `docs/EVENT-INTELLIGENCE-SPEC.md` seviyesindeki materiality, expectation/surprise, event thread, company memory gibi kavramlar henüz koda tam yansımamış |

## 9.3 Bu belgenin kullanım şekli

- Yeni bir geliştirme oturumuna başlarken önce bu belge okunur:
  "hangi P0 açık hâlâ açık?" sorusu, o oturumun önceliğini belirler.
- Bir açık kapatıldığında, hem `memory/CURRENT-STATE.md` hem bu belge
  güncellenir — kapatma iddiası da kanıt (test/log) ile desteklenmelidir.
- Bu belge asla "her şey yolunda" demek için kullanılmaz; amacı tam
  tersidir — gerçek durumu her zaman görünür tutmaktır.

## 9.4 Bu oturumda yapılan somut düzeltmeler (referans kaydı)

Bu doküman seti hazırlanmadan önceki çalışma oturumunda aşağıdaki somut
düzeltmeler yapılıp `main` branch'e commit edilmiştir (detay için git
geçmişine bakınız):

- Eksik bağımlılıklar (`polars`, `httpx`, `pytest-timeout`) `requirements.txt`'e
  eklendi.
- `services/api/server.py`'de deprecated `regex=` parametresi, var
  olmayan `regime_engine` metodları, `RegimeState` nesnesine dict gibi
  erişim hatası ve `/api/opportunities` endpoint'indeki eksik parametre
  düzeltildi.
- `services/ml/ranking_model.py`'de gerçek bir değişken-sızıntısı
  (variable leakage) bug'ı düzeltildi: `model_contribution` hesabı, tüm
  hisseler için yanlışlıkla aynı (son hissenin) normalize skorunu
  kullanıyordu.
- `services/ingestion/providers/yfinance_provider.py`'de tanımsız
  `get_yfinance_ticker` fonksiyonu eklendi — bu fonksiyon 4 farklı yerde
  çağrılıyordu ama hiçbir yerde tanımlı değildi; bu, provider'ın
  internet erişimi olsa bile her zaman çökeceği anlamına geliyordu.
- Çok sayıda test dosyası (`test_suite.py`, `test_faz2_motors.py`,
  `test_faz_v3.py`, `test_phase10_13.py`, `test_e2e_phase1.py`), artık
  var olmayan eski API sözleşmelerini test ettiği için güncel koda göre
  yeniden yazıldı; `test_faz3_ranking.py` ise sahte adapter sınıfları
  uydurup "geçirmek" yerine, gerekçesi açıkça belirtilerek skip edildi.

- `services/core/data_quality.py`'de Mask-First ihlali (P1) düzeltildi. `apply_mask` fonksiyonu artık post-hoc olarak feature'ları null yapmak yerine direkt olarak input ham fiyat/hacim verilerini maskelemektedir. Ayrıca mask öncelik sırasındaki (sıfır hacim maskının ezilmesi) mantık hataları giderildi.
- `services/core/event_bus.py` içindeki sessiz hata yönetimi (P2) fail-open `except: pass` blokları logger'larla değiştirilerek düzeltildi.
- `services/core/regime_detector.py`'deki `transition_matrix` içine eksik olan `LOW_VOL` rejimi eklenip olasılık toplamları 1.0 olacak şekilde düzeltildi.

Bu liste, "P0/P1 açıkların bir kısmı zaten kapatılmaya başlandı" anlamına
gelir ama **tamamı kapatılmamıştır** — özellikle sahte/sabit veri (P0) ve 
walk-forward gerçekliği (P1) hâlâ açıktır. Ancak Mask-first ihlali çözülmüştür.

### services/core Modülü Denetim Tamamlama Notu (21.08.2026)
- 64 dosyanın 64'ü de satır-satır okunup doğrulandı.
- DecisionEngine stop-loss parametreleri Canonical Strateji (%6.5 hard stop fallback, 2.5x ATR, min %4.0) ile birleştirildi.
- RiskGate negatif emir miktarı/fiyat zafiyeti ve Orchestrator dict risk bypass zafiyeti çözüldü.
- Tüm 6 regression testi geçildi.
- services/core tamamlama şartlarının tamamı sağlandı.
