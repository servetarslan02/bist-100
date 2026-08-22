# Risk Modülü — Güncel Durum Raporu

**Tarih:** 2026-08-21
**Analiz:** Kod tabanı envanteri

---

## Genel Durum

| Metrik | Değer |
|--------|-------|
| Modül sayısı | 14 |
| Toplam satır | ~4,647 |
| Sınıf sayısı | 44 |
| Fonksiyon sayısı | 113 |
| Test sayısı | 104 |
| Risk check sayısı | 6 (pre-trade) |

---

## Modül Olgunluk Durumu

| Modül | Durum | Not |
|-------|-------|-----|
| main.py | ✅ TAM | Event consumer, fail-closed |
| position_sizing.py | ✅ TAM | Fractional Kelly + vol targeting |
| enhanced_risk.py | ✅ TAM | Ledoit-Wolf, rebalance, concentration |
| var_cvar.py | ✅ TAM | 3 yöntem VaR/CVaR |
| stress_test.py | ✅ TAM | Tarihsel + hipotetik + MC |
| covariance.py | ✅ TAM | Ledoit-Wolf shrinkage |
| drawdown_response.py | ✅ TAM | 5/10/15/20% eşikleri |
| dynamic_limits.py | ✅ TAM | Vol/rejim/drawdown/VIX-adjusted |
| tail_hedge.py | ✅ TAM | Protective put, collar, crisis alpha |
| risk_parity.py | ✅ TAM | Eşit risk katkısı |
| calibration.py | ✅ TAM | Platt scaling |
| monitoring.py | ✅ TAM | Real-time alerting |
| reconciliation.py | ✅ TAM | Ledger vs DB mutabakat |

---

## Bilinen Sınırlamalar

| Sınırlama | Öncelik | Açıklama |
|-----------|---------|----------|
| Kalibrasyon soğuk başlangıç | P1 | 30 trade'den az sigmoid fallback |
| Monte Carlo normal dağılım | P2 | Fat tail'leri yakalamaz |
| Stres testi statik senaryolar | P2 | Otomatik adaptasyon yok |
| Reconciliation sadece kontrol | P2 | Otomatik düzeltme yapmaz |
| Monitoring callback yokluğu | P2 | `register_callback()` ile eklenmeli |
| Risk parity scipy bağımlılığı | P2 | scipy.optimize.minimize gerektirir |
