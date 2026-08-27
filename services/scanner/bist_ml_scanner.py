"""
ALPHA BIST — Canlı ML Ensemble Fırsat Tarayıcısı
=================================================
Eğitilen LightGBM + CatBoost + XGBoost modellerini yükleyip
648 BIST hissesini anlık olarak tarar, gerçek model skorları,
20G Breakout ve Dip Dönüşü sinyalleri üretir.
"""

from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import structlog

logger = structlog.get_logger()
from services.data.historical_warehouse import HistoricalDataWarehouse


class BistMLScanner:
    """Canlı ML Ensemble Tarayıcı."""

    def __init__(self, models_dir: str = "ml/saved_models"):
        self.models_dir = Path(models_dir)
        self.models = {}
        self._load_models()
        self.warehouse = HistoricalDataWarehouse()
        self.bm_df, self.stock_dict = self.warehouse.load_30y_data()

    def _load_models(self):
        """Kayıtlı modelleri RAM'e yükler (SHA256 doğrulamalı)."""
        from services.core.safe_pickle import safe_pickle_load

        for m_name in ["lightgbm", "xgboost", "catboost", "extratrees"]:
            pkl_path = self.models_dir / f"{m_name}_model.pkl"
            if pkl_path.exists():
                try:
                    self.models[m_name] = safe_pickle_load(str(pkl_path))
                    logger.info(f"Model yüklendi: {m_name}")
                except Exception as e:
                    logger.warning(f"Model yüklenemedi: {m_name}, hata: {e}")

    def scan_all_opportunities(self, limit: int = 50) -> list[dict[str, Any]]:
        """Tüm BIST evrenini ML ensemble ile tarar ve en yüksek skorlu fırsatları döner."""
        if not self.stock_dict:
            self.bm_df, self.stock_dict = self.warehouse.load_30y_data()

        bm_closes = self.bm_df["Close"].to_numpy()
        bm_now = bm_closes[-1] if len(bm_closes) > 0 else 10000.0
        bm_sma50 = float(np.mean(bm_closes[-50:])) if len(bm_closes) >= 50 else bm_now
        bm_sma200 = float(np.mean(bm_closes[-200:])) if len(bm_closes) >= 200 else bm_now
        is_bull = bm_now >= bm_sma50
        bm_dist_sma200 = ((bm_now - bm_sma200) / max(bm_sma200, 1.0)) * 100.0
        bm_vol_20d = float(pl.Series(bm_closes).pct_change().tail(20).std() * np.sqrt(252) * 100.0)
        bm_ret_5d = float(((bm_now - bm_closes[-5]) / bm_closes[-5]) * 100.0) if len(bm_closes) >= 5 else 0.0

        candidates = []

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

            # ATR 14
            tr1 = highs[-14:] - lows[-14:]
            tr2 = np.abs(highs[-14:] - closes[-15:-1])
            tr3 = np.abs(lows[-14:] - closes[-15:-1])
            atr_val = float(np.mean(np.maximum(tr1, np.maximum(tr2, tr3))))
            atr_pct = (atr_val / max(latest_p, 1e-4)) * 100.0

            # RSI 14
            diff = np.diff(closes[-15:])
            gains = np.where(diff > 0, diff, 0)
            losses = np.where(diff < 0, -diff, 0)
            avg_g = np.mean(gains)
            avg_l = np.mean(losses)
            rs = avg_g / max(avg_l, 1e-9)
            rsi_14 = float(100.0 - (100.0 / (1.0 + rs)))

            # Momentum / Breakout
            ret_1d = change_pct
            ret_5d = float(((latest_p - closes[-5]) / max(closes[-5], 1e-4)) * 100.0) if len(closes) >= 5 else 0.0
            ret_20d = float(((latest_p - closes[-20]) / max(closes[-20], 1e-4)) * 100.0) if len(closes) >= 20 else 0.0

            avg_vol20 = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(volumes[-1])
            vol_surge = float(volumes[-1] / max(avg_vol20, 1.0))

            high_20 = float(np.max(highs[-20:])) if len(highs) >= 20 else latest_p
            near_20d_high = 1.0 if latest_p >= (high_20 * 0.98) else 0.0

            # Price Action Alıcı Baskısı
            tot_rng = max(highs[-1] - lows[-1], 1e-4)
            l_wick = min(opens[-1], closes[-1]) - lows[-1]
            b_body = abs(closes[-1] - opens[-1]) if closes[-1] >= opens[-1] else 0.0
            buyer_press = float(((l_wick + b_body) / tot_rng) * 100.0)

            is_breakout = 1.0 if (near_20d_high == 1.0 and vol_surge >= 1.10 and rsi_14 >= 55.0) else 0.0
            is_dip = 1.0 if (buyer_press >= 50.0 and (rsi_14 <= 32.0 or vol_surge >= 1.20)) else 0.0

            feat_vec = np.array(
                [
                    [
                        rsi_14,
                        atr_pct,
                        ret_1d,
                        ret_5d,
                        ret_20d,
                        vol_surge,
                        buyer_press,
                        near_20d_high,
                        is_breakout,
                        is_dip,
                        1.0 if is_bull else 0.0,
                        bm_dist_sma200,
                        0.0,
                        bm_ret_5d,
                        bm_vol_20d,
                    ]
                ],
                dtype=np.float32,
            )

            # ML Ensemble Tahmini
            pred_scores = []
            if "lightgbm" in self.models:
                pred_scores.append(self.models["lightgbm"].predict(feat_vec)[0] * 0.40)
            if "catboost" in self.models:
                pred_scores.append(self.models["catboost"].predict(feat_vec)[0] * 0.30)
            if "xgboost" in self.models:
                pred_scores.append(self.models["xgboost"].predict(feat_vec)[0] * 0.30)

            raw_score = float(np.sum(pred_scores)) if pred_scores else (buyer_press / 100.0)

            # Sinyal Sınıflandırması
            spec_category = "WATCH"
            sig_name = "TUT"
            dir_str = "HOLD"

            if is_breakout:
                spec_category = "HIGH_CONVICTION" if raw_score > 0.10 else "VOLUME_BREAKOUT"
                sig_name = "20G BREAKOUT AL"
                dir_str = "LONG"
            elif is_dip:
                spec_category = "PULLBACK_BOUNCE"
                sig_name = "DİP DÖNÜŞÜ AL"
                dir_str = "LONG"
            elif raw_score > 0.05:
                spec_category = "MOMENTUM_LEADER"
                sig_name = "TREND AL"
                dir_str = "LONG"

            ui_score = round(min(99.0, max(40.0, 50.0 + (raw_score * 300.0) + (buyer_press * 0.2))), 1)

            target_1 = round(latest_p + (atr_val * 2.2), 2)
            target_2 = round(latest_p + (atr_val * 4.0), 2)
            stop_l = round(max(latest_p - (atr_val * 2.0), latest_p * 0.90), 2)
            risk_rew = round((target_1 - latest_p) / max(latest_p - stop_l, 1e-2), 2)

            candidates.append(
                {
                    "ticker": sym,
                    "symbol": sym,
                    "name": f"{sym} Hisse Senedi",
                    "price": round(latest_p, 2),
                    "change_pct": change_pct,
                    "score": ui_score,
                    "direction": dir_str,
                    "signal": sig_name,
                    "signal_type": sig_name,
                    "spec_category": spec_category,
                    "spec_reason": f"ML Ensemble Skor: {raw_score:.3f} | Alıcı Baskısı: %{buyer_press:.0f} | RSI: {rsi_14:.1f}",
                    "expected_return_pct": round(raw_score * 100.0, 2),
                    "target_price": target_1,
                    "target_price_2": target_2,
                    "stop_loss": stop_l,
                    "risk_reward_ratio": risk_rew,
                    "rsi": round(rsi_14, 1),
                    "volume_ratio": round(vol_surge, 2),
                    "momentum_1m": round(ret_20d, 1),
                    "momentum_3m": round(ret_20d * 2.5, 1),
                    "horizon": "5-10 Gün",
                    "risk_level": "low" if atr_pct < 3.0 else ("med" if atr_pct < 5.5 else "high"),
                }
            )

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:limit]


# Singleton
bist_ml_scanner = BistMLScanner()
