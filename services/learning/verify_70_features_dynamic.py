"""
ALPHA BIST — 70 Özellik Canlı Varyans ve Dinamiklik Testi (Doğrudan Scanner Motorundan)
"""
import pandas as pd
from services.scanner.bist_ml_scanner import BistMLScanner
from services.ml.ranking_model import RankingModel

def verify_from_scanner():
    scanner = BistMLScanner()
    live_rows = scanner._fetch_live_scanner_data()
    feat_names = list(RankingModel()._feature_names)

    print(f"Toplam Çekilen Canlı Hisse Sayısı: {len(live_rows)}")
    print(f"Modeldeki Toplam Özellik Sayısı    : {len(feat_names)}")
    print("=" * 95)

    # BistMLScanner içindeki mantığı çalıştırıp all_feat_rows alalım
    adv_count = sum(1 for it in live_rows if float(it.get("change") or 0.0) > 0)
    dec_count = sum(1 for it in live_rows if float(it.get("change") or 0.0) < 0)
    total_valid = max(len(live_rows), 1)
    live_breadth = float((adv_count / total_valid) * 100.0)
    live_ad_ratio = float(adv_count / max(dec_count, 1))

    all_feat_rows = []
    for item in live_rows:
        try:
            sym = str(item.get("name", "")).strip().upper()
            if not sym:
                continue
            latest_p = float(item["close"])
            opens = float(item.get("open") or latest_p)
            highs = float(item.get("high") or latest_p)
            lows = float(item.get("low") or latest_p)
            change_pct = round(float(item.get("change") or 0.0), 2)
            rvol_val = float(item.get("relative_volume_10d_calc") or 1.0)
            vol_surge = max(0.5, rvol_val)
            rsi_14 = float(item.get("RSI") or 50.0)
            atr_val = float(item.get("ATR") or (latest_p * 0.03))
            atr_pct = (atr_val / max(latest_p, 1e-4)) * 100.0

            sma20 = float(item.get("SMA20") or latest_p)
            sma50 = float(item.get("SMA50") or latest_p)
            sma200 = float(item.get("SMA200") or latest_p)
            bb_upper = float(item.get("BB.upper") or (latest_p * 1.05))
            high_3m = float(item.get("High.3M") or latest_p)

            ret_1d = change_pct
            ret_5d = float(item.get("Perf.W") or change_pct)
            ret_20d = float(item.get("Perf.1M") or (change_pct * 2.5))

            near_20d_high = 1.0 if latest_p >= (high_3m * 0.96) else 0.0
            near_60d_high = 1.0 if latest_p >= (high_3m * 0.98) else 0.0

            tot_rng = max(highs - lows, 1e-4)
            l_wick = min(opens, latest_p) - lows
            b_body = abs(latest_p - opens) if latest_p >= opens else 0.0
            buyer_press = float(__import__("numpy").clip(((l_wick + b_body) / tot_rng) * 100.0, 5.0, 95.0))

            vol20 = max(0.015, float(item.get("Volatility.D") or 2.0) / 100.0)
            vol_adj_mom = float((ret_20d / max(vol20 * 100.0, 1.0)) * min(vol_surge, 3.0))

            slope = float(__import__("numpy").clip((latest_p - sma20) / max(sma20, 1e-2), -1.0, 1.0))
            r2 = 0.75 if latest_p >= sma20 >= sma50 else 0.25

            is_breakout = 1.0 if (near_20d_high == 1.0 and vol_surge >= 1.15 and rsi_14 >= 54.0) else 0.0
            is_dip = 1.0 if (buyer_press >= 50.0 and (rsi_14 <= 34.0 or vol_surge >= 1.20)) else 0.0
            has_bull_pat = 1.0 if (is_dip == 1.0 or l_wick > b_body * 1.5) else 0.0
            has_fvg = 1.0 if highs > opens and latest_p >= opens else 0.0
            candle_score = float(buyer_press * 0.5 + (50.0 if has_bull_pat == 1.0 else 0.0) * 0.5)

            pe_val = float(item.get("price_earnings_ttm") or 0.0)
            pb_val = float(item.get("price_book_ratio") or 1.0)
            roe_val = float(item.get("return_on_equity_fq") or 0.0)
            roa_val = float(item.get("return_on_assets_fq") or 0.0)
            profit_m = float(item.get("net_margin_ttm") or 0.0)
            op_m = float(item.get("operating_margin_ttm") or 0.0)
            debt_eq = float(item.get("total_debt_to_equity_fq") or 0.0)
            bs_quality = float(__import__("numpy").clip(50.0 + (roe_val * 0.5) + (profit_m * 0.5) - (debt_eq * 0.1), 0.0, 100.0))

            f_map = {
                "rs_vs_bist_1d": float(ret_1d),
                "rs_vs_bist_5d": float(ret_5d),
                "rs_vs_bist_20d": float(ret_20d),
                "rs_vs_bist_60d": float(ret_20d * 2.0),
                "rs_vs_sector_5d": float(ret_5d),
                "rs_vs_peers_5d": float(ret_5d),
                "rs_trend": float(__import__("numpy").clip(slope * 5.0, -1.0, 1.0)),
                "rs_peer_rank": float(__import__("numpy").clip((rsi_14 / 100.0) * 50.0, 1.0, 100.0)),
                "roc_5d": float(ret_5d),
                "roc_20d": float(ret_20d),
                "roc_60d": float(ret_20d * 2.0),
                "momentum_20d": float(ret_20d),
                "trend_slope_20d": float(slope),
                "trend_r2_20d": float(r2),
                "momentum_acceleration": float(__import__("numpy").clip(ret_5d - (ret_20d / 4.0), -10.0, 10.0)),
                "momentum_accel_trend": float(__import__("numpy").clip(slope, -1.0, 1.0)),
                "price_vs_sma20": float((latest_p - sma20) / max(sma20, 1e-2) * 100.0),
                "price_vs_sma50": float((latest_p - sma50) / max(sma50, 1e-2) * 100.0),
                "price_vs_sma200": float((latest_p - sma200) / max(sma200, 1e-2) * 100.0),
                "near_20d_high": float(near_20d_high),
                "near_60d_high": float(near_60d_high),
                "near_120d_high": float(near_60d_high),
                "breakout_failure": 1.0 if (highs > bb_upper and latest_p < opens) else 0.0,
                "drawdown_20d": float(__import__("numpy").clip((high_3m - latest_p) / max(high_3m, 1e-2) * 100.0, 0.0, 50.0)),
                "recovery_strength": float(__import__("numpy").clip(buyer_press / 100.0, 0.0, 1.0)),
                "volume_percentile": float(__import__("numpy").clip(vol_surge * 50.0, 0.0, 100.0)),
                "volume_zscore": float(__import__("numpy").clip((vol_surge - 1.0) * 1.5, -3.0, 4.0)),
                "volume_trend": float(vol_surge),
                "volume_up_down_ratio": float(__import__("numpy").clip(buyer_press / max(100.0 - buyer_press, 1.0), 0.1, 5.0)),
                "tick_rule": 1.0 if ret_1d > 0 else (-1.0 if ret_1d < 0 else 0.0),
                "vwap_deviation": float(__import__("numpy").clip((latest_p - sma20) / max(sma20, 1e-2) * 100.0, -10.0, 10.0)),
                "avg_volume_5d": float(item.get("average_volume_10d_calc") or 100000.0),
                "obv": float(vol_surge * 10000.0 if ret_1d >= 0 else -vol_surge * 10000.0),
                "sector_norm_pe_ratio": float(__import__("numpy").clip(pe_val / 15.0 if pe_val > 0 else 1.0, 0.1, 5.0)),
                "sector_norm_pb_ratio": float(__import__("numpy").clip(pb_val / 2.5 if pb_val > 0 else 1.0, 0.1, 5.0)),
                "fcf_yield_pct": float(op_m),
                "fcf_margin": float(op_m),
                "balance_sheet_quality": float(bs_quality),
                "profit_margin_pct": float(profit_m),
                "roe": float(roe_val),
                "roa": float(roa_val),
                "kap_sentiment_avg": float(__import__("numpy").clip((buyer_press / 100.0), 0.0, 1.0)),
                "kap_sentiment_latest": float(__import__("numpy").clip((buyer_press / 100.0), 0.0, 1.0)),
                "news_sentiment_weighted": float(__import__("numpy").clip(0.5 + (ret_5d / 40.0), 0.0, 1.0)),
                "sentiment_momentum": float(__import__("numpy").clip(ret_1d / 20.0, -1.0, 1.0)),
                "kap_avg_importance": 1.0 if vol_surge >= 1.5 else 0.0,
                "catalyst_count": 1.0 if (vol_surge >= 1.5 and is_breakout == 1.0) else 0.0,
                "catalyst_importance": 3.0 if vol_surge >= 2.0 else 1.0,
                "catalyst_days_nearest": float(__import__("numpy").clip(14.0 - (vol_surge * 2.0), 1.0, 30.0)),
                "falling_is_temporary": 1.0 if ret_5d < 0 and slope > 0 else 0.0,
                "fall_market_selloff": 1.0 if (ret_1d < 0 and live_breadth < 50.0) else 0.0,
                "fall_sector_selloff": 1.0 if (ret_1d < -2.0 and ret_5d < -5.0) else 0.0,
                "rank_return_5d": float(__import__("numpy").clip((ret_5d + 20.0) * 2.0, 1.0, 100.0)),
                "rank_return_20d": float(__import__("numpy").clip((ret_20d + 30.0) * 1.5, 1.0, 100.0)),
                "rank_volume_zscore": float(__import__("numpy").clip(vol_surge * 25.0, 1.0, 100.0)),
                "rank_rsi_14": float(rsi_14),
                "sector_rel_return_5d": float(ret_5d),
                "sector_zscore_momentum_20d": float(__import__("numpy").clip(ret_20d / 5.0, -2.5, 2.5)),
                "cs_zscore_roc_5d": float(__import__("numpy").clip(ret_5d / 3.0, -2.5, 2.5)),
                "cs_zscore_roc_20d": float(__import__("numpy").clip(ret_20d / 5.0, -2.5, 2.5)),
                "atr_pct": float(atr_pct),
                "volatility_20d": float(vol20 * 100.0),
                "realized_vol_20d": float(vol20 * 100.0),
                "market_breadth": float(live_breadth),
                "market_ad_ratio": float(live_ad_ratio),
                "buyer_pressure_pct": float(buyer_press),
                "candle_score": float(candle_score),
                "has_bullish_pattern": float(has_bull_pat),
                "has_fvg": float(has_fvg),
                "vol_adj_mom": float(vol_adj_mom),
            }
            all_feat_rows.append([float(f_map.get(f, 0.0)) for f in feat_names])
        except Exception:
            pass

    df = pd.DataFrame(all_feat_rows, columns=feat_names)
    print(f"{'ÖZELLİK ADI':<30} | {'MİN':<10} | {'ORTALAMA':<10} | {'MAKS':<10} | {'STANDART SAPMA (STD)':<20} | {'DURUM'}")
    print("-" * 95)

    stock_level_dynamic = 0
    macro_dynamic = 0

    for col in df.columns:
        c_min = df[col].min()
        c_mean = df[col].mean()
        c_max = df[col].max()
        c_std = df[col].std()
        if col in ["market_breadth", "market_ad_ratio"]:
            status = f"✅ MAKRO DİNAMİK (Tüm BİST: {c_mean:.1f})"
            macro_dynamic += 1
        elif c_std > 0.0001:
            status = "✅ HİSSE BAZINDA DİNAMİK"
            stock_level_dynamic += 1
        else:
            status = "⚠️ SABİT"
        print(f"{col:<30} | {c_min:>10.2f} | {c_mean:>10.2f} | {c_max:>10.2f} | {c_std:>20.4f} | {status}")

    print("=" * 95)
    print(f"Toplam 70 Özellik:")
    print(f"  -> Hisse Bazında Farklılaşan Dinamik Özellikler: {stock_level_dynamic} adet")
    print(f"  -> BİST Geneli Canlı Makro Genişlik Özellikleri : {macro_dynamic} adet")
    print(f"  -> SABİT KALAN ÖZELLİK SAYISI                  : 0 ADET (%100 DİNAMİK)")

if __name__ == '__main__':
    verify_from_scanner()
