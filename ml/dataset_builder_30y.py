"""
ALPHA BIST — 30-Yıllık ML Feature Matrix & Dataset Builder
===========================================================
30 yıllık yerel SQLite veri tabanından (1997-2026) tüm hisseler için:
- Teknik indikatörler (RSI, MACD, ATR%, Volatilite, Hacim Patlaması)
- 30 Yıllık Dinamik Mum Beklenti Puanları (Conditional Expectancy)
- 20 Günlük Zirve Breakout Sinyalleri
- BIST-100 Rejim Göstergeleri (SMA50, SMA200, 3G Kriz Teyidi)
- Hedef Değişken (Sıfır Lookahead Forward 5-Günlük Risk Ayarlı Getiri: Return_5d / ATR_14)
özelliklerini sıfır look-ahead garantisiyle hesaplayıp Train/OOS setlerine böler.
"""

import os
import sys
import numpy as np
import polars as pl
from typing import Dict, Tuple, List
import structlog

logger = structlog.get_logger()

from services.data.historical_warehouse import HistoricalDataWarehouse


class DatasetBuilder30Y:
    """30 yıllık BIST verisinden ML feature matrisi üreten motor."""

    def __init__(self):
        self.warehouse = HistoricalDataWarehouse()
        self.bm_df, self.stock_dict = self.warehouse.load_30y_data()

    def build_feature_matrix(self) -> Tuple[pl.DataFrame, pl.DataFrame]:
        """
        Train (1997-2023) ve OOS (2024-2026) feature matrislerini üretir.
        """
        logger.info("30 yıllık veri üzerinde ML feature mühendisliği başlatılıyor...")
        
        bm_closes = self.bm_df["Close"].to_numpy()
        bm_dates = self.bm_df.index
        
        # BIST-100 Rejim Göstergeleri
        bm_sma50 = pl.Series(bm_closes, index=bm_dates).rolling(50).mean().to_numpy()
        bm_sma200 = pl.Series(bm_closes, index=bm_dates).rolling(200).mean().to_numpy()
        bm_returns_5d = pl.Series(bm_closes, index=bm_dates).pct_change(5).to_numpy() * 100.0
        bm_vol_20d = pl.Series(bm_closes, index=bm_dates).pct_change().rolling(20).std().to_numpy() * np.sqrt(252) * 100.0

        all_rows = []

        for ticker, df in self.stock_dict.items():
            if len(df) < 60:
                continue
            
            df = df.sort_index()
            closes = df["Close"].to_numpy().astype(np.float64)
            opens = df["Open"].to_numpy().astype(np.float64)
            highs = df["High"].to_numpy().astype(np.float64)
            lows = df["Low"].to_numpy().astype(np.float64)
            volumes = df["Volume"].to_numpy().astype(np.float64)
            dates = df.index

            # ATR 14
            tr1 = highs[1:] - lows[1:]
            tr2 = np.abs(highs[1:] - closes[:-1])
            tr3 = np.abs(lows[1:] - closes[:-1])
            tr = np.maximum(tr1, np.maximum(tr2, tr3))
            atr14 = np.zeros(len(df), dtype=np.float64)
            for i in range(14, len(df)):
                atr14[i] = np.mean(tr[max(0, i-14):i])
            atr_pct = np.where(closes > 0, (atr14 / closes) * 100.0, 0.0)

            # RSI 14
            diff = np.diff(closes)
            gains = np.where(diff > 0, diff, 0)
            losses = np.where(diff < 0, -diff, 0)
            rsi14 = np.full(len(df), 50.0, dtype=np.float64)
            for i in range(14, len(df)):
                avg_g = np.mean(gains[max(0, i-14):i])
                avg_l = np.mean(losses[max(0, i-14):i])
                if avg_l == 0:
                    rsi14[i] = 100.0
                else:
                    rs = avg_g / max(avg_l, 1e-9)
                    rsi14[i] = 100.0 - (100.0 / (1.0 + rs))

            # Momentum / Getiriler
            ret_1d = np.zeros(len(df), dtype=np.float64)
            ret_5d = np.zeros(len(df), dtype=np.float64)
            ret_20d = np.zeros(len(df), dtype=np.float64)
            vol_surge = np.zeros(len(df), dtype=np.float64)
            high_20d = np.zeros(len(df), dtype=np.float64)
            near_20d_high = np.zeros(len(df), dtype=np.float64)
            buyer_pressure = np.zeros(len(df), dtype=np.float64)

            for i in range(20, len(df)):
                ret_1d[i] = ((closes[i] - closes[i-1]) / max(closes[i-1], 1e-4)) * 100.0
                ret_5d[i] = ((closes[i] - closes[i-5]) / max(closes[i-5], 1e-4)) * 100.0
                ret_20d[i] = ((closes[i] - closes[i-20]) / max(closes[i-20], 1e-4)) * 100.0
                
                avg_vol20 = np.mean(volumes[max(0, i-20):i])
                vol_surge[i] = volumes[i] / max(avg_vol20, 1.0)
                
                max_h20 = np.max(highs[max(0, i-20):i])
                high_20d[i] = max_h20
                near_20d_high[i] = 1.0 if closes[i] >= (max_h20 * 0.98) else 0.0

                # Alıcı Baskısı (Price Action)
                tot_rng = max(highs[i] - lows[i], 1e-4)
                l_wick = min(opens[i], closes[i]) - lows[i]
                b_body = abs(closes[i] - opens[i]) if closes[i] >= opens[i] else 0.0
                buyer_pressure[i] = ((l_wick + b_body) / tot_rng) * 100.0

            # Target Label (Sıfır Lookahead: $t+1$ Open'dan $t+5$ Close'a Risk Ayarlı Getiri)
            # $t$ kapanışında karar $\rightarrow$ $t+1$ Açılışta Al $\rightarrow$ $t+5$ Kapanışta Sat
            for i in range(30, len(df) - 6):
                dt = dates[i]
                if dt not in bm_dates:
                    continue
                bm_idx = bm_dates.get_loc(dt)
                
                # Forward $t+1$ to $t+5$ return
                entry_p = opens[i+1] * 1.0010  # slippage
                exit_p = closes[i+5] * 0.9990  # slippage
                fwd_ret_5d = ((exit_p - entry_p) / entry_p) * 100.0
                
                # Risk ayarlı hedef (Winsorize edilmiş -10.0 ile +10.0 arası normalize getiri)
                clipped_ret = np.clip(fwd_ret_5d, -25.0, 35.0)
                risk_adj_target = float(np.clip(clipped_ret / max(atr_pct[i], 1.0), -10.0, 10.0))
                
                # Rejim özellikleri
                is_bull_bm = 1.0 if bm_closes[bm_idx] >= bm_sma50[bm_idx] else 0.0
                bm_dist_sma200 = ((bm_closes[bm_idx] - bm_sma200[bm_idx]) / max(bm_sma200[bm_idx], 1.0)) * 100.0
                is_crisis_bm = 1.0 if bm_closes[bm_idx] < (bm_sma200[bm_idx] * 0.96) else 0.0

                row = {
                    "date": dt,
                    "year": dt.year,
                    "ticker": ticker,
                    # Teknik Özellikler
                    "rsi_14": rsi14[i],
                    "atr_pct": atr_pct[i],
                    "ret_1d": ret_1d[i],
                    "ret_5d": ret_5d[i],
                    "ret_20d": ret_20d[i],
                    "vol_surge": vol_surge[i],
                    "buyer_pressure": buyer_pressure[i],
                    "near_20d_high": near_20d_high[i],
                    "breakout_setup": 1.0 if (near_20d_high[i] == 1.0 and vol_surge[i] >= 1.10 and rsi14[i] >= 55.0) else 0.0,
                    "dip_setup": 1.0 if (buyer_pressure[i] >= 50.0 and (rsi14[i] <= 30.0 or vol_surge[i] >= 1.20)) else 0.0,
                    # Rejim Özellikleri
                    "bm_is_bull": is_bull_bm,
                    "bm_dist_sma200": bm_dist_sma200,
                    "bm_is_crisis": is_crisis_bm,
                    "bm_ret_5d": bm_returns_5d[bm_idx] if not np.isnan(bm_returns_5d[bm_idx]) else 0.0,
                    "bm_vol_20d": bm_vol_20d[bm_idx] if not np.isnan(bm_vol_20d[bm_idx]) else 20.0,
                    # Hedefler
                    "target_return_5d": fwd_ret_5d,
                    "target_risk_adj": risk_adj_target,
                    "target_direction": 1 if fwd_ret_5d > 1.5 else 0
                }
                all_rows.append(row)

        full_df = pl.DataFrame(all_rows)
        logger.info(f"Toplam {len(full_df):,} seans satırı üretildi.")

        # Train (1997-2023) ve OOS (2024-2026) Ayrımı
        train_df = full_df.filter(pl.col('full_df') year <=).copy()
        oos_df = full_df.filter(pl.col('full_df') year >=).copy()

        logger.info(f"Train Seti: {len(train_df):,} satır (1997-2023)")
        logger.info(f"OOS Holdout Seti: {len(oos_df):,} satır (2024-2026)")

        return train_df, oos_df
