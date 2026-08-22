# Macro Modülü — Güncel Durum Raporu

**Tarih:** 2026-08-21
**Analiz:** Kod tabanı envanteri

---

## Genel Durum

| Metrik | Değer |
|--------|-------|
| Modül sayısı | 18 |
| Toplam satır | ~4,500 |
| Test sayısı | 22 |
| Feature sayısı | 60+ |

---

## Modül Olgunluk Durumu

| Modül | Durum | Not |
|-------|-------|-----|
| config/macro_config.py | ✅ TAM | Pydantic, tüm eşikler |
| tcmb.py | ✅ TAM | 10+ feature |
| inflation.py | ✅ TAM | 12+ feature |
| fx.py | ✅ TAM | 12+ feature |
| cds.py | ✅ TAM | 7+ feature |
| credit.py | ✅ TAM | 5+ feature |
| current_account.py | ✅ TAM | 5+ feature |
| surprise_model.py | ✅ TAM | Beklenti vs gerçek |
| regime_detector.py | ✅ TAM | 6 makro rejim |
| impact_analyzer.py | ✅ TAM | Şok etkisi, decay |
| stress_test.py | ✅ TAM | 7 senaryo |
| correlation_tracker.py | ✅ TAM | Rolling 60g korelasyon |
| calendar_engine.py | ✅ TAM | TCMB PPK/FOMC |
| calendar.py | ✅ TAM | Sabit olay listesi |
| historical_store.py | ✅ TAM | PIT-safe, JSON |
| factor_decomposition.py | ✅ TAM | 7 faktör ayrıştırma |
| sensitivity_engine.py | ✅ TAM | Dinamik sektör hassasiyeti |

---

## Bilinen Sınırlamalar

| Sınırlama | Öncelik | Açıklama |
|-----------|---------|----------|
| Beklenti verisi manuel | P1 | TCMB faiz beklentisi otomatik çekilemez |
| Calendar tarihleri sabit | P1 | Yıl başında güncellenmeli |
| JSON storage | P2 | Büyük veri setlerinde performans sorunlu |
| Sektör hassasiyeti 10 sektör | P2 | Daha detaylı sektör ayrımı gerekli |
| Scipy bağımlılığı | P2 | p-value hesaplaması için gerekli |
| CDS verisi dış kaynak | P2 | Otomatik çekme mekanizması yok |
| In-memory surprise history | P2 | Restart sonrası sıfırlanır |
