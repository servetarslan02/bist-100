# Bizim Nihai Hayalimiz — AI Yatırım Araştırma Organizasyonu

## Özet
BIST için kendi başına araştıran, piyasayı anlayan, farklı modellerden kanıt toplayan, çelişkileri fark eden, riskini hesaplayan, geçmiş kararlarını analiz eden ve kontrollü şekilde kendini geliştiren bir "AI yatırım araştırma organizasyonu".

## Temel Prensipler
- Tek bir AI'ya güvenme — birden fazla uzman model
- Kendi hatalarından ders çıkaran ama kontrollü değişen
- AI → Risk → Portfolio → Hard limits zinciri
- Değişiklikleri sandbox/test'te kanıtladıktan sonra uygula

## Sistem Akışı

```
GERÇEK DÜNYA
    ↓
VERİ + KAP + HABER + MAKRO
    ↓
FEATURE / STATE STORE
    ↓
┌───────────┼───────────┐
LightGBM  CatBoost  Time-Series
└───────────┼───────────┘
    ↓
ENSEMBLE ENGINE
    ↓
MULTI-HORIZON FORECAST (1D / 5D / 20D+)
    ↓
CROSS-SECTIONAL RANKING
    ↓
RISK & PORTFOLIO
    ↓
FINAL OPPORTUNITIES (BUY / HOLD / SELL)
    ↓
BACKTEST / WALK-FORWARD
    ↓
PAPER TRADING
    ↓
PERFORMANCE → POST-MORTEM → WHY?
    ↓
DRIFT DETECTION → CONTROLLED EVOLUTION
    ↓
SANDBOX → CHAMPION vs CHALLENGER → PASS/FAIL
    ↺

🛡️ SAFETY / GOVERNANCE (tüm sistemin üzerinde)
```

## Katmanlar (Eksiksiz)

### 📡 Veri Katmanı
- Gerçek zamanlı veri/state yönetimi
- KAP + haber + sentiment + event derin analiz
- Anomali / veri kalitesi tespiti

### 🧮 Feature Katmanı
- Feature / State Store
- Multi-horizon target/label sistemi
- Sektör/peer/piyasa hiyerarşisi

### 🤖 Model Katmanı
- LightGBM, CatBoost, Time-Series
- Intelligent Ensemble
- Champion–challenger model sistemi
- LLM araştırmacı/analist olarak kullanımı

### 🎯 Karar Katmanı
- Multi-horizon forecast
- Cross-sectional ranking
- Kararın nedenini açıklama (explainability)

### ⚖️ Risk Katmanı
- Dynamic position sizing
- Correlation, drawdown, volatility, exposure
- Sector weight, liquidity, capital limits

### 🧪 Test Katmanı
- Walk-forward, out-of-sample
- Leakage testleri, stress testleri
- Automated experiment / A-B / ablation

### 🔄 Öğrenme Katmanı
- Performance attribution
- Drift detection
- Kontrollü model/feature evolution
- Feedback loop

### 🧠 Hafıza Katmanı
- Memory / geçmiş deneyim ve karar hafızası
- Uzun dönem state/history saklama

### 🔌 Mimari
- Plugin-like mimari (sonradan yeni model/provider eklenebilir)
- Production güvenliği ve fail-safe mekanizmaları
