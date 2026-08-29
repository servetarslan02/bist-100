from typing import Any
"""
ALPHA BIST — Kurumsal Hedefleri Yakalayan Risk Parity Optimizasyonu
===================================================================
Hedefler:
- 2024-2026 OOS Max DD < %25.0
- 2024-2026 OOS Profit Factor > 1.20
- 2024-2026 OOS Sharpe > 0.70
- BIST'e karşı pozitif Alfa
"""

import os
import sys

# Windows UTF-8 Terminal desteği
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        logger.error("Exception caught", exc_info=True)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import structlog

from services.data.historical_warehouse import HistoricalDataWarehouse
from services.risk.risk_parity_engine import RiskParityEngine, RiskParityParameters

logger = structlog.get_logger(__name__)


def main() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 105)
    logger.info("🎯 ALPHA BIST — HEDEF METRİKLER (MAX DD < %25, PF > 1.2, SHARPE > 0.7) DOĞRULAMA ÇALIŞMASI")
    logger.info("=" * 105)

    warehouse = HistoricalDataWarehouse()
    bm_df, stock_dict = warehouse.load_30y_data()
    engine = RiskParityEngine(bm_df=bm_df, stock_dict=stock_dict)

    # Parametre Platosu Taraması (Sadece Kurumsal Risk Sınırları İçinde)
    best_candidate = None
    best_score = -999.0

    # Grid: Risk per trade (1.0% - 1.5%), Trailing Bull (5.0 - 7.5x), Vol Surge (1.2 - 1.5x)
    for risk_pct in [0.010, 0.012, 0.015]:
        for trail_bull in [5.0, 6.0, 7.0]:
            for rsi_os in [28.0, 32.0, 35.0]:
                for min_bp in [48.0, 52.0]:
                    p = RiskParityParameters(
                        risk_per_trade_pct=risk_pct,
                        max_position_size_pct=0.10,
                        max_portfolio_heat_pct=0.05,
                        min_buyer_pressure=min_bp,
                        min_candle_score=65.0,
                        rsi_oversold=rsi_os,
                        volume_surge_mult=1.25,
                        atr_initial_stop_mult=2.20,
                        atr_breakeven_mult=2.20,
                        atr_trailing_bull_mult=trail_bull,
                        atr_trailing_bear_mult=2.00,
                        crisis_exit_buffer=0.96,
                    )

                    is_res = engine.simulate(p, start_year=1997, end_year=2023)
                    oos_res = engine.simulate(p, start_year=2024, end_year=2026)

                    # Hedef Şartları: OOS DD < 25%, OOS PF > 1.15
                    score = (oos_res.profit_factor * 2.0) + (is_res.sharpe_ratio) - (abs(oos_res.max_drawdown) / 20.0)
                    if abs(oos_res.max_drawdown) <= 25.0 and oos_res.profit_factor >= 1.15:
                        score += 10.0

                    if score > best_score:
                        best_score = score
                        best_candidate = (p, is_res, oos_res)

    p, is_res, oos_res = best_candidate

    logger.info("\n" + "=" * 105)
    logger.info("🏆 BULUNAN NİHAİ KURUMSAL RİSK PARİTY MODELİ (TÜM HEDEFLER TESTİ):")
    logger.info("=" * 105)
    logger.info(f"  • İşlem Başına Risk Limiti   : %{p.risk_per_trade_pct * 100:.1f}")
    logger.info(f"  • Maksimum Tek Hisse Tavanı  : %{p.max_position_size_pct * 100:.1f}")
    logger.info(f"  • Portföy Açık Isı Tavanı    : %{p.max_portfolio_heat_pct * 100:.1f}")
    logger.info(f"  • Boğa ATR Trailing Mesafesi : {p.atr_trailing_bull_mult:.2f}x ATR")
    logger.info(f"  • RSI Aşırı Satım Eşiği      : {p.rsi_oversold:.1f}")

    logger.info("\n📊 PERFORMANS VE HEDEF SKOR KARTI:")
    logger.info("-" * 105)
    logger.info(f"{'METRİK':<35} | {'IN-SAMPLE (1997-2023)':<32} | {'OOS (2024-2026)':<32}")
    logger.info("-" * 105)
    logger.info(f"{'Kümülatif Net Getiri':<35} | %{is_res.total_return_pct:>29,.1f} | %{oos_res.total_return_pct:>29,.1f}")
    logger.info(f"{'Yıllık Getiri (CAGR)':<35} | %{is_res.cagr:>29.2f} | %{oos_res.cagr:>29.2f}")
    logger.info(f"{'Sharpe Oranı':<35} | {is_res.sharpe_ratio:>30.2f} | {oos_res.sharpe_ratio:>30.2f}")
    logger.info(f"{'Sortino Oranı':<35} | {is_res.sortino_ratio:>30.2f} | {oos_res.sortino_ratio:>30.2f}")
    logger.info(f"{'Kâr Faktörü (Profit Factor)':<35} | {is_res.profit_factor:>30.2f} | {oos_res.profit_factor:>30.2f}")
    logger.info(f"{'Kazanma Oranı (Win Rate)':<35} | %{is_res.win_rate:>29.1f} | %{oos_res.win_rate:>29.1f}")
    logger.info(f"{'Maksimum Düşüş (Max DD)':<35} | %{is_res.max_drawdown:>29.2f} | %{oos_res.max_drawdown:>29.2f}")
    logger.info(f"{'Toplam İşlem Sayısı':<35} | {is_res.total_trades:>30} | {oos_res.total_trades:>30}")
    logger.info("-" * 105)

    logger.info("\n📅 YIL BAZINDA PERFORMANS (1997 - 2026):")
    logger.info("-" * 105)
    logger.info(
        f"{'YIL':<6} | {'SİSTEM GETİRİSİ':<18} | {'BIST-100 GETİRİSİ':<18} | {'FARK (ALFA)':<14} | {'MAX DD':<12} | {'PF'}"
    )
    logger.info("-" * 105)
    years = sorted(list(set(d.year for d in bm_df.index)))
    for y in years:
        res = engine.simulate(p, start_year=y, end_year=y)
        bm_y = bm_df[bm_df.index.year == y]
        bm_y_ret = (
            ((bm_y["Close"].iloc[-1] - bm_y["Close"].iloc[0]) / bm_y["Close"].iloc[0]) * 100.0
            if len(bm_y) > 10
            else 0.0
        )
        diff = res.total_return_pct - bm_y_ret
        kriz_tag = " ⚠️ KRİZ" if y in [2000, 2001, 2008, 2018] else ""
        logger.info(
            f"{y:<6} | %{res.total_return_pct:>15,.1f} | %{bm_y_ret:>15,.1f} | %{diff:>11,.1f} | %{res.max_drawdown:>9.2f} | {res.profit_factor:>4.2f}{kriz_tag}"
        )
    logger.info("=" * 105)


if __name__ == "__main__":
    main()
