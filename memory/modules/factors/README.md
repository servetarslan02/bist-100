# Factors Nihai Sistem

**Modül sayısı:** 10 | **Test sayısı:** 43 | **Kaynak:** Fama-French, Piotroski, Beneish, Altman

## Modüller

| # | Modül | Fonksiyon/Sınıf | Açıklama |
|---|-------|-----------------|----------|
| 1 | `piotroski.py` | `calculate_f_score()` | 9 kriter, ağırlıklı, sub-scores |
| 2 | `beneish.py` | `calculate_m_score()` | 8 değişken, gerçek veri + raw index |
| 3 | `altman.py` | `calculate_z_score()` | Türkiye düzeltmeli (enflasyon, kur, sektör) |
| 4 | `fama_french.py` | `calculate_factor_scores()` | 8 faktör, cross-sectional z-score |
| 5 | `bist_anomalies.py` | `calculate_bist_anomalies()` | 8 anomaly: temettü, likidite, kur, enflasyon, faiz, momentum, KAP, yabancı |
| 6 | `ranking.py` | `rank_stocks()` | Risk-adjusted, sector-neutral, regime-based |
| 7 | `performance.py` | `track_factor_performance()` | 15+ metrik (Sharpe, Sortino, Calmar, alpha, beta, IR, Treynor) |
| 8 | `factor_correlation.py` | `calculate_factor_correlation()` | Korelasyon matrisi, VIF, diversifikasyon skoru |
| 9 | `factor_rotation.py` | `detect_regime()` | Rejim tespiti, rotasyon sinyali, dynamic weighting |
| 10 | `factor_time_series.py` | `analyze_factor_trend()` | Trend, momentum, mevsimsellik |

## Faktörler

| Faktör | Metrikler | Ağırlık |
|--------|-----------|---------|
| Value | P/B, P/E, EV/EBITDA, FCF Yield | 15% |
| Momentum | 1M, 3M, 6M, 12M | 20% |
| Quality | ROE, ROIC, Gross Margin, Operating Margin | 20% |
| Size | Market Cap | 10% |
| Low Vol | Volatility, Beta | 10% |
| Dividend | Yield, Payout Ratio | 10% |
| Leverage | D/E, Net Debt/EBITDA | 10% |
| BIST-Specific | FX Sensitivity, Inflation Beta, Foreign Ownership | 5% |

## Rejime Göre Ağırlıklar

| Rejim | Preferred | Avoid |
|-------|-----------|-------|
| BULL | Momentum (30%), Quality (15%) | Low Vol (5%), Dividend |
| BEAR | Quality (30%), Low Vol (20%) | Momentum (5%), Size |
| SIDEWAYS | Value (25%), Dividend (20%) | Momentum |
| HIGH_VOL | Low Vol (25%), Quality (25%) | Momentum, Size |

## Backward Compatibility

Eski API (`calculate_f_score`, `calculate_m_score`, `calculate_z_score`) artık dict döndürür.
Basitleştirilmiş fonksiyonlar mevcut: `calculate_f_score_simple`, `calculate_m_score_simple`, `calculate_z_score_simple`.

## Kaynaklar

- Fama-French Five-Factor (Borsa Istanbul, ResearchGate 2023)
- Piotroski F-Score (BIST, İşler Dergisi 2025)
- Beneish M-Score (BIST, SAGE 2025)
- Robeco Next-Gen Quant (2024)
- CFA Institute Factor Investing (2025)
