# ALPHA BIST — Çalışma Kuralları (Dokümantasyondan Çıkarılan)

> Bu kurallar `bist-100/documentation/` klasöründeki manifesto ve mimari belgelerden çıkarılmıştır.
> Her çalışma oturumunda bu kurallara uyulması zorunludur.

---

## 🔴 KIRMIZI ÇİZGİLER (Asla Yapılmaz)

1. **Sahte/uydurma veri asla gerçek gözlem gibi sunulmaz.** Sabit (hard-coded) "canlı görünen" piyasa değerleri kullanılmaz. Gerçek veri yoksa "eksik/bilinmiyor" olarak işaretlenir.
2. **Geleceği gören (leakage) hiçbir özellik/model canlıya alınamaz.** Point-in-time doğruluk kanıtlanmadan hiçbir feature üretim ortamına girmez.
3. **Kendi kendini terfi ettiren bileşen olamaz.** Yeni model/strateji yalnızca Yönetişim Beyni'nin bağımsız doğrulamasından geçerse "champion" statüsüne yükselir.
4. **Test sayısı veya dosya sayısı başarı kanıtı değildir.** `assert ... or True` tarzı sahte assertion yasaktır.
5. **Sır (secret) kaynak kodunda tutulmaz.** Şifre, token, API anahtarı asla repoya commit edilmez.
6. **Gerçek para ile işlem bu projenin hedefi değildir.** Yıllar süren sanal doğrulama olmadan bu sınır aşılmaz.

---

## 🧠 ÜÇ BEYN FELSEFESİ

1. **Operasyon Beyni** — Bugünü yönetir (gözlem, sıralama, risk, sanal emir, portföy)
2. **Araştırma Beyni** — Geleceği araştırır (hipotez, feature keşfi, model araştırması) AMA kendi kendini terfi ettiremez
3. **Yönetişim Beyni** — Hakemdir (sızıntı koruması, OOS doğrulama, terfi onayı) AMA strateji üretmez

**Kural:** Araştırma Beyni kendi ürettiği stratejiyi canlıya alamaz. Operasyon Beyni kendi risk kurallarını gevşetemez.

---

## 📊 DEĞERLENDİRME STANDARTLARI

### Süreç doğrulama (1. soru) — "hayır" ise diğer sorular değerlendirilmez:
- Her feature'ın PIT doğruluğu birim testle kanıtlanmış mı?
- Etiket üretimi ile feature üretimi arasında purge+embargo uygulanmış mı?
- Walk-forward her fold'da modeli gerçekten yeniden eğitiyor mu?
- Veri kalite kapısı feature hesaplamasından **önce** mi uygulanıyor?

### İstatistiksel anlamlılık (zorunlu kontroller):
- **Deflated Sharpe Ratio (DSR)** — çoklu test düzeltmesi
- **Probabilistic Sharpe Ratio (PSR)** — güven aralığı
- **Block bootstrap güven aralıkları** — tek nokta tahmini yeterli değil
- **Information Coefficient (IC)** — Spearman korelasyon + ICIR
- **Precision@K / NDCG** — sıralama kalitesi
- **Fold-arası istikrar** — yalnızca 1-2 fold'da iyi olan model "genel olarak iyi" sayılmaz

### Resmi hedef aralığı:
| Metrik | Hedef |
|---|---|
| BIST100 üzeri yıllık alfa | %10-20 |
| Sharpe Oranı | 1.0–1.5 (yıllar boyunca istikrarlı) |
| Maksimum Drawdown | %25–35 altında |
| Doğrulama ufku | En az 3 tam piyasa döngüsü |

---

## 🏗️ MİMARİ KURALLAR

1. **Katı katmanlama:** Her katman yalnızca bir alt katmana bağımlıdır. Katman atlayan bağımlılıklar mimari ihlal sayılır.
2. **Fail-closed / fail-safe:** Data quality motoru hata verdiğinde "veri kaliteli kabul et" olmamalı. `except: pass` gibi sessiz yutma yasaktır.
3. **Point-in-time bütünlüğü:** Ham veri asla geriye dönük değiştirilmez; düzeltme gerekirse yeni kayıt eklenir.
4. **Mask-First:** Mask feature hesaplamasından **önce** uygulanır, sonra değil.

---

## 💾 VERİTABANI STRATEJİSİ

| Veritabanı | Amaç |
|---|---|
| PostgreSQL + TimescaleDB | İşlemsel + zaman serisi (hypertable) |
| QuestDB | Tick verisi (ILP ile ultra hızlı yazma) |
| ClickHouse (2 node) | OLAP analitik (30 yıllık veri) |
| DuckDB | Local state + offline research (embedded OLAP) |
| Redis 8 + Sentinel | Cache + Pub/Sub + Streams |

**Kural:** Aynı veriyi üç farklı DB'de gereksiz yere tutma.

---

## 🤖 ML KURALLARI

1. **LightGBM ana model olarak kalır.** XGBoost/CatBoost challenger olarak, aynı walk-forward ile test edilir.
2. **Ensemble = default değil.** Gerçek fayda kanıtlanırsa kullanılır.
3. **Model selection metrikleri:** Return + Sharpe + Max DD + IC + ICIR + Stability + Turnover + Regime performance + Statistical significance
4. **Calibration zorunlu:** Platt/Isotonic, Brier Score, ECE, drift takibi
5. **Feature contract:** Her feature için metadata (name, source, formula, lookback, PIT-safe, version)
6. **Pandas sadece uyumluluk için.** Yeni yüksek hacimli kod → Polars.

---

## 🔧 GELİŞTİRME İLKELERİ

1. **Dürüstlük > iddia.** Bir özelliğin dosyada var olması çalıştığı anlamına gelmez. Kanıt gerekir.
2. **Sanal para, gerçek disiplin.** Paper trading gerçek risk taşımaz ama gerçek karar disiplini taşımalıdır.
3. **Sızıntı (leakage) ölümdür.** Geleceği görmüş model her zaman iyi görünür ve her zaman yanlıştır.
4. **Basit ve doğru > karmaşık ve şüpheli.** Yeni motor/model eklemek kanıtla kazanılan ayrıcalıktır.
5. **Otonomluk gözetimsizlik değildir.** İnsan hedefleri, risk sınırlarını ve "dur" düğmesini elinde tutar.

---

## 🔍 BACKTEST DENETİM KURALLARI

> `services/backtest/AUDIT_REPORT.md` dosyasından çıkarılmıştır.
> Her backtest dosyası bu kurallara göre denetlenir.

### 1. Mock / Sahte Veri — Kesinlikle Yasak
- Test verisi, hardcoded değer, statik JSON, placeholder data **production kodunda olmayacak**
- `"Otomatik eklendi"` docstring'leri yasaktır — her docstring açıklayıcı ve anlamlı olacak
- `pass` ile boş fonksiyon gövdesi yasaktır

### 2. Tüm Hatalar Düzeltilecek
- Boundary hatası, dead code, exception yutma, yanlış veri kaynağı, bypass, tutarsızlık — sistemi bozan her şey düzeltilir
- `except: pass` gibi sessiz yutma yasaktır

### 3. Eksik Fonksiyonellik Tamamlanacak
- Eksik parametre, eksik loglama, eksik fallback, eksik validasyon tespit edilen her eksik tamamlanır

### 4. Kod Profesyonel Olacak
- Her docstring açıklayıcı ve **Türkçe**
- Her dataclass'ta `__repr__` metodu olacak
- Return type annotation doğru olacak
- Gereksiz import olmayacak
- Değişken isimleri anlamlı olacak
- Structlog yerine standart `logging` kullanılacak

### 5. Düzeltme Sonrası Kontrol
- Syntax kontrolü yapılacak (`python -c "import ..."`)
- Import zinciri kontrolü yapılacak

### 6. Geliştirme Önerileri Verilecek
- Eksik değil ama geliştirilebilecek her alan için öneri sunulacak

### 7. Mimari Tutarlılık
- İsim çakışmaları önlemek için sınıflar yeniden adlandırılabilir
- Motor isimleri amacına uygun olmalı (ör. `engine.py` → `execution_engine.py`)
- `__all__` listesi eksiksiz ve güncel olacak

---

## 📁 ÇALIŞMA DOSYASI

**Ana çalışma dosyası:** `Teknolojik gelişim` (repo kökünde) ve `docs/TEKNOLOJIK_GELISIM.md`

Bu dosya teknoloji stack'inin kapsamlı analizi ve geliştirme raporunu içerir.
İlerleme: 14/32 tamamlandı (%43.8)

### Öncelikli geliştirme alanları:
1. Feature Engine düzeltme + standardizasyon ✅
2. PIT/data leakage garantisi ✅
3. Data quality + fail-closed ✅
4. ML training/inference feature parity 🔴
5. Model version + reproducibility 🔴
6. Champion/Challenger gerçek entegrasyonu 🟠
7. GitHub Actions kapsamını genişletme 🟠

---

## 📂 PROJE YAPISI

```
bist-100/
├── documentation/     # Kurumsal dokümantasyon (12 belge)
├── docs/              # Teknik spec'ler ve raporlar
├── services/          # Microservice'ler (34 dizin)
├── ml/                # ML modelleri
├── backtest/          # Backtest motoru
├── tests/             # Test suite (105 dizin)
├── scripts/           # Utility scriptler (66 dizin)
├── config/            # Konfigürasyon
├── database/          # DB schema ve migration
├── infrastructure/    # Docker, Prometheus, Grafana
└── workers/           # Background worker'lar
```
