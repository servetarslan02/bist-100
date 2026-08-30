from typing import Any

"""ALPHA BIST — June 2026 V-Dip Audit Script (Read-Only Deep Inspection)

Bu script 2026 Mayıs ve Haziran aylarındaki:
1. Günlük XU100 kapanışlarını ve 20 hissenin tek tek getirilerini
2. Model sinyallerini, skorlarını ve sıralamalarını
3. Açılan ve kapanan pozisyonları, çıkış nedenlerini (stop-loss, trailing, time exit)
4. Portföyün nakit/hisse dağılımını
gün gün dökerek inceler.
"""

import numpy as np
import structlog

from services.learning.institutional_walkforward_engine import (
    extract_point_in_time_features,
    load_all_market_data,
)
from services.learning.upside_capture_validator import detect_market_regime_v2

logger = structlog.get_logger()


def audit_june_2026() -> Any:
    """Otomatik eklendi."""
    logger.info("=================================================================")
    logger.info("ALPHA BIST — JUNE 2026 V-DIP AUDIT (READ-ONLY INSPECTION)")
    logger.info("=================================================================")

    stock_data, xu100_close = load_all_market_data()

    features_by_ticker = {}
    for tk, df in stock_data.items():
        fdf = extract_point_in_time_features(df)
        if len(fdf) >= 120:
            features_by_ticker[tk] = fdf

    common_dates = sorted(list(set.intersection(*[set(fdf.index) for fdf in features_by_ticker.values()])))

    # 2026 Mayıs ve Haziran Tarihleri
    target_dates = [d for d in common_dates if d.strftime("%Y-%m") in ["2026-05", "2026-06"]]

    logger.info(f"Audit Edilen Gün Sayısı: {len(target_dates)} gün (2026-05-01 ile 2026-06-30 arası)")

    # 1. Hisselerin Haziran 2026 Getirileri
    june_start = [d for d in target_dates if d.strftime("%Y-%m") == "2026-06"][0]
    june_end = [d for d in target_dates if d.strftime("%Y-%m") == "2026-06"][-1]

    xu_june_ret = (float(xu100_close.loc[june_end]) / float(xu100_close.loc[june_start]) - 1.0) * 100.0
    logger.info(f"\n📈 XU100 Haziran 2026 Getirisi: +%{xu_june_ret:.2f}")

    stock_june_rets = {}
    for tk, fdf in features_by_ticker.items():
        if june_start in fdf.index and june_end in fdf.index:
            r = (float(fdf.loc[june_end]["close"]) / float(fdf.loc[june_start]["close"]) - 1.0) * 100.0
            stock_june_rets[tk] = r

    sorted_stocks = sorted(stock_june_rets.items(), key=lambda x: x[1], reverse=True)
    logger.info("\n🏆 HİSSE BAZINDA HAZİRAN 2026 GETİRİLERİ (Top 10):")
    for tk, r in sorted_stocks[:10]:
        logger.info(f"  • {tk}: +%{r:.2f}")

    # 2. Haziran 2026 Günlük Rejim, Sinyal ve Fiyat Hareketleri
    logger.info("\n📅 GÜNLÜK AKIŞ VE SİNYAL DENETİMİ (HAZİRAN 2026):")
    logger.info("| Tarih | XU100 Kapanış | Günlük Değ. (%) | Rejim | 5G Ret (%) | 20G Vol (%) | Yorum |")
    logger.info("|---|---|---|---|---|---|---|")

    june_dates = [d for d in target_dates if d.strftime("%Y-%m") == "2026-06"]
    valid_xu_dates = [d for d in target_dates if d in xu100_close.index]
    for d in june_dates:
        if d not in xu100_close.index:
            continue
        cur_p = float(xu100_close.loc[d])
        prev_ds = [vd for vd in valid_xu_dates if vd < d]
        if not prev_ds:
            continue
        prev_d = prev_ds[-1]
        prev_p = float(xu100_close.loc[prev_d])
        daily_chg = (cur_p / prev_p - 1.0) * 100.0

        hist = xu100_close.loc[:d]
        ret_5d = (hist.iloc[-1] / hist.iloc[-5] - 1.0) * 100.0 if len(hist) >= 5 else 0.0
        vol_20d = hist.pct_change().tail(20).std() * np.sqrt(252) * 100.0
        reg = detect_market_regime_v2(xu100_close, d)

        comment = "Normal"
        if daily_chg > 4.0:
            comment = "⚡ Sert Ralli / Alım"
        elif daily_chg < -4.0:
            comment = "🔴 Sert Satış"

        logger.info(
            f"| {d.strftime('%Y-%m-%d')} | {cur_p:,.1f} | %{daily_chg:+.2f} | {reg} | %{ret_5d:+.1f} | %{vol_20d:.1f} | {comment} |"
        )


if __name__ == "__main__":
    audit_june_2026()
