from typing import Any

"""
ALPHA BIST — Kilitli Tek Seferlik Kör Validasyon ve 30-Yıllık Denetim
====================================================================
Kilitli Başarı Kriterleri:
- OOS Profit Factor > 1.20
- OOS Max Drawdown < %25.0
- OOS Sharpe > 0.70
- OOS CAGR > %0.0
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
    logger.info("🔒 ALPHA BIST — KİLİTLİ 2024-2026 KÖR HOLDOUT VE 30-YILLIK PERFORMANS TESTİ")
    logger.info("=" * 105)

    warehouse = HistoricalDataWarehouse()
    bm_df, stock_dict = warehouse.load_30y_data()
    engine = RiskParityEngine(bm_df=bm_df, stock_dict=stock_dict)

    # Kilitli Parametre Kümesi (Hiçbir ek optimizasyon yapılmamıştır)
    params = RiskParityParameters()

    # 1. In-Sample (1997 - 2023)
    engine.simulate(params, start_year=1997, end_year=2023)

    # 2. TEK SEFERLİK KİLİTLİ KÖR TEST (2024 - 2026)
    oos_res = engine.simulate(params, start_year=2024, end_year=2026)

    # ---------------------------------------------------------------------------------------------
    # BÖLÜM 1: KİLİTLİ BAŞARI KRİTERLERİ KONTROL PANELİ
    # ---------------------------------------------------------------------------------------------
    logger.info("\n" + "=" * 105)
    logger.info("🎯 KİLİTLİ HEDEF KRİTERLERİN KONTROLÜ (2024 - 2026 KÖR DÖNEM):")
    logger.info("=" * 105)

    pf_pass = oos_res.profit_factor >= 1.20
    dd_pass = abs(oos_res.max_drawdown) <= 25.0
    sharpe_pass = oos_res.sharpe_ratio >= 0.70
    cagr_pass = oos_res.cagr > 0.0

    logger.info(
        f"  1. Kâr Faktörü (Hedef: > 1.20)     : {oos_res.profit_factor:.2f}  --> {'✅ GEÇTİ' if pf_pass else '❌ GEÇMEDİ'}"
    )
    logger.info(
        f"  2. Max Drawdown (Hedef: < %25.0)   : %{oos_res.max_drawdown:.2f} --> {'✅ GEÇTİ' if dd_pass else '❌ GEÇMEDİ'}"
    )
    logger.info(
        f"  3. Sharpe Oranı (Hedef: > 0.70)    : {oos_res.sharpe_ratio:.2f}  --> {'✅ GEÇTİ' if sharpe_pass else '❌ GEÇMEDİ'}"
    )
    logger.info(
        f"  4. Yıllık Getiri (Hedef: > %0.0)   : %{oos_res.cagr:.2f}  --> {'✅ GEÇTİ' if cagr_pass else '❌ GEÇMEDİ'}"
    )
    logger.info(f"  • Kümülatif 2024-2026 Getirisi     : %{oos_res.total_return_pct:+.1f}")
    logger.info(
        f"  • Toplam İşlem Sayısı              : {oos_res.total_trades} Adet (Kazanma Oranı: %{oos_res.win_rate:.1f})"
    )

    # ---------------------------------------------------------------------------------------------
    # BÖLÜM 2: 1997 - 2026 YIL BAZINDA PERFORMANS & KRİZ TABLOSU
    # ---------------------------------------------------------------------------------------------
    logger.info("\n" + "=" * 105)
    logger.info("📅 1997 - 2026 YIL BAZINDA PERFORMANS VE ALFA TABLOSU:")
    logger.info("=" * 105)
    logger.info(
        f"{'YIL':<6} | {'SİSTEM GETİRİSİ':<18} | {'BIST-100 GETİRİSİ':<18} | {'FARK (ALFA)':<14} | {'MAX DD':<12} | {'PF':<6} | {'DÖNEM'}"
    )
    logger.info("-" * 105)

    years = sorted(list(set(d.year for d in bm_df.index)))
    for y in years:
        res = engine.simulate(params, start_year=y, end_year=y)
        bm_y = bm_df[bm_df.index.year == y]
        bm_y_ret = (
            ((bm_y["Close"].iloc[-1] - bm_y["Close"].iloc[0]) / bm_y["Close"].iloc[0]) * 100.0
            if len(bm_y) > 10
            else 0.0
        )
        diff = res.total_return_pct - bm_y_ret
        kriz_tag = " ⚠️ KRİZ" if y in [2000, 2001, 2008, 2018] else ""
        period_lbl = "KÖR HOLDOUT" if y >= 2024 else "IN-SAMPLE"
        logger.info(
            f"{y:<6} | %{res.total_return_pct:>15,.1f} | %{bm_y_ret:>15,.1f} | %{diff:>11,.1f} | %{res.max_drawdown:>9.2f} | {res.profit_factor:>4.2f} | {period_lbl}{kriz_tag}"
        )
    logger.info("=" * 105)


if __name__ == "__main__":
    main()
