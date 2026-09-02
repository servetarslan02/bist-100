# Açık Sorular ve Şüpheli İş Mantığı Listesi

(Sistem sahibi tarafından karar verilmesi gereken konular — bu dosya kod
değişikliği içermez, sadece karar bekleyen açık soruları listeler.)

**Not (encoding düzeltmesi):** Bu dosya önceki halinde bozuk karakter
kodlamasıyla (Türkçe karakterler `�` olarak) kaydedilmişti; içerik
korunarak doğru UTF-8 ile yeniden yazıldı.

## 1. services/core/regime_detector.py (Rejim Tespiti)
- **Senaryo:** Hisse veya pazar geçmişi 200 günden kısaysa (örn. yeni
  halka arz), sma200 hesaplanamadığı için sma50'ye fallback yapılıyor.
  Bu durumda sma50 > sma200 eşitliği hiçbir zaman sağlanamıyor (False
  dönüyor) ve Trend skoru 20 puan eksik çıkıyor.
- **Neden şüpheli:** Kısa geçmişli varlıkların (örneğin son 6 aylık
  verisi olanların) rejim tespiti, teknik olarak hiçbir zaman tam bir
  'BULL' trend skoruna ulaşamayabilir.
- **Soru:** 200 günden az geçmişi olan varlıklar için bu faktörün (20
  puanlık kısmın) ağırlığı diğer faktörlere mi dağıtılmalı, yoksa rejim
  hesaplamasında tamamen exclude mu edilmelidir?

## 2. services/core/data_quality.py (Limit-Up/Down Feature Maskeleme)
- **Senaryo:** Tavan/taban olan (limit-up/limit-down) hisseler için
  fiyat güvenilir olmadığı gerekçesiyle price_mask = 0.0 yapılıyor.
- **Neden şüpheli:** Alım/satım işlemi gerçekleştirilemediği için
  Execution motorunda kullanılmaması kesinlikle doğru, ancak Hareketli
  Ortalamalar (SMA20/SMA50 vb.) gibi geçmiş trend feature'ları
  hesaplanırken o günkü fiyatın tamamıyla 'None' (NaN) varsayılması
  sinyal çizgilerini (MACD vb.) koparabilir/bozabilir.
- **Soru:** Mask-first kuralı kesin bir kural olarak tanımlanmış, ancak
  momentum ve osilatör feature'larında serinin kopmaması için tavan/taban
  fiyatların *sadece hesaplama amaçlı* kullanılıp, sadece execution'da
  maskelenmesi daha doğru olmaz mı?

## 3. services/core/event_bus.py (Fail-Open Publish)
- **Senaryo:** Redis veya Kafka event gönderme (publish) işleminde hata
  oluştuğunda, sistem sadece log yazıp (exception swallow) sessizce
  işleme devam ediyor.
- **Neden şüpheli:** Eğer bu bir trade sinyali veya order iptal emri ise,
  hedefe ulaşmadığı halde sistemin normal seyrine devam etmesi finansal
  olarak fail-open (güvensiz) bir davranıştır.
- **Soru:** Publish hatalarında işlem durdurulmalı (fail-closed) mı,
  yoksa sadece loglayıp devam etmek yeterli mi?

## 4. [ÇÖZÜLDÜ] Stop-Loss Eşik Uyumsuzluğu
- **Çözüm:** decision_engine.py fallback stop-loss değeri (%5.0)
  backtest/learning katmanındaki canonical parametrelerle (%6.5 hard
  stop, 2.5x ATR, min %4.0) eşlendi ve regression testine alındı.

---

## 5. services/market_state/ensemble_regime.py (Ağırlık Dairesellik Şüphesi)
- **Senaryo:** `get_regime_adapted_weights()` artık gerçekten çağrılıyor
  (bağlantı hatası düzeltildi — bkz. `documentation/09` madde ile ilgili
  commit), ama mekanizmanın kendisi: skor-bazlı yöntemin ürettiği
  "preliminary rejim" tahmini, aynı skor yönteminin kendi ağırlığını
  artırmak için kullanılıyor (örn. BULL tahmininde skor ağırlığı
  0.50→0.60'a çıkıyor).
- **Neden şüpheli:** Bu bir dairesellik (circularity) riski — skor
  yöntemi ne derse desin, kendi dediğine daha çok inanılıyor; HMM/GMM'nin
  "farklı görüyorum" deme gücü tam da anlaşmadıkları anlarda azalıyor.
- **Soru:** Bu tasarım bilinçli olarak kabul edilebilir mi (bazı
  sistemlerde "kendine güvenen yöntem daha güvenilirdir" varsayımı
  vardır), yoksa ağırlık adaptasyonu bağımsız bir sinyale (örn.
  volatilite seviyesi, veri kalitesi) mi dayandırılmalı?

## 6. services/core/decision_engine.py (`_calculate_composite_score`) — "Kazanan Kazanır" Yanlılığı
- **Senaryo:** `ml_component = max(inp.ml_score, inp.spec_score * 0.9)` —
  iki bağımsız skordan (ML modeli ve kural-tabanlı sistem) her zaman daha
  iyimser olanı seçiliyor, ortalama/ağırlıklı birleşim değil.
- **Neden şüpheli:** Bu, sistematik aşırı-güven (overconfidence)
  yanlılığı yaratabilir — iki kaynaktan biri yanılıp iyimser bir skor
  üretse bile, o skor kazanıyor.
- **Soru:** Bu "en iyimser olanı seç" mantığı kasıtlı bir tasarım mı,
  yoksa ortalama veya ağırlıklı ortalamaya mı çevrilmeli?

## 7. services/ingestion/providers/bist_provider.py, matriks_provider.py — Muhtemelen Var Olmayan API Uç Noktaları
- **Senaryo:** `bist_provider.py` (`BASE_URL="https://www.borsaistanbul.com"`,
  "güvenilirlik 10/10" olarak belgelenmiş) ve `matriks_provider.py`
  (`BASE_URL="https://www.matriks.com"`, "güvenilirlik 8/10") web
  araştırmasıyla doğrulanamadı — gerçek BIST API'si (VERDA) ayrı bir
  kimlik-doğrulamalı domain'de (`verda.borsaistanbul.com`), gerçek
  Matriks API'si de ücretli/sözleşmeli bir domain'de (`matriksdata.com`).
  Bu iki dosyadaki endpoint'ler büyük ihtimalle hiç çalışmıyor (her
  çağrı `except Exception` ile sessizce yutulup boş/None dönüyor).
- **Neden şüpheli:** Provider failover mantığı bu iki kaynağı "yüksek
  güvenilirlikli" olarak önceliklendiriyor olabilir; gerçekte sürekli
  başarısız oluyorlarsa, sistem iddia ettiği "çoklu kaynak/çapraz
  doğrulama" mimarisine sahip değil, sessizce tek kaynağa (yfinance)
  bağımlı çalışıyor olabilir.
- **Soru:** Bu iki provider'a gerçek (ücretli/kimlik doğrulamalı) erişim
  sağlanacak mı, yoksa dürüstçe kaldırılıp mimari "gerçekte tek kaynaklı"
  olarak mı güncellenecek?

## 8. services/paper_trading/paper_orchestrator.py — Canlı/Sanal İşlemde T+1 Koruması Devre Dışı
- **Durum (güncelleme):** Bu madde henüz çözülmediği doğrulandı — bkz.
  `documentation/09` "Veri Alım Katmanı" bölümü. Backtest tarafındaki
  T+1 açığı (`multi_asset_engine.py`, commit `3edfb45`) çözülmüştü;
  canlı/sanal tarafındaki bu madde hâlâ aynı durumda.
- **Senaryo:** `execute_signal(signal_price=price, market_price=price)`
  — ikisine de aynı değişken veriliyor. `paper_execution.py`'nin kendi
  docstring'i bu iki fiyatın AYRI olması gerektiğini (look-ahead bias'ı
  önlemek için) açıkça belirtiyor, ama çağıran kod bunu sağlamıyor.
- **Neden şüpheli:** Bu, `services/backtest/multi_asset_engine.py`'de
  bulunup düzeltilen T+1 execution hatasının (bkz. commit `3edfb45`)
  canlı/sanal işlem tarafındaki karşılığı — orada düzeltildi, burada
  henüz düzeltilmedi.
- **Soru:** Canlı/sanal tarafta da gerçek "ertesi an/tick" fiyatı nasıl
  temin edilecek (streaming veri gecikmesi göz önüne alınarak)? Bu,
  sadece kod değişikliği değil, gerçek zamanlı veri akışının
  zamanlamasıyla ilgili bir tasarım kararı gerektiriyor.

## 9. services/ingestion/realtime.py, realtime_provider.py — Yanlış "Tazelik" Zaman Damgası
- **Durum (güncelleme):** Bu maddenin güncel kod durumu tekrar
  doğrulanmadı (son "code quality" refactor turundan sonra). Bir
  sonraki denetimde tekrar kontrol edilmeli.
- **Senaryo:** `self._last_update[ticker] = datetime.now(timezone.utc)`
  — bu, verinin gerçek piyasa zaman damgası değil, kodun çalıştığı an.
  yfinance kaynağı zaten ~15-20 dakika gecikmeli (bilinen bir Yahoo
  Finance sınırlaması), ama "son güncelleme" alanı her zaman "az önce"
  gösteriyor.
- **Neden şüpheli:** Herhangi bir "bu veri taze mi?" kontrolü, gerçekte
  15-20 dakika eski bir fiyatı "şu an" sanabilir — sessiz, tespit
  edilemez bir tazelik yanılsaması.
- **Soru:** Zaman damgası, sağlayıcının döndürdüğü gerçek bar/veri
  zaman damgasına mı çevrilmeli (fetch zamanı yerine)?

## 10. services/ingestion/ — Sabit Evren Tavanı (En Az 2 Yerde)
- **Senaryo:** `BIST_STOCKS[:50]` / `tickers[:50]` gibi sabit ilk-N
  sınırlamaları en az iki "gerçek zamanlı" veri modülünde var.
- **Neden şüpheli:** `documentation/02.7`'deki HOT/WARM/COLD adaptif
  önceliklendirme modeliyle çelişiyor; evrenin büyük kısmı için canlı
  fiyat hiç güncellenmiyor olabilir.
- **Soru:** Bu sabit tavan, HOT/WARM/COLD modeliyle mi değiştirilecek,
  yoksa bilinçli bir kaynak kısıtlaması olarak mı kalacak (ki bu durumda
  en azından açıkça belgelenmeli)?

## 11. services/portfolio/autonomous_conviction_engine.py — Hurdle Rate Resmi Hedefle Çelişiyor
- **Senaryo:** `base_hurdle_rate=0.35` (%35, "BIST politika faizi/mevduat
  barajı") + rejim primi (%5-40) + friction → toplam kabul eşiği
  %40-60'a kadar çıkıyor. `CandidateAsset.expected_return` alanının
  kendi docstring örneği bile ("0.15 = %15") bu eşiği hiçbir zaman
  geçemez.
- **Neden şüpheli:** `documentation/01 §1.7.2`'de belirlediğimiz resmi
  hedef aralığıyla (%10-20 BIST100 üzeri alfa) doğrudan çelişiyor. İki
  kötü senaryodan biri gerçekleşir: (a) ML modeli gerçekçi tahminler
  üretiyorsa portföy sürekli %100 nakitte kalır, (b) ML modeli %40-60
  gibi gerçekçi olmayan tahminler üretiyorsa bu filtre onları
  sorgusuzca kabul eder ("Holy Grail" tuzağı).
- **Not:** `services/core/risk_config.py` (merkezi risk parametreleri)
  eklendiğinde bu alan oraya taşınmamış, hâlâ `autonomous_conviction_
  engine.py` içinde sabit kodlu.
- **Soru:** `base_hurdle_rate`, projenin resmi %10-20 alfa hedefiyle
  tutarlı bir seviyeye mi çekilmeli (örn. risk-free oranı ayrı bir
  "fırsat maliyeti" olarak değil, doğrudan BIST100 karşılaştırmalı
  alfa hedefine göre mi tanımlanmalı)?

## 12. services/risk/var_cvar.py — Monte Carlo GPU Yolunda Seed Yok Sayılıyor
- **Senaryo:** `calculate_monte_carlo_var`'ın CPU yolu
  (`np.random.default_rng(seed)`) seed'i doğru kullanıyor (test
  edildi), ama GPU yolu (`torch.normal(...)`) seed parametresini hiç
  almıyor, PyTorch'un global rastgele durumunu kullanıyor.
- **Neden şüpheli:** Fonksiyonun kendi docstring'i seed'i
  "reproducibility için" tanımlıyor. GPU'lu bir makinede üretilen bir
  VaR kararı, aynı seed'le asla tam olarak yeniden üretilemez —
  `documentation/02.4`'teki "kanıt paketi/tekrar-oynatılabilirlik"
  ilkesiyle çelişiyor.
- **Soru:** GPU yolu da `rng`'den türetilen bir seed ile mi
  başlatılmalı (örn. `torch.manual_seed(seed)` çağrısı eklenerek)?

## 13. services/intelligence/trade_planner.py, services/simulation/main.py — Sabit Senaryo Olasılıkları
- **Senaryo:** Bull/Base/Bear (ve simulation/main.py'de Crash) senaryo
  olasılıkları (%30/%50/%20 veya %25/%50/%20/%5) her ticker/portföy
  için sabit — fonksiyon imzaları `spec_score`/`regime` parametresi
  bile almıyor.
- **Neden şüpheli:** Kullanıcıya/karar zincirine gerçek bir olasılıksal
  analiz yapılmış izlenimi veriyor ama girdiye hiç duyarlı değil.
- **Soru:** Bu olasılıklar gerçekten sinyal gücüne/rejime duyarlı hale
  mi getirilmeli, yoksa "kaba bir varsayılan senaryo şablonu" olduğu
  açıkça mı belgelenmeli?
