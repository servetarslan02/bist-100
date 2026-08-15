# Uygulama Planı v4 — İnceleme Sonrası Güncellenmiş

## Durum Özeti

| Kategori | Durum |
|----------|-------|
| Bölüm 1-8 kodları | ✅ TAMAMI mevcut (119 Python dosyası) |
| Bölüm 9-22 kodları | ✅ Mevcut modüller tarafından kapsanıyor |
| Bölüm 23-32 kodları | ❌ 9 yeni modül gerekli |
| Test dosyaları | ❌ Hiç yok |
| Entegrasyon testleri | ❌ Yapılmamış |
| Dokümantasyon-kod eşleşmesi | ❌ Doğrulanmamış |

---

## AŞAMA 1: Mevcut Kodu Doğrula (Bölüm 1-8)

### 1.1 Her modülü tek tek import et ve çalıştır

```python
# Her modül için:
try:
    from services.core.market_calendar import market_calendar
    print("✓ market_calendar import OK")
except Exception as e:
    print(f"✗ market_calendar FAIL: {e}")
```

**87 modül** import test edilecek.

### 1.2 Dokümantasyondaki kod örneklerini çalıştır

Her bölümdeki `python` kod bloğunu kopyala-yapıştır çalıştır:

| Bölüm | Kod Örneği | Test |
|-------|-----------|------|
| 1 | `cross_source_reconciliation.reconcile_price()` | quality_score: 100 |
| 1 | `WorldStateManager().get_state_dict()` | risk_appetite: 0.42 |
| 2 | `tradability_mask.compute_mask()` | mask: [1,1,0,1,0,1] |
| 2 | `data_quality_gate.check_tick()` | INVALID (zero volume) |
| 3 | `regime_engine.detect_regime()` | BULL, confidence: 0.85 |
| 4 | `factor_engine.compute_factor_scores()` | composite: 74.5 |
| 5 | `fundamental_feature_engine.compute_all_fundamental_features()` | fcf_yield: 6.8% |
| 6 | `kap_extractor.extract()` | CONTRACT, impact: +0.3 |
| 7 | `valuation_engine.compute_multiples_valuation()` | P/E upside: +29.4% |
| 7 | `valuation_engine.compute_dcf()` | implied_price: 340.50 |
| 8 | `forecasting_engine.compute_forecasts()` | 1d: +0.5% |
| 8 | `probability_engine.compute_probability_from_features()` | prob: 0.68 |

### 1.3 Entegrasyon zincirini test et

```
Veri Çekme → Kalite Kontrol → Feature Hesaplama → Rejim Tespiti →
Factor Skoru → Ranking → Fundamental → Valuation → Forecast →
Signal Fusion → Risk → Portfolio → Karar
```

Her adım bir sonrakiyle bağlantılı çalışmalı.

---

## AŞAMA 2: Test Yaz (Sıfırdan)

### Test yapısı:

```
tests/
├── test_core/
│   ├── test_market_calendar.py
│   ├── test_data_quality.py
│   ├── test_tradability_mask.py
│   ├── test_reconciliation.py
│   ├── test_pit_store.py
│   ├── test_streaming_anomaly.py
│   └── test_security.py
├── test_ingestion/
│   ├── test_providers.py
│   └── test_universe.py
├── test_features/
│   ├── test_seven_motors.py
│   ├── test_fundamental.py
│   ├── test_sentiment.py
│   └── test_cross_sectional.py
├── test_intelligence/
│   ├── test_regime.py
│   ├── test_factor_engine.py
│   ├── test_valuation.py
│   ├── test_forecasting.py
│   └── test_signal_fusion.py
├── test_risk/
│   └── test_enhanced_risk.py
├── test_learning/
│   └── test_backtest.py
└── test_integration/
    ├── test_data_to_feature_pipeline.py
    └── test_full_pipeline.py
```

### Her test dosyası:

```python
import pytest
from services.core.market_calendar import market_calendar

class TestMarketCalendar:
    def test_is_trading_day(self):
        assert market_calendar.is_trading_day(date(2026, 8, 18)) == True
    
    def test_is_not_trading_day(self):
        assert market_calendar.is_trading_day(date(2026, 1, 1)) == False
    
    def test_is_market_open(self):
        assert market_calendar.is_market_open(datetime(2026, 8, 18, 11, 0)) == True
    
    def test_is_market_closed(self):
        assert market_calendar.is_market_open(datetime(2026, 8, 18, 20, 0)) == False
```

---

## AŞAMA 3: Yeni Modüller (Bölüm 23-32)

### Yeni dosyalar:

| # | Dosya | Bölüm | Öncelik |
|---|-------|-------|---------|
| 1 | `services/core/short_selling.py` | 23 | Yüksek |
| 2 | `services/core/fee_calculator.py` | 23 | Yüksek |
| 3 | `services/core/price_limits.py` | 23 | Yüksek |
| 4 | `services/core/halt_monitor.py` | 23 | Yüksek |
| 5 | `services/core/compliance.py` | 27 | Yüksek |
| 6 | `services/core/manipulation_detector.py` | 27 | Yüksek |
| 7 | `services/features/technical_features.py` | 24 | Orta |
| 8 | `services/features/bist_specific.py` | 28 | Orta |
| 9 | `services/ml/model_comparator.py` | 25 | Orta |
| 10 | `services/ml/finrl_bist.py` | 29 | Düşük |
| 11 | `services/factors/piotroski.py` | 30 | Orta |
| 12 | `services/factors/beneish.py` | 30 | Orta |
| 13 | `services/factors/altman.py` | 30 | Orta |
| 14 | `services/event_study/expected_return.py` | 31 | Düşük |
| 15 | `services/event_study/abnormal_return.py` | 31 | Düşük |
| 16 | `services/viop/options_pricing.py` | 32 | Düşük |
| 17 | `services/viop/greeks.py` | 32 | Düşük |
| 18 | `services/alternative/web_scraping.py` | 26 | Düşük |
| 19 | `services/alternative/social.py` | 26 | Düşük |
| 20 | `services/alternative/jobs.py` | 26 | Düşük |

---

## AŞAMA 4: Entegrasyon ve Doğrulama

### 4.1 Tam pipeline testi:

```python
def test_full_pipeline():
    # 1. Veri çek
    data = yfinance_provider.get_ohlcv("THYAO")
    
    # 2. Kalite kontrol
    quality = data_quality_gate.check_tick("THYAO", data[-1]["close"], data[-1]["volume"])
    assert quality.passed == True
    
    # 3. Feature hesapla
    features = seven_motor_engine.compute_all("THYAO", data)
    assert len(features) > 40
    
    # 4. Rejim tespiti
    regime = regime_engine.detect_regime(features)
    assert regime.regime in ["BULL", "BEAR", "SIDEWAYS"]
    
    # 5. Factor skoru
    factor = factor_engine.compute_factor_scores("THYAO", fundamentals, features)
    assert factor.composite > 0
    
    # 6. Değerleme
    valuation = valuation_engine.compute_multiples_valuation("THYAO", 305.25, company, sector)
    assert valuation is not None
    
    # 7. Tahmin
    forecast = forecasting_engine.compute_forecasts("THYAO", features, [1, 5])
    assert len(forecast) > 0
    
    # 8. Risk
    risk = enhanced_risk.compute_risk_metrics(returns)
    assert risk is not None
    
    # 9. Karar
    decision = decision_engine.make_decision("THYAO", all_data)
    assert decision.action in ["BUY", "SELL", "HOLD", "NO_TRADE"]
```

### 4.2 run_system.py entegrasyonu:

Mevcut `run_system.py` hangi modülleri çağırıyor? Eksik modül var mı?

---

## Uygulama Sırası (Öncelik Sırasıyla)

```
GÜN 1-2: Aşama 1 (Import testleri + kod örnekleri doğrulama)
GÜN 3-4: Aşama 2 (Test yazma — core + features)
GÜN 5-6: Aşama 2 (Test yazma — intelligence + risk)
GÜN 7-8: Aşama 3 (Yeni modüller — yüksek öncelik)
GÜN 9-10: Aşama 3 (Yeni modüller — orta öncelik)
GÜN 11-12: Aşama 4 (Entegrasyon testleri)
GÜN 13-14: Aşama 4 (Düşük öncelik modüller + son doğrulama)
```

---

## Başarı Kriterleri

- [ ] 87 modülün tamamı import edilebiliyor
- [ ] 12 kod örneği beklenen çıktıyı üretiyor
- [ ] 6 entegrasyon zinciri çalışıyor
- [ ] 20 yeni modül implemente edilmiş
- [ ] 30+ test dosyası yazıl
- [ ] `pytest` ile tüm testler geçiyor
- [ ] `run_system.py` sorunsuz çalışıyor
