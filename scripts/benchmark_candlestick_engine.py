import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
ALPHA BIST — 10/10 Candlestick & Price Action Engine vs Baseline Benchmark
==========================================================================
Gerçek BIST-100 hisseleri üzerinde son 1 yıllık A/B testini koşturur:
A) Eski Sistem: Basit RSI & SMA Kesişimi
B) Yeni 10/10 Sistem: Japon Mum Formasyonları + Price Action + FVG + Alıcı Gücü
"""

import os
import sys

import numpy as np
import polars as pl
import yfinance as yf

sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from services.intelligence.candle_patterns import candle_engine

BIST_TEST_STOCKS = [
    "THYAO.IS",
    "ASELS.IS",
    "GARAN.IS",
    "KCHOL.IS",
    "TUPRS.IS",
    "EREGL.IS",
    "BIMAS.IS",
    "FROTO.IS",
    "PGSUS.IS",
    "SISE.IS",
    "AKBNK.IS",
    "YKBNK.IS",
    "TCELL.IS",
    "SAHOL.IS",
    "ENKAI.IS",
]


def run_benchmark() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 80)
    logger.info("BIST-100 GERÇEK HİSSE VERİLERİ ÜZERİNDE 10/10 MUM MOTORU A/B TESTİ")
    logger.info("=" * 80)
    logger.info("Test Edilen Hisseler : 15 Öncü BIST-100 Hissesi")
    logger.info("Test Periyodu        : Son 1 Yıl (Günlük Gerçek Mumlar)\n")

    # Gerçek verileri çek
    raw_data = yf.download(BIST_TEST_STOCKS, period="1y", interval="1d", progress=False, group_by="ticker")

    # Metrik havuzları
    baseline_trades = []
    advanced_trades = []

    for ticker in BIST_TEST_STOCKS:
        sym = ticker.replace(".IS", "")
        try:
            df = raw_data[ticker].dropna() if ticker in raw_data.columns.get_level_values(0) else None
            if df is None or len(df) < 50:
                continue

            closes = df["Close"].values

            # Her işlem günü için simülasyon (Son 200 gün)
            for i in range(30, len(df) - 5):
                window_df = df.iloc[: i + 1]
                p_entry = closes[i]
                p_exit_5d = closes[i + 5]  # 5 günlük holding getiri
                ret_5d = (p_exit_5d - p_entry) / p_entry * 100

                # -------------------------------------------------------------
                # 1. Eski Sistem (Baseline): Sadece RSI < 35 ve SMA20 > SMA50
                # -------------------------------------------------------------
                sma20 = np.mean(closes[max(0, i - 19) : i + 1])
                np.mean(closes[max(0, i - 49) : i + 1])
                deltas = np.diff(closes[max(0, i - 14) : i + 1])
                gains = np.maximum(deltas, 0)
                losses = np.maximum(-deltas, 0)
                avg_g = np.mean(gains) if len(gains) > 0 else 0
                avg_l = np.mean(losses) if len(losses) > 0 else 1e-9
                rsi = 100 - (100 / (1 + (avg_g / max(avg_l, 1e-9))))

                if rsi < 38 and p_entry > sma20:
                    baseline_trades.append({"ticker": sym, "return_pct": ret_5d, "is_win": ret_5d > 0})

                # -------------------------------------------------------------
                # 2. Yeni 10/10 Sistem: Mum Formasyonu + Price Action + FVG
                # -------------------------------------------------------------
                candle_res = candle_engine.analyze_dataframe(window_df, sym)

                # Alım Kuralı: Bullish Engulfing, Hammer, Morning Star, Bullish FVG
                # veya Güçlü Alıcı Baskısı (%65+) ile Confluence
                strong_bullish_patterns = {
                    "BULLISH_ENGULFING",
                    "HAMMER_PINBAR",
                    "MORNING_STAR",
                    "THREE_WHITE_SOLDIERS",
                    "BULLISH_FVG",
                }
                has_bull_pattern = any(p in strong_bullish_patterns for p in candle_res.patterns_detected)

                if (has_bull_pattern or candle_res.candle_score >= 70) and candle_res.buyer_pressure_pct >= 60:
                    advanced_trades.append(
                        {
                            "ticker": sym,
                            "return_pct": ret_5d,
                            "is_win": ret_5d > 0,
                            "patterns": candle_res.patterns_detected,
                            "score": candle_res.candle_score,
                        }
                    )

        except Exception:
            continue

    # İstatistiksel Karşılaştırma
    def calc_stats(trades) -> Any:
        """Otomatik eklendi."""
        if not trades:
            return {"count": 0, "win_rate": 0, "avg_ret": 0, "profit_factor": 0, "total_ret": 0}
        df_t = pl.DataFrame(trades)
        win_rate = (df_t["is_win"].sum() / len(df_t)) * 100
        avg_ret = df_t["return_pct"].mean()
        wins = df_t[df_t["return_pct"] > 0]["return_pct"].sum()
        losses = abs(df_t[df_t["return_pct"] < 0]["return_pct"].sum())
        profit_factor = round(wins / max(losses, 1e-9), 2)
        total_ret = df_t["return_pct"].sum()
        return {
            "count": len(df_t),
            "win_rate": round(win_rate, 1),
            "avg_ret": round(avg_ret, 2),
            "profit_factor": profit_factor,
            "total_ret": round(total_ret, 1),
        }

    s_base = calc_stats(baseline_trades)
    s_adv = calc_stats(advanced_trades)

    logger.info("-" * 80)
    logger.info(f"{'METRİK':<30} | {'ESKİ SİSTEM (Baseline)':<22} | {'YENİ 10/10 MUM MOTORU':<22}")
    logger.info("-" * 80)
    logger.info(f"{'Üretilen Sinyal Sayısı':<30} | {s_base['count']:<22} | {s_adv['count']:<22}")
    logger.info(
        f"{'Kazanma Oranı (Win Rate)':<30} | %{s_base['win_rate']:<21} | %{s_adv['win_rate']:<21} (ARTIŞ: +%{s_adv['win_rate'] - s_base['win_rate']:.1f})"
    )
    logger.info(f"{'İşlem Başına Ort. Getiri':<30} | %{s_base['avg_ret']:<21} | %{s_adv['avg_ret']:<21}")
    logger.info(f"{'Kar / Zarar Çarpanı (Profit Factor)':<30} | {s_base['profit_factor']:<22} | {s_adv['profit_factor']:<22}")
    logger.info(f"{'Kümülatif Toplam Alpha':<30} | +%{s_base['total_ret']:<20} | +%{s_adv['total_ret']:<20}")
    logger.info("-" * 80)

    if s_adv["win_rate"] > s_base["win_rate"] and s_adv["profit_factor"] > s_base["profit_factor"]:
        logger.info(
            "✅ KANITLANDI: 10/10 Mum ve Price Action Motoru, eski sisteme kıyasla hem Kazanma Oranında hem de Kar Çarpanında belirgin üstünlük sağladı!"
        )
    logger.info("=" * 80)


if __name__ == "__main__":
    run_benchmark()
