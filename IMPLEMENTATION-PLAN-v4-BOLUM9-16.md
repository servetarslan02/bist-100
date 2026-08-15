# Uygulama Planı v4 — Bölüm 9-16

## Durum Özeti

| Bölüm | Konu | Mevcut Kod | Durum |
|-------|------|-----------|-------|
| 9 | Monte Carlo + Senaryo | `intelligence/monte_carlo.py`, `intelligence/scenario.py` | ✅ |
| 10 | Risk Motoru | `risk/enhanced_risk.py`, `risk/main.py`, `risk/position_sizing.py` | ✅ |
| 11 | Portföy Optimizasyonu | `risk/enhanced_risk.py`, `portfolio/main.py`, `portfolio/enhancements.py` | ✅ |
| 12 | Sinyal Füzyonu | `intelligence/signal_fusion.py`, `core/decision_engine.py` | ✅ |
| 13 | Backtest | `backtest/engine.py`, `backtest/enhanced_walk_forward.py` | ✅ |
| 14 | Paper Trading | `simulation/execution_simulator.py`, `simulation/main.py` | ✅ |
| 15 | Sonuçlardan Öğrenme | `learning/integrated_learning.py`, `learning/outcome_tracker.py` | ✅ |
| 16 | AI Agent Orkestrasyonu | `agents/agent_system.py` | ✅ |

**Sonuç:** 8 bölümün TAMAMI mevcut kodda implemente edilmiş.

---

## AŞAMA 1: Kod Doğrulama (Bölüm 9-16)

### Her modül için kontrol listesi:

#### 9. Monte Carlo + Senaryo

| # | Kontrol | Dosya | Test |
|---|---------|-------|------|
| 9.1 | MonteCarloEngine sınıfı var mı? | `intelligence/monte_carlo.py` | ✅ |
| 9.2 | simulate_price_paths() çalışıyor mu? | `intelligence/monte_carlo.py` | ❓ Test et |
| 9.3 | P10, P50, P90, VaR, CVaR dönüyor mu? | `intelligence/monte_carlo.py` | ❓ Test et |
| 9.4 | ScenarioEngine sınıfı var mı? | `intelligence/scenario.py` | ✅ |
| 9.5 | run_scenario() çalışıyor mu? | `intelligence/scenario.py` | ❓ Test et |
| 9.6 | PREDEFINED_SCENARIOS tanımlı mı? | `intelligence/scenario.py` | ✅ |
| 9.7 | USDTRY_10_PCT senaryosu var mı? | `intelligence/scenario.py` | ❓ Test et |

**Test senaryosu:**
```python
result = monte_carlo_engine.simulate_price_paths(
    "THYAO", 305.25, 0.15, 0.25, 20, 10000)
assert result.p10 < result.p50 < result.p90
assert result.var_95 < 0
assert result.cvar < result.var_95
```

---

#### 10. Risk Motoru

| # | Kontrol | Dosya | Test |
|---|---------|-------|------|
| 10.1 | LedoitWolfCovariance sınıfı var mı? | `risk/enhanced_risk.py` | ✅ |
| 10.2 | estimate() çalışıyor mu? | `risk/enhanced_risk.py` | ❓ Test et |
| 10.3 | PositionSizer sınıfı var mı? | `risk/enhanced_risk.py` | ✅ |
| 10.4 | kelly_criterion() çalışıyor mu? | `risk/enhanced_risk.py` | ❓ Test et |
| 10.5 | compute_position_size() çalışıyor mu? | `risk/enhanced_risk.py` | ❓ Test et |
| 10.6 | VolatilityTargeter sınıfı var mı? | `risk/enhanced_risk.py` | ✅ |
| 10.7 | compute_leverage() çalışıyor mu? | `risk/enhanced_risk.py` | ❓ Test et |
| 10.8 | Risk Metrics hesaplanıyor mu? | `risk/main.py` | ❓ Test et |
| 10.9 | VaR/CVaR hesaplanıyor mu? | `risk/main.py` | ❓ Test et |
| 10.10 | Max Drawdown hesaplanıyor mu? | `risk/main.py` | ❓ Test et |

**Test senaryosu:**
```python
kelly = position_sizer.kelly_criterion(0.6, 2.0, 1.0, 0.5)
assert kelly == 0.20

leverage = volatility_targeter.compute_leverage(0.10, 0.20)
assert leverage == 2.0
```

---

#### 11. Portföy Optimizasyonu

| # | Kontrol | Dosya | Test |
|---|---------|-------|------|
| 11.1 | ConcentrationRisk sınıfı var mı? | `risk/enhanced_risk.py` | ✅ |
| 11.2 | compute_hhi() çalışıyor mu? | `risk/enhanced_risk.py` | ❓ Test et |
| 11.3 | compute_sector_concentration() var mı? | `risk/enhanced_risk.py` | ❓ Test et |
| 11.4 | RebalanceEngine sınıfı var mı? | `risk/enhanced_risk.py` | ✅ |
| 11.5 | compute_rebalance() çalışıyor mu? | `risk/enhanced_risk.py` | ❓ Test et |
| 11.6 | Portfolio optimization var mı? | `portfolio/main.py` | ❓ Test et |
| 11.7 | FX impact hesaplanıyor mu? | `portfolio/enhancements.py` | ❓ Test et |

**Test senaryosu:**
```python
hhi = concentration_risk.compute_hhi({"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})
assert hhi == 0.25

orders = rebalance_engine.compute_rebalance(
    {"A": 0.5, "B": 0.3, "C": 0.2},
    {"A": 0.3, "B": 0.4, "C": 0.3},
    100000)
assert len(orders) > 0
```

---

#### 12. Sinyal Füzyonu

| # | Kontrol | Dosya | Test |
|---|---------|-------|------|
| 12.1 | SignalFusionEngine sınıfı var mı? | `intelligence/signal_fusion.py` | ✅ |
| 12.2 | fuse_signals() çalışıyor mu? | `intelligence/signal_fusion.py` | ❓ Test et |
| 12.3 | Çelişki tespiti çalışıyor mu? | `intelligence/signal_fusion.py` | ❓ Test et |
| 12.4 | has_conflict dönüyor mu? | `intelligence/signal_fusion.py` | ❓ Test et |
| 12.5 | DecisionEngine sınıfı var mı? | `core/decision_engine.py` | ✅ |
| 12.6 | Karar seviyeleri doğru mu? | `core/decision_engine.py` | ❓ Test et |

**Test senaryosu:**
```python
signals = {
    "technical": {"direction": "LONG", "score": 70},
    "fundamental": {"direction": "LONG", "score": 65},
    "news": {"direction": "SHORT", "score": 30},
}
result = signal_fusion_engine.fuse_signals("THYAO", signals, "BULL")
assert result.has_conflict == True
assert result.fused_direction == "LONG"
```

---

#### 13. Backtest

| # | Kontrol | Dosya | Test |
|---|---------|-------|------|
| 13.1 | BacktestEngine sınıfı var mı? | `backtest/engine.py` | ✅ |
| 13.2 | PurgeEmbargoWalkForward sınıfı var mı? | `backtest/enhanced_walk_forward.py` | ✅ |
| 13.3 | Walk-forward çalışıyor mu? | `backtest/enhanced_walk_forward.py` | ❓ Test et |
| 13.4 | _deflated_sharpe() çalışıyor mu? | `backtest/enhanced_walk_forward.py` | ❓ Test et |
| 13.5 | purge/embargo uygulanıyor mu? | `backtest/enhanced_walk_forward.py` | ❓ Test et |
| 13.6 | BIST komisyon modeli var mı? | `backtest/enhanced_walk_forward.py` | ❓ Test et |

**Test senaryosu:**
```python
engine = PurgeEmbargoWalkForward(
    train_days=252, test_days=63, step_days=21,
    purge_days=5, embargo_days=5)
result = engine.run(predictions, actuals, tickers, dates)
assert result.total_folds > 0
```

---

#### 14. Paper Trading

| # | Kontrol | Dosya | Test |
|---|---------|-------|------|
| 14.1 | ExecutionSimulator sınıfı var mı? | `simulation/execution_simulator.py` | ✅ |
| 14.2 | execute_order() çalışıyor mu? | `simulation/execution_simulator.py` | ❓ Test et |
| 14.3 | Slippage hesaplanıyor mu? | `simulation/execution_simulator.py` | ❓ Test et |
| 14.4 | Komisyon hesaplanıyor mu? | `simulation/execution_simulator.py` | ❓ Test et |
| 14.5 | Partial fill desteği var mı? | `simulation/execution_simulator.py` | ❓ Test et |
| 14.6 | Portfolio ledger var mı? | `simulation/main.py` | ❓ Test et |

**Test senaryosu:**
```python
order = Order(order_id="ORD-001", ticker="THYAO",
    side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=1000)
result = execution_simulator.execute_order(
    order, 305.25, 500000, 0.25, 0.1)
assert result.status == "FILLED"
assert result.avg_fill_price > 305.25  # slippage
```

---

#### 15. Sonuçlardan Öğrenme

| # | Kontrol | Dosya | Test |
|---|---------|-------|------|
| 15.1 | record_decision() çalışıyor mu? | `learning/integrated_learning.py` | ❓ Test et |
| 15.2 | record_outcome() çalışıyor mu? | `learning/integrated_learning.py` | ❓ Test et |
| 15.3 | get_insights() çalışıyor mu? | `learning/integrated_learning.py` | ❓ Test et |
| 15.4 | Accuracy hesaplanıyor mu? | `learning/integrated_learning.py` | ❓ Test et |
| 15.5 | Calibration error hesaplanıyor mu? | `learning/integrated_learning.py` | ❓ Test et |
| 15.6 | Drift detection var mı? | `learning/integrated_learning.py` | ❓ Test et |
| 15.7 | Outcome tracker var mı? | `learning/outcome_tracker.py` | ❓ Test et |

**Test senaryosu:**
```python
integrated_learning.record_decision("THYAO",
    {"direction": "LONG", "action": "BUY", "composite_score": 70},
    {"momentum_20d": 5, "rsi_14": 60, "price": 305.25}, "BULL")

# 5 gün sonra
integrated_learning.record_outcome("THYAO", 320.0, 305.25, 5, "auto")

insights = integrated_learning.get_insights()
assert insights.overall_accuracy >= 0
```

---

#### 16. AI Agent Orkestrasyonu

| # | Kontrol | Dosya | Test |
|---|---------|-------|------|
| 16.1 | AgentOrchestrator sınıfı var mı? | `agents/agent_system.py` | ✅ |
| 16.2 | run_research_pipeline() var mı? | `agents/agent_system.py` | ✅ |
| 16.3 | AgentToolRegistry var mı? | `agents/agent_system.py` | ✅ |
| 16.4 | can_access() çalışıyor mu? | `agents/agent_system.py` | ❓ Test et |
| 16.5 | AIOutputValidator var mı? | `agents/agent_system.py` | ✅ |
| 16.6 | validate() çalışıyor mu? | `agents/agent_system.py` | ❓ Test et |
| 16.7 | AIFallback var mı? | `agents/agent_system.py` | ✅ |
| 16.8 | rule_based_analysis() çalışıyor mu? | `agents/agent_system.py` | ❓ Test et |
| 16.9 | Agent rolleri tanımlı mı? | `agents/agent_system.py` | ❓ Test et |

**Test senaryosu:**
```python
assert AgentToolRegistry.can_access(AgentRole.RESEARCH, "read_market_data") == True
assert AgentToolRegistry.can_access(AgentRole.NEWS, "calculate_risk") == False

validation = AIOutputValidator.validate(
    '{"direction": "LONG", "confidence": 75}')
assert validation.valid == True
```

---

## AŞAMA 2: Test Yazma (Bölüm 9-16)

### Test dosyaları:

```
tests/test_intelligence/
├── test_monte_carlo.py        # Bölüm 9
├── test_scenario.py           # Bölüm 9
├── test_signal_fusion.py      # Bölüm 12

tests/test_risk/
├── test_enhanced_risk.py      # Bölüm 10-11
├── test_position_sizing.py    # Bölüm 10
├── test_concentration.py      # Bölüm 11
├── test_rebalance.py          # Bölüm 11

tests/test_backtest/
├── test_engine.py             # Bölüm 13
├── test_walk_forward.py       # Bölüm 13

tests/test_simulation/
├── test_execution_simulator.py # Bölüm 14

tests/test_learning/
├── test_integrated_learning.py # Bölüm 15
├── test_outcome_tracker.py    # Bölüm 15

tests/test_agents/
├── test_agent_system.py       # Bölüm 16
├── test_tool_registry.py      # Bölüm 16
```

---

## AŞAMA 3: Entegrasyon Testleri (Bölüm 9-16)

### Zincir testleri:

| # | Zincir | Adımlar |
|---|--------|---------|
| E1 | Forecast → Monte Carlo → Risk | Tahmin → simülasyon → risk skoru |
| E2 | Risk → Portfolio → Rebalance | Risk → pozisyon boyutu → rebalance |
| E3 | Signal Fusion → Decision → Execution | Sinyal → karar → emir |
| E4 | Backtest → Learning → Drift | Backtest → sonuç → drift tespiti |
| E5 | Agent → Pipeline → Synthesis | Agent → paralel çalıştırma → sentez |

---

## AŞAMA 4: Yeni Modül Gereksinimleri (Bölüm 9-16)

Bölüm 9-16 için **yeni modül gerekmiyor**. Tüm gereksinimler mevcut kodda var.

Ancak şu eklemeler gerekebilir:

| # | Ek | Gerekçe |
|---|-----|---------|
| 1 | BIST-specific risk fonksiyonları | Ülke riski, kur riski, siyasi risk (Bölüm 10'da dokümante edildi) |
| 2 | BIST komisyon modeli | Detaylı fee breakdown (Bölüm 13'te dokümante edildi) |
| 3 | Drift detection implementasyonu | Feature/prediction drift (Bölüm 15'te dokümante edildi) |

---

## Uygulama Sırası

```
GÜN 1: Aşama 1 (9-12 modül doğrulama)
GÜN 2: Aşama 1 (13-16 modül doğrulama)
GÜN 3: Aşama 2 (Test yazma — intelligence + risk)
GÜN 4: Aşama 2 (Test yazma — backtest + learning + agents)
GÜN 5: Aşama 3 (Entegrasyon testleri)
GÜN 6: Aşama 4 (BIST-specific eklemeler)
```

---

## Başarı Kriterleri

- [ ] 8 bölümdeki tüm kod örnekleri çalışıyor
- [ ] Monte Carlo: P10 < P50 < P90, VaR < 0
- [ ] Kelly: 0.6 win rate → 0.20 kelly
- [ ] Signal Fusion: çelişki tespiti çalışıyor
- [ ] Walk-Forward: purge/embargo uygulanıyor
- [ ] Execution: slippage + komisyon hesaplanıyor
- [ ] Learning: prediction→outcome→accuracy döngüsü çalışıyor
- [ ] Agent: tool erişim kontrolü çalışıyor
- [ ] 15+ test dosyası yazıl
- [ ] 5 entegrasyon zinciri çalışıyor
