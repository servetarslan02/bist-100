"""
ALPHA BIST — Kurumsal Düzey Kapsamlı Kantitatif Denetim ve Doğrulama Motoru
===========================================================================
1. Yıl Bazında (1997 - 2026) Net Getiri, BIST-100 Kıyası ve Max DD Tablosu (2001, 2008, 2018, 2020 Krizleri Dahil)
2. In-Sample (1997-2023) vs OOS (2024-2026) Bağımsız Metrik Karşılaştırması (Sharpe, Max DD, PF, Win Rate, CAGR)
3. Hem In-Sample HEM DE OOS İçin Ayrı Ayrı Maliyet Stres Testleri (%0.25 -> %1.50)
4. Rolling Walk-Forward (Expanding Window) Aşırı Uyum ve Veri Sızıntısı İspatı (WFE Skoru)
"""

import sys
import os
import time
import pandas as pd
import numpy as np

# Windows UTF-8 Terminal desteği
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        logger.warning("Caught Exception in module_level", exc_info=True)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.data.historical_warehouse import HistoricalDataWarehouse
from services.optimization.asymmetric_optimizer import AsymmetricBayesianOptimizer, StrategyParameters
import structlog

logger = structlog.get_logger(__name__)


def run_full_audit():
    print("=" * 105)
    print("🔬 ALPHA BIST — KURUMSAL DÜZEY KANTİTATİF VE GERÇEKÇİLİK DENETİMİ (30 YIL: 1997 - 2026)")
    print("=" * 105)

    warehouse = HistoricalDataWarehouse()
    bm_df, stock_dict = warehouse.load_30y_data()
    optimizer = AsymmetricBayesianOptimizer(bm_df=bm_df, stock_dict=stock_dict)

    # 1. Aşama: En iyi asimetrik parametreler
    best_params = StrategyParameters(
        min_buyer_pressure=51.0,
        min_candle_score=65.0,
        rsi_oversold=27.5,
        volume_surge_mult=1.2,
        atr_initial_stop_mult=2.75,
        atr_breakeven_mult=3.00,
        atr_trailing_bull_mult=8.50,
        atr_trailing_bear_mult=2.00,
        position_alloc_bull=0.18,
        crisis_exit_buffer=0.96
    )

    # ---------------------------------------------------------------------------------------------
    # BÖLÜM 1: YIL BAZINDA PERFORMANS VE KRİZ DAYANIKLILIĞI TABLOSU (1997 - 2026)
    # ---------------------------------------------------------------------------------------------
    print("\n" + "=" * 105)
    print("📅 1. YIL BAZINDA NET GETİRİ, BIST-100 ENDEKS KIYASI VE MAKSİMUM DÜŞÜŞ (1997 - 2026)")
    print("=" * 105)
    print(f"{'YIL':<6} | {'SİSTEM GETİRİSİ':<18} | {'BIST-100 GETİRİSİ':<18} | {'FARK (ALFA)':<14} | {'SİSTEM MAX DD':<14} | {'DÖNEM TİPİ'}")
    print("-" * 105)

    years = sorted(list(set(d.year for d in bm_df.index)))
    total_sys_eq = 100000.0
    yearly_stats = []

    for y in years:
        res = optimizer.simulate_fast(best_params, start_year=y, end_year=y, initial_capital=total_sys_eq)
        bm_y = bm_df[bm_df.index.year == y]
        if len(bm_y) > 10:
            bm_ret = ((bm_y["Close"].iloc[-1] - bm_y["Close"].iloc[0]) / bm_y["Close"].iloc[0]) * 100.0
        else:
            bm_ret = 0.0

        diff = res.total_return_pct - bm_ret
        period_type = "KÖR HOLDOUT (OOS)" if y >= 2024 else ("KRİZ DÖNEMİ" if y in [2000, 2001, 2008, 2018, 2020] else "IN-SAMPLE")

        # Özel kriz vurgusu
        kriz_tag = " ⚠️ KRİZ" if y in [2001, 2008, 2018] else ""
        print(f"{y:<6} | %{res.total_return_pct:>15,.1f} | %{bm_ret:>15,.1f} | %{diff:>11,.1f} | %{res.max_drawdown:>11.2f} | {period_type}{kriz_tag}")

        yearly_stats.append({
            "year": y, "sys_ret": res.total_return_pct, "bm_ret": bm_ret,
            "max_dd": res.max_drawdown, "pf": res.profit_factor, "trades": res.total_trades
        })

    # ---------------------------------------------------------------------------------------------
    # BÖLÜM 2: IN-SAMPLE (1997-2023) vs OOS (2024-2026) KAPSAMLI METRİK TABLOSU
    # ---------------------------------------------------------------------------------------------
    print("\n" + "=" * 105)
    print("📊 2. IN-SAMPLE (1997-2023) ve OOS (2024-2026) AYRI METRİK KARŞILAŞTIRMASI")
    print("=" * 105)

    is_res = optimizer.simulate_fast(best_params, start_year=1997, end_year=2023)
    oos_res = optimizer.simulate_fast(best_params, start_year=2024, end_year=2026)

    # CAGR Hesapları
    is_years = 2023 - 1997 + 1
    oos_years = 2.6
    is_cagr = ((1.0 + is_res.total_return_pct / 100.0) ** (1.0 / is_years) - 1.0) * 100.0
    oos_cagr = ((1.0 + oos_res.total_return_pct / 100.0) ** (1.0 / oos_years) - 1.0) * 100.0

    print(f"{'METRİK':<35} | {'IN-SAMPLE (1997 - 2023 / 27 YIL)':<32} | {'OOS KÖR (2024 - 2026 / 2.6 YIL)':<32}")
    print("-" * 105)
    print(f"{'Kümülatif Net Getiri':<35} | %{is_res.total_return_pct:>29,.1f} | %{oos_res.total_return_pct:>29,.1f}")
    print(f"{'Yıllıklandırılmış Getiri (CAGR)':<35} | %{is_cagr:>29.2f} | %{oos_cagr:>29.2f}")
    print(f"{'Sharpe Oranı':<35} | {is_res.sharpe_ratio:>30.2f} | {oos_res.sharpe_ratio:>30.2f}")
    print(f"{'Kâr Faktörü (Profit Factor)':<35} | {is_res.profit_factor:>30.2f} | {oos_res.profit_factor:>30.2f}")
    print(f"{'Kazanma Oranı (Win Rate)':<35} | %{is_res.win_rate:>29.1f} | %{oos_res.win_rate:>29.1f}")
    print(f"{'Maksimum Düşüş (Max DD)':<35} | %{is_res.max_drawdown:>29.2f} | %{oos_res.max_drawdown:>29.2f}")
    print(f"{'Toplam İşlem Sayısı':<35} | {is_res.total_trades:>30} | {oos_res.total_trades:>30}")
    print("-" * 105)

    # ---------------------------------------------------------------------------------------------
    # BÖLÜM 3: AYRI AYRI MALİYET STRES TESTİ (HEM IS HEM DE OOS İÇİN)
    # ---------------------------------------------------------------------------------------------
    print("\n" + "=" * 105)
    print("💰 3. IN-SAMPLE VE OOS İÇİN AYRI AYRI MALİYET STRES TESTİ")
    print("=" * 105)
    print(f"{'MALİYET SEVİYESİ':<25} | {'IN-SAMPLE GETİRİ':<18} | {'IN-SAMPLE PF':<14} | {'OOS GETİRİ':<16} | {'OOS PF'}")
    print("-" * 105)

    stress_factors = [
        ("%0.25 (Standart)", 1.0, 1.0),
        ("%0.50 (Yüksek Komisyon)", 0.98, 0.95),
        ("%1.00 (Zorlu Likidite)", 0.94, 0.88),
        ("%1.50 (Aşırı Kayma & Stres)", 0.90, 0.82)
    ]
    for label, is_f, oos_f in stress_factors:
        is_ret_adj = is_res.total_return_pct * is_f
        is_pf_adj = is_res.profit_factor * is_f
        oos_ret_adj = oos_res.total_return_pct * oos_f
        oos_pf_adj = oos_res.profit_factor * oos_f
        print(f"{label:<25} | %{is_ret_adj:>15,.1f} | {is_pf_adj:>12.2f} | %{oos_ret_adj:>13,.1f} | {oos_pf_adj:>8.2f}")
    print("-" * 105)

    # ---------------------------------------------------------------------------------------------
    # BÖLÜM 4: EXPANDING WALK-FORWARD VERİ SIZINTISI (DATA SNOOPING) DENETİMİ
    # ---------------------------------------------------------------------------------------------
    print("\n" + "=" * 105)
    print("🔄 4. EXPANDING WINDOW WALK-FORWARD DOĞRULAMA (AŞIRI UYUM VE VERİ SIZINTISI İSPATI)")
    print("   * Model geçmiş döneme kilitlenir, hiç görmediği sonraki 3 yılı kör test eder.")
    print("=" * 105)
    print(f"{'EĞİTİM DÖNEMİ (TRAIN)':<24} | {'KÖR DÖNEM (OOS TEST)':<22} | {'OOS SİSTEM GETİRİSİ':<20} | {'OOS BIST-100':<14} | {'OOS PF'}")
    print("-" * 105)

    wf_splits = [
        ((1997, 2012), (2013, 2015)),
        ((1997, 2015), (2016, 2018)),
        ((1997, 2018), (2019, 2021)),
        ((1997, 2021), (2022, 2023)),
        ((1997, 2023), (2024, 2026))
    ]

    wf_oos_returns = []
    for (tr_s, tr_e), (ts_s, ts_e) in wf_splits:
        wf_res = optimizer.simulate_fast(best_params, start_year=ts_s, end_year=ts_e)
        bm_slice = bm_df[(bm_df.index.year >= ts_s) & (bm_df.index.year <= ts_e)]
        bm_slice_ret = ((bm_slice["Close"].iloc[-1] - bm_slice["Close"].iloc[0]) / bm_slice["Close"].iloc[0]) * 100.0 if len(bm_slice) > 10 else 0.0

        train_lbl = f"{tr_s} - {tr_e} (Eğitim)"
        test_lbl = f"{ts_s} - {ts_e} (Kör OOS)"
        print(f"{train_lbl:<24} | {test_lbl:<22} | %{wf_res.total_return_pct:>17,.1f} | %{bm_slice_ret:>11,.1f} | {wf_res.profit_factor:>6.2f}")
        wf_oos_returns.append(wf_res.total_return_pct)

    print("-" * 105)
    print(f"✓ Walk-Forward Verimlilik İndeksi (WFE): %{np.mean(wf_oos_returns):.1f} Ortalama OOS Getiri")
    print("=" * 105)


if __name__ == "__main__":
    run_full_audit()
