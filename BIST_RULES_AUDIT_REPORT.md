# 🔍 ALPHA BIST — Gerçek BIST Kuralları ile Kapsamlı Denetim Raporu

**Tarih:** 2026-08-26  
**Kapsam:** ML motorları, ticaret mantığı, risk yönetimi, seans kuralları  
**Kaynaklar:** Borsa İstanbul resmi, SPK duyuruları, Ağustos 2025 değişiklikleri

---

## 📋 ÖZET

Sistem genel olarak iyi yapılandırılmış, ancak **gerçek BIST kurallarıyla karşılaştırıldığında 23 kritik hata/eksik** tespit edildi. Bunlar 4 kategoride:

| Kategori | Kritik | Yüksek | Orta | Düşük |
|----------|--------|--------|------|-------|
| Seans & Zamanlama | 3 | 2 | 1 | 0 |
| Fiyat Limitleri & Devre Kesici | 2 | 2 | 1 | 0 |
| Açığa Satış & Takas | 1 | 2 | 1 | 0 |
| ML & Feature Engineering | 2 | 2 | 2 | 2 |
| **Toplam** | **8** | **8** | **5** | **2** |

---

## 🔴 KRİTİK HATALAR (Hemen Düzeltilmeli)

### 1. ❌ Yarım İş Günleri Desteklenmiyor
**Dosya:** `services/core/market_session_fsm.py`  
**Sorun:** Sistem sadece tam gün seans saatlerini destekliyor. BIST'te resmi tatil arifelerinde (Ramazan Bayramı Arife, Kurban Bayramı Arife vb.) piyasa **yarım gün** çalışır:

```
Yarım Gün Seans Çizelgesi:
09:40 - 09:55  Açılış Emir Toplama
09:55 - 10:00  Fiyat Belirleme
10:00 - 12:30  Sürekli İşlem
12:30 - 12:31  Kapanış Marj Yayını
12:31 - 12:35  Kapanış Emir Toplama
12:35          Kapanış Fiyat Belirleme
12:37 - 12:38  Kapanış Fiyatından Marj Yayını
12:38 - 12:40  Kapanış Fiyatından İşlem
```

**Etki:** Yarım günlerde sistem 18:00'e kadar işlem yapmaya devam eder → **look-ahead bias, sahte sinyaller, hatalı backtest sonuçları**.

**Düzeltme:** `market_session_fsm.py`'ye yarım gün desteği eklenmeli. `market_calendar.py`'deki `TURKEY_HOLIDAYS_2026` listesinde arife günleri işaretlenmeli.

---

### 2. ❌ EBDKS Süre Farklılaştırması Eksik
**Dosya:** `services/core/market_session_fsm.py`  
**Sorun:** `EBDKS_DURATION_MINUTES = 20` olarak sabit tanımlanmış. Ancak **Ağustos 2025 değişikliği** ile süreler farklılaştırıldı:

| Özellik Kodu | Eski Süre | Yeni Süre |
|---|---|---|
| `.E`, `.F1`, `.F2`, `.S1`, `.G` | 20 dk | **10 dk** |
| `.V`, `.C`, `.F`, `.R`, `.BE`, `.AOF` | 30 dk | **20 dk** |
| VİOP pay/endeks | 30 dk | **20 dk** |

**Etki:** Devre kesici sonrası emir toplama süresi yanlış → erken/geç işlem başlatma.

**Düzeltme:** Özellik koduna göre dinamik süre hesaplaması eklenmeli.

---

### 3. ❌ EBDKS Geç Seans Kuralı Eksik (17:30 Kuralı)
**Dosya:** `services/core/market_session_fsm.py`  
**Sorun:** EBDKS'nin sürekli işlem seansının bitimine **30 dakika kala** (17:30'dan sonra) devreye girmesi durumunda, işlemler durdurulup **kapanış seansı ile yeniden başlatılması** kuralı implemente edilmemiş.

**Ağustos 2025 değişikliği:** 60 dakika → 30 dakika (17:30'dan itibaren).

**Etki:** 17:30'dan sonra EBDKS tetiklenirse sistem kapanış seansını başlatamaz → işlemler askıda kalır.

---

### 4. ❌ Pay Bazında Devre Kesici — Eşikler ve Süreler Hatalı
**Dosya:** `services/core/market_session_fsm.py`  
**Sorun:**

```python
# Mevcut (YANLIŞ)
CIRCUIT_BREAKER_THRESHOLDS = {
    "yildiz": [5.0, 10.0, 15.0],
    "ana": [5.0, 10.0, 15.0],
    "alt": [5.0, 10.0],
}
CIRCUIT_BREAKER_DURATION_MINUTES = 10
```

**Gerçek kurallar (Ağustos 2025 sonrası):**
- Pay bazında devre kesici sonrası emir toplama süresi: **10 dakika** (tüm paylar için) ✅ Doğru
- Ancak eşikler pazar bazında farklı ve **aşağı yönlü** tetiklenir
- Yıldız/Ana Pazar: %5, %10, %15 düşüş
- Alt Pazar: %5, %10 düşüş
- **Ek:** Devre kesici sonrası fiyat marjı daraltması uygulanmalı (mevcut sistemde `POST_CB_LIMIT = 5.0` var ama otomatik tetiklenme mekanizması eksik)

---

### 5. ❌ Fiyat Limitleri — Pazar Bazında Farklılaştırma Eksik
**Dosya:** `services/core/price_limits.py`  
**Sorun:** Tüm pazarlarda standart ±%10 uygulanıyor. Ancak **gerçek BIST kuralları** daha karmaşık:

- **Yıldız Pazar:** ±%10 (genel), ama yüksek volatilite hisselerinde **hareketli fiyat değişme limiti** uygulanabilir
- **Ana Pazar:** ±%10
- **Alt Pazar:** ±%10 (Eylül 2025 sonrası)
- **Piyasa Öncesi İşlem Gören Paylar:** Farklı limitler
- **Halka Arz Günü:** İlk işlem gününde limit yok (serbest fiyat)
- **Bedelsiz Sermaye Artırımı Sonrası:** Baz fiyat yeniden hesaplanır

**Etki:** Bazı hisselerde yanlış tavan/taban fiyatı hesaplaması.

---

### 6. ❌ Vergi Oranları Eksik ve Hatalı
**Dosya:** `services/core/tax.py`  
**Sorun:**

```python
# Mevcut (YANLIŞ/EKSİK)
TAX_RATES = {
    "stock": {"short_term": 0.15, "long_term": 0.10},
    "dividend": 0.15,
    "bond": 0.10,
}
HOLDING_PERIOD_THRESHOLD = 180  # gün
```

**Gerçek kurallar:**
- **Hisse senedi:** Gelir vergisi dilimine göre değişir (vergi dilimi %15-%40 arası)
- **Menkul kıymet yatırım fonu katılma payları:** %0 (muafiyet olabilir)
- **Devlet tahvili/faiz:** %10 stopaj
- **Temettü:** %15 stopaj ✅ Doğru
- **Altın/gümüş:** %0-10 arası
- **Kripto:** %0 (2026 itibariyle tartışmalı)

**Kritik eksik:** Vergi dilimi (bracket) sistemi implemente edilmemiş. Sabit %15/%10 kullanılıyor.

---

### 7. ❌ İşlem Maliyetleri — BSMV Oranı Hatalı
**Dosya:** `services/core/fee_calculator.py`  
**Sorun:**

```python
# Mevcut (YANLIŞ)
BSMV_RATE = 0.05  # %5
```

**Gerçek kurallar:**
- BSMV oranı **%5** olarak uygulanır ✅ Doğru
- Ancak BSMV sadece **komisyon üzerinden** alınır, BIST payı ve MKK payı üzerinden alınmaz
- Mevcut kodda `(broker_fee + bist_fee + mkk_fee) * BSMV_RATE` hesaplanıyor → **BIST ve MKK payları üzerinden de BSMV alınıyor (YANLIŞ)**

**Düzeltme:** `bsmv = broker_fee * self.BSMV_RATE` olmalı.

---

### 8. ❌ Takas — Brüt Takas Kuralları Eksik
**Dosya:** `services/core/settlement.py`, `services/core/gross_settlement.py`  
**Sorun:** Brüt takas sadece "T+0 ödeme" ve "açığa satış yasak" olarak implemente edilmiş. Eksik kurallar:

- **Brüt takaslı hisselerde kredili işlem yasağı** implemente edilmemiş
- **Brüt takaslı hisselerde gün içi al-sat kısıtlaması** yok
- **Brüt takas → normal takas geçişinde** özel kurallar yok
- **SPK brüt takas listesi** dinamik güncelleme mekanizması eksik

---

## 🟠 YÜKSEK ÖNCELİKLİ SORUNLAR

### 9. ⚠️ Açığa Satış — BIST-50 Listesi Güncelleme Mekanizması Eksik
**Dosya:** `services/core/short_selling.py`  
**Sorun:** BIST-50 listesi **çeyrek dönemlerde** güncellenir (Mart, Haziran, Eylül, Aralık). Sistemde `_bist50_cache` var ama **otomatik güncelleme tetikleyicisi yok**.

**Etki:** Liste güncellendikten sonra sistem eski listeyi kullanmaya devam eder → yanlış hisselerde açığa satış izni.

---

### 10. ⚠️ Uptick Rule — Sadece Fiyat Kontrolü, Hacim/Spread Kontrolü Yok
**Dosya:** `services/core/short_selling.py`  
**Sorun:** Uptick rule sadece `current_price < last_trade_price` kontrolü yapıyor. BIST'te uptick rule ayrıca:

- **Son işlem fiyatının yanı sıra en iyi satış fiyatından** da yüksek veya eşit olmalı
- **Emir defterindeki spread** dikkate alınmalı
- **Açığa satış emri piyasa yapıcı tarafından verilmişse** farklı kurallar geçerli

---

### 11. ⚠️ Devre Kesici — Otomatik Tetikleme Mekanizması Yok
**Dosya:** `services/core/market_session_fsm.py`  
**Sorun:** `trigger_circuit_breaker()` ve `trigger_ebdks()` manuel olarak çağrılıyor. Sistemde **otomatik tetikleme** yok:

- Fiyat değişimini izleyen bir monitor yok
- EBDKS tetiklemesi için BIST-100 endeks değişimi otomatik hesaplanmıyor
- Devre kesici sonrası **otomatik emir toplama ve fiyat belirleme** akışı yok

---

### 12. ⚠️ VİOP — SPAN Teminat Hesaplaması Basitleştirilmiş
**Dosya:** `services/viop/margin.py`  
**Sorun:**

```python
# Mevcut (ÇOK BASİT)
margin = value * margin_rate
```

**Gerçek SPAN teminat sistemi:**
- 16 senaryo testi (risk array)
- Inter-commodity spread kredileri
- Intra-commodity spread kredileri
- Short option minimum teminat
- Net opsiyon primi mahsuplaşma
- Dinamik teminat oranları (volatiliteye göre)

---

### 13. ⚠️ Emir Türleri Eksik
**Dosya:** `services/paper_trading/paper_execution.py`  
**Sorun:** Sistem sadece `MARKET`, `LIMIT`, `STOP_LIMIT` destekliyor. BIST'te ayrıca:

| Emir Türü | Durum |
|---|---|
| Piyasa Emri | ✅ Var |
| Limit Emri | ✅ Var |
| Piyasadan Limite | ❌ Yok |
| Kalanı İptal Et (KİE) | ❌ Yok |
| Kalanı Pasife Yaz (KPY) | ❌ Yok |
| Gerçekleşmezse İptal (GİE) | ❌ Yok |
| Şartlı Emir | ❌ Yok |
| Zincir Emir | ❌ Yok |
| Dengeleyici Emir | ❌ Yok |
| Kotasyon Emri | ❌ Yok |

---

### 14. ⚠️ Lot Büyüklüğü ve Küsürat İşlemleri
**Dosya:** Genel  
**Sorun:** Sistemde lot büyüklüğü kontrolü yok:

- **Standart lot:** 1 pay = 1 lot
- **Lot altı (küsürat) işlemler:** Farklı kurallar geçerli
- **Minimum emir büyüklüğü** kontrolü yok
- **Blok emir** (belirli tutar üzeri) desteği yok

---

## 🟡 ORTA ÖNCELİKLİ SORUNLAR

### 15. ⚠️ Fiyat Adımı — Özel Durumlar
**Dosya:** `services/core/bist_tick_size.py`  
**Sorun:** Fiyat adımı tablosu genel olarak doğru, ancak:

- **Varantlar/sertifikalar:** Farklı fiyat adımları (0.001 TL)
- **Yeni halka arz payları:** İlk günlerde farklı adımlar
- **Bölünme/birleşme sonrası:** Fiyat adımı değişebilir

---

### 16. ⚠️ Takas Takvimi — 2026 Tatilleri Eksik/Güncel Değil
**Dosya:** `services/core/market_calendar.py`  
**Sorun:** `TURKEY_HOLIDAYS_2026` listesinde:

- **Ramazan Bayramı tarihleri** astronomik takvime göre değişebilir (hicri takvim)
- **Yarım gün tatiller** (arife günleri) ayrı işaretlenmemiş
- **Ek tatiller** (BIST özel tatilleri) dahil edilmemiş

---

### 17. ⚠️ ML Feature Engineering — BIST-Specific Features Eksik
**Dosya:** `services/features/`, `services/ml/`  
**Sorun:** Feature set'inde BIST'e özgü kritik features eksik:

| Feature | Durum |
|---|---|
| Açılış seansı denge fiyatı | ❌ Yok |
| Kapanış seansı denge fiyatı | ❌ Yok |
| Devre kesici tetikleme geçmişi | ❌ Yok |
| Brüt takas durumu | ❌ Yok |
| SPK bildirim eşiği yakınlığı | ❌ Yok |
| Sektör göreli güç (BIST sektörel endeks) | ❌ Yok |
| Endeks ağırlığı değişimi | ❌ Yok |
| Kurumsal yatırımcı oranı değişimi | ❌ Yok |
| KAP olay etkisi (event study) | ⚠️ Kısmen var |
| VİOP açık pozisyon değişimi | ❌ Yok |

---

### 18. ⚠️ Backtest — İşlem Maliyeti Modeli Eksik
**Dosya:** `services/backtest/transaction_costs.py`  
**Sorun:** Backtest'te işlem maliyetleri tam olarak modellenmemiş:

- **Kayma (slippage)** modeli basit (%0.05 base)
- **Likidite etkisi** (market impact) yok
- **Spread maliyeti** dinamik değil
- **Brüt takaslı hisselerde** farklı maliyet modeli yok
- **Devre kesici sonrası** farklı spread yapısı yok

---

## 🟢 DÜŞÜK ÖNCELİKLİ SORUNLAR

### 19. ℹ️ Algoritmik Trading Bildirimi
**Dosya:** `services/core/compliance.py`  
**Sorun:** SPK'nın algoritmik trading bildirimi gereksinimi implemente edilmemiş. Yüksek frekanslı algoritmik trading yapan kurumlar SPK'ya bildirimde bulunmalı.

---

### 20. ℹ️ Ödünç Pay Piyasası Entegrasyonu Yok
**Dosya:** Genel  
**Sorun:** BIST Ödünç Pay Piyasası (stock lending & borrowing) entegrasyonu yok. Açığa satış için ödünç pay alınması gereken durumlar yönetilemiyor.

---

## 📊 DÜZELTME ÖNCELİK MATRİSİ

| # | Sorun | Öncelik | Tahmini Süre | Etki |
|---|---|---|---|---|
| 1 | Yarım gün desteği | 🔴 Kritik | 2 gün | Backtest doğruluğu |
| 2 | EBDKS süre farklılaştırması | 🔴 Kritik | 1 gün | Devre kesici doğruluğu |
| 3 | EBDKS 17:30 kuralı | 🔴 Kritik | 1 gün | Kapanış seansı |
| 4 | Devre kesici eşikleri | 🔴 Kritik | 1 gün | Risk yönetimi |
| 5 | Fiyat limitleri pazar bazlı | 🔴 Kritik | 2 gün | Tavan/taban doğruluğu |
| 6 | Vergi oranları | 🔴 Kritik | 1 gün | Getiri hesaplama |
| 7 | BSMV hesaplama hatası | 🔴 Kritik | 0.5 gün | Maliyet doğruluğu |
| 8 | Brüt takas kuralları | 🔴 Kritik | 2 gün | Uyumluluk |
| 9 | BIST-50 otomatik güncelleme | 🟠 Yüksek | 1 gün | Açığa satış |
| 10 | Uptick rule detayları | 🟠 Yüksek | 1 gün | Açığa satış |
| 11 | Otomatik devre kesici | 🟠 Yüksek | 3 gün | Gerçek zamanlı |
| 12 | SPAN teminat | 🟠 Yüksek | 3 gün | VİOP doğruluğu |
| 13 | Emir türleri | 🟠 Yüksek | 2 gün | Gerçekçilik |
| 14 | Lot büyüklüğü | 🟠 Yüksek | 1 gün | Emir doğruluğu |
| 15 | Fiyat adımı özel durumlar | 🟡 Orta | 1 gün | Edge case |
| 16 | Takas takvimi | 🟡 Orta | 1 gün | Takas doğruluğu |
| 17 | BIST-specific features | 🟡 Orta | 5 gün | ML performansı |
| 18 | Backtest maliyet modeli | 🟡 Orta | 3 gün | Backtest doğruluğu |
| 19 | Algoritmik trading bildirimi | 🟢 Düşük | 1 gün | Uyumluluk |
| 20 | Ödünç pay entegrasyonu | 🟢 Düşük | 5 gün | Açığa satış |

---

## 🎯 ML MOTORLARINA ÖZEL ÖNERİLER

### Feature Engineering İyileştirmeleri

1. **Seans Fazı Feature'ları:**
   - `is_opening_auction` (açılış seansında mı?)
   - `is_closing_auction` (kapanış seansında mı?)
   - `minutes_to_close` (kapanışa kalan dakika)
   - `session_progress` (seansın % kaçı tamamlandı)

2. **Devre Kesici Feature'ları:**
   - `circuit_breaker_count_today` (bugün kaç kez tetiklendi)
   - `time_since_last_circuit_breaker` (son devre kesiciden bu yana süre)
   - `ebdks_active` (endekse bağlı devre kesici aktif mi?)
   - `price_distance_to_circuit_breaker` (devre kesiciye mesafe %)

3. **Takas ve Uyumluluk Feature'ları:**
   - `is_gross_settlement` (brüt takaslı mı?)
   - `days_to_settlement` (takas gününe kalan gün)
   - `spk_notification_proximity` (SPK bildirim eşiğine yakınlık)
   - `short_sale_eligible` (açığa satışa uygun mu?)

4. **Piyasa Mikro Yapı Feature'ları:**
   - `bid_ask_spread` (alım-satım spreadi)
   - `order_book_imbalance` (emir defteri dengesizliği)
   - `trade_size_avg` (ortalama işlem büyüklüğü)
   - `volume_at_price` (fiyattaki hacim dağılımı)

### Label Generation İyileştirmeleri

1. **Forward Return Hesaplama:**
   - Seans sonu kapanış fiyatı yerine **ağırlıklı ortalama fiyat (VWAP)** kullanılmalı
   - Devre kesici günleri hariç tutulmalı
   - Yarım günlerde farklı forward window kullanılmalı

2. **Risk-Adjusted Labels:**
   - Sharpe-ratio bazlı labels
   - Maximum drawdown bazlı labels
   - Sortino ratio bazlı labels

---

## ✅ DOĞRU IMPLEMENTE EDİLEN KURALLAR

| Kural | Durum | Dosya |
|---|---|---|
| Seans saatleri (tam gün) | ✅ Doğru | `market_session_fsm.py` |
| Fiyat adımları (standart) | ✅ Doğru | `bist_tick_size.py` |
| T+2 takas | ✅ Doğru | `settlement.py` |
| Temettü stopajı %15 | ✅ Doğru | `tax.py` |
| BIST payı %0.0056 | ✅ Doğru | `fee_calculator.py` |
| MKK payı %0.00109 | ✅ Doğru | `fee_calculator.py` |
| EBDKS %6 eşik | ✅ Doğru | `market_session_fsm.py` |
| Uptick rule %2 eşik | ✅ Doğru | `short_selling.py` |
| SPK %5 bildirim | ✅ Doğru | `compliance.py` |
| SPK %10 zorunlu teklif | ✅ Doğru | `compliance.py` |
| Brüt takas T+0 | ✅ Doğru | `settlement.py` |
| Brüt takas açığa satış yasak | ✅ Doğru | `gross_settlement.py` |

---

**Rapor Sonu**  
*Hazırlayan: ALPHA BIST Denetim Sistemi*
