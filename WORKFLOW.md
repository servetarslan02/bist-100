# 🛡️ ALPHA BIST — Çalışma Protokolü

> **Oluşturulma:** 2026-08-28  
> **Amaç:** Her iş sonrası tam doğrulama, sahte veri yok, eksiksiz ilerleme  
> **Öncelik:** Kalite > Hız

---

## ❌ KESİNLİKLE YASAK

1. **Sahte/mock veri yok** — Asla gelişi güzel, baştan savma veri üretme
2. **"Kritikleri yapıp geçeyim" yok** — Her şey eksiksiz olacak
3. **Test etmeden "tamam" demek yok** — Canlı doğrulama şart
4. **Yarım iş bırakmak yok** — Her adım tamamlanacak

---

## ✅ HER İŞ SONRASI ZORUNLU ADIMLAR

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

## 📋 İLERLEME TAKİBİ

Her iş için:
1. Başlamadan önce → ne yapılacak, netleştir
2. Yaparken → her adım kaydedilsin
3. Bittikten sonra → tam doğrulama + rapor güncelleme

---

## 🔍 DOĞRULAMA KOMUTLARI

```bash
# Servis sağlık kontrolü
curl -s http://localhost:8000/health | python -m json.tool

# Tüm container'ların durumu
docker compose ps

# Log'larda hata taraması
docker compose logs --tail=50 api 2>&1 | grep -i "error\|exception\|critical"

# Prometheus metrics
curl -s http://localhost:9090/api/v1/targets | python -m json.tool

# Python syntax kontrolü
ruff check services/ --select E,F,W

# Test çalıştırma
python -m pytest tests/ -x --timeout=30 -q --tb=short

# PostgreSQL integration testleri
python -m pytest tests/test_postgresql_integration.py -v

# Migration çalıştırma (dry-run)
python scripts/run_migrations.py --dry-run

# Migration çalıştırma
python scripts/run_migrations.py

# Migration durumu
python scripts/run_migrations.py --status

# Query performance audit
python scripts/audit_query_performance.py

# TimescaleDB health audit
python scripts/audit_timescaledb_health.py
```

---

## 📌 NOT

Bu protokol her zaman geçerlidir. Hiçbir istisna yoktur.
