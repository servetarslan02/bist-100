# Açık Sorular ve Şüpheli İş Mantığı Listesi
(Sistem sahibi tarafından karar verilmesi gereken konular)

## 1. services/core/regime_detector.py (Rejim Tespiti)
- **Senaryo:** Hisse veya pazar geçmişi 200 günden kısaysa (örn. yeni halka arz), sma200 hesaplanamadığı için sma50'ye fallback yapılıyor. Bu durumda sma50 > sma200 eşitliği hiçbir zaman sağlanamıyor (False dönüyor) ve Trend skoru 20 puan eksik çıkıyor.
- **Neden Şüpheli:** Kısa geçmişli varlıkların (örneğin son 6 aylık verisi olanların) rejim tespiti, teknik olarak hiçbir zaman tam bir 'BULL' trend skoruna ulaşamayabilir.
- **Soru:** 200 günden az geçmişi olan varlıklar için bu faktörün (20 puanlık kısmın) ağırlığı diğer faktörlere mi dağıtılmalı, yoksa rejim hesaplamasında tamamen exclude mu edilmelidir?

## 2. services/core/data_quality.py (Limit-Up/Down Feature Maskeleme)
- **Senaryo:** Tavan/taban olan (limit-up/limit-down) hisseler için fiyat güvenilir olmadığı gerekçesiyle price_mask = 0.0 yapılıyor. 
- **Neden Şüpheli:** Alım/satım işlemi gerçekleştirilemediği için Execution motorunda kullanılmaması kesinlikle doğru, ancak Hareketli Ortalamalar (SMA20/SMA50 vb.) gibi geçmiş trend feature'ları hesaplanırken o günkü fiyatın tamamiyle 'None' (NaN) varsayılması sinyal çizgilerini (MACD vb.) koparabilir/bozabilir.
- **Soru:** Mask-first kuralı kesin bir kural olarak tanımlanmış, ancak momentum ve osilatör feature'larında serinin kopmaması için tavan/taban fiyatların *sadece hesaplama amaçlı* kullanılıp, sadece execution'da maskelenmesi daha doğru olmaz mı?


## 3. services/core/event_bus.py (Fail-Open Publish)
- **Senaryo:** Redis veya Kafka event gÃ¶nderme (publish) iÅŸleminde hata oluÅŸtuÄŸunda, sistem sadece log yazÄ±p (exception swallow) sessizce iÅŸleme devam ediyor.
- **Neden ÅÃ¼pheli:** EÄŸer bu bir trade sinyali veya order iptal emri ise, hedefe ulaÅŸmadÄ±ÄŸÄ± halde sistemin normal seyrine devam etmesi finansal olarak fail-open (gÃ¼vensiz) bir davranÄ±ÅŸtÄ±r.
- **Soru:** Publish hatalarÄ±nda iÅŸlem durdurulmalÄ± (fail-closed) mÄ±, yoksa sadece loglayÄ±p devam etmek yeterli mi?


## 4. [Ã‡Ã–ZÃœLDÃœ] Stop-Loss EÅŸik UyumsuzluÄŸu
- **Ã‡Ã¶zÃ¼m:** decision_engine.py fallback stop-loss deÄŸeri (%5.0) backtest/learning katmanÄ±ndaki canonical parametrelerle (%6.5 hard stop, 2.5x ATR, min %4.0) eÅŸlendi ve regression testine alÄ±ndÄ±.

