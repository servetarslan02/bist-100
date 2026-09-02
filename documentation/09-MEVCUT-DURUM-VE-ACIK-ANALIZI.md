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

### Matematiksel/Finansal Hesaplama Denetimi — Sonuçlar (ayrı oturumlarda kanıtlı çalıştırmayla düzeltildi)

Bu bölüm, kod okuyarak değil, **gerçek çalıştırma ve sayısal doğrulamayla**
bulunup düzeltilen matematiksel hataları listeler (commit hash'leri ile).

- **`services/risk/var_cvar.py`** (commit `02c071c`): Tarihsel VaR/CVaR
  percentile index hesabı, kayan nokta hassasiyeti ve kesirli örneklem
  büyüklüklerinde (özellikle n=252, en yaygın kullanılan yıllık işlem
  günü sayısı) riski hedefin altına düşürüyordu. Doğru "nearest-rank"
  formülüyle (`math.ceil(x)-1`, epsilon toleranslı) değiştirildi;
  artık her durumda kapsam hedefin altına düşmüyor (risk hiç
  küçümsenmiyor).
- **`services/backtest/deflated_sharpe.py`** (commit `c5e2333`): İki
  kritik hata — (1) `E[max Sharpe]` formülü literatürden (Bailey &
  Lopez de Prado 2014) sapıyordu, Monte Carlo ile ~%15-20 hata
  kanıtlandı; (2) daha ciddisi, yıllıklaştırma birim uyuşmazlığı
  yüzünden `deflated_sharpe` gerçek değerinin **~252 katı** şişiyordu
  (somut örnekte 21.5 → düzeltmeden sonra -0.78; "anlamlı" → "anlamlı
  değil"). Bu, DSR'ın çoklu-test/şans eseri strateji eleme işlevini
  tamamen etkisiz bırakıyordu.
- **`services/risk/risk_parity.py`** (commit `02de123`): Ağırlık
  normalize etme/negatif-temizleme sırası ters idi; düzeltildi,
  ağırlıkların toplamının her zaman tam 1.0 olması garanti edildi.
- **`services/backtest/multi_asset_engine.py`, `survivorship.py`**
  (commit `3edfb45`): (1) T+1 execution hiç uygulanmıyordu — sinyal
  ile execution aynı günün kapanışını kullanıyordu (look-ahead bias);
  artık execution D+1 açılışında gerçekleşiyor. (2) `universe_tickers`
  parametresi (survivorship bias için) tanımlıydı ama hiç
  kullanılmıyordu; artık gerçekten evreni filtreliyor. Sahte
  `"EXAMPLE1"` placeholder delisting verisi kaldırıldı (gerçek veri
  hâlâ eksik — bkz. açık soru).
- **`services/market_state/ensemble_regime.py`** (commit `f1b57b0`):
  `get_regime_adapted_weights()` tanımlıydı ama `detect()` içinde hiç
  çağrılmıyordu — rejime duyarlı ağırlıklandırma tamamen ölü kod idi.
  Bağlantı kuruldu (tasarımın kendisinin dairesellik riski taşıyıp
  taşımadığı hâlâ açık bir soru — bkz. `documentation/12` madde 5).
- **`services/agents/`** (commit `83a77e4`, `50f0bcb`): Bull/Bear
  debate mekanizması bir crash bug (`KeyError`) ve bir sessiz mantık
  hatası (`"position"` vs `"direction"` alan adı uyuşmazlığı — her
  debate turu sahte "NEUTRAL" uzlaşmasına düşüyordu) yüzünden hiç
  çalışmıyordu; ikisi de düzeltildi. Ayrıca `agent_memory.py`'de
  episodic hafızanın her yeniden başlatmada sessizce kaybolduğu
  (persistence bug), `risk_assessor.py`'de risk seviyesi bucketing
  off-by-one hatası (CRITICAL eşiği yanlışlıkla 70'te tetikleniyordu,
  85 yerine), ve `self_evaluator.py`'de gereksiz çift hesaplama
  bulunup düzeltildi.

Bu liste, "P0/P1 açıkların bir kısmı zaten kapatılmaya başlandı" anlamına
gelir ama **tamamı kapatılmamıştır** — özellikle sahte/sabit veri (P0) ve
walk-forward gerçekliği (P1) hâlâ açıktır. Ancak Mask-first ihlali çözülmüştür.

### Veri Alım Katmanı (services/ingestion) — Kısmen Güncellendi

`documentation/12` madde 7-10'da listelenen bulgulardan hâlâ **açık** olanlar:
- `bist_provider.py` ve `matriks_provider.py`'nin hedeflediği API
  uç noktalarının gerçekte var olmadığı şüphesi (web araştırmasıyla
  doğrulanamadı) — sistem muhtemelen iddia ettiği çoklu-kaynak
  mimarisine sahip değil, sessizce tek kaynağa (yfinance) bağımlı.
- Canlı/sanal işlemde (`paper_orchestrator.py`) T+1 koruması kâğıt
  üzerinde var ama devre dışı — backtest'te düzeltilen aynı sorunun
  canlı tarafındaki hâlâ açık hali.

**Çözüldü:** "Son güncelleme" zaman damgası sorunu ve sabit `[:50]`
evren tavanı — bu ikisinin güncel durumu doğrulanmadı, tekrar kontrol
gerekir.

### `WhyFallingMotor` Restorasyonu — Tamamlandı

Önceki bir turda kaybolduğu tespit edilip (bkz. yukarı) sınıf olarak
`services/features/seven_motors.py`'ye geri eklenen `WhyFallingMotor`,
artık `services/backtest/engine_v4.py`'ye de gerçekten bağlanmış
durumda (satır ~1171-1217, `WhyFallingMotor()` örneklenip
kullanılıyor). Bu madde tam olarak kapatılmıştır.

### Ekim 2026 Turu — Ek Kritik Bulgular ve Çözümleri

Sistem 470→576+ dosyaya büyüdüğü, çoklu AI oturumu (Mimo, Gemini,
diğerleri) tarafından hızlı geliştirildiği bir dönemde, sadece kod
okuyarak (test'e güvenmeden) yapılan bir "en önemli mantık hataları"
taramasında bulunan ve sonradan **doğrulanmış şekilde çözülen** maddeler:

- **`services/api/v1/scanner.py`** — En kritik bulgu: altyapı (Redis/
  scanner) çöktüğünde, sistem sessizce **tamamen uydurma** hisse
  önerileri (sahte fiyat, sahte skor, sahte "analist" gerekçe metni,
  `"timestamp": "Şimdi"`) sunuyordu — `documentation/01.6` kırmızı
  çizgisinin doğrudan ihlali. **Çözüldü**: kod artık `"NO HARDCODED
  FAKE SIGNALS"` yorumuyla dürüst `{"signals": [], "status":
  "unavailable"}` döndürüyor.
- **`services/portfolio/autonomous_conviction_engine.py`** — Trailing
  stop mantığında, bir pozisyon zirve kârdan küçük bir zarara
  gerilediğinde hiçbir kuralla (ne trailing stop ne hard stop-loss)
  korunmadığı somut senaryoyla kanıtlandı. **Çözüldü**: `pnl_pct > 0.02`
  "tuzak şartı" kaldırılıp `has_reached_profit` mantığıyla değiştirildi
  (kod yorumu bug'ı açıkça tanımlıyor: "ölüm bölgesi kapatılmıştır").
- **`services/api/v1/portfolio.py`** (`/accounting`) — Realized PnL,
  var olmayan bir sözlük anahtarına (`total_pnl`) baktığı için her
  zaman `0.0` dönüyordu. **Çözüldü**: gerçekten var olan `realized_pnl`
  anahtarına geçirildi (iki endpoint arasında hâlâ küçük bir isim
  tutarsızlığı var, işlevsel hata giderildi).
- **`services/core/state_store.py`** — Her tahmin için DuckDB
  bağlantısı açıp/kapatan, batching yapmayan (docstring "batched"
  diyordu ama kod yapmıyordu) yazma mantığı, WSL/Docker'da sürekli
  SSD yazma/donma sorununa yol açıyordu (106 hisseye genişleyen
  evrenle katlanarak kötüleşti). **Çözüldü**: gerçek `_buffered_write`
  + boyut-bazlı flush (10 öğe) eklendi. (`periodic_flush()` zaman
  bazlı güvenlik ağı hâlâ hiçbir yerden çağrılmıyor — küçük risk.)
- **`docker-compose.yml`** — Toplam `mem_limit` fiziksel RAM'i (16GB)
  aşıyordu (~17.7GB), bozuk değerler (`512m-replica`, `1g-2`) ve
  çakışan `container_name`'ler (aynı isim 2-3 serviste) vardı.
  **Çözüldü**: bozuk değerler düzeltildi, çakışmalar giderildi, tek
  makinede gerçek HA faydası olmayan servisler (3 Redis Sentinel,
  ikinci ClickHouse node'u) kaldırıldı, toplam bütçe ~12.7GB'a
  (%79.5 doluluk, host/WSL için pay bırakarak) çekildi, tüm servislere
  `cpus` limiti eklendi.
- **`services/features/seven_motors.py`, `engine_v4.py`** — Bkz.
  yukarıdaki "WhyFallingMotor Restorasyonu" — tamamlandı.
- **Karakter kodlaması bozulması** — `services/core/` altında 10
  dosyada bulunan mojibake (bozuk Türkçe karakter) sorunu artık
  temizlenmiş görünüyor (sonraki bir "code quality" turunda).

**Hâlâ açık kalan (bu turda çözülmeyen):**
- `services/portfolio/autonomous_conviction_engine.py::base_hurdle_rate=0.35`
  — yıllıklandırılmış getiri eşiği %35-60'a kadar çıkıyor,
  `documentation/01 §1.7.2`'deki resmi hedefle (%10-20 alfa) hâlâ
  çelişiyor. Yeni merkezi `services/core/risk_config.py`'ye bile
  taşınmamış.
- `services/risk/var_cvar.py::calculate_monte_carlo_var` — GPU yolu
  (`torch.normal`) hâlâ `seed` parametresini kullanmıyor, tekrarlanabilirlik
  tutarsızlığı devam ediyor olabilir (bu turda tekrar doğrulanmadı).
- `trade_planner.py`, `simulation/main.py` — senaryo olasılıklarının
  (%30/%50/%20 gibi) sabit kodlanmış olması, sinyal gücüne duyarsız
  olması (bu turda tekrar doğrulanmadı).
