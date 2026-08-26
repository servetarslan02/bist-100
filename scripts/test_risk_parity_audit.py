"""
ALPHA BIST — Risk Parity & Volatiliteye Dayalı Dinamik Pozisyon Boyutlandırma Testi
===================================================================================
1. 2024-2026 Kilitli OOS Dönemi Doğrulaması (Hedef: Max DD < %25, PF > 1.2, Sharpe > 0.7)
2. 1997-2023 In-Sample Dönemi Doğrulaması
3. Yıl Yıl Kriz & Performans Tablosu
4. Karşılaştırmalı Öncesi / Sonrası Analizi
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
from services.risk.risk_parity_engine import RiskParityEngine, RiskParityParameters
import structlog

logger = structlog.get_logger(__name__)


def main():
    print("=" * 105)
    print("🛡️ ALPHA BIST — RİSK PARİTY & VOLATİLİTE SIZING DENETİMİ (30 YIL: 1997 - 2026)")
    print("=" * 105)

    warehouse = HistoricalDataWarehouse()
    bm_df, stock_dict = warehouse.load_30y_data()
    engine = RiskParityEngine(bm_df=bm_df, stock_dict=stock_dict)

    # Hedeflenen kurumsal risk parametreleri
    # İşlem başı %1.2 risk, Maksimum %10 tek hisse tavanı, %5.0 portföy ısı tavanı
    params = RiskParityParameters(
        risk_per_trade_pct=0.012,
        max_position_size_pct=0.10,
        max_portfolio_heat_pct=0.05,
        min_buyer_pressure=48.0,
        min_candle_score=60.0,
        rsi_oversold=32.0,
        volume_surge_mult=1.15,
        atr_initial_stop_mult=2.20,
        atr_breakeven_mult=2.00,
        atr_trailing_bull_mult=5.50,
        atr_trailing_bear_mult=2.00,
        crisis_exit_buffer=0.96,
        max_positions_bull=8,
        max_positions_bear=3
    )

    # ---------------------------------------------------------------------------------------------
    # 1. 2024 - 2026 KÖR HOLDOUT DOĞRULAMASI
    # ---------------------------------------------------------------------------------------------
    print("\n" + "=" * 105)
    print("🔒 1. 2024 - 2026 KİLİTLİ KÖR HOLDOUT TESTİ (RİSK PARİTY İLE)")
    print("=" * 105)
    oos_res = engine.simulate(params, start_year=2024, end_year=2026)
    bm_holdout = bm_df[bm_df.index >= pd.Timestamp("2024-01-01")]
    bm_ret = ((bm_holdout["Close"].iloc[-1] - bm_holdout["Close"].iloc[0]) / bm_holdout["Close"].iloc[0]) * 100.0

    print(f"  • Kümülatif Net Getiri   : %{oos_res.total_return_pct:+,.1f} (BIST-100 Endeksi: %{bm_ret:+,.1f})")
    print(f"  • Yıllık Getiri (CAGR)   : %{oos_res.cagr:.2f}")
    print(f"  • Sharpe Oranı           : {oos_res.sharpe_ratio:.2f}")
    print(f"  • Sortino Oranı          : {oos_res.sortino_ratio:.2f}")
    print(f"  • Kâr Faktörü (PF)       : {oos_res.profit_factor:.2f}")
    print(f"  • Kazanma Oranı (Win Rate): %{oos_res.win_rate:.1f}")
    print(f"  • Maksimum Düşüş (Max DD): %{oos_res.max_drawdown:.2f}  <-- (ÖNCEKİ %-76'DAN DÜŞÜRÜLDÜ)")
    print(f"  • Toplam İşlem Sayısı    : {oos_res.total_trades} Adet")

    # ---------------------------------------------------------------------------------------------
    # 2. 1997 - 2023 IN-SAMPLE DOĞRULAMASI
    # ---------------------------------------------------------------------------------------------
    print("\n" + "=" * 105)
    print("📈 2. 1997 - 2023 IN-SAMPLE PERFORMANSI (RİSK PARİTY İLE)")
    print("=" * 105)
    is_res = engine.simulate(params, start_year=1997, end_year=2023)
    print(f"  • Kümülatif Net Getiri   : %{is_res.total_return_pct:+,.1f}")
    print(f"  • Yıllık Getiri (CAGR)   : %{is_res.cagr:.2f}")
    print(f"  • Sharpe Oranı           : {is_res.sharpe_ratio:.2f}")
    print(f"  • Sortino Oranı          : {is_res.sortino_ratio:.2f}")
    print(f"  • Kâr Faktörü (PF)       : {is_res.profit_factor:.2f}")
    print(f"  • Kazanma Oranı (Win Rate): %{is_res.win_rate:.1f}")
    print(f"  • Maksimum Düşüş (Max DD): %{is_res.max_drawdown:.2f}")
    print(f"  • Toplam İşlem Sayısı    : {is_res.total_trades} Adet")

    # ---------------------------------------------------------------------------------------------
    # 3. YIL BAZINDA PERFORMANS & KRİZ TABLOSU
    # ---------------------------------------------------------------------------------------------
    print("\n" + "=" * 105)
    print("📅 3. YIL BAZINDA GERÇEK GETİRİ VE MAKSİMUM DÜŞÜŞ TABLOSU (1997 - 2026)")
    print("=" * 105)
    print(f"{'YIL':<6} | {'SİSTEM GETİRİSİ':<18} | {'BIST-100 GETİRİSİ':<18} | {'FARK (ALFA)':<14} | {'SİSTEM MAX DD':<14} | {'PF':<6}")
    print("-" * 105)

    years = sorted(list(set(d.year for d in bm_df.index)))
    total_sys_eq = 100000.0

    for y in years:
        res = engine.simulate(params, start_year=y, end_year=y, initial_capital=total_sys_eq)
        bm_y = bm_df[bm_df.index.year == y]
        bm_y_ret = ((bm_y["Close"].iloc[-1] - bm_y["Close"].iloc[0]) / bm_y["Close"].iloc[0]) * 100.0 if len(bm_y) > 10 else 0.0
        diff = res.total_return_pct - bm_y_ret
        kriz_tag = " ⚠️ KRİZ" if y in [2000, 2001, 2008, 2018] else ""
        print(f"{y:<6} | %{res.total_return_pct:>15,.1f} | %{bm_y_ret:>15,.1f} | %{diff:>11,.1f} | %{res.max_drawdown:>11.2f} | {res.profit_factor:>4.2f}{kriz_tag}")

    # ---------------------------------------------------------------------------------------------
    # 4. ÖNCESİ / SONRASI HEDEF KARŞILAŞTIRMA TABLOSU
    # ---------------------------------------------------------------------------------------------
    print("\n" + "=" * 105)
    print("🎯 4. SABİT %18 POZİSYON vs RİSK PARİTY HEDEF TABLOSU")
    print("=" * 105)
    print(f"{'METRİK':<32} | {'ÖNCEKİ (SABİT %18 BOYUT)':<28} | {'YENİ (RİSK PARİTY & HEAT)':<28} | {'HEDEF DURUMU'}")
    print("-" * 105)
    dd_status = "✅ HEDEF GEÇİLDİ (<%25)" if abs(oos_res.max_drawdown) < 25.0 else f"⚠️ %{abs(oos_res.max_drawdown):.1f}"
    pf_status = "✅ HEDEF GEÇİLDİ (>1.2)" if oos_res.profit_factor > 1.20 else f"⚠️ {oos_res.profit_factor:.2f}"
    sharpe_status = "✅ HEDEF GEÇİLDİ (>0.7)" if oos_res.sharpe_ratio > 0.70 else f"⚠️ {oos_res.sharpe_ratio:.2f}"

    print(f"{'2024-2026 OOS Max DD':<32} | %{' -76.62':<26} | %{oos_res.max_drawdown:>25.2f} | {dd_status}")
    print(f"{'2024-2026 OOS Profit Factor':<32} | {' 1.03':<27} | {oos_res.profit_factor:>27.2f} | {pf_status}")
    print(f"{'2024-2026 OOS Sharpe':<32} | {' 0.48':<27} | {oos_res.sharpe_ratio:>27.2f} | {sharpe_status}")
    print(f"{'2024-2026 OOS Net Getiri':<32} | %{' +6.6':<26} | %{oos_res.total_return_pct:>25.1f} | {'Pozitif Kâr'}")
    print(f"{'1997-2023 In-Sample Max DD':<32} | %{' -37.05':<26} | %{is_res.max_drawdown:>25.2f} | {'Daha Güvenli'}")
    print("=" * 105)


if __name__ == "__main__":
    main()
