# 03 — Veri ve Bilgi Evreni

## 3.1 Temel ilke: Point-in-Time (PIT) disiplini

Bu belgedeki en önemli kural şudur: **Sistem, geçmişteki herhangi bir "t"
anında karar verirken, yalnızca o an gerçekten bilinebilecek bilgiyi
görmelidir.** Bunun ihlali (leakage), backtest sonuçlarını sistematik
olarak iyimser gösterir ve canlıda tamamen farklı (kötü) sonuçlar üretir.
Bu, kantitatif finansta modellerin başarısız olmasının #1 nedenidir.

PIT ihlaline yol açan tipik hatalar ve ALPHA'daki karşılığı:

| Hata türü | Örnek | ALPHA'da önleme mekanizması |
|---|---|---|
| Finansal veri revizyon sızıntısı | Bir şirketin çeyrek karı ilk açıklandığında X, sonra revize edilip Y oldu; backtest Y'yi t anında biliyormuş gibi kullanır | Her temel veri kaydı **yayın zamanı (as-reported) + revizyon zinciri** ile saklanır; backtest sadece o ana kadar yayınlanmış versiyonu kullanır |
| Survivorship bias | Sadece bugün hâlâ işlem gören hisselerle geçmiş test edilir; iflas eden/delist olanlar evrenden düşer | Delisted/iflas etmiş enstrümanlar evren geçmişinde tutulur (COLD katman, bkz. 02.7) |
| Etiket sızıntısı | Gelecekteki getiriyi hesaplarken kullanılan fiyat penceresi, feature hesaplama penceresiyle çakışıyor | `services/labels/` etiket üretim penceresi feature penceresinden **purge + embargo** ile ayrılır (bkz. Bölüm 05.3) |
| Haber zaman damgası hatası | Bir haberin "yayın zamanı" yerine "sisteme giriş zamanı" kullanılıyor, ki bu geçmişte geriye dönük toplu yüklemelerde yanlış olabilir | Her haber/KAP kaydı hem `kaynak_zamanı` hem `sisteme_giriş_zamanı` taşır; PIT sorgular `kaynak_zamanı` kullanır |

## 3.2 Bilgi evreni katmanları (Master-Spec ile uyumlu)

1. **Piyasa verisi**: fiyat, hacim, emir defteri proxy'leri (mevcut/free
   veri kaynaklarının izin verdiği ölçüde), endeksler.
2. **Temel veri (fundamentals)**: bilanço, gelir tablosu, nakit akışı,
   oranlar — as-reported + revizyon geçmişi.
3. **KAP açıklamaları**: zorunlu bildirimler, olay sınıflandırması
   (bkz. `docs/EVENT-INTELLIGENCE-SPEC.md`).
4. **Haber ve kamuya açık bilgi**: RSS, web kaynakları — lisans/robots.txt
   ve yasal erişim sınırlarına uyularak.
5. **Türkiye makro/politika verisi**: enflasyon, faiz, TCMB kararları,
   döviz kuru, düzenleyici değişiklikler.
6. **Küresel bağlam**: küresel endeksler, emtia, faiz, döviz, risk
   iştahı proxy'leri (VIX vb.) — Türk varlıklarına olan etkisi ölçüldüğü
   ölçüde.
7. **İlişki grafiği**: şirket-sektör-tedarik zinciri-rakip-ortaklık
   ilişkileri — olayların bir şirketten diğerine nasıl yayılacağını
   modellemek için.

Her katman için üç zorunlu alan vardır: **kaynak (provenance)**,
**zaman damgası** ve **güven/kalite skoru**. Kaynağı belirsiz hiçbir veri
karar sürecine "kesin bilgi" olarak giremez; en fazla düşük ağırlıklı bir
sinyal olarak değerlendirilir.

## 3.3 Veri kalite kapısı (Quality Gate) ve Tradability Mask

`services/core/data_quality.py` prensipte şu kontrolleri yapar:

- Fiyat pozitif mi, mantıklı bir aralıkta mı (örn. bir önceki kapanışa göre
  aşırı sıçrama yoksa devre kesici/hata şüphesi)?
- OHLC mantıksal tutarlı mı (High ≥ Low, High ≥ Open/Close, Low ≤ Open/Close)?
- Hacim negatif veya mantıksız derecede yüksek mi?
- Enstrüman o an işlem görüyor mu (halt, tatil, delisting)?

**Mask-First kuralı**: Bir veri noktası "tradable değil" olarak
işaretlendiğinde, bu maskeleme **feature hesaplamasından önce** uygulanır.
Önce feature hesaplayıp sonra sonucu `None` yapmak (post-hoc masking)
yasaktır, çünkü bu ara hesaplamalarda (örn. hareketli ortalamalar) kirli
veri sızıntısına yol açar. `memory/CURRENT-STATE.md` madde 12'de bu
konuda mevcut kod tabanında bir sapma tespit edilmiştir — düzeltilmesi
gereken bilinen bir açıktır.

## 3.4 Olay grafiği (Event Graph)

Bir olay (örn. "TCMB faiz artırdı" veya "Şirket X CEO'su istifa etti"),
tek bir hisseyi değil bir zincir boyunca birden fazla varlığı etkileyebilir:

```
OLAY → VARLIK/ENTİTE → MAKRO FAKTÖR → ÜLKE → SEKTÖR → ŞİRKET → ENSTRÜMAN → PORTFÖY
```

`docs/EVENT-INTELLIGENCE-SPEC.md` bu modelin teknik sözleşmesini
tanımlar: materiality (önemlilik), expectation/surprise (beklenti/sürpriz
farkı), event thread (bir konunun zaman içindeki gelişimi), binding/
conditionality (olayın hangi koşullara bağlı olduğu), company memory
(şirketin geçmiş olay tepkisi profili), evidence binding (her çıkarımın
kaynağa bağlanması) ve post-event reaction ölçümü. Bu, ALPHA'yı "haber
başlığına göre alım-satım yapan basit bir sentiment botu" olmaktan
çıkarıp, olayın **gerçek önemini ve olası yayılımını** değerlendiren bir
sisteme dönüştürür.

## 3.5 Veri sağlayıcı (provider) soyutlaması

Hiçbir üst katman doğrudan "yfinance" veya belirli bir sağlayıcıya
bağımlı olmamalıdır. `services/ingestion/providers/` altında her sağlayıcı
ortak bir arayüz (fetch_ohlcv, fetch_fundamentals, fetch_current_price vb.)
implemente eder. Bu, şu avantajları sağlar:

- Bir sağlayıcı değiştiğinde (örn. ücretsiz yfinance'den lisanslı bir
  feed'e geçiş) üst katmanlarda değişiklik gerekmez.
- Birden fazla sağlayıcı çapraz doğrulama (cross-validation) için
  paralel kullanılabilir — özellikle kritik fiyat/hacim verisinde.
- Sağlayıcı bazlı güvenilirlik/gecikme istatistiği tutulabilir.

## 3.6 Veri saklama ve yeniden işleme (reprocessing) politikası

- Ham veri katmanı **immutable**'dır (asla üzerine yazılmaz).
- Feature/etiket/model tahminleri, üretildikleri kod ve parametre
  versiyonuna bağlı olarak **versiyonlanır**. Bir feature hesaplama
  mantığı değiştiğinde eski feature'lar silinmez; yeni bir versiyon
  numarasıyla yan yana durur (bu, "hangi model hangi feature versiyonuyla
  eğitildi" sorusunu her zaman cevaplanabilir kılar).
- Geriye dönük yeniden işleme (backfill/reprocessing) yalnızca kontrollü,
  loglu bir süreçle yapılır ve mevcut canlı sonuçları sessizce değiştirmez.

## 3.7 Yasal ve etik veri toplama sınırları

- Yalnızca yasal ve teknik olarak erişime açık kaynaklar kullanılır
  (robots.txt, kullanım şartları, telif hakları gözetilir).
  Kimlik doğrulama/ödeme duvarı arkasındaki içerik yalnızca uygun
  lisans/sözleşme ile alınır.
- Kişisel veri toplama hedefi yoktur; toplanan veri finansal/kurumsal
  bilgi ve kamuya açık kurumsal açıklamalarla sınırlıdır.
- Bir kaynağın güvenilirliği düşükse (spam, manipülasyon şüphesi), bu
  kaynağın sinyal ağırlığı otomatik olarak azaltılır; kaynak listeden
  tamamen çıkarılmadan önce insan gözden geçirmesi önerilir.
