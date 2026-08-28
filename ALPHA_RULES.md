# ALPHA BIST — Çalışma Kuralları (Manifesto Özeti)

> Bu dosya, `documentation/` seti ve `WORKFLOW.md`'den çıkarılan zorunlu kuralları içerir.
> Her çalışma oturumunda bu kurallara uyulacaktır.

---

## 🔴 KIRMIZI ÇİZGİLER (Asla Yapılamaz)

1. **Sahte/mock veri asla gerçek gözlem gibi sunulmaz.** Hard-coded "canlı görünen" piyasa değerleri yasaktır. Veri yoksa "eksik/bilinmiyor" olarak işaretlenir, uydurulmaz.
2. **Geleceği gören (leakage) hiçbir feature/model canlıya alınamaz.** Point-in-time doğruluk kanıtlanmadan hiçbir feature üretim ortamına girmez.
3. **Kendi kendini terfi ettiren bileşen olamaz.** Yeni model/strateji yalnızca Yönetişim Beyni'nin bağımsız doğrulamasından geçerse champion statüsüne yükselir.
4. **Test sayısı veya dosya sayısı başarı kanıtı değildir.** `assert ... or True` tarzı sahte assertion yasaktır.
5. **Sır (secret) kaynak kodunda tutulmaz.** Şifre, token, API anahtarı asla repoya commit edilmez.
6. **Gerçek para ile işlem bu doküman setinin onayladığı bir hedef değildir.** Yıllar süren sanal doğrulama ve ayrı yönetişim/hukuki inceleme olmadan bu sınır aşılmaz.

---

## 📋 HER İŞ SONRASI ZORUNLU ADIMLAR

### 1. Uygulama
- [ ] Kod yazıldı/değiştirildi
- [ ] Syntax kontrolü (ruff, type check)
- [ ] İlgili testler çalıştırıldı

### 2. Canlı Doğrulama
- [ ] Servis sağlık kontrolü (`/health` endpoint)
- [ ] İlgili API endpoint'leri test edildi
- [ ] Veritabanı bağlantısı doğrulandı
- [ ] Log'larda hata yok

### 3. Sistem Bütünlüğü
- [ ] Docker container'ları çalışıyor mu?
- [ ] Prometheus metrics akıyor mu?
- [ ] Mevcut fonksiyonlar bozulmadı mı? (regression)
- [ ] Bellek/CPU kullanımı normal mi?

### 4. Dokümantasyon
- [ ] İlgili rapor/döküman güncellendi
- [ ] Değişiklik log'u yazıldı
- [ ] Progress dosyası güncellendi

---

## 🧠 TEMEL İLKELER

1. **Dürüstlük > İddia.** Bir özelliğin dosyada var olması, onun çalıştığı veya doğru olduğu anlamına gelmez. "Tamamlandı" demek için kanıt (geçen test + gerçek veri + bağımsız doğrulama) gerekir.
2. **Sanal para, gerçek disiplin.** Paper trading gerçek para riski taşımaz ama gerçek karar disiplini taşımalıdır.
3. **Sızıntı (leakage) ölümdür.** Geleceği görmüş bir model her zaman iyi görünür ve her zaman yanlıştır.
4. **Basit ve doğru > karmaşık ve şüpheli.** Yeni motor/model eklemek varsayılan davranış değil, kanıtla kazanılan ayrıcalıktır.
5. **Otonomluk gözetimsizlik değildir.** İnsan hedefleri, risk sınırlarını ve "dur" düğmesini her zaman elinde tutar.

---

## 🏗️ ÜÇ BEYİN FELSEFESİ

1. **Operasyon Beyni** — Bugünü yönetir (gözlem, sıralama, risk uygulaması, sanal emir, portföy defteri)
2. **Araştırma Beyni** — Geleceği araştırır ama kendi kendini terfi ettiremez (hipotez, feature keşfi, challenger model)
3. **Yönetişim Beyni** — Hakemdir; ne strateji üretir ne sonuç uydurur (sızıntı koruması, OOS doğrulama, terfi onayı)

**Kural:** Araştırma Beyni kendi ürettiği stratejiyi canlıya alamaz. Operasyon Beyni kendi risk kurallarını gevşetemez.

---

## 📊 RESMİ HEDEF ARALIĞI

| Metrik | Hedef |
|---|---|
| BIST100 üzeri yıllık alfa | %10-20 |
| Sharpe Oranı | 1.0–1.5 (yıllar boyunca istikrarlı) |
| Maksimum Drawdown | %25–35 altında |
| Doğrulama ufku | En az 3 tam piyasa döngüsü |

**Otomatik şüphe eşiği:** %50+ yıllık alfa iddiası → varsayılan olarak "şüpheli", ek tur inceleme gerekir.

---

## 🔬 SÜREÇ DOĞRULAMA KONTROL LİSTESİ

- [ ] Her feature'ın point-in-time doğruluğu birim testle kanıtlanmış mı?
- [ ] Etiket üretimi ile feature üretimi arasında purge+embargo uygulanmış mı?
- [ ] Walk-forward her fold'da modeli gerçekten yeniden eğitiyor mu?
- [ ] Test paketinde "her zaman geçen" sahte assertion var mı?
- [ ] Sabit/hard-coded "canlı görünen" veri var mı?
- [ ] Veri kalite kapısı (mask) feature hesaplamasından önce mi uygulanıyor?

---

## 🛡️ RİLK YÖNETİMİ KURALLARI

- **Kesirli Kelly** kullanılır (tam Kelly asla — aşırı volatilite)
- **Sert limitler:** Tek pozisyon max %10, sektör max %25-30
- **Safe Mode:** Kritik veri kalitesi düşüşünde yeni pozisyon açılmaz
- **Kravza modu:** Aşırı volatilitede otomatik risk azaltma
- **`except: pass` yasaktır** — hata loglanır, bileşen güvenli devre dışı kalır

---

## 📐 MİMARİ KURALLAR

1. **Katı katmanlama:** Her katman yalnızca bir alt katmana bağımlıdır
2. **Mask-First:** Tradability mask, feature hesaplamasından ÖNCE uygulanır
3. **Immutable ham veri:** Ham veri katmanı asla üzerine yazılmaz
4. **Versioned feature:** Feature mantığı değişirse eski versiyon silinmez
5. **HOT/WARM/COLD:** Keyfi `[:N]` tavanları yerine adaptif önceliklendirme
6. **Kanıt paketi:** Her karar feature değerleri + model versiyonu + rejim + eşik ile saklanır

---

## 📈 DOĞRULAMA KOMUTLARI

```bash
# Servis sağlık kontrolü
curl -s http://localhost:8000/health | python -m json.tool

# Docker durumu
docker compose ps

# Log'larda hata
docker compose logs --tail=50 api 2>&1 | grep -i "error\|exception\|critical"

# Python syntax
ruff check services/ --select E,F,W

# Test çalıştırma
python -m pytest tests/ -x --timeout=30 -q --tb=short

# Migration (dry-run)
python scripts/run_migrations.py --dry-run
```

---

## 🚫 YASAK DAVRANIŞLAR

1. Sahte/gelişi güzel veri üretmek
2. "Kritikleri yapıp geçeyim" demek
3. Test etmeden "tamam" demek
4. Yarım iş bırakmak
5. `assert ... or True` ile test geçirmek
6. Sırları kodda/depoitörde tutmak
7. `except: pass` ile hata yutmak
8. Gelecek veriyi geçmişe sızdırmak
9. Kendi modelini kendisi terfi ettirmek
10. Başarı kanıtı olmadan "tamamlandı" demek

---

## 📂 ÇALIŞMA DOSYASI

**`Teknolojik gelişim`** (repo kökünde) ve **`docs/TEKNOLOJIK_GELISIM.md`** — üzerinde çalışacağımız ana dosya.

---

## 📖 DOKÜMANTASYON SETİ OKUMA SIRASI

| # | Dosya | Kapsam |
|---|---|---|
| 01 | `01-VIZYON-VE-MANIFESTO.md` | Vizyon, üç beyin, kırmızı çizgiler |
| 02 | `02-SISTEM-MIMARISI.md` | Katmanlar, veri akışı, teknoloji seçimleri |
| 03 | `03-VERI-VE-BILGI-EVRENI.md` | PIT disiplini, veri kalite kapısı |
| 04 | `04-FEATURE-MOTORLARI-VE-SINYAL-URETIMI.md` | 9 motor, sinyal üretimi |
| 05 | `05-MODEL-OGRENME-VE-ARASTIRMA-DONGUSU.md` | Ranking, walk-forward, champion/challenger |
| 06 | `06-RISK-PORTFOY-VE-EXECUTION.md` | Pozisyon boyutlandırma, risk limitleri |
| 07 | `07-DEGERLENDIRME-VE-BASARI-KRITERLERI.md` | DSR, PSR, istatistiksel anlamlılık |
| 08 | `08-YOL-HARITASI-VE-FAZLAR.md` | Faz 0-6+, çıkış kapıları |
| 09 | `09-MEVCUT-DURUM-VE-ACIK-ANALIZI.md` | P0/P1/P2 açıklar |
| 10 | `10-YONETISIM-GUVENLIK-VE-UYUM.md` | Güvenlik, denetim, felaket senaryoları |
| 11 | `11-SOZLUK.md` | Terimler sözlüğü |
| 12 | `12-ACIK-SORULAR.md` | Karar bekleyen açık sorular |

---

*Bu kurallar `documentation/` setinden çıkarılmıştır. Her oturum başlangıcında okunacaktır.*
