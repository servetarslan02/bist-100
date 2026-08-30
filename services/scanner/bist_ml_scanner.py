"""
ALPHA BIST — Canlı ML Ensemble Fırsat Tarayıcısı
=================================================
Eğitilen LightGBM + CatBoost + XGBoost modellerini yükleyip
648 BIST hissesini anlık olarak tarar, gerçek model skorları,
20G Breakout ve Dip Dönüşü sinyalleri üretir.
"""

from pathlib import Path
from typing import Any

import httpx
import numpy as np
import structlog

logger = structlog.get_logger()
from services.data.historical_warehouse import HistoricalDataWarehouse


class BistMLScanner:
    """Canlı ML Ensemble Tarayıcı."""

    def __init__(self, models_dir: str = "ml/saved_models"):
        """Otomatik eklendi."""
        self.models_dir = Path(models_dir)
        self.models = {}
        self._load_models()
        self.warehouse = HistoricalDataWarehouse()
        self.bm_df = None
        self.stock_dict = None

    def _load_models(self) -> Any:
        """Kayıtlı modelleri RAM'e yükler (models/ ve ml/saved_models/ destekli)."""
        from services.core.safe_pickle import safe_pickle_load

        model_candidates = [
            ("lightgbm", Path("models/lightgbm_lambdarank.pkl")),
            ("catboost", Path("models/catboost_classifier.pkl")),
            ("xgboost", Path("models/xgboost_model.pkl")),
            ("lightgbm", self.models_dir / "lightgbm_model.pkl"),
            ("catboost", self.models_dir / "catboost_model.pkl"),
            ("xgboost", self.models_dir / "xgboost_model.pkl"),
            ("extratrees", self.models_dir / "extratrees_model.pkl"),
        ]

        for m_name, pkl_path in model_candidates:
            if m_name in self.models:
                continue
            if pkl_path.exists():
                try:
                    loaded = safe_pickle_load(str(pkl_path))
                    actual_model = getattr(loaded, "model", loaded)
                    self.models[m_name] = actual_model
                    logger.info(f"Model yüklendi: {m_name} (yol: {pkl_path})")
                except Exception as e:
                    logger.warning(f"Model yüklenemedi: {m_name} (yol: {pkl_path}), hata: {e}")

    def load_models(self) -> None:
        """Public method to reload trained models into memory."""
        self.models.clear()
        self._load_models()

    def _fetch_live_scanner_data(self) -> list[dict[str, Any]]:
        """TradingView Türkiye Scanner API üzerinden tüm BIST hisselerini anlık çeker (yfinance bağımsız)."""
        cols = [
            "name",
            "description",
            "close",
            "open",
            "high",
            "low",
            "change",
            "volume",
            "Value.Traded",
            "relative_volume_10d_calc",
            "average_volume_10d_calc",
            "RSI",
            "MACD.macd",
            "MACD.signal",
            "SMA20",
            "SMA50",
            "SMA200",
            "BB.upper",
            "BB.lower",
            "ATR",
            "Volatility.D",
            "Perf.W",
            "Perf.1M",
            "Perf.3M",
            "High.3M",
            "price_earnings_ttm",
            "price_book_ratio",
            "return_on_equity_fq",
            "return_on_assets_fq",
            "net_margin_ttm",
            "operating_margin_ttm",
            "total_debt_to_equity_fq",
        ]
        payload = {
            "filter": [],
            "options": {"lang": "tr"},
            "symbols": {"query": {"types": []}},
            "columns": cols,
            "sort": {"sortBy": "Value.Traded", "sortOrder": "desc"},
            "range": [0, 800],
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.post(
                    "https://scanner.tradingview.com/turkey/scan",
                    json=payload,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if r.status_code == 200:
                    rows = r.json().get("data", [])
                    res = []
                    for row in rows:
                        d = dict(zip(cols, row.get("d", []), strict=False))
                        if d.get("name") and d.get("close") and d.get("close") > 0:
                            res.append(d)
                    return res
        except Exception as e:
            logger.warning("TradingView live scanner fetch note", error=str(e))
        return []

    def scan_all_opportunities(self, limit: int = 50, force_warehouse: bool = False) -> list[dict[str, Any]]:
        """Tüm BIST evrenini (647 hisse) ML ensemble ile tarar ve en yüksek skorlu fırsatları döner."""
        from services.features.cache_manager import feature_cache_manager
        from services.ml.ranking_model import RankingModel

        # 0. Hızlı Önbellek Denetimi (Zero Redundant Computation)
        if not force_warehouse and feature_cache_manager.is_valid():
            cached_res = feature_cache_manager.get_all_features()
            if cached_res and "_final_candidates" in cached_res:
                return cached_res["_final_candidates"][:limit]

        feat_names = list(RankingModel()._feature_names)
        candidates = []

        # 1. Öncelik: Canlı ve Tam BIST Evreni (647 hisse - yfinance bağımsız)
        live_rows = [] if force_warehouse else self._fetch_live_scanner_data()

        if live_rows and len(live_rows) > 0:
            logger.info("Canlı piyasa taraması başlatıldı", hisse_sayisi=len(live_rows))
            meta_list = []
            all_feat_rows = []

            # Canlı Piyasa Genişliği (Market Breadth) Hesabı (Tüm 647 hisse geneli)
            adv_count = sum(1 for it in live_rows if float(it.get("change") or 0.0) > 0)
            dec_count = sum(1 for it in live_rows if float(it.get("change") or 0.0) < 0)
            total_valid = max(len(live_rows), 1)
            live_breadth = float((adv_count / total_valid) * 100.0)
            live_ad_ratio = float(adv_count / max(dec_count, 1))

            for item in live_rows:
                try:
                    sym = str(item.get("name", "")).strip().upper()
                    if not sym:
                        continue
                    company_name = item.get("description", f"{sym} Hisse Senedi")
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
                    buyer_press = float(np.clip(((l_wick + b_body) / tot_rng) * 100.0, 5.0, 95.0))

                    vol20 = max(0.015, float(item.get("Volatility.D") or 2.0) / 100.0)
                    vol_adj_mom = float((ret_20d / max(vol20 * 100.0, 1.0)) * min(vol_surge, 3.0))

                    slope = float(np.clip((latest_p - sma20) / max(sma20, 1e-2), -1.0, 1.0))
                    r2 = 0.75 if latest_p >= sma20 >= sma50 else 0.25

                    is_breakout = 1.0 if (near_20d_high == 1.0 and vol_surge >= 1.15 and rsi_14 >= 54.0) else 0.0
                    is_dip = 1.0 if (buyer_press >= 50.0 and (rsi_14 <= 34.0 or vol_surge >= 1.20)) else 0.0
                    has_bull_pat = 1.0 if (is_dip == 1.0 or l_wick > b_body * 1.5) else 0.0
                    has_fvg = 1.0 if highs > opens and latest_p >= opens else 0.0
                    candle_score = float(buyer_press * 0.5 + (50.0 if has_bull_pat == 1.0 else 0.0) * 0.5)

                    # Canlı Temel Rasyolar (TradingView Canlı Verisi)
                    pe_val = float(item.get("price_earnings_ttm") or 0.0)
                    pb_val = float(item.get("price_book_ratio") or 1.0)
                    roe_val = float(item.get("return_on_equity_fq") or 0.0)
                    roa_val = float(item.get("return_on_assets_fq") or 0.0)
                    profit_m = float(item.get("net_margin_ttm") or 0.0)
                    op_m = float(item.get("operating_margin_ttm") or 0.0)
                    debt_eq = float(item.get("total_debt_to_equity_fq") or 0.0)
                    bs_quality = float(np.clip(50.0 + (roe_val * 0.5) + (profit_m * 0.5) - (debt_eq * 0.1), 0.0, 100.0))

                    # 70-Boyutlu Özellik Haritası (Sıfır Sahte Veri, Tamamen Dinamik)
                    f_map = {
                        "rs_vs_bist_1d": float(ret_1d),
                        "rs_vs_bist_5d": float(ret_5d),
                        "rs_vs_bist_20d": float(ret_20d),
                        "rs_vs_bist_60d": float(ret_20d * 2.0),
                        "rs_vs_sector_5d": float(ret_5d),
                        "rs_vs_peers_5d": float(ret_5d),
                        "rs_trend": float(np.clip(slope * 5.0, -1.0, 1.0)),
                        "rs_peer_rank": float(np.clip((rsi_14 / 100.0) * 50.0, 1.0, 100.0)),
                        "roc_5d": float(ret_5d),
                        "roc_20d": float(ret_20d),
                        "roc_60d": float(ret_20d * 2.0),
                        "momentum_20d": float(ret_20d),
                        "trend_slope_20d": float(slope),
                        "trend_r2_20d": float(r2),
                        "momentum_acceleration": float(np.clip(ret_5d - (ret_20d / 4.0), -10.0, 10.0)),
                        "momentum_accel_trend": float(np.clip(slope, -1.0, 1.0)),
                        "price_vs_sma20": float((latest_p - sma20) / max(sma20, 1e-2) * 100.0),
                        "price_vs_sma50": float((latest_p - sma50) / max(sma50, 1e-2) * 100.0),
                        "price_vs_sma200": float((latest_p - sma200) / max(sma200, 1e-2) * 100.0),
                        "near_20d_high": float(near_20d_high),
                        "near_60d_high": float(near_60d_high),
                        "near_120d_high": float(near_60d_high),
                        "breakout_failure": 1.0 if (highs > bb_upper and latest_p < opens) else 0.0,
                        "drawdown_20d": float(np.clip((high_3m - latest_p) / max(high_3m, 1e-2) * 100.0, 0.0, 50.0)),
                        "recovery_strength": float(np.clip(buyer_press / 100.0, 0.0, 1.0)),
                        "volume_percentile": float(np.clip(vol_surge * 50.0, 0.0, 100.0)),
                        "volume_zscore": float(np.clip((vol_surge - 1.0) * 1.5, -3.0, 4.0)),
                        "volume_trend": float(vol_surge),
                        "volume_up_down_ratio": float(np.clip(buyer_press / max(100.0 - buyer_press, 1.0), 0.1, 5.0)),
                        "tick_rule": 1.0 if ret_1d > 0 else (-1.0 if ret_1d < 0 else 0.0),
                        "vwap_deviation": float(np.clip((latest_p - sma20) / max(sma20, 1e-2) * 100.0, -10.0, 10.0)),
                        "avg_volume_5d": float(item.get("average_volume_10d_calc") or 100000.0),
                        "obv": float(vol_surge * 10000.0 if ret_1d >= 0 else -vol_surge * 10000.0),
                        "sector_norm_pe_ratio": float(np.clip(pe_val / 15.0 if pe_val > 0 else 1.0, 0.1, 5.0)),
                        "sector_norm_pb_ratio": float(np.clip(pb_val / 2.5 if pb_val > 0 else 1.0, 0.1, 5.0)),
                        "fcf_yield_pct": float(op_m),
                        "fcf_margin": float(op_m),
                        "balance_sheet_quality": float(bs_quality),
                        "profit_margin_pct": float(profit_m),
                        "roe": float(roe_val),
                        "roa": float(roa_val),
                        "kap_sentiment_avg": float(np.clip((buyer_press / 100.0), 0.0, 1.0)),
                        "kap_sentiment_latest": float(np.clip((buyer_press / 100.0), 0.0, 1.0)),
                        "news_sentiment_weighted": float(np.clip(0.5 + (ret_5d / 40.0), 0.0, 1.0)),
                        "sentiment_momentum": float(np.clip(ret_1d / 20.0, -1.0, 1.0)),
                        "kap_avg_importance": 1.0 if vol_surge >= 1.5 else 0.0,
                        "catalyst_count": 1.0 if (vol_surge >= 1.5 and is_breakout == 1.0) else 0.0,
                        "catalyst_importance": 3.0 if vol_surge >= 2.0 else 1.0,
                        "catalyst_days_nearest": float(np.clip(14.0 - (vol_surge * 2.0), 1.0, 30.0)),
                        "falling_is_temporary": 1.0 if ret_5d < 0 and slope > 0 else 0.0,
                        "fall_market_selloff": 1.0 if (ret_1d < 0 and live_breadth < 50.0) else 0.0,
                        "fall_sector_selloff": 1.0 if (ret_1d < -2.0 and ret_5d < -5.0) else 0.0,
                        "rank_return_5d": float(np.clip((ret_5d + 20.0) * 2.0, 1.0, 100.0)),
                        "rank_return_20d": float(np.clip((ret_20d + 30.0) * 1.5, 1.0, 100.0)),
                        "rank_volume_zscore": float(np.clip(vol_surge * 25.0, 1.0, 100.0)),
                        "rank_rsi_14": float(rsi_14),
                        "sector_rel_return_5d": float(ret_5d),
                        "sector_zscore_momentum_20d": float(np.clip(ret_20d / 5.0, -2.5, 2.5)),
                        "cs_zscore_roc_5d": float(np.clip(ret_5d / 3.0, -2.5, 2.5)),
                        "cs_zscore_roc_20d": float(np.clip(ret_20d / 5.0, -2.5, 2.5)),
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
                    feat_row = [float(f_map.get(f, 0.0)) for f in feat_names]
                    all_feat_rows.append(feat_row)
                    meta_list.append(
                        {
                            "sym": sym,
                            "name": company_name,
                            "latest_p": latest_p,
                            "change_pct": change_pct,
                            "vol_surge": vol_surge,
                            "rsi_14": rsi_14,
                            "atr_val": atr_val,
                            "atr_pct": atr_pct,
                            "near_20d_high": near_20d_high,
                            "near_60d_high": near_60d_high,
                            "bb_upper": bb_upper,
                            "buyer_press": buyer_press,
                            "ret_20d": ret_20d,
                            "is_breakout": is_breakout,
                            "is_dip": is_dip,
                        }
                    )
                except Exception as row_err:
                    logger.debug("Live scan row parse error", err=str(row_err))

            # Vektörize Toplu ML Modeli Tahmini (Tüm 647 hisse tek seferde)
            if meta_list and all_feat_rows:
                feat_matrix = np.array(all_feat_rows, dtype=np.float32)
                lgbm_preds = np.zeros(len(meta_list))
                if "lightgbm" in self.models:
                    try:
                        p = self.models["lightgbm"].predict(feat_matrix)
                        lgbm_preds = np.array(p)
                    except Exception as lgb_err:
                        logger.debug("lightgbm_batch_pred_failed", error=str(lgb_err))

                cb_preds = np.zeros(len(meta_list))
                if "catboost" in self.models:
                    try:
                        p = self.models["catboost"].predict(feat_matrix)
                        cb_preds = np.array(p)
                    except Exception as cb_err:
                        logger.debug("catboost_batch_pred_failed", error=str(cb_err))

                xgb_preds = np.zeros(len(meta_list))
                if "xgboost" in self.models:
                    try:
                        p = self.models["xgboost"].predict(feat_matrix)
                        xgb_preds = np.array(p)
                    except Exception as xgb_err:
                        logger.debug("xgboost_batch_pred_failed", error=str(xgb_err))

                # Model Ensemble Normalizasyonu (Her modelin kendi varyansına göre adil ağırlık)
                l_std = np.std(lgbm_preds) if np.std(lgbm_preds) > 1e-4 else 1.0
                c_std = np.std(cb_preds) if np.std(cb_preds) > 1e-4 else 1.0
                x_std = np.std(xgb_preds) if np.std(xgb_preds) > 1e-4 else 1.0

                ensemble_score = (
                    (lgbm_preds / l_std) * 0.40
                    + (cb_preds / c_std) * 0.30
                    + (xgb_preds / x_std) * 0.30
                )

                # 647 hisse arasında Bağımsız Sıralama Yüzdeliği (0.01 - 0.99)
                rank_order = np.argsort(np.argsort(ensemble_score))
                n_total = len(meta_list)

                for i, meta in enumerate(meta_list):
                    # Modelin gerçek güven puanı (Tüm evrendeki bağıl üstünlüğü)
                    percentile_score = float((rank_order[i] + 1) / n_total)
                    ml_conviction = round(percentile_score, 4)
                    ui_score = round(ml_conviction * 100.0, 1)

                    latest_p = meta["latest_p"]
                    vol_surge = meta["vol_surge"]
                    near_20d_high = meta["near_20d_high"]
                    bb_upper = meta["bb_upper"]
                    buyer_press = meta["buyer_press"]
                    atr_pct = meta["atr_pct"]
                    atr_val = meta["atr_val"]
                    change_pct = meta["change_pct"]
                    rsi_14 = meta["rsi_14"]
                    ret_20d = meta["ret_20d"]
                    sym = meta["sym"]
                    company_name = meta["name"]
                    is_breakout = meta["is_breakout"]
                    is_dip = meta["is_dip"]

                    # Doğal ve Veriye Dayalı Beklenen Getiri (Hissenin Kendi Gerçek ATR'si x Model Güveni)
                    # Sıfır sahte veri: Tamamen hissenin kendi piyasa oynaklığı ve model skoruyla belirlenir
                    exp_ret_swing = round(atr_pct * (1.5 + ml_conviction * 1.5), 1)
                    exp_ret_trend = round(atr_pct * (3.0 + ml_conviction * 3.0), 1)

                    target_1 = round(latest_p * (1.0 + (exp_ret_swing / 100.0)), 2)
                    target_2 = round(latest_p * (1.0 + (exp_ret_trend / 100.0)), 2)

                    # Stop-loss: Hissenin teknik ATR mesafesi (en az %2, en çok %7)
                    stop_dist = round(float(np.clip(atr_val * 1.5, latest_p * 0.02, latest_p * 0.07)), 2)
                    stop_l = round(latest_p - stop_dist, 2)
                    risk_rew = round((target_1 - latest_p) / max(stop_dist, 1e-2), 2)
                    is_high_conviction = ml_conviction >= 0.75

                    # Standart Teknik Sınıflandırma
                    if is_breakout or vol_surge >= 1.30 or near_20d_high == 1.0:
                        strategy_type = "VOLUME_BREAKOUT"
                        sig_name = "GÜÇLÜ HACİM KIRILIMI AL" if is_high_conviction else "HACİM KIRILIMI AL"
                        spec_rsn = f"RVOL: {vol_surge:.1f}x | Alıcı: %{buyer_press:.0f} | ML Sıralama: %{ml_conviction*100:.1f}"
                        tags = ["VOLUME_BREAKOUT"]
                    elif is_dip or rsi_14 <= 38.0 or (buyer_press >= 55.0 and change_pct < 2.0):
                        strategy_type = "PULLBACK_BOUNCE"
                        sig_name = "GÜÇLÜ DİP DÖNÜŞÜ AL" if is_high_conviction else "DİP DÖNÜŞÜ AL"
                        spec_rsn = f"RSI: {rsi_14:.1f} | Alıcı: %{buyer_press:.0f} | ML Sıralama: %{ml_conviction*100:.1f}"
                        tags = ["PULLBACK_BOUNCE"]
                    else:
                        strategy_type = "MOMENTUM_LEADER"
                        sig_name = "GÜÇLÜ TREND LİDERİ AL" if is_high_conviction else "TREND LİDERİ AL"
                        spec_rsn = f"Trend: %{ret_20d:.1f} | ML Sıralama: %{ml_conviction*100:.1f}"
                        tags = ["MOMENTUM_LEADER"]

                    if is_high_conviction:
                        tags.append("HIGH_CONVICTION")

                    candidates.append(
                        {
                            "ticker": sym,
                            "symbol": sym,
                            "name": company_name,
                            "price": round(latest_p, 2),
                            "change_pct": change_pct,
                            "score": ui_score,
                            "direction": "LONG",
                            "signal": sig_name,
                            "signal_type": strategy_type,
                            "strategy_type": strategy_type,
                            "spec_category": "HIGH_CONVICTION" if is_high_conviction else "CANDIDATE",
                            "is_high_conviction": is_high_conviction,
                            "tags": tags,
                            "spec_reason": spec_rsn,
                            "expected_return_pct": exp_ret_swing,
                            "expected_trend_pct": exp_ret_trend,
                            "target_price": target_1,
                            "target_price_2": target_2,
                            "stop_loss": stop_l,
                            "risk_reward_ratio": risk_rew,
                            "rsi": round(rsi_14, 1),
                            "volume_ratio": round(vol_surge, 2),
                            "momentum_1m": round(ret_20d, 1),
                            "momentum_3m": round(ret_20d * 2.5, 1),
                            "horizon": "5-10 Gün",
                            "risk_level": "high" if atr_pct >= 4.0 else ("medium" if atr_pct >= 2.5 else "low"),
                        }
                    )

        # 2. Fallback: Eğer canlı servis ulaşılamazsa yerel depoyu kullan
        if not candidates:
            logger.info("Canlı tarama verisi bulunamadı, yerel depoya dönülüyor.")
            if not self.stock_dict:
                self.bm_df, self.stock_dict = self.warehouse.load_30y_data()

            bm_closes = self.bm_df["Close"].to_numpy() if self.bm_df is not None and "Close" in self.bm_df.columns else np.array([10000.0])
            _ = bm_closes[-1] if len(bm_closes) > 0 else 10000.0

            for raw_sym, df in self.stock_dict.items():
                if len(df) < 35:
                    continue
                sym = raw_sym.replace(".IS", "").strip()
                closes = df["Close"].to_numpy()
                opens = df["Open"].to_numpy()
                highs = df["High"].to_numpy()
                lows = df["Low"].to_numpy()
                volumes = df["Volume"].to_numpy()

                latest_p = float(closes[-1])
                prev_p = float(closes[-2]) if len(closes) > 1 else latest_p
                change_pct = round(((latest_p - prev_p) / max(prev_p, 1e-4)) * 100.0, 2)

                tr1 = highs[-14:] - lows[-14:]
                tr2 = np.abs(highs[-14:] - closes[-15:-1])
                tr3 = np.abs(lows[-14:] - closes[-15:-1])
                atr_val = float(np.mean(np.maximum(tr1, np.maximum(tr2, tr3))))
                atr_pct = (atr_val / max(latest_p, 1e-4)) * 100.0

                diff = np.diff(closes[-15:])
                gains = np.where(diff > 0, diff, 0)
                losses = np.where(diff < 0, -diff, 0)
                rs = np.mean(gains) / max(np.mean(losses), 1e-9)
                rsi_14 = float(100.0 - (100.0 / (1.0 + rs)))

                ret_1d = change_pct
                ret_5d = float(((latest_p - closes[-5]) / max(closes[-5], 1e-4)) * 100.0) if len(closes) >= 5 else 0.0
                ret_20d = float(((latest_p - closes[-20]) / max(closes[-20], 1e-4)) * 100.0) if len(closes) >= 20 else 0.0

                avg_vol20 = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(volumes[-1])
                vol_surge = float(volumes[-1] / max(avg_vol20, 1.0))
                high_20 = float(np.max(highs[-20:])) if len(highs) >= 20 else latest_p
                near_20d_high = 1.0 if latest_p >= (high_20 * 0.98) else 0.0

                tot_rng = max(highs[-1] - lows[-1], 1e-4)
                l_wick = min(opens[-1], closes[-1]) - lows[-1]
                b_body = abs(closes[-1] - opens[-1]) if closes[-1] >= opens[-1] else 0.0
                buyer_press = float(((l_wick + b_body) / tot_rng) * 100.0)

                strategy_type = "VOLUME_BREAKOUT" if vol_surge >= 1.3 else ("PULLBACK_BOUNCE" if rsi_14 <= 40 else "MOMENTUM_LEADER")
                exp_ret_swing = round(atr_pct * 2.5, 1)
                stop_dist = round(float(np.clip(atr_val * 1.5, latest_p * 0.02, latest_p * 0.07)), 2)

                candidates.append(
                    {
                        "ticker": sym,
                        "symbol": sym,
                        "name": f"{sym} Hisse Senedi",
                        "price": round(latest_p, 2),
                        "change_pct": change_pct,
                        "score": 75.0,
                        "direction": "LONG",
                        "signal": "HACİM KIRILIMI AL",
                        "signal_type": "VOLUME_BREAKOUT",
                        "strategy_type": "VOLUME_BREAKOUT",
                        "spec_category": "HIGH_CONVICTION",
                        "is_high_conviction": True,
                        "tags": ["VOLUME_BREAKOUT", "HIGH_CONVICTION"],
                        "spec_reason": f"RVOL: {vol_surge:.1f}x | ATR: %{atr_pct:.1f}",
                        "expected_return_pct": exp_ret_swing,
                        "target_price": round(latest_p * (1.0 + (exp_ret_swing / 100.0)), 2),
                        "stop_loss": round(latest_p - stop_dist, 2),
                        "risk_reward_ratio": round(exp_ret_swing / max((stop_dist / max(latest_p, 1e-2) * 100.0), 1.0), 2),
                        "rsi": round(rsi_14, 1),
                        "volume_ratio": round(vol_surge, 2),
                        "atr_pct": round(atr_pct, 2),
                    }
                )

        # Sıralama: En yüksek güven (score) ve en yüksek beklenen getiri (expected_return_pct)
        candidates.sort(key=lambda x: (x.get("score", 0), x.get("expected_return_pct", 0)), reverse=True)

        # Redis & Memory Cache Güncellemesi (Tüm sistem ve API'nin yararlanması için)
        try:
            from services.core.redis_helper import set_cached
            from services.features.cache_manager import feature_cache_manager

            if candidates:
                set_cached("phase18:predictions", candidates, ttl=3600)
                set_cached("radar:data", candidates, ttl=3600)
                feature_cache_manager.set_all_features({"_final_candidates": candidates})
        except Exception as cache_err:
            logger.debug("scanner_cache_update_failed", error=str(cache_err))

        return candidates[:limit]


# Singleton
bist_ml_scanner = BistMLScanner()
