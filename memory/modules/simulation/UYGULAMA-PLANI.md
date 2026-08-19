# 🚀 Simulation System Nihai Mimari — Uygulama Planı

**Tarih:** 2026-08-20
**Kaynaklar:** arXiv Agentic Trading (2026), mbrenndoerfer Market Microstructure (2026), Springer Data-Driven Monte Carlo (2026), MDPI Regime-Dependent CVaR (2026), LinkedIn Jump-Diffusion (2025)

---

## 1. Araştırma Bulguları

### 1.1 Execution Simulator — En İyi Uygulama

**Temel prensip:** Simülasyon gerçek broker'a ne kadar yakınsa, backtest sonuçları o kadar güvenilir.

| Bileşen | En İyi Uygulama | Kaynak |
|---------|-----------------|--------|
| Slippage | Bid/ask spread + square root impact | mbrenndoerfer (2026) |
| Market Impact | σ × √(Q/V) × η | mbrenndoerfer (2026) |
| Regime Impact | Rejime göre slippage çarpanı | arXiv (2026) |
| Transaction Cost | Broker + BIST + MKK + BSMV + min | BIST kuralları |
| Partial Fill | Günlük hacim limiti + likidite profili | Endüstri standardı |

### 1.2 Monte Carlo — En İyi Uygulama

| Model | Özellik | Kaynak |
|-------|---------|--------|
| GBM | Basit geometric Brownian motion | Temel |
| Fat Tails | Student-t dağılımı (df=5) | MDPI (2026) |
| GARCH(1,1) | Volatility clustering | Springer (2026) |
| Jump-Diffusion | Ani fiyat sıçramaları (Poisson) | LinkedIn (2025) |
| Correlated Paths | Cholesky decomposition | Endüstri standardı |
| Regime-Conditioned | Rejime göre parametre | arXiv (2026) |

### 1.3 Stress Test — En İyi Uygulama

8+ senaryo: Market Crash, Currency Crisis, Rate Shock, Sector Rotation, Black Swan, Liquidity Crisis, Stagflation, Global Risk-Off, Company-specific.

---

## 2. Mevcut Sistem (2 dosya, 601 satır)

| Modül | Satır | Ne Yapıyor | Durum |
|-------|-------|------------|-------|
| `execution_simulator.py` | 258 | Order lifecycle, slippage, commission, partial fill | ✅ İyi |
| `main.py` | 343 | Monte Carlo (GARCH, fat tails), scenario, stress test | ✅ İyi |

### Eksikler:
1. Slippage model basit (linear volume impact)
2. Jump-diffusion Monte Carlo yok
3. Correlated paths yok
4. Regime-aware slippage yok
5. Stress test sadece 5 senaryo
6. Scenario analysis beta=1 varsayımı

---

## 3. Faz Planı

### FAZ 1: Enhanced Execution Simulator (1 gün)
- Square root market impact
- Regime-aware slippage
- Bid/ask spread bazlı slippage

### FAZ 2: Jump-Diffusion Monte Carlo (1 gün)
- Merton jump-diffusion model
- Poisson jump process
- Event shock integration

### FAZ 3: Correlated Monte Carlo (1 gün)
- Cholesky decomposition
- Portföy bazlı Monte Carlo
- Multi-asset simulation

### FAZ 4: Enhanced Stress Test (1 gün)
- 8+ stres senaryosu
- Company-specific stress
- Breaking point analysis

### FAZ 5: Scenario Analysis Enhancement (1 gün)
- Beta bazlı etki
- Sektör bazlı etki
- Custom senaryo desteği

---

## 📊 Zaman Özeti: 5 gün
