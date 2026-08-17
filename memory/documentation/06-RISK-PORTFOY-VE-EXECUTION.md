# 06 — Risk, Portföy Yönetimi ve Execution

## 6.1 Temel felsefe: getiri ikincil, hayatta kalma birincil

Bir yatırım sisteminin en büyük başarısızlık modu, iyi bir sıralama
modeline sahip olup onu kötü bir risk yönetimiyle heba etmektir. Bu
yüzden risk katmanı, model katmanından **bağımsız ve onu geçersiz
kılabilen** bir otoriteye sahiptir: model "bu harika bir fırsat" dese
bile, risk katmanı pozisyon büyüklüğünü sıfıra indirebilir veya işlemi
tamamen reddedebilir.

## 6.2 Pozisyon boyutlandırma (Position Sizing)

`services/risk/position_sizing.py` üç bileşenin birleşimini kullanır:

1. **Kesirli Kelly (Fractional Kelly)**: Bir stratejinin tahmini kazanma
   olasılığı ve ortalama kazanç/kayıp oranından teorik optimal bahis
   büyüklüğünü hesaplar; ancak **tam Kelly asla kullanılmaz** — aşırı
   volatiliteye yol açar. Sistem varsayılan olarak yarım-Kelly
   (`kelly_fraction=0.5`) veya daha muhafazakar bir kesir kullanır.
2. **Volatilite Hedefleme (Vol Targeting)**: Portföyün hedef bir
   volatilite seviyesinde (örn. yıllık %15) kalması için pozisyon
   büyüklükleri güncel gerçekleşen volatiliteye göre ters orantılı
   ayarlanır — volatilite artınca pozisyon küçülür.
3. **Sert limitler (hard caps)**: Kelly ve vol-targeting sonucu ne
   olursa olsun, tek pozisyon `max_position_pct` (örn. portföyün %10'u)
   ve toplam maruziyet `max_total_exposure` (örn. %100, kaldıraçsız)
   sınırlarını aşamaz. Bu limitler modelin "çok güvenliyim" demesine
   rağmen aşılamayan, kod seviyesinde uygulanan (enforced) sınırlardır.

## 6.3 Çok katmanlı risk limitleri

| Seviye | Örnek limit | Amaç |
|---|---|---|
| Pozisyon | Tek hissede maks. %10 ağırlık | Tekil şirket riskine aşırı maruziyeti önlemek |
| Sektör | Tek sektörde maks. %25-30 ağırlık | Sektörel şok riskini sınırlamak |
| Portföy volatilitesi | Hedef yıllık volatilite bandı | Getiri/risk profilinin tutarlılığı |
| Portföy drawdown | Belirli bir düşüş eşiğinde risk azaltma/safe-mode | Sermaye korumasını önceliklendirmek |
| Likidite | Günlük hacmin belirli bir yüzdesini aşmayan pozisyon büyüklüğü | Gerçekçi çıkış kapasitesi (bkz. 6.5) |
| Korelasyon | Yüksek korelasyonlu pozisyonlar toplamda ek limitle sınırlanır | Gizli yoğunlaşma riskini önlemek |

Bu limitler statik sabitler değil, **politika olarak tanımlanmış ve
versiyonlanmış** parametrelerdir; değişiklikleri Yönetişim Beyni onayı
gerektirir (bkz. Bölüm 10).

## 6.4 Karar Motoru ile risk katmanının ilişkisi

`services/core/decision_engine.py`, ranking skorunu, güveni, rejimi ve
haber duyarlılığını birleştirip bir eylem üretir; ancak **eşik altı
skorlar otomatik olarak NO_ACTION/HOLD döner** (örn. skor veya güven
minimum eşiğin altındaysa hiçbir işlem yapılmaz). Bu, "her zaman bir
şey yapma" dürtüsüne karşı bilinçli bir tasarım kararıdır — çoğu gün
için en doğru eylem hiçbir şey yapmamaktır.

## 6.5 Execution simülasyonu (sanal ama gerçekçi)

Sanal olsa da, emir yürütme simülasyonu **kolay kazanılmış** (unrealistic)
sonuçlar üretmemelidir. Bu yüzden:

- **Slipaj (slippage)**: Emrin gerçekleşme fiyatı, karar anındaki
  fiyattan; hacme, volatiliteye ve emir büyüklüğüne bağlı bir model ile
  saptırılır (büyük emir → daha fazla slipaj).
- **Spread**: Alış-satış farkı, gerçekçi piyasa yapıcı davranışını
  yaklaşık temsil edecek şekilde modellenir.
- **Likidite kısıtı**: Bir pozisyon, günlük ortalama hacmin makul bir
  yüzdesini (örn. %5-10) aşacak şekilde "anında" gerçekleşmiş
  varsayılmaz; büyük pozisyonlar zaman içine yayılarak simüle edilir.
- **Komisyon/vergi**: Gerçekçi işlem maliyetleri (BIST'e özgü işlem
  ücretleri, stopaj vb.) dahil edilir.

Bu gerçekçilik, "kağıt üzerinde harika, gerçekte imkansız" bir stratejiyi
erken aşamada elemek için zorunludur.

## 6.6 Portföy defteri (Ledger)

`services/portfolio/` altında portföy durumu bir **defter** olarak
tutulur — her pozisyon açma/kapama, boyut değişikliği ve nakit hareketi
denetlenebilir bir kayıt bırakır (double-entry muhasebe mantığına
yakın). Bu şu soruları her zaman cevaplanabilir kılar:

- Şu an portföyün gerçek (mark-to-market) değeri nedir?
- Bu pozisyon ne zaman, hangi kararla, hangi fiyattan açıldı?
- Gerçekleşmiş (realized) ve gerçekleşmemiş (unrealized) kâr/zarar
  ayrımı doğru mu?

`memory/CURRENT-STATE.md` madde 10'da belirtildiği gibi, bugün backtest
motorunda açık pozisyonlar için mark-to-market, drawdown süresi ve
maruziyet hesaplamalarında basitleştirmeler tespit edilmiştir; bunlar
finansal doğruluk açısından düzeltilmesi gereken bilinen açıklardır.

## 6.7 Performans ölçüm çerçevesi (özet — detay Bölüm 07)

Portföy seviyesinde asgari izlenmesi gereken metrikler: toplam getiri,
CAGR, volatilite, Sharpe/Sortino oranı, maksimum drawdown ve süresi,
Calmar oranı, isabet oranı (hit rate), ortalama kazanç/kayıp oranı,
maruziyet (exposure) zaman serisi, sektör/rejim bazlı performans
kırılımı. Bunların **basitleştirilmiş/yaklaşık** değil, gerçek
mark-to-market veriden hesaplanması zorunludur.

## 6.8 Kriz/anomali davranışı

- Aşırı volatilite veya piyasa genelinde devre kesici benzeri olaylarda,
  sistem yeni pozisyon açmayı otomatik durdurur (bkz. Bölüm 02.5 — Safe
  Mode).
- Bir veri kalitesi krizi (örn. bir sağlayıcının yanlış veri vermesi)
  tespit edildiğinde, o kaynağa bağımlı tüm kararlar otomatik olarak
  düşük güvene çekilir.
- Portföy, belirlenen bir maksimum drawdown eşiğine ulaştığında, insan
  onayı olmadan otomatik olarak risk azaltma (pozisyonları küçültme)
  moduna geçer; bu eşik ve davranış açıkça belgelenmiş bir politika
  olmalıdır (bkz. Bölüm 10).
