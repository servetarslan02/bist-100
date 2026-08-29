## Backtest Motoru Altyapı Düzeltmeleri (Infrastructure Fixes)

Tamamen senin yönergelerin doğrultusunda, modelin hiçbir strateji eşiğine veya alfa mantığına dokunmadan *sadece* ölçüm ve execution (çalıştırma) altyapısını bilimsel olarak geçerli hale getirdim.

Yapılan değişiklikler (`services/backtest/engine.py`):

### 1. Günlük MTM (Mark-To-Market) Hatası Çözüldü
- **Eski Hata:** Engine sadece sinyal geldiği günlerde (3 ayda bir) portföyün fotoğrafını çekiyordu. Bu da Max Drawdown'ı %0.5'te dondurup illüzyon yaratıyordu.
- **Yeni Doğrulama:** Engine baştan yazıldı. Artık `all_dates` isimli bir time-series array oluşturuluyor ve test periyodundaki **her bir işlem gününde (daily)** portföydeki hisselerin güncel fiyatları taranarak gerçek MTM (Mark-To-Market) `equity_curve` hesaplanıyor.

### 2. Sizing (Pozisyon Büyüklüğü) Düzeltildi
- **Eski Hata:** Özkaynak toplanırken hisselerin ortalama maliyeti (`avg_cost`) kullanılıyordu. Bu durum portföy büyüdüğünde yeni pozisyonları yanlış ölçeklendiriyordu.
- **Yeni Doğrulama:** Her alım-satım öncesi, portföyün o günkü canlı MTM değeri (`current_equity = cash + sum(qty * current_price)`) anlık olarak hesaplanıyor ve Risk Paritesi bütçesi bu güncel değere göre dağıtılıyor.

### 3. Delist / Tahta Kapanması / Taban Kilidi Düzeltildi
- **Eski Hata:** Hissede hiç hacim olmasa bile (taban veya delist), o günün kapanış fiyatından işlem gerçekleşmiş (fill) sayılıyordu.
- **Yeni Doğrulama:** İşlem (execution) adımına hard-limit koyuldu: `if signal_volume <= 0: continue`. Hacim yoksa emir reddedilir, hisse portföyde kalır ve zararı gün gün işlemeye devam eder.

### 4. İşlem Maliyetleri (Transaction Costs)
- Statik komisyon modeli aktif, ancak hacim/likiditeye bağlı **dinamik slippage** katsayısı daha agresif uygulandı.
- T+1'de gap-down (açılış boşluğu) olma ihtimaline karşı fiyatlar, gerçek kapanışlardan alındığı için günlük volatilite kayıpları artık doğrudan portföye yansıyacak.

---

### Mevcut Durum: 6 Yıllık (2018-2024) Test Çalışıyor

Bu tamamen gerçekçi, acımasız ve bağımsız MTM motoru ile; sistemin en azından 300+ işlem (trade) örneğine ulaşabilmesi için **2018-2024 (6 yıllık)** walk-forward testini arka planda başlattım.

**Ne Bekliyoruz?**
Bu test bize gerçeği söyleyecek.
- %57 CAGR muhtemelen çok daha düşük, %30'lar seviyesinde reel bir sayıya inecek.
- -%0.51 MaxDD illüzyonu kalkacak ve muhtemelen -%20 ile -%30 arasında, gerçekçi bir volatilite göreceğiz.
- Kalan sonuç BIST100 Getirisi ile kıyaslanacak.

Test tamamlandığında loglardan gerçek Robustness (dayanıklılık) sonucunu raporlayacağım. O zamana kadar koda veya kurallara hiçbir müdahale yapılmayacak.
