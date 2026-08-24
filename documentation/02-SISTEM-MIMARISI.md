# 02 — Sistem Mimarisi

Bu doküman, ALPHA'nın uçtan uca **hedef** mimarisini tanımlar. Bugün kodda
gerçekte var olan / olmayan kısımlar için `09-MEVCUT-DURUM-VE-ACIK-ANALIZI.md`
belgesine bakın — bu belge bir "olması gereken" haritasıdır, "şu an böyle"
iddiası değildir.

## 2.1 Katman haritası (üst seviye)

```
┌─────────────────────────────────────────────────────────────────┐
│  KATMAN 7 — Arayüzler: API (FastAPI), Web dashboard (Next.js)    │
├─────────────────────────────────────────────────────────────────┤
│  KATMAN 6 — Yönetişim: doğrulama, promotion, audit, safe-mode    │
├─────────────────────────────────────────────────────────────────┤
│  KATMAN 5 — Portföy & Risk & Execution (sanal)                   │
├─────────────────────────────────────────────────────────────────┤
│  KATMAN 4 — Karar Motoru (Decision Engine): sıralama + rejim +   │
│              risk bütçesi → BUY/SELL/HOLD/NO_ACTION              │
├─────────────────────────────────────────────────────────────────┤
│  KATMAN 3 — Model & Öğrenme: Ranking Model, Rejim Tespiti,       │
│              Walk-Forward, Champion/Challenger, Sürekli öğrenme  │
├─────────────────────────────────────────────────────────────────┤
│  KATMAN 2 — Feature/Sinyal Üretimi: 7 Motor + Cross-Sectional +  │
│              Event/KAP/Haber zekası + Tradability Mask           │
├─────────────────────────────────────────────────────────────────┤
│  KATMAN 1 — Veri Alımı (Ingestion): fiyat, hacim, temel veri,    │
│              KAP, haber, makro — provider soyutlaması            │
├─────────────────────────────────────────────────────────────────┤
│  KATMAN 0 — Depolama: Postgres (durum/ledger), ClickHouse        │
│              (zaman serisi/olay), Redis (cache/kuyruk), nesne    │
│              depoları (model artifact, dataset manifest)         │
└─────────────────────────────────────────────────────────────────┘
```

Her katman yalnızca bir alt katmana bağımlıdır (katı katmanlama). Katman
atlayan bağımlılıklar (örn. Katman 5'in doğrudan Katman 1'den veri çekmesi)
mimari ihlal sayılır ve kod incelemesinde reddedilir.

## 2.2 Neden bu teknoloji seçimleri

| Bileşen | Seçim | Gerekçe |
|---|---|---|
| Zaman serisi / tick / olay depolama | ClickHouse | Kolon-tabanlı depolama, yüksek hacimli point-in-time sorgular (walk-forward, backtest replay) için gereken agregasyon hızı |
| İşlemsel durum (portföy, ledger, kullanıcı/politika) | PostgreSQL | ACID garantisi — portföy bakiyesi/pozisyon gibi verilerde tutarlılık pazarlık konusu değildir |
| Cache / kısa ömürlü kuyruk | Redis | Düşük gecikmeli sıralama sonucu/rejim durumu paylaşımı |
| Olay akışı (event streaming) | NATS + JetStream | Ingestion → feature → model → karar zincirinde asenkron, tekrar-oynatılabilir (replay edilebilir) olay akışı |
| API | FastAPI | Async I/O, otomatik şema doğrulama (Pydantic), test edilebilirlik |
| Web arayüzü | Next.js | Gerçek zamanlı dashboard (portföy, sinyaller, rejim durumu) |
| ML | LightGBM (ranking) + rule-based fallback | Tablo verisinde güçlü, yorumlanabilir, üretimde hızlı; "kara kutu" derin öğrenme başlangıç noktası olarak tercih edilmedi çünkü yorumlanabilirlik + az veriyle sağlamlık önceliklidir |
| Gözlemlenebilirlik | Prometheus + Grafana | Servis sağlığı, veri kalitesi, model drift metrikleri |
| Deney takibi | MLflow | Model versiyonlama, champion/challenger karşılaştırması, tekrarlanabilirlik |

## 2.3 Uçtan uca veri akışı (bir "tick"in yolculuğu)

1. **Ingestion**: Bir provider (yfinance, KAP, RSS, gelecekte lisanslı
   feed'ler) ham veriyi çeker → `services/ingestion/`.
2. **Data Quality Gate**: `services/core/data_quality.py` — fiyat/hacim
   mantıksal kontrolden geçer (devre kesici, halt, anormal OHLC, negatif
   fiyat vb.). Geçemeyen veri **mask'lenir**, silinmez; neden maskelendiği
   kayıt altına alınır.
3. **Persist (ham katman)**: Doğrulanmış ham veri ClickHouse'a point-in-time
   damgasıyla yazılır. Bu katman **asla geriye dönük değiştirilmez** —
   düzeltme gerekirse yeni bir kayıt eklenir, eskisi silinmez (point-in-time
   bütünlüğü için).
4. **Feature Engine (7 Motor)**: `services/features/seven_motors.py` +
   `services/features/calculator.py` — sadece maskelenmemiş (tradable)
   veriden feature türetir (bkz. Bölüm 04).
5. **Rejim Tespiti**: `services/intelligence/regime.py` — piyasa genelinin
   şu an hangi rejimde (BULL/BEAR/SIDEWAYS/HIGH_VOL vb.) olduğunu tahmin
   eder.
6. **Ranking Model**: `services/ml/ranking_model.py` — rejime duyarlı
   ağırlıklarla, LightGBM + rule-based ensemble kullanarak evrendeki
   hisseleri risk-ayarlı fırsat skoruna göre sıralar.
7. **Decision Engine**: `services/core/decision_engine.py` — skor, güven,
   rejim ve haber duyarlılığını birleştirip eşik tabanlı bir eylem
   (BUY/SELL/HOLD/NO_ACTION) ve hedef/stop fiyatları üretir.
8. **Risk & Position Sizing**: `services/risk/position_sizing.py` —
   Kelly-türevi + volatilite hedefleme + korelasyon ayarlı pozisyon
   büyüklüğü hesaplar; portföy düzeyinde maksimum risk bütçesini aşamaz.
9. **Execution Simulator (sanal)**: emir, gerçekçi slipaj/spread/likidite
   varsayımlarıyla simüle edilir; gerçek borsaya gönderilmez.
10. **Portfolio Ledger**: Postgres'te çift-girişli (double-entry benzeri)
    bir defter olarak tutulur; her pozisyon değişikliği denetlenebilir.
11. **Öğrenme Döngüsü**: Gerçekleşen sonuçlar (`services/learning/`) tahminle
    karşılaştırılır; model/politika performansı sürekli izlenir, belirli
    eşikler aşıldığında yeniden eğitim/kalibrasyon tetiklenir (bkz. Bölüm 05).
12. **Gözlemlenebilirlik**: Her adım structured log + metrik üretir;
    sessiz hata (`except: pass`) mimari olarak yasaktır.

## 2.4 Idempotency ve tekrar-oynatılabilirlik (replay)

Sistem, "bu kararı 6 ay önce neden verdik?" sorusuna cevap verebilmelidir.
Bunun için:

- Her karar; kullanılan feature değerleri, model versiyonu, rejim etiketi
  ve eşik parametreleriyle birlikte **kanıt paketi (evidence bundle)**
  olarak saklanır.
- `backtest/replay_engine.py` ve ClickHouse'daki point-in-time veri,
  geçmişteki herhangi bir anın **tam olarak o an bilinen bilgiyle**
  yeniden oynatılmasına izin verir (gelecekteki veri hiçbir şekilde
  sızmaz).
- Bu özellik hem hata ayıklama hem de walk-forward doğrulama için
  zorunludur (bkz. Bölüm 05.3).

## 2.5 Hata modeli ve "safe mode"

Sistem bir bütün olarak "ya çalışır ya çökers" mantığıyla tasarlanmaz.
Bunun yerine kademeli bozulma (graceful degradation) ilkesi uygulanır:

- Bir veri kaynağı başarısız olursa → o kaynağa bağımlı feature'lar
  `None`/eksik olarak işaretlenir, sistemin geri kalanı çalışmaya devam
  eder.
- Veri kalitesi kritik eşiğin altına düşerse (örn. evrenin büyük kısmı
  maskelenmiş) → sistem **SAFE MODE**'a geçer: yeni pozisyon açmaz, sadece
  mevcut pozisyonları izler ve risk yönetimi (stop/hedge) çalışmaya devam
  eder.
- Model/veri drift'i belirli bir eşiği aşarsa → ilgili model otomatik
  olarak "karantina" (quarantine) durumuna alınır ve Yönetişim Beyni
  onayı olmadan tekrar aktif hale gelemez.

## 2.6 Servis sınırları (repo `services/` ile eşleşme)

| Modül | Sorumluluk | Katman |
|---|---|---|
| `services/ingestion/` | Ham veri toplama, provider soyutlaması | 1 |
| `services/core/data_quality.py` | Tradability mask, veri doğrulama | 1→2 arası kapı |
| `services/features/` | 7 Motor, feature calculator | 2 |
| `services/intelligence/regime.py` | Rejim tespiti | 2→3 arası |
| `services/ml/` | Ranking model, kalibrasyon | 3 |
| `services/labels/` | Etiket (label) üretimi — eğitim için gerçekleşen getiri | 3 |
| `services/backtest/` | Walk-forward, backtest engine, replay | 3 (doğrulama) |
| `services/core/decision_engine.py` | Karar üretimi | 4 |
| `services/risk/` | Pozisyon boyutlandırma, reconciliation | 5 |
| `services/portfolio/` | Portföy defteri, PnL | 5 |
| `services/paper_trading/` | Sanal emir yürütme | 5 |
| `services/scanner/` | Fırsat tarama motoru | 3→4 arası |
| `services/learning/` | Sonuç izleme, drift tespiti, geri besleme | Öğrenme döngüsü |
| `services/agents/` | Araştırma otomasyonu (ileri faz) | Araştırma Beyni |
| `services/scheduler/` | Zamanlama, periyodik işler | Çapraz-kesme |
| `services/api/` | Dış arayüz | 7 |
| `services/market_state/`, `services/simulation/`, `services/events/`, `services/data/` | Destekleyici/gelişmekte olan modüller | Çeşitli |

## 2.7 Ölçeklenebilirlik ilkesi: HOT / WARM / COLD

Tüm BIST evreni + küresel bağlam + haber akışı her an eşit önceliğe sahip
değildir. Sistem üç işleme katmanı kullanır:

- **HOT**: Aktif izlenen, likit, güncel sinyali olan enstrümanlar —
  yüksek frekansta (dakikalar) yeniden hesaplanır.
- **WARM**: Evrende ama şu an öncelikli olmayan enstrümanlar — günlük
  yeniden hesaplanır.
- **COLD**: Tarihsel/delisted veya çok düşük likiditeli enstrümanlar —
  yalnızca araştırma/backtest amaçlı, talep üzerine hesaplanır.

Bir enstrümanın katmanlar arası geçişi likidite, haber yoğunluğu, açık
pozisyon varlığı ve kullanıcı önceliklendirmesi gibi sinyallerle
otomatik yönetilir. Bu, "sabit N ilk hisse" gibi keyfi tavanların yerini
alan, gerekçeli bir kaynak yönetimi modelidir (bkz. `memory/CURRENT-STATE.md`
madde 5 — bugün kodda bulunan keyfi `[:50]` tarzı tavanlar bu modelle
değiştirilmelidir).
