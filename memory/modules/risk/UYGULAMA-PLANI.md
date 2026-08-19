# 🚀 Risk System Nihai Mimari — Uygulama Planı

**Tarih:** 2026-08-19
**Hazırlayan:** AI Analiz (Kod Analizi + İnternet Araştırması)
**Kaynaklar:** ScienceDirect Integrated Risk Management (2026), arXiv Agentic Trading (2026), SSRN Regime-Conditioned Kelly (2026), CFA Institute Market Risk (2026), ScienceDirect RMSE-Triggered Rebalancing (2026), Resonanz Capital Tail-Risk Hedging (2025), Quantt Kelly Criterion (2026), Nature ML Risk-Based Allocation (2025)

---

## 📋 İçindekiler

1. [Araştırma Bulguları](#1-araştırma-bulguları)
2. [Mevcut Sistem Analizi](#2-mevcut-sistem-analizi)
3. [Eksiklikler ve Nihai Hedef](#3-eksiklikler-ve-nihai-hedef)
4. [Genel Mimari Tasarım](#4-genel-mimari-tasarım)
5. [Faz Planı](#5-faz-planı)
6. [Test Stratejisi](#6-test-stratejisi)
7. [Risk ve Azaltma](#7-risk-ve-azaltma)

---

## 1. Araştırma Bulguları

### 1.1 ScienceDirect — Integrated Risk Management Framework (2026)

**Kaynak:** ScienceDirect, 2026

**Temel Bulgular:**
- VaR + CVaR + Stokastik optimizasyon entegre çerçeve
- **Multi-metric risk assessment**: Tek metrik (sadece VaR) yetersiz; VaR + CVaR + drawdown birlikte kullanılmalı
- **Dynamic risk limits**: Volatilite artınca limitler otomatik sıkılaşmalı
- **Stress testing**: Historical + hypothetical + Monte Carlo üçlüsü
- **Component VaR**: Her pozisyonun portföy riskine katkısı ölçülmeli

### 1.2 arXiv Agentic Trading Meta-Analizi (2026)

**Kaynak:** arXiv 2605.19337

**Risk Pipeline En İyi Uygulama:**
```
PRE-TRADE → POSITION SIZING → PORTFOLIO RISK → DYNAMIC LIMITS → STRESS TEST → MONITORING
```

**Kritik Bulgular:**
- **Kelly Criterion + Volatility Targeting**: İkisi birlikte kullanılmalı
- **Regime-conditioned risk**: Farklı rejimlerde farklı risk limitleri
- **Real-time risk monitoring**: Pozisyon açıkken sürekli izleme
- **Risk as AI override**: Risk motoru AI'ın üzerinde çalışmalı, hiçbir model risk limitini bypass edemez

### 1.3 SSRN Regime-Conditioned Kelly (2026)

**Kaynak:** SSRN, 2026

**Temel Katkı:**
- Kelly fraction rejime göre değişmeli:
  - **BULL**: 0.6x (agresif)
  - **BEAR**: 0.3x (muhafazakar)
  - **CRISIS**: 0.15x (çok muhafazakar)
  - **SIDEWAYS**: 0.4x (orta)
- **Bayesian changepoint detection**: Rejim değişimi erken tespit
- **Online learning**: Her trade sonrası Kelly parametreleri güncellenmeli

### 1.4 CFA Institute — Measuring and Managing Market Risk (2026)

**Kaynak:** CFA Institute, 2026

**Metodoloji:**
- **Parametrik VaR**: Normal dağılım varsayımı, hızlı hesaplama
- **Tarihsel VaR**: Dağılım varsayımı yok, geçmiş veriye dayalı
- **Monte Carlo VaR**: En esnek, stokastik simülasyon
- **CVaR (Expected Shortfall)**: VaR'ı aşan ortalama kayıp — tail risk ölçümü
- **Component VaR**: Pozisyon bazlı risk katkısı
- **Marginal VaR**: Yeni pozisyon eklenince risk değişimi

### 1.5 Nature — ML-Based Dynamic Risk Allocation (2025)

**Kaynak:** Nature Scientific Reports, 2025

**Temel Bulgular:**
- ML tabanlı risk tahmini geleneksel yöntemlerden %15-20 daha iyi
- **Dynamic risk budgeting**: Sabit limitler yerine dinamik bütçe
- **Feature engineering**: Volatilite, korelasyon, momentum risk tahmininde en önemli feature'lar

### 1.6 Quantt — Kelly Criterion 2026

**Kaynak:** Quantt.co.uk, 2026

**En İyi Uygulama:**
- **Fractional Kelly (0.25x-0.5x)**: Full Kelly çok riskli
- **Multi-asset Kelly**: Korelasyonu hesaba katan çoklu varlık Kelly'si
- **Bayesian Kelly**: Prior bilgi ile güncellenen Kelly
- **Kelly + Drawdown constraint**: Kelly fraction = min(kelly, max_drawdown_tolerance)

---

## 2. Mevcut Sistem Analizi

### 2.1 Modül Özeti (7 dosya, 1,654 satır)

| Modül | Satır | Sınıf | Ne Yapıyor | Durum |
|-------|-------|-------|------------|-------|
| `main.py` | 456 | 1 | RiskEngine — event consumer, position/sector/daily/drawdown checks | ✅ İyi |
| `position_sizing.py` | 335 | 4 | Fractional Kelly + volatility targeting + cold-start policy | ✅ İyi |
| `enhanced_risk.py` | 318 | 7 | Ledoit-Wolf, vol targeting, rebalance, concentration, VIOP hedge | ✅ İyi |
| `covariance.py` | 153 | 1 | Ledoit-Wolf shrinkage covariance (optimal intensity) | ✅ İyi |
| `calibration.py` | 122 | 2 | Platt scaling — score → win_probability | ✅ İyi |
| `reconciliation.py` | 90 | 2 | Ledger vs DB reconciliation | ✅ İyi |
| `risk_gate.py` | 180 | 1 | Pre-trade 9-check risk gate + BIST rules | ✅ İyi |

### 2.2 Mevcut Güçlü Yönler

1. **Fail-closed mimari**: Risk limitleri yüklenemezse tüm işlemler BLOCKED
2. **Fractional Kelly**: Yarım Kelly (0.5x) — güvenli
3. **Ledoit-Wolf covariance**: Optimal shrinkage intensity ile
4. **Cold-start policy**: Trade geçmişi yoksa Kelly devre dışı, score-based weight
5. **BIST kuralları entegrasyonu**: Açığa satış, halt, SPK uyumluluk
6. **Platt scaling calibration**: Score → probability dönüşümü
7. **Reconciliation**: Ledger vs DB tutarlılık kontrolü

### 2.3 Mevcut Zayıf Yönler (Kritik Eksiklikler)

| # | Eksiklik | Etki | Öncelik |
|---|----------|------|---------|
| 1 | **VaR/CVaR yok** | Tail risk ölçülemiyor | 🔴 Kritik |
| 2 | **Regime-conditioned Kelly yok** | Bull'da muhafazakar, Bear'da agresif olabilir | 🔴 Kritik |
| 3 | **Dynamic risk limits yok** | Volatilite artınca limitler sıkılaşmıyor | 🔴 Kritik |
| 4 | **Stress test entegrasyonu zayıf** | Stres testi sonuçları risk kararlarına yansımıyor | 🟡 Yüksek |
| 5 | **Risk dashboard yok** | Risk durumu hızlı değerlendirilemiyor | 🟡 Yüksek |
| 6 | **Tail risk hedging yok** | Kriz durumlarında büyük kayıp | 🟡 Yüksek |
| 7 | **Correlation risk basit** | Gerçek korelasyon riski ölçülemiyor | 🟠 Orta |
| 8 | **Alert system zayıf** | Kritik risk durumları yeterince bildirilmiyor | 🟠 Orta |
| 9 | **Risk parity yok** | Eşit risk dağılımı yapılamıyor | 🟠 Orta |
| 10 | **Drawdown response otomatik değil** | Drawdown olunca manuel müdahale gerekiyor | 🟡 Yüksek |

---

## 3. Eksiklikler ve Nihai Hedef

### 3.1 Nihai Risk Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│                    RISK PIPELINE v2.0 (NİHAİ)                       │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              PRE-TRADE RISK GATE (Mevcut + Gelişmiş)        │   │
│  │  ✅ Circuit breaker check                                   │   │
│  │  ✅ Market session check                                    │   │
│  │  ✅ Data validity check                                     │   │
│  │  ✅ Portfolio exposure check                                │   │
│  │  ✅ Order size check                                        │   │
│  │  ✅ Position concentration check                            │   │
│  │  ✅ Confidence threshold check                              │   │
│  │  ✅ Daily loss limit check                                  │   │
│  │  ✅ Drawdown limit check                                    │   │
│  │  ✅ BIST rules (short selling, halt, compliance)            │   │
│  │  🆕 Liquidity check                                         │   │
│  │  🆕 Volatility limit check                                  │   │
│  │  🆕 VaR limit check                                         │   │
│  │  🆕 Correlation check                                       │   │
│  └─────────────────────────┬───────────────────────────────────┘   │
│                            ↓                                        │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              POSITION SIZING (Mevcut + Regime-Conditioned)  │   │
│  │  ✅ Kelly Criterion (calibrated)                            │   │
│  │  ✅ Fractional Kelly (0.5x default)                         │   │
│  │  ✅ Volatility targeting                                    │   │
│  │  ✅ Cold-start policy                                       │   │
│  │  🆕 Regime-conditioned Kelly                                │   │
│  │  🆕 Risk parity option                                      │   │
│  │  🆕 Max position from VaR constraint                        │   │
│  └─────────────────────────┬───────────────────────────────────┘   │
│                            ↓                                        │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              PORTFOLIO RISK (Mevcut + VaR/CVaR)             │   │
│  │  ✅ Ledoit-Wolf covariance                                  │   │
│  │  ✅ Portfolio volatility                                    │   │
│  │  ✅ Concentration risk (HHI)                                │   │
│  │  ✅ Sector concentration                                    │   │
│  │  ✅ Diversification ratio                                   │   │
│  │  🆕 VaR (95%, 99%) — Parametrik + Tarihsel                 │   │
│  │  🆕 CVaR (95%, 99%) — Expected Shortfall                   │   │
│  │  🆕 Component VaR                                           │   │
│  │  🆕 Marginal VaR                                            │   │
│  │  🆕 Rolling correlation risk                                │   │
│  └─────────────────────────┬───────────────────────────────────┘   │
│                            ↓                                        │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              DYNAMIC RISK LIMITS 🆕                         │   │
│  │  - Volatilite artınca limitler sıkılaşır                    │   │
│  │  - Rejim değişince limitler ayarlanır                       │   │
│  │  - Drawdown olunca limitler düşürülür                       │   │
│  │  - VIX bazlı global risk algısı                             │   │
│  └─────────────────────────┬───────────────────────────────────┘   │
│                            ↓                                        │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              STRESS TEST (Gelişmiş)                         │   │
│  │  ✅ Historical scenarios (2008, 2020, 2022)                 │   │
│  │  ✅ Hypothetical scenarios                                  │   │
│  │  🆕 Monte Carlo simulation (10,000+ paths)                  │   │
│  │  🆕 Breaking point analysis                                 │   │
│  │  🆕 Portfolio impact scoring                                │   │
│  │  🆕 Risk gate'e otomatik besleme                            │   │
│  └─────────────────────────┬───────────────────────────────────┘   │
│                            ↓                                        │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              DRAWDOWN RESPONSE 🆕                           │   │
│  │  - DD > 5%  → Pozisyon boyutunu azalt (%50)                 │   │
│  │  - DD > 10% → Yeni pozisyon durdur                          │   │
│  │  - DD > 15% → Pozisyon kapat                                │   │
│  │  - DD > 20% → Sistem durdur                                 │   │
│  └─────────────────────────┬───────────────────────────────────┘   │
│                            ↓                                        │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              CALIBRATION (Mevcut + Brier Score)             │   │
│  │  ✅ Platt scaling                                           │   │
│  │  ✅ Online learning (her 50 trade'te refit)                 │   │
│  │  🆕 Brier score tracking                                    │   │
│  │  🆕 Calibration curve monitoring                            │   │
│  │  🆕 Isotonic regression option                              │   │
│  └─────────────────────────┬───────────────────────────────────┘   │
│                            ↓                                        │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              TAIL RISK HEDGING 🆕                           │   │
│  │  - Protective put strategy                                  │   │
│  │  - Tail risk hedge (VIX-based)                              │   │
│  │  - Crisis alpha detection                                   │   │
│  └─────────────────────────┬───────────────────────────────────┘   │
│                            ↓                                        │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              MONITORING & ALERTS (Gelişmiş)                 │   │
│  │  ✅ Risk check results (Redis)                              │   │
│  │  🆕 Real-time risk metrics API                              │   │
│  │  🆕 Alert rules (özelleştirilebilir)                        │   │
│  │  🆕 Risk dashboard endpoint'leri                            │   │
│  │  🆕 Performance attribution                                 │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 Nihai Dosya Yapısı

```
services/risk/
├── __init__.py
├── main.py                    # RiskEngine — mevcut, genişletilecek
├── position_sizing.py         # PositionSizer — mevcut, regime-conditioned ekle
├── enhanced_risk.py           # Mevcut, VaR/CVaR ekle
├── covariance.py              # Mevcut, iyi
├── calibration.py             # Mevcut, Brier score ekle
├── reconciliation.py          # Mevcut, iyi
├── var_cvar.py                # 🆕 VaR/CVaR modülü
├── dynamic_limits.py          # 🆕 Dinamik risk limitleri
├── stress_test.py             # 🆕 Stres test motoru
├── drawdown_response.py       # 🆕 Drawdown otomatik yanıt
├── tail_hedge.py              # 🆕 Tail risk hedging
├── risk_parity.py             # 🆕 Risk parity position sizing
├── monitoring.py              # 🆕 Risk monitoring + alerting
└── dashboard_api.py           # 🆕 Risk dashboard API endpoints
```

---

## 4. Genel Mimari Tasarım

### 4.1 Modül Bağımlılıkları

```
                    ┌──────────────┐
                    │  risk_gate   │ (services/core/)
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ↓            ↓            ↓
     ┌────────────┐ ┌────────────┐ ┌────────────┐
     │ var_cvar   │ │  dynamic   │ │  stress    │
     │            │ │  _limits   │ │  _test     │
     └─────┬──────┘ └─────┬──────┘ └─────┬──────┘
           │              │              │
           └──────────────┼──────────────┘
                          ↓
                 ┌────────────────┐
                 │  enhanced_risk │ (mevcut, genişletilecek)
                 └────────┬───────┘
                          │
              ┌───────────┼───────────┐
              ↓           ↓           ↓
     ┌────────────┐ ┌────────────┐ ┌────────────┐
     │ position   │ │ drawdown   │ │ tail       │
     │ _sizing    │ │ _response  │ │ _hedge     │
     └────────────┘ └────────────┘ └────────────┘
```

### 4.2 Event-Driven Entegrasyon

```python
# Risk metrikleri hesaplandığında event publish
event_bus.publish("risk.metrics.updated", CanonicalEvent(
    event_type="risk.metrics.updated",
    payload={
        "var_95": var_95,
        "cvar_95": cvar_95,
        "portfolio_vol": portfolio_vol,
        "drawdown": current_drawdown,
        "dynamic_limits": dynamic_limits,
    }
))

# Drawdown threshold aşıldığında alert
event_bus.publish("risk.alert", CanonicalEvent(
    event_type="risk.alert",
    payload={
        "alert_type": "DRAWDOWN_THRESHOLD",
        "severity": "CRITICAL",
        "drawdown_pct": current_drawdown,
        "action": "STOP_NEW_POSITIONS",
    }
))
```

---

## 5. Faz Planı

### FAZ 1: VaR/CVaR Modülü (1-2 gün)

**Amaç:** Tail risk ölçümü — en kritik eksiklik.

#### 1.1 — VaR/CVaR Hesaplama
```
Dosya: services/risk/var_cvar.py
```
- [ ] `VaRCalculator` sınıfı
  - [ ] `calculate_parametric_var()` — Normal dağılım varsayımı
  - [ ] `calculate_historical_var()` — Dağılım varsayımı yok
  - [ ] `calculate_cvar()` — Expected Shortfall
  - [ ] `calculate_component_var()` — Pozisyon bazlı risk katkısı
  - [ ] `calculate_marginal_var()` — Yeni pozisyon risk etkisi
  - [ ] `calculate Monte Carlo VaR()` — Stokastik simülasyon

#### 1.2 — Risk Metriklerine Entegrasyon
- [ ] `enhanced_risk.py`'ye VaR/CVaR ekle
- [ ] `RiskMetrics` dataclass'ına var_95, cvar_99, component_var ekle
- [ ] Portfolio risk hesaplarken VaR/CVaR da hesapla

#### 1.3 — Risk Gate'e VaR Limiti
- [ ] `risk_gate.py`'ye VaR limiti check ekle
- [ ] VaR > limit → BLOCK

**Teslimat:** `pytest tests/test_risk_faz1.py` — VaR/CVaR hesaplama doğruluğu

---

### FAZ 2: Regime-Conditioned Kelly (1 gün)

**Amaç:** Rejime göre pozisyon boyutu ayarlama.

#### 2.1 — Regime-Conditioned Kelly
```
Dosya: services/risk/position_sizing.py (değişiklik)
```
- [ ] `REGIME_KELLY_FRACTIONS` sözlüğü ekle
  - BULL: 0.6, BEAR: 0.3, CRISIS: 0.15, SIDEWAYS: 0.4
- [ ] `_fractional_kelly()`'ye regime parametresi ekle
- [ ] `calculate_position_sizes()`'de regime'i kullan

#### 2.2 — Bayesian Changepoint Detection (Opsiyonel)
- [ ] Rejim değişimini erken tespit
- [ ] Regime engine'den gelen rejim bilgisini kullan

**Teslimat:** `pytest tests/test_risk_faz2.py` — farklı rejimlerde farklı Kelly fraction

---

### FAZ 3: Dynamic Risk Limits (1-2 gün)

**Amaç:** Volatilite ve rejime göre dinamik limitler.

#### 3.1 — Dynamic Risk Limits
```
Dosya: services/risk/dynamic_limits.py
```
- [ ] `DynamicRiskLimits` sınıfı
  - [ ] `get_limits()` — volatilite, rejim, drawdown'a göre limitler
  - [ ] Volatilite bazlı: yüksek vol → sıkı limit
  - [ ] Rejim bazlı: CRISIS → %50 limit azaltma
  - [ ] Drawdown bazlı: DD > 10% → limit düşür

#### 3.2 — Risk Gate Entegrasyonu
- [ ] `risk_gate.py`'de sabit limitler yerine dynamic limits kullan
- [ ] Her risk check'te güncel volatilite/rejim bilgisi al

**Teslimat:** `pytest tests/test_risk_faz3.py` — dinamik limit değişimi doğruluğu

---

### FAZ 4: Stress Test Enhancement (1-2 gün)

**Amaç:** Kapsamlı stres testi ve risk gate entegrasyonu.

#### 4.1 — Stress Test Motoru
```
Dosya: services/risk/stress_test.py
```
- [ ] `StressTestEngine` sınıfı
  - [ ] Historical scenarios: 2008, 2020, 2022
  - [ ] Hypothetical scenarios: USDTRY +10%, BIST -15%, TCMB +500bp
  - [ ] Monte Carlo simulation: 10,000+ paths
  - [ ] Breaking point analysis: portföy ne kadar kaybeder?
  - [ ] Portfolio impact scoring

#### 4.2 — Risk Gate Entegrasyonu
- [ ] Stres testi sonuçlarını risk gate'e besle
- [ ] Worst scenario > threshold → BLOCK

**Teslimat:** `pytest tests/test_risk_faz4.py` — stres testi senaryo doğruluğu

---

### FAZ 5: Drawdown Response & Tail Hedge (1-2 gün)

**Amaç:** Otomatik drawdown yönetimi ve tail risk koruması.

#### 5.1 — Drawdown Response
```
Dosya: services/risk/drawdown_response.py
```
- [ ] `DrawdownResponse` sınıfı
  - [ ] DD > 5%: pozisyon boyutunu %50 azalt
  - [ ] DD > 10%: yeni pozisyon durdur
  - [ ] DD > 15%: pozisyon kapat
  - [ ] DD > 20%: sistem durdur
  - [ ] Otomatik tetikleme mekanizması

#### 5.2 — Tail Risk Hedging
```
Dosya: services/risk/tail_hedge.py
```
- [ ] `TailRiskHedger` sınıfı
  - [ ] Protective put strategy
  - [ ] VIX-based hedge ratio
  - [ ] Crisis alpha detection
  - [ ] Hedge maliyeti hesaplama

**Teslimat:** `pytest tests/test_risk_faz5.py` — drawdown response tetikleme

---

### FAZ 6: Monitoring, Alerting & Dashboard (1-2 gün)

**Amaç:** Gerçek zamanlı risk izleme ve uyarı.

#### 6.1 — Risk Monitoring
```
Dosya: services/risk/monitoring.py
```
- [ ] `RiskMonitor` sınıfı
  - [ ] Real-time risk metrics toplama
  - [ ] Alert rules engine (özelleştirilebilir)
  - [ ] Alert severity: INFO, WARN, BLOCK, CRITICAL
  - [ ] Alert channels: event bus, log, dashboard

#### 6.2 — Dashboard API
```
Dosya: services/risk/dashboard_api.py
```
- [ ] `GET /api/risk/metrics` — güncel risk metrikleri
- [ ] `GET /api/risk/var-cvar` — VaR/CVaR değerleri
- [ ] `GET /api/risk/limits` — dinamik limitler
- [ ] `GET /api/risk/stress-test` — son stres testi sonuçları
- [ ] `GET /api/risk/drawdown` — drawdown durumu
- [ ] `GET /api/risk/alerts` — son alert'ler

#### 6.3 — Calibration Enhancement
- [ ] Brier score tracking
- [ ] Calibration curve monitoring
- [ ] Isotonic regression option

**Teslimat:** `pytest tests/test_risk_faz6.py` — API endpoint'leri çalışır

---

### FAZ 7: Risk Parity & Entegrasyon Testi (1 gün)

**Amaç:** Risk parity position sizing ve tam entegrasyon testi.

#### 7.1 — Risk Parity
```
Dosya: services/risk/risk_parity.py
```
- [ ] `RiskParityOptimizer` sınıfı
  - [ ] Her pozisyonun eşit risk katkısı
  - [ ] Iterative optimization (scipy)
  - [ ] Transaction cost-aware

#### 7.2 — Tam Entegrasyon Testi
- [ ] Pipeline: features → regime → risk → decision
- [ ] VaR/CVaR → dynamic limits → position sizing → risk gate
- [ ] Stres testi → risk gate entegrasyonu
- [ ] Drawdown response tetikleme

**Teslimat:** `pytest tests/test_risk_faz7.py` — end-to-end risk pipeline

---

## 6. Test Stratejisi

### Test Piramidi

```
         ┌─────────────┐
         │  E2E Tests   │  ← 5 test (tam risk pipeline)
         ├─────────────┤
         │ Integration  │  ← 12 test (modül arası)
         ├─────────────┤
         │   Unit Tests │  ← 40+ test (her fonksiyon)
         └─────────────┘
```

### Her Faz İçin Test Kriterleri

| Faz | Test Dosyası | Min Test Sayısı | Kritik Test |
|-----|-------------|-----------------|-------------|
| 1 | test_risk_faz1.py | 10 | VaR/CVaR hesaplama doğruluğu |
| 2 | test_risk_faz2.py | 6 | Regime-conditioned Kelly fraction |
| 3 | test_risk_faz3.py | 8 | Dynamic limits değişimi |
| 4 | test_risk_faz4.py | 8 | Stress test senaryo doğruluğu |
| 5 | test_risk_faz5.py | 8 | Drawdown response tetikleme |
| 6 | test_risk_faz6.py | 6 | API endpoint'leri |
| 7 | test_risk_faz7.py | 10 | End-to-end pipeline |

---

## 7. Risk ve Azaltma

| Risk | Olasılık | Etki | Azaltma |
|------|----------|------|---------|
| VaR normal dağılım varsayımı | Yüksek | Orta | Tarihsel VaR + Monte Carlo VaR de kullan |
| Regime detection gecikmesi | Orta | Yüksek | Bayesian changepoint + multiple indicators |
| Stres testi senaryoları yetersiz | Orta | Yüksek | Custom scenario ekleme + Monte Carlo |
| Drawdown response çok agresif | Düşük | Yüksek | Eşikler ayarlanabilir, manual override |
| Dynamic limits çok sık değişiyor | Orta | Orta | Smoothing + minimum change threshold |
| Tail hedge maliyetli | Yüksek | Orta | Fractional hedge + maliyet limiti |

---

## 📊 Zaman Özeti

| Faz | Süre | Bağımlılık | Teslimat |
|-----|------|------------|----------|
| **Faz 1** | 1-2 gün | Yok | VaR/CVaR modülü |
| **Faz 2** | 1 gün | Faz 1 | Regime-conditioned Kelly |
| **Faz 3** | 1-2 gün | Faz 1 | Dynamic risk limits |
| **Faz 4** | 1-2 gün | Faz 1 | Stress test enhancement |
| **Faz 5** | 1-2 gün | Faz 3 | Drawdown response + tail hedge |
| **Faz 6** | 1-2 gün | Faz 1-5 | Monitoring + dashboard |
| **Faz 7** | 1 gün | Faz 1-6 | Risk parity + entegrasyon testi |
| **TOPLAM** | **7-12 gün** | | |

**Not:** Faz 1-4 paralel geliştirilebilir (bağımsız). Bu durumda toplam süre **5-8 gün**'e düşer.

---

## 🔑 Kritik Tasarım Kararları

1. **Fail-closed**: Risk limitleri yüklenemezse tüm işlemler BLOCKED (mevcut)
2. **Multi-metric risk**: VaR + CVaR + Drawdown birlikte kullanılmalı
3. **Regime-conditioned**: Farklı rejimlerde farklı risk limitleri ve Kelly fraction
4. **Dynamic limits**: Sabit limitler yerine volatilite/rejim bazlı dinamik limitler
5. **Stress test → Risk gate**: Stres testi sonuçları otomatik risk kararlarına yansıtılmalı
6. **Drawdown response otomatik**: Manuel müdahale gerektirmeden otomatik aksiyon
7. **Fractional hedge**: Tail risk hedge maliyetli, fractional approach daha pragmatic
8. **Event-driven**: Tüm risk metrikleri event bus ile publish edilmeli

---

## 📚 Referanslar

1. ScienceDirect — Integrated Risk Management Framework (2026)
2. arXiv 2605.19337 — Agentic Trading Meta-Analiz (2026)
3. SSRN — Regime-Conditioned Kelly (2026)
4. CFA Institute — Measuring and Managing Market Risk (2026)
5. Nature — ML-Based Dynamic Risk Allocation (2025)
6. Quantt — Kelly Criterion Best Practices (2026)
7. ScienceDirect — RMSE-Triggered Rebalancing (2026)
8. Resonanz Capital — Tail-Risk Hedging (2025)
