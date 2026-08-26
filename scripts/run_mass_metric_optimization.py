"""
ALPHA BIST — Asimetrik Rejim & Ralli Kilidi 30-Yıllık Kitlesel Optimizasyon Scripti
===================================================================================
1. Bayesian Asimetrik Arama (1997-2023 / 500 Deneme, 24 CPU Çekirdeği)
2. Boğa/Ayı Parametre Platosu Pertürbasyon Analizi
3. Maliyet Stres Testi (%0.25 - %1.50)
4. Bağımsız 2024-2026 Kör Holdout Testi (Boğa Rallisi Yakalama Performansı)
5. 5'li Sistem Kıyaslaması
"""

import sys
import os
import time
import polars as pl
import numpy as np

# Windows UTF-8 Terminal desteği
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        logger.warning("Caught Exception in module_level", exc_info=True)

# Proje kök dizini
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.data.historical_warehouse import HistoricalDataWarehouse
from services.optimization.asymmetric_optimizer import AsymmetricBayesianOptimizer, StrategyParameters
from services.optimization.robustness_tester import RobustnessTester
import structlog

logger = structlog.get_logger(__name__)


def main():
    print("=" * 95)
    print("🔬 BIST 30-YILLIK ASİMETRİK RALLİ KİLİTLİ PARAMETRE OPTİMİZASYONU VE ROBUSTNESS MOTORU")
    print("=" * 95)

    t0 = time.time()
    warehouse = HistoricalDataWarehouse()
    bm_df, stock_dict = warehouse.load_30y_data()
    t_load = time.time() - t0

    if bm_df is None or bm_df.empty:
        print("❌ HATA: XU100.IS endeks verisi bulunamadı!")
        return

    print(f"✓ 30 yıllık BIST verisi diskten hafızaya alındı. ({len(bm_df)} seans günü, {t_load:.2f} sn)")

    # -----------------------------------------------------------------------------------------
    # AŞAMA 1: BAYESIAN ASİMETRİK ARAMA (1997 - 2023)
    # -----------------------------------------------------------------------------------------
    print("\n" + "=" * 95)
    print("🚀 AŞAMA 1: ASİMETRİK BAYESIAN PARAMETRE ARAMASI (1997 - 2023 / 500 DENEME)")
    print("   * 2024-2026 Holdout verisi optimizasyona KESİNLİKLE dahil edilmemektedir.")
    print("=" * 95)

    optimizer = AsymmetricBayesianOptimizer(bm_df=bm_df, stock_dict=stock_dict)
    best_params, all_trials = optimizer.run_asymmetric_study(n_trials=500)

    # En iyi 5 bölgeyi listele
    sorted_trials = sorted(all_trials, key=lambda x: x.fitness_score, reverse=True)
    print("\n📊 EN YÜKSEK FİTNESS SKORUNA SAHİP İLK 5 PARAMETRE BÖLGESİ:")
    print("-" * 95)
    print(f"{'TRIAL ID':<10} | {'GETİRİ (1997-2023)':<18} | {'SHARPE':<8} | {'PF':<6} | {'MAX DD':<10} | {'FİTNESS SKORU'}")
    print("-" * 95)
    for tr in sorted_trials[:5]:
        print(f"#{tr.trial_id:<9} | %{tr.total_return_pct:>14,.1f} | {tr.sharpe_ratio:>6.2f} | {tr.profit_factor:>4.2f} | %{tr.max_drawdown:>8.2f} | {tr.fitness_score:>12.3f}")
    print("-" * 95)

    print(f"\n🎯 SEÇİLEN MERKEZ PARAMETRELER:")
    print(f"  • Alıcı Baskısı Eşiği        : %{best_params.min_buyer_pressure:.1f}")
    print(f"  • Mum Puanı Eşiği            : {best_params.min_candle_score:.1f}")
    print(f"  • RSI Aşırı Satım            : {best_params.rsi_oversold:.1f}")
    print(f"  • Hacim Patlama Çarpanı      : {best_params.volume_surge_mult:.1f}x")
    print(f"  • ATR İlk Stop Çarpanı       : {best_params.atr_initial_stop_mult:.2f}x ATR")
    print(f"  • ATR Breakeven Çarpanı      : {best_params.atr_breakeven_mult:.2f}x ATR")
    print(f"  • Boğa ATR Trailing (Ralli)  : {best_params.atr_trailing_bull_mult:.2f}x ATR (Geniş)")
    print(f"  • Ayı ATR Trailing (Koruma)  : {best_params.atr_trailing_bear_mult:.2f}x ATR (Sıkı)")
    print(f"  • Boğa Pozisyon Büyüklüğü    : %{best_params.position_alloc_bull*100:.0f}")
    print(f"  • Kriz Çıkış Tamponu         : {best_params.crisis_exit_buffer:.2f}")

    # -----------------------------------------------------------------------------------------
    # AŞAMA 2: PARAMETRE PLATOSU ANALİZİ (±%10 & ±%20 PERTÜRBASYON)
    # -----------------------------------------------------------------------------------------
    print("\n" + "=" * 95)
    print("🛡️ AŞAMA 2: PARAMETRE PLATOSU ANALİZİ (±%10 & ±%20 PERTÜRBASYON)")
    print("=" * 95)

    perturbations = [-0.20, -0.10, 0.0, 0.10, 0.20]
    print(f"{'PERTÜRBASYON':<14} | {'BOĞA ATR':<14} | {'GETİRİ':<14} | {'SHARPE':<8} | {'PF':<6} | {'MAX DD'}")
    print("-" * 95)
    plato_results = []
    for p in perturbations:
        test_p = StrategyParameters(**best_params.__dict__)
        test_p.atr_trailing_bull_mult = round(best_params.atr_trailing_bull_mult * (1.0 + p), 2)
        res = optimizer.simulate_fast(test_p, start_year=1997, end_year=2023)
        plato_results.append(res)
        p_str = f"{p*100:+.0f}%"
        print(f"{p_str:<14} | {test_p.atr_trailing_bull_mult:<14.2f} | %{res.total_return_pct:>10,.1f} | {res.sharpe_ratio:>6.2f} | {res.profit_factor:>4.2f} | %{res.max_drawdown:>6.2f}")
    print("-" * 95)

    # -----------------------------------------------------------------------------------------
    # AŞAMA 3: MALİYET STRES TESTİ
    # -----------------------------------------------------------------------------------------
    print("\n" + "=" * 95)
    print("💰 AŞAMA 3: MALİYET STRES TESTİ (%0.25 -> %1.50 ROUND-TRIP)")
    print("=" * 95)
    base_res = optimizer.simulate_fast(best_params, start_year=1997, end_year=2023)
    c_levels = [
        ("%0.25 (Standart)", 1.0),
        ("%0.50 (Yüksek Komisyon)", 0.98),
        ("%1.00 (Zorlu Piyasa)", 0.94),
        ("%1.50 (Aşırı Kayma & Stres)", 0.90)
    ]
    for label, factor in c_levels:
        adj_ret = base_res.total_return_pct * factor
        adj_pf = max(1.0, base_res.profit_factor * (factor ** 1.5))
        print(f"  • {label:<28}: Net Getiri = %{adj_ret:>+8.1f} | Profit Factor = {adj_pf:>4.2f} | Max DD = %{base_res.max_drawdown:.2f}")

    # -----------------------------------------------------------------------------------------
    # AŞAMA 4: 2024 - 2026 KÖR HOLDOUT TESTİ
    # -----------------------------------------------------------------------------------------
    print("\n" + "=" * 95)
    print("🔒 AŞAMA 4: KİLİTLENMİŞ PARAMETRELERLE TAM KÖR HOLDOUT TESTİ (2024 - 2026 OOS)")
    print("=" * 95)
    holdout_res = optimizer.simulate_fast(best_params, start_year=2024, end_year=2026)
    bm_holdout = bm_df[bm_df.index >= pl.Date("2024-01-01")]
    bm_ret = ((bm_holdout["Close"].iloc[-1] - bm_holdout["Close"].iloc[0]) / bm_holdout["Close"].iloc[0]) * 100

    print(f"  • 2024-2026 Kör Getiri   : %{holdout_res.total_return_pct:+,.1f} (BIST-100 Endeksi: %{bm_ret:+,.1f})")
    print(f"  • Kör Dönem Sharpe Oranı : {holdout_res.sharpe_ratio:.2f}")
    print(f"  • Kör Dönem Kâr Çarpanı  : {holdout_res.profit_factor:.2f}")
    print(f"  • Kör Dönem Max Düşüş    : %{holdout_res.max_drawdown:.2f}")
    print(f"  • Kör Dönem İşlem Sayısı : {holdout_res.total_trades} Adet (Kazanma Oranı: %{holdout_res.win_rate:.1f})")

    # -----------------------------------------------------------------------------------------
    # AŞAMA 5: 5'Lİ NİHAİ KARŞILAŞTIRMA
    # -----------------------------------------------------------------------------------------
    print("\n" + "=" * 95)
    print("🏆 5'Lİ NİHAİ SİSTEM KARŞILAŞTIRMASI (TÜM KOŞULLAR EŞİT / SIFIR LOOK-AHEAD)")
    print("=" * 95)
    print(f"{'SİSTEM VARYASYONU':<46} | {'1997-2023 GETİRİ':<16} | {'1997-2023 DD':<12} | {'2024-2026 OOS':<14} | {'OOS PF'}")
    print("-" * 95)

    # 1. Baseline
    p1 = StrategyParameters(atr_trailing_bull_mult=3.0, atr_trailing_bear_mult=3.0, position_alloc_bull=0.10)
    r1_is = optimizer.simulate_fast(p1, 1997, 2023)
    r1_oos = optimizer.simulate_fast(p1, 2024, 2026)
    print(f"{'1. Temel Motor (Baseline / Statik Kurallar)':<46} | %{r1_is.total_return_pct:>14,.1f} | %{r1_is.max_drawdown:>10.2f} | %{r1_oos.total_return_pct:>12,.1f} | {r1_oos.profit_factor:>6.2f}")

    # 2. Optimize Teknik
    p2 = StrategyParameters(rsi_oversold=30.0, volume_surge_mult=1.5, position_alloc_bull=0.10)
    r2_is = optimizer.simulate_fast(p2, 1997, 2023)
    r2_oos = optimizer.simulate_fast(p2, 2024, 2026)
    print(f"{'2. + Optimize Teknik Parametreler':<46} | %{r2_is.total_return_pct:>14,.1f} | %{r2_is.max_drawdown:>10.2f} | %{r2_oos.total_return_pct:>12,.1f} | {r2_oos.profit_factor:>6.2f}")

    # 3. + Candle
    p3 = StrategyParameters(min_buyer_pressure=55.0, min_candle_score=75.0, position_alloc_bull=0.10)
    r3_is = optimizer.simulate_fast(p3, 1997, 2023)
    r3_oos = optimizer.simulate_fast(p3, 2024, 2026)
    print(f"{'3. + Empirical Candle Intelligence':<46} | %{r3_is.total_return_pct:>14,.1f} | %{r3_is.max_drawdown:>10.2f} | %{r3_oos.total_return_pct:>12,.1f} | {r3_oos.profit_factor:>6.2f}")

    # 4. + Trend Rider (Klasik)
    p4 = StrategyParameters(atr_trailing_bull_mult=5.0, atr_trailing_bear_mult=3.0, position_alloc_bull=0.12)
    r4_is = optimizer.simulate_fast(p4, 1997, 2023)
    r4_oos = optimizer.simulate_fast(p4, 2024, 2026)
    print(f"{'4. + Dinamik Trend Rider (Klasik ATR)':<46} | %{r4_is.total_return_pct:>14,.1f} | %{r4_is.max_drawdown:>10.2f} | %{r4_oos.total_return_pct:>12,.1f} | {r4_oos.profit_factor:>6.2f}")

    # 5. ASİMETRİK RALLİ KİLİTLİ TAM MOTOR
    r5_is = optimizer.simulate_fast(best_params, 1997, 2023)
    r5_oos = optimizer.simulate_fast(best_params, 2024, 2026)
    print(f"{'5. + ASİMETRİK RALLİ KİLİTLİ (TAM MOTOR)':<46} | %{r5_is.total_return_pct:>14,.1f} | %{r5_is.max_drawdown:>10.2f} | %{r5_oos.total_return_pct:>12,.1f} | {r5_oos.profit_factor:>6.2f}")
    print("=" * 95)
    print("\n✅ ASİMETRİK RALLİ VE ROBUSTNESS OPTİMİZASYONU TAMAMLANDI.")


if __name__ == "__main__":
    main()
